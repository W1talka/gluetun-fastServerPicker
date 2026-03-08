from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import time
from typing import Any, Callable

from .config import AppConfig
from .gluetun_api import GluetunClient
from .models import ProbeResult, ProbeSpec, ServerCandidate
from .privado import fetch_catalog, filter_candidates_by_region, resolve_hostnames
from .regions import REGION_CUSTOM
from .runtime import ContainerRuntime
from .state import AppState, StateStore
from .telegram import send_notification


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SweepOutcome:
    recommended_hostname: str | None
    applied_hostname: str | None
    switched: bool
    reason: str
    region: str
    candidate_count: int
    results: list[ProbeResult]

    def to_dict(self) -> dict[str, Any]:
        winner = best_result(self.results)
        return {
            "recommended_hostname": self.recommended_hostname,
            "applied_hostname": self.applied_hostname,
            "switched": self.switched,
            "reason": self.reason,
            "region": self.region,
            "candidate_count": self.candidate_count,
            "recommended_throughput_bps": winner.throughput_bps if winner is not None else None,
            "recommended_throughput_mb_per_s": winner.throughput_mb_per_s if winner is not None else None,
            "recommended_throughput_mbps": winner.throughput_mbps if winner is not None else None,
            "results": [result.to_dict() for result in self.results],
        }


@dataclass(frozen=True)
class BenchmarkRun:
    region: str
    candidate_count: int
    results: list[ProbeResult]
    current_hostname: str | None = None


class Controller:
    def __init__(
        self,
        config: AppConfig,
        *,
        client: GluetunClient | None = None,
        runtime: ContainerRuntime | None = None,
        state_store: StateStore | None = None,
        catalog_fetcher: Callable[..., list[ServerCandidate]] = fetch_catalog,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self._config = config
        self._client = client or GluetunClient(config.gluetun)
        self._runtime = runtime or ContainerRuntime(config.runtime)
        self._state_store = state_store or StateStore(config.state.filepath)
        self._catalog_fetcher = catalog_fetcher
        self._sleep = sleeper

    def run_forever(self, *, limit: int | None = None) -> None:
        first_cycle = True
        while True:
            outcome = self.run_cycle(startup=first_cycle, apply=True, limit=limit)
            LOGGER.info("cycle finished: %s", outcome.reason)
            first_cycle = False
            self._sleep(self._config.benchmark.interval_seconds)

    def run_cycle(self, *, startup: bool, apply: bool, limit: int | None = None) -> SweepOutcome:
        benchmark_run = self.benchmark_candidates(limit=limit)
        results = benchmark_run.results
        current_hostname = benchmark_run.current_hostname
        winner, should_switch, reason = pick_winner(
            results,
            current_hostname=current_hostname,
            threshold=self._config.benchmark.switch_threshold,
            startup=startup,
        )

        applied_hostname: str | None = current_hostname
        if apply and winner is not None and should_switch:
            applied_hostname = self.switch_to_hostname(winner.hostname)
            LOGGER.info("switched Gluetun to %s", applied_hostname)
        elif winner is not None:
            LOGGER.info("keeping Gluetun on %s: %s", current_hostname, reason)
        else:
            LOGGER.warning("no successful benchmark results, leaving Gluetun unchanged")

        state = self._state_store.load()
        state.last_sweep_at = utc_now_iso()
        state.current_winner = winner.hostname if winner is not None else state.current_winner
        state.last_applied_gluetun_hostname = applied_hostname
        state.update_results(results)
        self._state_store.save(state)

        outcome = SweepOutcome(
            recommended_hostname=winner.hostname if winner is not None else None,
            applied_hostname=applied_hostname,
            switched=bool(apply and winner is not None and should_switch),
            reason=reason,
            region=benchmark_run.region,
            candidate_count=benchmark_run.candidate_count,
            results=results,
        )
        send_notification(self._config.telegram, outcome)
        return outcome

    def benchmark_candidates(self, *, limit: int | None = None) -> BenchmarkRun:
        region, candidates = self.resolve_candidates()
        current_hostname = self._resolve_current_hostname(candidates)

        if current_hostname:
            current_candidate = next(
                (c for c in candidates if c.hostname == current_hostname), None
            )
            if current_candidate is not None:
                candidates = [current_candidate] + [
                    c for c in candidates if c.hostname != current_hostname
                ]
                LOGGER.info(
                    "current Gluetun server: %s — benchmarking it first as baseline",
                    current_hostname,
                )
            else:
                LOGGER.info(
                    "current Gluetun server %s is not in the candidate list",
                    current_hostname,
                )

        total = len(candidates)
        if limit is not None and limit < total:
            candidates = candidates[:limit]
        LOGGER.info("benchmarking %d/%d %s", len(candidates), total, describe_scope(region, total))
        results: list[ProbeResult] = []
        for candidate in candidates:
            LOGGER.info("probing %s (%s)", candidate.hostname, candidate.ip)
            result = self._run_single_probe(candidate)
            if result.success:
                LOGGER.info(
                    "probe success for %s: %.2f MB/s (%.2f Mbps) via %s",
                    result.hostname,
                    result.throughput_mb_per_s,
                    result.throughput_mbps,
                    result.benchmark_url,
                )
            else:
                LOGGER.warning("probe failed for %s: %s", result.hostname, result.error)
            results.append(result)
        return BenchmarkRun(
            region=region,
            candidate_count=len(candidates),
            results=results,
            current_hostname=current_hostname,
        )

    def _resolve_current_hostname(self, catalog: list[ServerCandidate]) -> str | None:
        try:
            settings = self._client.get_vpn_settings()
            hostname = current_gluetun_hostname(settings)
            if hostname:
                return hostname
            public_ip = self._client.get_public_ip()
            match = _match_by_ip(public_ip, catalog)
            if match:
                LOGGER.info("identified current server via public IP %s: %s", public_ip, match.hostname)
                return match.hostname
            LOGGER.info("public IP %s did not match any catalog server", public_ip)
            return None
        except Exception as exc:
            LOGGER.warning("could not resolve current Gluetun server: %s", exc)
            return None

    def _run_single_probe(self, candidate: ServerCandidate) -> ProbeResult:
        spec = ProbeSpec(
            candidate=candidate,
            username=self._config.privado.username,
            password=self._config.privado.password,
            benchmark_urls=self._config.benchmark.urls,
            benchmark_duration_seconds=self._config.benchmark.duration_seconds,
            connect_timeout_seconds=self._config.benchmark.connect_timeout_seconds,
            openvpn_verbosity=self._config.benchmark.openvpn_verbosity,
        )
        return self._runtime.run_probe(spec)

    def resolve_candidates(self) -> tuple[str, list[ServerCandidate]]:
        catalog = self._catalog_fetcher(
            timeout=self._config.benchmark.connect_timeout_seconds,
            cache_path=self._config.catalog.filepath,
            max_age_seconds=self._config.catalog.max_age_seconds,
        )
        if self._config.candidates.hostnames:
            return REGION_CUSTOM, resolve_hostnames(self._config.candidates.hostnames, catalog)

        region = self._config.candidates.region
        candidates = filter_candidates_by_region(catalog, region)
        if not candidates:
            raise RuntimeError(f"no Privado servers matched region {region!r}")
        return region, candidates

    def switch_to_hostname(self, hostname: str, *, current_settings: dict[str, Any] | None = None) -> str:
        normalized_hostname = hostname.lower()
        if self._config.candidates.hostnames and normalized_hostname not in self._config.candidates.hostnames:
            raise ValueError(
                f"{normalized_hostname!r} is not in candidates.hostnames; "
                "add it to the shortlist before forcing a switch"
            )
        if current_settings is None:
            current_settings = self._client.get_vpn_settings()
        updated_settings = rewrite_settings_for_hostname(current_settings, normalized_hostname)
        self._client.put_vpn_settings(updated_settings)
        self._client.wait_for_running()
        return normalized_hostname


def best_result(results: list[ProbeResult]) -> ProbeResult | None:
    successful = [result for result in results if result.success]
    if not successful:
        return None
    successful.sort(key=lambda result: result.throughput_bps, reverse=True)
    return successful[0]


def fastest_payload(benchmark_run: BenchmarkRun) -> dict[str, Any]:
    winner = best_result(benchmark_run.results)
    return {
        "current_hostname": benchmark_run.current_hostname,
        "fastest_hostname": winner.hostname if winner is not None else None,
        "throughput_bps": winner.throughput_bps if winner is not None else None,
        "throughput_mb_per_s": winner.throughput_mb_per_s if winner is not None else None,
        "throughput_mbps": winner.throughput_mbps if winner is not None else None,
        "benchmark_url": winner.benchmark_url if winner is not None else None,
        "candidate_count": benchmark_run.candidate_count,
        "region": benchmark_run.region,
        "results": [result.to_dict() for result in benchmark_run.results],
    }


def pick_winner(
    results: list[ProbeResult],
    *,
    current_hostname: str | None,
    threshold: float,
    startup: bool,
) -> tuple[ProbeResult | None, bool, str]:
    winner = best_result(results)
    if winner is None:
        return None, False, "all probes failed"

    successful = [result for result in results if result.success]
    if startup:
        if current_hostname == winner.hostname:
            return winner, False, "startup winner already pinned in Gluetun"
        return winner, True, "startup picked the fastest server"

    if current_hostname is None:
        return winner, True, "no current Gluetun hostname was pinned"

    if winner.hostname == current_hostname:
        return winner, False, "current Gluetun hostname remains the fastest"

    current_result = next((result for result in successful if result.hostname == current_hostname), None)
    if current_result is None:
        return winner, True, "current Gluetun hostname did not benchmark successfully"

    if winner.throughput_bps <= current_result.throughput_bps * threshold:
        return current_result, False, "challenger did not beat the current hostname by the switch threshold"

    return winner, True, "found a sufficiently faster server"


def current_gluetun_hostname(settings: dict[str, Any]) -> str | None:
    provider = settings.get("provider", {})
    if not isinstance(provider, dict):
        return None
    selection = provider.get("server_selection", {})
    if not isinstance(selection, dict):
        return None
    hostnames = selection.get("hostnames")
    if not isinstance(hostnames, list) or len(hostnames) != 1:
        return None
    hostname = str(hostnames[0]).strip().lower()
    if hostname == "":
        return None
    return hostname


def _match_by_ip(public_ip: str, catalog: list[ServerCandidate]) -> ServerCandidate | None:
    exact = next((c for c in catalog if c.ip == public_ip), None)
    if exact:
        return exact
    prefix = public_ip.rsplit(".", 1)[0] + "."
    return next((c for c in catalog if c.ip.startswith(prefix)), None)


def rewrite_settings_for_hostname(settings: dict[str, Any], hostname: str) -> dict[str, Any]:
    updated_settings = deep_copy(settings)
    updated_settings["type"] = "openvpn"
    provider = updated_settings.setdefault("provider", {})
    if not isinstance(provider, dict):
        raise ValueError("Gluetun settings provider field is not an object")
    provider["name"] = "privado"
    selection = provider.setdefault("server_selection", {})
    if not isinstance(selection, dict):
        raise ValueError("Gluetun settings provider.server_selection field is not an object")
    selection["vpn"] = "openvpn"
    selection["hostnames"] = [hostname]
    for key in ("countries", "categories", "regions", "cities", "isps", "names", "numbers"):
        selection[key] = []
    return updated_settings


def deep_copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: deep_copy(child) for key, child in value.items()}
    if isinstance(value, list):
        return [deep_copy(item) for item in value]
    return value


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def describe_scope(region: str, candidate_count: int) -> str:
    noun = "host" if candidate_count == 1 else "hosts"
    if region == REGION_CUSTOM:
        return f"{candidate_count} custom {noun}"
    noun = "server" if candidate_count == 1 else "servers"
    return f"{region} {noun}"

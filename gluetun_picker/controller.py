from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import time
from typing import Any, Callable

from .config import AppConfig
from .gluetun_api import GluetunClient
from .models import ProbeResult, ProbeSpec, ServerCandidate
from .privado import fetch_catalog, resolve_hostnames
from .runtime import ContainerRuntime
from .state import AppState, StateStore


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SweepOutcome:
    recommended_hostname: str | None
    applied_hostname: str | None
    switched: bool
    reason: str
    results: list[ProbeResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommended_hostname": self.recommended_hostname,
            "applied_hostname": self.applied_hostname,
            "switched": self.switched,
            "reason": self.reason,
            "results": [result.to_dict() for result in self.results],
        }


class Controller:
    def __init__(
        self,
        config: AppConfig,
        *,
        client: GluetunClient | None = None,
        runtime: ContainerRuntime | None = None,
        state_store: StateStore | None = None,
        catalog_fetcher: Callable[[float], list[ServerCandidate]] = fetch_catalog,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self._config = config
        self._client = client or GluetunClient(config.gluetun)
        self._runtime = runtime or ContainerRuntime(config.runtime)
        self._state_store = state_store or StateStore(config.state.filepath)
        self._catalog_fetcher = catalog_fetcher
        self._sleep = sleeper

    def run_forever(self) -> None:
        first_cycle = True
        while True:
            outcome = self.run_cycle(startup=first_cycle, apply=True)
            LOGGER.info("cycle finished: %s", outcome.reason)
            first_cycle = False
            self._sleep(self._config.benchmark.interval_seconds)

    def run_cycle(self, *, startup: bool, apply: bool) -> SweepOutcome:
        results = self.benchmark_candidates()
        current_settings = self._client.get_vpn_settings()
        current_hostname = current_gluetun_hostname(current_settings)
        winner, should_switch, reason = pick_winner(
            results,
            current_hostname=current_hostname,
            threshold=self._config.benchmark.switch_threshold,
            startup=startup,
        )

        applied_hostname: str | None = current_hostname
        if apply and winner is not None and should_switch:
            applied_hostname = self.switch_to_hostname(winner.hostname, current_settings=current_settings)
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

        return SweepOutcome(
            recommended_hostname=winner.hostname if winner is not None else None,
            applied_hostname=applied_hostname,
            switched=bool(apply and winner is not None and should_switch),
            reason=reason,
            results=results,
        )

    def benchmark_candidates(self) -> list[ProbeResult]:
        candidates = self.resolve_candidates()
        results: list[ProbeResult] = []
        for candidate in candidates:
            LOGGER.info("probing %s (%s)", candidate.hostname, candidate.ip)
            spec = ProbeSpec(
                candidate=candidate,
                username=self._config.privado.username,
                password=self._config.privado.password,
                benchmark_urls=self._config.benchmark.urls,
                benchmark_duration_seconds=self._config.benchmark.duration_seconds,
                connect_timeout_seconds=self._config.benchmark.connect_timeout_seconds,
                openvpn_verbosity=self._config.benchmark.openvpn_verbosity,
            )
            result = self._runtime.run_probe(spec)
            if result.success:
                LOGGER.info(
                    "probe success for %s: %.0f B/s via %s",
                    result.hostname,
                    result.throughput_bps,
                    result.benchmark_url,
                )
            else:
                LOGGER.warning("probe failed for %s: %s", result.hostname, result.error)
            results.append(result)
        return results

    def resolve_candidates(self) -> list[ServerCandidate]:
        catalog = self._catalog_fetcher(self._config.benchmark.connect_timeout_seconds)
        if not self._config.candidates.hostnames:
            return catalog
        return resolve_hostnames(self._config.candidates.hostnames, catalog)

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

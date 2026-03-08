from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from standalone.gluetun_picker.config import (
    AppConfig,
    BenchmarkConfig,
    CatalogConfig,
    CandidatesConfig,
    GluetunConfig,
    PrivadoConfig,
    RuntimeConfig,
    StateConfig,
)
from standalone.gluetun_picker.controller import Controller, best_result, pick_winner, rewrite_settings_for_hostname
from standalone.gluetun_picker.models import ProbeResult, ServerCandidate
from standalone.gluetun_picker.state import StateStore


class FakeClient:
    def __init__(self, settings: dict):
        self.settings = deepcopy(settings)
        self.put_calls: list[dict] = []
        self.wait_calls = 0

    def get_vpn_settings(self) -> dict:
        return deepcopy(self.settings)

    def put_vpn_settings(self, settings: dict) -> str:
        self.settings = deepcopy(settings)
        self.put_calls.append(deepcopy(settings))
        return "settings updated"

    def wait_for_running(self) -> None:
        self.wait_calls += 1


class FakeRuntime:
    def __init__(self, results: dict[str, ProbeResult]):
        self.results = results
        self.probed_hostnames: list[str] = []

    def run_probe(self, spec) -> ProbeResult:
        self.probed_hostnames.append(spec.candidate.hostname)
        return self.results[spec.candidate.hostname]


def make_config(state_path: Path) -> AppConfig:
    return AppConfig(
        gluetun=GluetunConfig(base_url="http://127.0.0.1:8000"),
        runtime=RuntimeConfig(),
        privado=PrivadoConfig(username="user", password="pass"),
        candidates=CandidatesConfig(hostnames=["old-host", "fast-host"]),
        benchmark=BenchmarkConfig(
            urls=["https://example.com/file.bin"],
            duration_seconds=8.0,
            connect_timeout_seconds=30.0,
            interval_seconds=60.0,
            switch_threshold=1.10,
            openvpn_verbosity=3,
        ),
        state=StateConfig(filepath=state_path),
        catalog=CatalogConfig(filepath=state_path.with_name("servers.json")),
    )


def make_catalog() -> list[ServerCandidate]:
    return [
        ServerCandidate(hostname="old-host", ip="10.0.0.1", country="USA", city="New York"),
        ServerCandidate(hostname="fast-host", ip="10.0.0.2", country="USA", city="Miami"),
    ]


def make_result(hostname: str, throughput_bps: float, *, success: bool = True, error: str | None = None) -> ProbeResult:
    return ProbeResult(
        hostname=hostname,
        ip="10.0.0.1" if hostname == "old-host" else "10.0.0.2",
        country="USA",
        city="City",
        success=success,
        throughput_bps=throughput_bps,
        benchmark_url="https://example.com/file.bin" if success else None,
        bytes_downloaded=1024 if success else 0,
        elapsed_seconds=1.0 if success else 0.0,
        connect_seconds=2.0 if success else 0.0,
        error=error,
    )


class ControllerTests(unittest.TestCase):
    def test_best_result_returns_fastest_successful_probe(self) -> None:
        winner = best_result(
            [
                make_result("old-host", 100.0),
                make_result("fast-host", 200.0),
                make_result("failed-host", 0.0, success=False, error="timeout"),
            ]
        )
        self.assertIsNotNone(winner)
        self.assertEqual(winner.hostname, "fast-host")

    def test_resolve_candidates_uses_full_catalog_when_shortlist_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            config = make_config(state_path)
            config = AppConfig(
                gluetun=config.gluetun,
                runtime=config.runtime,
                privado=config.privado,
                candidates=CandidatesConfig(hostnames=[]),
                benchmark=config.benchmark,
                state=config.state,
                catalog=config.catalog,
            )
            controller = Controller(
                config,
                client=FakeClient({"provider": {"server_selection": {}}}),
                runtime=FakeRuntime(
                    {
                        "old-host": make_result("old-host", 100.0),
                        "fast-host": make_result("fast-host", 200.0),
                    }
                ),
                state_store=StateStore(state_path),
                catalog_fetcher=lambda **kwargs: make_catalog(),
            )

            region, candidates = controller.resolve_candidates()
            self.assertEqual(region, "north_america")
            self.assertEqual([candidate.hostname for candidate in candidates], ["old-host", "fast-host"])

    def test_rewrite_settings_for_hostname(self) -> None:
        settings = {
            "type": "wireguard",
            "provider": {
                "name": "mullvad",
                "server_selection": {
                    "hostnames": ["old-host"],
                    "countries": ["us"],
                    "categories": ["streaming"],
                    "regions": ["new york"],
                    "cities": ["new york"],
                    "isps": ["isp"],
                    "names": ["foo"],
                    "numbers": [1],
                },
            },
        }
        rewritten = rewrite_settings_for_hostname(settings, "fast-host")
        self.assertEqual(rewritten["type"], "openvpn")
        self.assertEqual(rewritten["provider"]["name"], "privado")
        self.assertEqual(rewritten["provider"]["server_selection"]["hostnames"], ["fast-host"])
        self.assertEqual(rewritten["provider"]["server_selection"]["countries"], [])
        self.assertEqual(rewritten["provider"]["server_selection"]["categories"], [])
        self.assertEqual(rewritten["provider"]["server_selection"]["numbers"], [])

    def test_pick_winner_keeps_current_when_threshold_not_met(self) -> None:
        winner, should_switch, reason = pick_winner(
            [make_result("old-host", 100.0), make_result("fast-host", 105.0)],
            current_hostname="old-host",
            threshold=1.10,
            startup=False,
        )
        self.assertEqual(winner.hostname, "old-host")
        self.assertFalse(should_switch)
        self.assertIn("threshold", reason)

    def test_pick_winner_switches_when_threshold_met(self) -> None:
        winner, should_switch, reason = pick_winner(
            [make_result("old-host", 100.0), make_result("fast-host", 120.0)],
            current_hostname="old-host",
            threshold=1.10,
            startup=False,
        )
        self.assertEqual(winner.hostname, "fast-host")
        self.assertTrue(should_switch)
        self.assertIn("faster", reason)

    def test_run_cycle_switches_on_startup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            client = FakeClient(
                {
                    "type": "openvpn",
                    "provider": {
                        "name": "privado",
                        "server_selection": {"hostnames": ["old-host"]},
                    },
                }
            )
            runtime = FakeRuntime(
                {
                    "old-host": make_result("old-host", 100.0),
                    "fast-host": make_result("fast-host", 200.0),
                }
            )
            controller = Controller(
                make_config(state_path),
                client=client,
                runtime=runtime,
                state_store=StateStore(state_path),
                catalog_fetcher=lambda **kwargs: make_catalog(),
            )

            outcome = controller.run_cycle(startup=True, apply=True)

            self.assertTrue(outcome.switched)
            self.assertEqual(outcome.applied_hostname, "fast-host")
            self.assertEqual(client.settings["provider"]["server_selection"]["hostnames"], ["fast-host"])
            self.assertEqual(client.wait_calls, 1)
            self.assertEqual(runtime.probed_hostnames, ["old-host", "fast-host"])

    def test_run_cycle_keeps_current_on_periodic_retest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            client = FakeClient(
                {
                    "type": "openvpn",
                    "provider": {
                        "name": "privado",
                        "server_selection": {"hostnames": ["old-host"]},
                    },
                }
            )
            runtime = FakeRuntime(
                {
                    "old-host": make_result("old-host", 100.0),
                    "fast-host": make_result("fast-host", 105.0),
                }
            )
            controller = Controller(
                make_config(state_path),
                client=client,
                runtime=runtime,
                state_store=StateStore(state_path),
                catalog_fetcher=lambda **kwargs: make_catalog(),
            )

            outcome = controller.run_cycle(startup=False, apply=True)

            self.assertFalse(outcome.switched)
            self.assertEqual(client.wait_calls, 0)
            self.assertEqual(len(client.put_calls), 0)

    def test_run_cycle_leaves_gluetun_unchanged_when_all_probes_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            client = FakeClient(
                {
                    "type": "openvpn",
                    "provider": {
                        "name": "privado",
                        "server_selection": {"hostnames": ["old-host"]},
                    },
                }
            )
            runtime = FakeRuntime(
                {
                    "old-host": make_result("old-host", 0.0, success=False, error="auth failed"),
                    "fast-host": make_result("fast-host", 0.0, success=False, error="timeout"),
                }
            )
            controller = Controller(
                make_config(state_path),
                client=client,
                runtime=runtime,
                state_store=StateStore(state_path),
                catalog_fetcher=lambda **kwargs: make_catalog(),
            )

            outcome = controller.run_cycle(startup=False, apply=True)

            self.assertFalse(outcome.switched)
            self.assertIsNone(outcome.recommended_hostname)
            self.assertEqual(len(client.put_calls), 0)


if __name__ == "__main__":
    unittest.main()

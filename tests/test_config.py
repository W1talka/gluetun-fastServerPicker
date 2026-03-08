from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from standalone.gluetun_picker.config import load_config, load_config_from_env


def write_config(path: Path, extra: str = "") -> Path:
    path.write_text(
        "\n".join(
            [
                "[gluetun]",
                'base_url = "http://127.0.0.1:8000"',
                "",
                "[privado]",
                'username = "user"',
                'password = "pass"',
                "",
                "[candidates]",
                'hostnames = ["us-nyc-001.privado.io"]',
                "",
                "[benchmark]",
                'urls = ["https://example.com/file.bin"]',
                "",
                "[state]",
                'filepath = "state.json"',
                extra.strip(),
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


class LoadConfigTests(unittest.TestCase):
    def test_load_config_resolves_relative_state_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = write_config(Path(temp_dir) / "config.toml")
            config = load_config(config_path)
            self.assertEqual(config.state.filepath, Path(temp_dir) / "state.json")
            self.assertEqual(config.catalog.filepath, Path(temp_dir) / "servers.json")
            self.assertEqual(config.catalog.max_age_seconds, 604800.0)

    def test_load_config_allows_empty_candidate_hostnames(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            write_config(config_path)
            config_path.write_text(
                config_path.read_text(encoding="utf-8").replace(
                    'hostnames = ["us-nyc-001.privado.io"]',
                    "hostnames = []",
                ),
                encoding="utf-8",
            )
            config = load_config(config_path)
            self.assertEqual(config.candidates.hostnames, [])

    def test_load_config_requires_benchmark_urls(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            write_config(config_path)
            config_path.write_text(
                config_path.read_text(encoding="utf-8").replace(
                    'urls = ["https://example.com/file.bin"]',
                    "urls = []",
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "benchmark.urls"):
                load_config(config_path)

    def test_load_config_from_env(self) -> None:
        env = {
            "PICKER_GLUETUN_BASE_URL": "http://gluetun.example:8000",
            "OPENVPN_USER": "user",
            "OPENVPN_PASSWORD": "pass",
            "PICKER_CANDIDATE_HOSTNAMES": "us-nyc-001.privado.io,us-mia-001.privado.io",
            "PICKER_BENCHMARK_URLS": "https://example.com/file.bin,https://example.com/file2.bin",
            "PICKER_STATE_FILEPATH": "/tmp/state.json",
        }
        with patch.dict("os.environ", env, clear=True):
            config = load_config_from_env()

        self.assertEqual(config.gluetun.base_url, "http://gluetun.example:8000")
        self.assertEqual(config.privado.username, "user")
        self.assertEqual(config.candidates.hostnames, ["us-nyc-001.privado.io", "us-mia-001.privado.io"])
        self.assertEqual(config.catalog.filepath, Path("/tmp/servers.json"))
        self.assertEqual(
            config.benchmark.urls,
            ["https://example.com/file.bin", "https://example.com/file2.bin"],
        )

    def test_load_config_from_env_allows_catalog_overrides(self) -> None:
        env = {
            "OPENVPN_USER": "user",
            "OPENVPN_PASSWORD": "pass",
            "PICKER_BENCHMARK_URLS": "https://example.com/file.bin",
            "PICKER_STATE_FILEPATH": "/tmp/state.json",
            "PICKER_CATALOG_FILEPATH": "/tmp/catalog/servers.json",
            "PICKER_CATALOG_MAX_AGE_SECONDS": "3600",
        }
        with patch.dict("os.environ", env, clear=True):
            config = load_config_from_env()

        self.assertEqual(config.catalog.filepath, Path("/tmp/catalog/servers.json"))
        self.assertEqual(config.catalog.max_age_seconds, 3600.0)


if __name__ == "__main__":
    unittest.main()

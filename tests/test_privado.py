from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time
import unittest
import urllib.error
from unittest.mock import patch

from standalone.gluetun_picker.privado import fetch_catalog


def make_payload(hostname: str, ip: str) -> dict:
    return {
        "servers": [
            {
                "hostname": hostname,
                "ip": ip,
                "country": "USA",
                "city": "New York",
            }
        ]
    }


def write_cache(path: Path, payload: dict, *, age_seconds: float = 0.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    mtime = time.time() - age_seconds
    os.utime(path, (mtime, mtime))


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, *args, **kwargs) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class PrivadoCatalogCacheTests(unittest.TestCase):
    def test_fetch_catalog_uses_fresh_cache_without_network(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "servers.json"
            write_cache(cache_path, make_payload("cached-host", "10.0.0.1"))

            with patch("urllib.request.urlopen") as urlopen:
                candidates = fetch_catalog(cache_path=cache_path, max_age_seconds=604800.0)

            self.assertEqual([candidate.hostname for candidate in candidates], ["cached-host"])
            urlopen.assert_not_called()

    def test_fetch_catalog_refreshes_stale_cache_from_network(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "servers.json"
            write_cache(cache_path, make_payload("stale-host", "10.0.0.1"), age_seconds=7200)
            live_payload = make_payload("live-host", "10.0.0.2")

            with patch("urllib.request.urlopen", return_value=FakeResponse(live_payload)) as urlopen:
                candidates = fetch_catalog(cache_path=cache_path, max_age_seconds=60.0)

            self.assertEqual([candidate.hostname for candidate in candidates], ["live-host"])
            self.assertEqual(json.loads(cache_path.read_text(encoding="utf-8")), live_payload)
            urlopen.assert_called_once()

    def test_fetch_catalog_falls_back_to_stale_cache_on_network_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "servers.json"
            write_cache(cache_path, make_payload("stale-host", "10.0.0.1"), age_seconds=7200)

            with patch(
                "urllib.request.urlopen",
                side_effect=urllib.error.URLError("temporary failure"),
            ):
                candidates = fetch_catalog(cache_path=cache_path, max_age_seconds=60.0)

            self.assertEqual([candidate.hostname for candidate in candidates], ["stale-host"])


if __name__ == "__main__":
    unittest.main()

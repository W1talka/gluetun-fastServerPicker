from __future__ import annotations

from base64 import b64encode
from typing import Any
import json
import time
import urllib.error
import urllib.request

from .config import GluetunConfig


class GluetunClient:
    def __init__(self, config: GluetunConfig):
        self._config = config

    def get_vpn_settings(self) -> dict[str, Any]:
        return self._request_json("GET", "/v1/vpn/settings")

    def put_vpn_settings(self, settings: dict[str, Any]) -> str:
        response = self._request_text("PUT", "/v1/vpn/settings", settings)
        return response.strip()

    def get_public_ip(self) -> str:
        data = self._request_json("GET", "/v1/publicip/ip")
        return str(data["public_ip"])

    def get_vpn_status(self) -> str:
        data = self._request_json("GET", "/v1/vpn/status")
        return str(data["status"])

    def wait_for_running(self) -> None:
        deadline = time.monotonic() + self._config.status_timeout_seconds
        last_status = "unknown"
        while time.monotonic() < deadline:
            last_status = self.get_vpn_status()
            if last_status == "running":
                return
            time.sleep(self._config.status_poll_interval_seconds)
        raise TimeoutError(f"Gluetun did not reach running state before timeout, last status was {last_status!r}")

    def _request_json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        response = self._request(method, path, payload)
        return json.loads(response)

    def _request_text(self, method: str, path: str, payload: dict[str, Any] | None = None) -> str:
        return self._request(method, path, payload)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> str:
        body = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        headers.update(self._config.headers)

        if self._config.username is not None and self._config.password is not None:
            token = f"{self._config.username}:{self._config.password}".encode("utf-8")
            headers["Authorization"] = "Basic " + b64encode(token).decode("ascii")

        request = urllib.request.Request(
            self._config.base_url + path,
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self._config.status_timeout_seconds) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Gluetun API {method} {path} failed with {exc.code}: {details}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Gluetun API {method} {path} failed: {exc.reason}") from exc

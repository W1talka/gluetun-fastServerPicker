from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
import re
from typing import Any
import json
import urllib.error
import urllib.request

from .models import ServerCandidate


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PRIVADO_CATALOG_URL = "https://privadovpn.com/apps/servers_export.json"
REPO_PRIVADO_UPDATER = REPO_ROOT / "internal" / "provider" / "privado" / "updater" / "servers.go"


def fetch_catalog(timeout: float = 30.0) -> list[ServerCandidate]:
    request = urllib.request.Request(discover_catalog_url(), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.URLError as exc:
        raise RuntimeError(f"failed to fetch Privado server catalog: {exc.reason}") from exc

    servers = payload.get("servers", [])
    if not isinstance(servers, list):
        raise RuntimeError("Privado server catalog returned an unexpected payload")

    candidates: list[ServerCandidate] = []
    for raw_server in servers:
        if not isinstance(raw_server, dict):
            continue
        candidates.append(_server_candidate(raw_server))
    if not candidates:
        raise RuntimeError("Privado server catalog did not contain any servers")
    return candidates


def discover_catalog_url() -> str:
    if not REPO_PRIVADO_UPDATER.exists():
        return DEFAULT_PRIVADO_CATALOG_URL

    source = REPO_PRIVADO_UPDATER.read_text(encoding="utf-8")
    match = re.search(r'const url = "([^"]+)"', source)
    if match is None:
        return DEFAULT_PRIVADO_CATALOG_URL
    return match.group(1)


def resolve_hostnames(hostnames: list[str], catalog: Iterable[ServerCandidate]) -> list[ServerCandidate]:
    by_hostname = {candidate.hostname.lower(): candidate for candidate in catalog}
    resolved: list[ServerCandidate] = []
    missing: list[str] = []
    for hostname in hostnames:
        candidate = by_hostname.get(hostname.lower())
        if candidate is None:
            missing.append(hostname)
            continue
        resolved.append(candidate)

    if missing:
        raise RuntimeError(
            "the following configured hostnames were not found in the Privado catalog: " + ", ".join(missing)
        )
    return resolved


def _server_candidate(raw_server: dict[str, Any]) -> ServerCandidate:
    hostname = str(raw_server.get("hostname", "")).strip().lower()
    ip = str(raw_server.get("ip", "")).strip()
    if not hostname or not ip:
        raise RuntimeError("Privado server catalog contained a server without hostname or IP")
    return ServerCandidate(
        hostname=hostname,
        ip=ip,
        country=str(raw_server.get("country", "")).strip(),
        city=str(raw_server.get("city", "")).strip(),
    )

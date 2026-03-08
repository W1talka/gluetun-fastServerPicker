from __future__ import annotations

from collections.abc import Iterable
import logging
import tempfile
from pathlib import Path
import re
import time
from typing import Any
import json
import urllib.error
import urllib.request

from .models import ServerCandidate
from .regions import REGION_ALL, REGION_COUNTRIES


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PRIVADO_CATALOG_URL = "https://privadovpn.com/apps/servers_export.json"
REPO_PRIVADO_UPDATER = REPO_ROOT / "internal" / "provider" / "privado" / "updater" / "servers.go"
LOGGER = logging.getLogger(__name__)


def fetch_catalog(
    timeout: float = 30.0,
    *,
    cache_path: Path | None = None,
    max_age_seconds: float = 604800.0,
) -> list[ServerCandidate]:
    if cache_path is not None:
        try:
            cached_catalog = _load_cached_catalog(cache_path, max_age_seconds=max_age_seconds, allow_stale=False)
        except RuntimeError as exc:
            LOGGER.warning("ignoring invalid cached Privado server catalog at %s: %s", cache_path, exc)
        else:
            if cached_catalog is not None:
                LOGGER.info("using cached Privado server catalog from %s", cache_path)
                return cached_catalog

    request = urllib.request.Request(discover_catalog_url(), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.URLError as exc:
        if cache_path is not None:
            try:
                cached_catalog = _load_cached_catalog(cache_path, max_age_seconds=max_age_seconds, allow_stale=True)
            except RuntimeError as cache_exc:
                raise RuntimeError(
                    f"failed to fetch Privado server catalog: {exc.reason}; cached catalog at {cache_path} is unusable: {cache_exc}"
                ) from exc
            else:
                if cached_catalog is not None:
                    LOGGER.warning(
                        "failed to fetch live Privado server catalog, using stale cache at %s: %s",
                        cache_path,
                        exc.reason,
                    )
                    return cached_catalog
        raise RuntimeError(f"failed to fetch Privado server catalog: {exc.reason}") from exc

    try:
        candidates = _payload_to_candidates(payload)
    except RuntimeError as exc:
        if cache_path is not None:
            try:
                cached_catalog = _load_cached_catalog(cache_path, max_age_seconds=max_age_seconds, allow_stale=True)
            except RuntimeError as cache_exc:
                raise RuntimeError(
                    f"live Privado server catalog is invalid: {exc}; cached catalog at {cache_path} is unusable: {cache_exc}"
                ) from exc
            else:
                if cached_catalog is not None:
                    LOGGER.warning(
                        "live Privado server catalog was invalid, using stale cache at %s: %s",
                        cache_path,
                        exc,
                    )
                    return cached_catalog
        raise

    if cache_path is not None:
        _write_cache(cache_path, payload)

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


def filter_candidates_by_region(catalog: Iterable[ServerCandidate], region: str) -> list[ServerCandidate]:
    candidates = list(catalog)
    if region == REGION_ALL:
        return candidates

    countries = REGION_COUNTRIES[region]
    return [candidate for candidate in candidates if candidate.country in countries]


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


def _load_cached_catalog(
    cache_path: Path,
    *,
    max_age_seconds: float,
    allow_stale: bool,
) -> list[ServerCandidate] | None:
    if not cache_path.exists():
        return None

    if not allow_stale and _cache_age_seconds(cache_path) > max_age_seconds:
        return None

    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"cached catalog is not valid JSON: {exc.msg}") from exc
    return _payload_to_candidates(payload)


def _cache_age_seconds(cache_path: Path) -> float:
    return max(0.0, time.time() - cache_path.stat().st_mtime)


def _payload_to_candidates(payload: Any) -> list[ServerCandidate]:
    if not isinstance(payload, dict):
        raise RuntimeError("Privado server catalog returned an unexpected payload")

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


def _write_cache(cache_path: Path, payload: Any) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        delete=False,
        dir=cache_path.parent,
        prefix=cache_path.name + ".",
        suffix=".tmp",
    ) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temp_path = Path(handle.name)
    temp_path.replace(cache_path)

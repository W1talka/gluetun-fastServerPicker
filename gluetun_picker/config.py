from __future__ import annotations

from dataclasses import dataclass, field, replace
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
import tomllib

from .regions import DEFAULT_REGION, INPUT_REGIONS


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKER_DOCKERFILE = REPO_ROOT / "worker.Dockerfile"


@dataclass(frozen=True)
class GluetunConfig:
    base_url: str
    username: str | None = None
    password: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    status_timeout_seconds: float = 120.0
    status_poll_interval_seconds: float = 2.0

    def validate(self) -> None:
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"gluetun.base_url must be a valid http/https URL, got {self.base_url!r}")

        if (self.username is None) != (self.password is None):
            raise ValueError("gluetun.username and gluetun.password must be set together")

        if self.status_timeout_seconds <= 0:
            raise ValueError("gluetun.status_timeout_seconds must be greater than 0")

        if self.status_poll_interval_seconds <= 0:
            raise ValueError("gluetun.status_poll_interval_seconds must be greater than 0")

        for key, value in self.headers.items():
            if not key or not value:
                raise ValueError("gluetun.headers cannot contain empty keys or values")


@dataclass(frozen=True)
class RuntimeConfig:
    binary: str = "docker"
    worker_image: str = "gluetun-privado-probe:latest"
    build_if_missing: bool = True
    build_context: Path = REPO_ROOT
    worker_dockerfile: Path = DEFAULT_WORKER_DOCKERFILE

    def validate(self) -> None:
        if self.binary not in {"docker", "podman"}:
            raise ValueError("runtime.binary must be either 'docker' or 'podman'")

        if not self.worker_image:
            raise ValueError("runtime.worker_image cannot be empty")

        if not self.build_context:
            raise ValueError("runtime.build_context cannot be empty")

        if not self.worker_dockerfile:
            raise ValueError("runtime.worker_dockerfile cannot be empty")


@dataclass(frozen=True)
class PrivadoConfig:
    username: str
    password: str

    def validate(self) -> None:
        if not self.username:
            raise ValueError("privado.username cannot be empty")
        if not self.password:
            raise ValueError("privado.password cannot be empty")


@dataclass(frozen=True)
class CandidatesConfig:
    hostnames: list[str]
    region: str = DEFAULT_REGION
    random_order: bool = True

    def validate(self) -> None:
        if self.region not in INPUT_REGIONS:
            raise ValueError(
                "candidates.region must be one of: " + ", ".join(INPUT_REGIONS)
            )

        normalized: set[str] = set()
        for hostname in self.hostnames:
            if not hostname:
                raise ValueError("candidates.hostnames cannot contain empty values")
            lowered = hostname.lower()
            if lowered in normalized:
                raise ValueError(f"candidates.hostnames contains a duplicate hostname: {hostname}")
            normalized.add(lowered)


@dataclass(frozen=True)
class BenchmarkConfig:
    urls: list[str]
    duration_seconds: float = 8.0
    connect_timeout_seconds: float = 45.0
    interval_seconds: float = 21600.0
    switch_threshold: float = 1.10
    openvpn_verbosity: int = 3

    def validate(self) -> None:
        if not self.urls:
            raise ValueError("benchmark.urls must contain at least one URL")

        for url in self.urls:
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"benchmark.urls must contain valid http/https URLs, got {url!r}")

        if self.duration_seconds <= 0:
            raise ValueError("benchmark.duration_seconds must be greater than 0")

        if self.connect_timeout_seconds <= 0:
            raise ValueError("benchmark.connect_timeout_seconds must be greater than 0")

        if self.interval_seconds <= 0:
            raise ValueError("benchmark.interval_seconds must be greater than 0")

        if self.switch_threshold < 1.0:
            raise ValueError("benchmark.switch_threshold must be at least 1.0")

        if self.openvpn_verbosity < 0:
            raise ValueError("benchmark.openvpn_verbosity cannot be negative")


@dataclass(frozen=True)
class StateConfig:
    filepath: Path

    def validate(self) -> None:
        if not self.filepath:
            raise ValueError("state.filepath cannot be empty")


@dataclass(frozen=True)
class CatalogConfig:
    filepath: Path
    max_age_seconds: float = 604800.0

    def validate(self) -> None:
        if not self.filepath:
            raise ValueError("catalog.filepath cannot be empty")

        if self.max_age_seconds <= 0:
            raise ValueError("catalog.max_age_seconds must be greater than 0")


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str = ""
    chat_id: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.bot_token) and bool(self.chat_id)

    def validate(self) -> None:
        if bool(self.bot_token) != bool(self.chat_id):
            raise ValueError("telegram.bot_token and telegram.chat_id must be set together")


@dataclass(frozen=True)
class AppConfig:
    gluetun: GluetunConfig
    runtime: RuntimeConfig
    privado: PrivadoConfig
    candidates: CandidatesConfig
    benchmark: BenchmarkConfig
    state: StateConfig
    catalog: CatalogConfig
    telegram: TelegramConfig = field(default_factory=TelegramConfig)

    def validate(self) -> None:
        self.gluetun.validate()
        self.runtime.validate()
        self.privado.validate()
        self.candidates.validate()
        self.benchmark.validate()
        self.state.validate()
        self.catalog.validate()
        self.telegram.validate()


def load_config(path: str | Path | None = None) -> AppConfig:
    if path is None:
        default_path = REPO_ROOT / "config.toml"
        if default_path.exists():
            return _load_config_from_file(default_path)
        return load_config_from_env()

    config_path = Path(path).expanduser().resolve()
    if config_path.exists():
        return _load_config_from_file(config_path)

    raise FileNotFoundError(f"config file does not exist: {config_path}")


def _load_config_from_file(path: str | Path) -> AppConfig:
    config_path = Path(path).expanduser().resolve()
    raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    config_dir = config_path.parent

    gluetun_raw = _mapping(raw, "gluetun")
    runtime_raw = _mapping(raw, "runtime")
    privado_raw = _mapping(raw, "privado")
    candidates_raw = _mapping(raw, "candidates")
    benchmark_raw = _mapping(raw, "benchmark")
    state_raw = _mapping(raw, "state")
    catalog_raw = _mapping(raw, "catalog")
    state_filepath = _resolve_path(state_raw.get("filepath"), config_dir, config_dir / "state.json")

    config = AppConfig(
        gluetun=GluetunConfig(
            base_url=str(gluetun_raw.get("base_url", "http://127.0.0.1:8000")).rstrip("/"),
            username=_optional_string(gluetun_raw.get("username")),
            password=_optional_string(gluetun_raw.get("password")),
            headers={str(key): str(value) for key, value in _mapping(gluetun_raw, "headers", required=False).items()},
            status_timeout_seconds=float(gluetun_raw.get("status_timeout_seconds", 120.0)),
            status_poll_interval_seconds=float(gluetun_raw.get("status_poll_interval_seconds", 2.0)),
        ),
        runtime=RuntimeConfig(
            binary=str(runtime_raw.get("binary", "docker")),
            worker_image=str(runtime_raw.get("worker_image", "gluetun-privado-probe:latest")),
            build_if_missing=bool(runtime_raw.get("build_if_missing", True)),
            build_context=_resolve_path(runtime_raw.get("build_context"), config_dir, REPO_ROOT),
            worker_dockerfile=_resolve_path(
                runtime_raw.get("worker_dockerfile"), config_dir, DEFAULT_WORKER_DOCKERFILE
            ),
        ),
        privado=PrivadoConfig(
            username=str(privado_raw.get("username", "")),
            password=str(privado_raw.get("password", "")),
        ),
        candidates=CandidatesConfig(
            hostnames=[str(hostname).strip().lower() for hostname in candidates_raw.get("hostnames", [])],
            region=str(candidates_raw.get("region", DEFAULT_REGION)).strip().lower(),
            random_order=bool(candidates_raw.get("random_order", True)),
        ),
        benchmark=BenchmarkConfig(
            urls=[str(url).strip() for url in benchmark_raw.get("urls", [])],
            duration_seconds=float(benchmark_raw.get("duration_seconds", 8.0)),
            connect_timeout_seconds=float(benchmark_raw.get("connect_timeout_seconds", 45.0)),
            interval_seconds=float(benchmark_raw.get("interval_seconds", 21600.0)),
            switch_threshold=float(benchmark_raw.get("switch_threshold", 1.10)),
            openvpn_verbosity=int(benchmark_raw.get("openvpn_verbosity", 3)),
        ),
        state=StateConfig(
            filepath=state_filepath,
        ),
        catalog=CatalogConfig(
            filepath=_resolve_path(catalog_raw.get("filepath"), config_dir, state_filepath.with_name("servers.json")),
            max_age_seconds=float(catalog_raw.get("max_age_seconds", 604800.0)),
        ),
        telegram=TelegramConfig(
            bot_token=str(_mapping(raw, "telegram", required=False).get("bot_token", "")),
            chat_id=str(_mapping(raw, "telegram", required=False).get("chat_id", "")),
        ),
    )
    config.validate()
    return config


def load_config_from_env() -> AppConfig:
    config = AppConfig(
        gluetun=GluetunConfig(
            base_url=os.environ.get("PICKER_GLUETUN_BASE_URL", "http://127.0.0.1:8000").rstrip("/"),
            username=_optional_string(os.environ.get("PICKER_GLUETUN_USERNAME")),
            password=_optional_string(os.environ.get("PICKER_GLUETUN_PASSWORD")),
            headers=_parse_headers(os.environ.get("PICKER_GLUETUN_HEADERS", "")),
            status_timeout_seconds=_float_env("PICKER_GLUETUN_STATUS_TIMEOUT_SECONDS", 120.0),
            status_poll_interval_seconds=_float_env("PICKER_GLUETUN_STATUS_POLL_INTERVAL_SECONDS", 2.0),
        ),
        runtime=RuntimeConfig(
            binary=os.environ.get("PICKER_RUNTIME_BINARY", "docker"),
            worker_image=os.environ.get("PICKER_RUNTIME_WORKER_IMAGE", "gluetun-privado-probe:latest"),
            build_if_missing=_bool_env("PICKER_RUNTIME_BUILD_IF_MISSING", True),
            build_context=_resolve_path(
                os.environ.get("PICKER_RUNTIME_BUILD_CONTEXT"),
                REPO_ROOT,
                REPO_ROOT,
            ),
            worker_dockerfile=_resolve_path(
                os.environ.get("PICKER_RUNTIME_WORKER_DOCKERFILE"),
                REPO_ROOT,
                DEFAULT_WORKER_DOCKERFILE,
            ),
        ),
        privado=PrivadoConfig(
            username=(
                os.environ.get("PICKER_PRIVADO_USERNAME")
                or os.environ.get("OPENVPN_USER")
                or ""
            ),
            password=(
                os.environ.get("PICKER_PRIVADO_PASSWORD")
                or os.environ.get("OPENVPN_PASSWORD")
                or ""
            ),
        ),
        candidates=CandidatesConfig(
            hostnames=_csv_env("PICKER_CANDIDATE_HOSTNAMES", lowercase=True),
            region=os.environ.get("PICKER_REGION", DEFAULT_REGION).strip().lower(),
            random_order=_bool_env("PICKER_CANDIDATE_RANDOM", True),
        ),
        benchmark=BenchmarkConfig(
            urls=_csv_env("PICKER_BENCHMARK_URLS"),
            duration_seconds=_float_env("PICKER_BENCHMARK_DURATION_SECONDS", 8.0),
            connect_timeout_seconds=_float_env("PICKER_BENCHMARK_CONNECT_TIMEOUT_SECONDS", 45.0),
            interval_seconds=_float_env("PICKER_BENCHMARK_INTERVAL_SECONDS", 21600.0),
            switch_threshold=_float_env("PICKER_BENCHMARK_SWITCH_THRESHOLD", 1.10),
            openvpn_verbosity=_int_env("PICKER_OPENVPN_VERBOSITY", 3),
        ),
        state=StateConfig(
            filepath=_resolve_path(os.environ.get("PICKER_STATE_FILEPATH"), REPO_ROOT, REPO_ROOT / "data" / "state.json"),
        ),
        catalog=CatalogConfig(
            filepath=_resolve_path(
                os.environ.get("PICKER_CATALOG_FILEPATH"),
                REPO_ROOT,
                _resolve_path(os.environ.get("PICKER_STATE_FILEPATH"), REPO_ROOT, REPO_ROOT / "data" / "state.json")
                .with_name("servers.json"),
            ),
            max_age_seconds=_float_env("PICKER_CATALOG_MAX_AGE_SECONDS", 604800.0),
        ),
        telegram=TelegramConfig(
            bot_token=os.environ.get("PICKER_TELEGRAM_BOT_TOKEN", ""),
            chat_id=os.environ.get("PICKER_TELEGRAM_CHAT_ID", ""),
        ),
    )
    config.validate()
    return config


def override_region(config: AppConfig, region: str | None) -> AppConfig:
    if region is None:
        return config

    updated_config = replace(
        config,
        candidates=replace(config.candidates, region=region),
    )
    updated_config.validate()
    return updated_config


def _mapping(data: dict[str, Any], key: str, *, required: bool = True) -> dict[str, Any]:
    if key not in data:
        if required:
            return {}
        return {}

    value = data[key]
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be a TOML table")
    return value


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    if text == "":
        return None
    return text


def _resolve_path(value: Any, base_dir: Path, default: Path) -> Path:
    if value is None or value == "":
        return default.resolve()
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    return path


def _csv_env(key: str, *, lowercase: bool = False) -> list[str]:
    value = os.environ.get(key, "")
    if value == "":
        return []
    values = [part.strip() for part in value.split(",") if part.strip()]
    if lowercase:
        return [part.lower() for part in values]
    return values


def _float_env(key: str, default: float) -> float:
    value = os.environ.get(key)
    if value is None or value == "":
        return default
    return float(value)


def _int_env(key: str, default: int) -> int:
    value = os.environ.get(key)
    if value is None or value == "":
        return default
    return int(value)


def _bool_env(key: str, default: bool) -> bool:
    value = os.environ.get(key)
    if value is None or value == "":
        return default
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{key} must be a boolean-like value")


def _parse_headers(raw: str) -> dict[str, str]:
    if raw.strip() == "":
        return {}
    headers: dict[str, str] = {}
    for item in raw.split(","):
        pair = item.strip()
        if not pair:
            continue
        if "=" not in pair:
            raise ValueError("PICKER_GLUETUN_HEADERS entries must be in KEY=VALUE form")
        key, value = pair.split("=", 1)
        headers[key.strip()] = value.strip()
    return headers

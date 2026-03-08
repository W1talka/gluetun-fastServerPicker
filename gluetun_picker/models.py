from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def bytes_per_second_to_mb_per_second(value: float) -> float:
    return value / 1_000_000


def bytes_per_second_to_mbps(value: float) -> float:
    return value * 8 / 1_000_000


@dataclass(frozen=True)
class ServerCandidate:
    hostname: str
    ip: str
    country: str
    city: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "hostname": self.hostname,
            "ip": self.ip,
            "country": self.country,
            "city": self.city,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ServerCandidate":
        return cls(
            hostname=str(data["hostname"]),
            ip=str(data["ip"]),
            country=str(data.get("country", "")),
            city=str(data.get("city", "")),
        )


@dataclass(frozen=True)
class ProbeSpec:
    candidate: ServerCandidate
    username: str
    password: str
    benchmark_urls: list[str]
    benchmark_duration_seconds: float
    connect_timeout_seconds: float
    openvpn_verbosity: int = 3

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.to_dict(),
            "username": self.username,
            "password": self.password,
            "benchmark_urls": list(self.benchmark_urls),
            "benchmark_duration_seconds": self.benchmark_duration_seconds,
            "connect_timeout_seconds": self.connect_timeout_seconds,
            "openvpn_verbosity": self.openvpn_verbosity,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProbeSpec":
        return cls(
            candidate=ServerCandidate.from_dict(data["candidate"]),
            username=str(data["username"]),
            password=str(data["password"]),
            benchmark_urls=[str(url) for url in data["benchmark_urls"]],
            benchmark_duration_seconds=float(data["benchmark_duration_seconds"]),
            connect_timeout_seconds=float(data["connect_timeout_seconds"]),
            openvpn_verbosity=int(data.get("openvpn_verbosity", 3)),
        )


@dataclass(frozen=True)
class ProbeResult:
    hostname: str
    ip: str
    country: str
    city: str
    success: bool
    throughput_bps: float = 0.0
    benchmark_url: str | None = None
    bytes_downloaded: int = 0
    elapsed_seconds: float = 0.0
    connect_seconds: float = 0.0
    error: str | None = None

    @property
    def throughput_mb_per_s(self) -> float:
        return bytes_per_second_to_mb_per_second(self.throughput_bps)

    @property
    def throughput_mbps(self) -> float:
        return bytes_per_second_to_mbps(self.throughput_bps)

    def to_dict(self) -> dict[str, Any]:
        return {
            "hostname": self.hostname,
            "ip": self.ip,
            "country": self.country,
            "city": self.city,
            "success": self.success,
            "throughput_bps": self.throughput_bps,
            "throughput_mb_per_s": self.throughput_mb_per_s,
            "throughput_mbps": self.throughput_mbps,
            "benchmark_url": self.benchmark_url,
            "bytes_downloaded": self.bytes_downloaded,
            "elapsed_seconds": self.elapsed_seconds,
            "connect_seconds": self.connect_seconds,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProbeResult":
        return cls(
            hostname=str(data["hostname"]),
            ip=str(data["ip"]),
            country=str(data.get("country", "")),
            city=str(data.get("city", "")),
            success=bool(data["success"]),
            throughput_bps=float(data.get("throughput_bps", 0.0)),
            benchmark_url=data.get("benchmark_url"),
            bytes_downloaded=int(data.get("bytes_downloaded", 0)),
            elapsed_seconds=float(data.get("elapsed_seconds", 0.0)),
            connect_seconds=float(data.get("connect_seconds", 0.0)),
            error=data.get("error"),
        )

from __future__ import annotations

import json
from pathlib import Path
import subprocess

from .config import RuntimeConfig
from .models import ProbeResult, ProbeSpec


PROBE_DNS_SERVERS = ("1.1.1.1", "8.8.8.8")


class ContainerRuntime:
    def __init__(self, config: RuntimeConfig):
        self._config = config

    def ensure_worker_image(self) -> None:
        inspect = subprocess.run(
            [self._config.binary, "image", "inspect", self._config.worker_image],
            capture_output=True,
            text=True,
            check=False,
        )
        if inspect.returncode == 0:
            return
        if not self._config.build_if_missing:
            raise RuntimeError(
                f"worker image {self._config.worker_image!r} does not exist and runtime.build_if_missing is false"
            )
        self.build_worker_image()

    def build_worker_image(self) -> None:
        subprocess.run(
            [
                self._config.binary,
                "build",
                "-f",
                str(self._config.worker_dockerfile),
                "-t",
                self._config.worker_image,
                str(self._config.build_context),
            ],
            check=True,
        )

    def run_probe(self, spec: ProbeSpec) -> ProbeResult:
        self.ensure_worker_image()
        command = [
            self._config.binary,
            "run",
            "--rm",
            "--cap-add=NET_ADMIN",
            "--device",
            "/dev/net/tun",
            *self._dns_args(),
            "-e",
            "PYTHONUNBUFFERED=1",
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
            "-e",
            "GLUETUN_PICKER_PROBE_SPEC=" + json.dumps(spec.to_dict(), separators=(",", ":")),
            self._config.worker_image,
        ]
        timeout = int(spec.connect_timeout_seconds + spec.benchmark_duration_seconds + 30)
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        payload = self._extract_json_payload(completed.stdout)
        if payload is None:
            stderr = completed.stderr.strip()
            raise RuntimeError(
                f"probe container failed with exit code {completed.returncode}: {stderr or 'missing JSON output'}"
            )
        return ProbeResult.from_dict(json.loads(payload))

    @staticmethod
    def _dns_args() -> list[str]:
        args: list[str] = []
        for server in PROBE_DNS_SERVERS:
            args.extend(["--dns", server])
        return args

    @staticmethod
    def _extract_json_payload(stdout: str) -> str | None:
        lines = [line.strip() for line in stdout.splitlines() if line.strip()]
        if not lines:
            return None
        return lines[-1]

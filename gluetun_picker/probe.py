from __future__ import annotations

from queue import Empty, Queue
from threading import Thread
from typing import TextIO
import json
import logging
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

from .models import ProbeResult, ProbeSpec
from .openvpn import write_openvpn_files


LOGGER = logging.getLogger(__name__)
READY_LINE = "Initialization Sequence Completed"
FATAL_PATTERNS = ("AUTH_FAILED", "Options error:", "Exiting due to fatal error")


def run_probe_from_env() -> int:
    encoded_spec = os.environ.get("GLUETUN_PICKER_PROBE_SPEC")
    if not encoded_spec:
        raise RuntimeError("GLUETUN_PICKER_PROBE_SPEC is not set")
    spec = ProbeSpec.from_dict(json.loads(encoded_spec))
    result = run_probe(spec)
    print(json.dumps(result.to_dict(), sort_keys=True))
    return 0 if result.success else 1


def run_probe(spec: ProbeSpec) -> ProbeResult:
    with tempfile.TemporaryDirectory(prefix="gluetun-picker-") as temp_dir:
        workdir = Path(temp_dir)
        config_path, _ = write_openvpn_files(workdir, spec)
        process = subprocess.Popen(
            ["openvpn", "--config", str(config_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        queue: Queue[str | None] = Queue()
        reader = Thread(target=_pump_output, args=(process.stdout, queue), daemon=True)
        reader.start()
        started = time.monotonic()
        try:
            wait_for_tunnel(process, queue, spec.connect_timeout_seconds)
            connect_seconds = time.monotonic() - started
            throughput_bps, benchmark_url, bytes_downloaded, elapsed_seconds = measure_throughput(
                spec.benchmark_urls,
                duration_seconds=spec.benchmark_duration_seconds,
                connect_timeout_seconds=spec.connect_timeout_seconds,
            )
            return ProbeResult(
                hostname=spec.candidate.hostname,
                ip=spec.candidate.ip,
                country=spec.candidate.country,
                city=spec.candidate.city,
                success=True,
                throughput_bps=throughput_bps,
                benchmark_url=benchmark_url,
                bytes_downloaded=bytes_downloaded,
                elapsed_seconds=elapsed_seconds,
                connect_seconds=connect_seconds,
            )
        except Exception as exc:
            return ProbeResult(
                hostname=spec.candidate.hostname,
                ip=spec.candidate.ip,
                country=spec.candidate.country,
                city=spec.candidate.city,
                success=False,
                error=str(exc),
            )
        finally:
            terminate_openvpn(process)


def wait_for_tunnel(process: subprocess.Popen[str], queue: Queue[str | None], timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_line = ""
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"OpenVPN exited before the tunnel came up: {last_line or 'no output'}")

        try:
            line = queue.get(timeout=0.5)
        except Empty:
            continue

        if line is None:
            continue

        last_line = line
        LOGGER.debug("openvpn: %s", line)
        if READY_LINE in line:
            return
        if any(pattern in line for pattern in FATAL_PATTERNS):
            raise RuntimeError(f"OpenVPN failed while connecting: {line}")

    raise TimeoutError(f"OpenVPN did not report tunnel readiness within {timeout_seconds} seconds")


def measure_throughput(
    urls: list[str],
    *,
    duration_seconds: float,
    connect_timeout_seconds: float,
) -> tuple[float, str, int, float]:
    deadline = time.monotonic() + duration_seconds
    errors: list[str] = []
    for url in urls:
        bytes_downloaded = 0
        started_at: float | None = None
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            timeout = max(1.0, min(connect_timeout_seconds, remaining))
            try:
                request = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    if started_at is None:
                        started_at = time.monotonic()
                    while time.monotonic() < deadline:
                        chunk = response.read(128 * 1024)
                        if not chunk:
                            break
                        bytes_downloaded += len(chunk)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if bytes_downloaded == 0:
                    errors.append(f"{url}: {exc}")
                break

        if started_at is not None and bytes_downloaded > 0:
            elapsed = max(time.monotonic() - started_at, 1e-6)
            return float(bytes_downloaded) / elapsed, url, bytes_downloaded, elapsed

    if errors:
        raise RuntimeError("all benchmark URLs failed: " + "; ".join(errors))
    raise RuntimeError("benchmark completed without downloading any bytes")


def terminate_openvpn(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _pump_output(stream: TextIO | None, queue: Queue[str | None]) -> None:
    if stream is None:
        queue.put(None)
        return

    for line in stream:
        queue.put(line.strip())
    queue.put(None)

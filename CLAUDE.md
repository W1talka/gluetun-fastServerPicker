# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Gluetun Privado Picker — a standalone Python controller that benchmarks Privado VPN servers using temporary OpenVPN probe containers, then switches Gluetun to the fastest server via its control API. Zero external dependencies (pure Python 3.12+ stdlib).

## Commands

```bash
# Run locally (requires uv)
uv run python -m gluetun_picker <command>

# Key commands
uv run python -m gluetun_picker auto --limit 5      # One-shot benchmark + switch
uv run python -m gluetun_picker fastest --region europe --limit 10
uv run python -m gluetun_picker sweep                # Benchmark without switching
uv run python -m gluetun_picker run                  # Periodic loop
uv run python -m gluetun_picker switch --hostname us-nyc-001.privado.io

# Docker
docker compose run --rm picker fastest --limit 5
docker compose up -d
```

### Tests

Tests use `unittest` with fake collaborators (`FakeClient`, `FakeRuntime`). The import path in tests is `standalone.gluetun_picker.*` — tests expect a parent directory named `standalone` on `PYTHONPATH` (or the repo cloned into such a path).

```bash
# From parent of this repo, with the repo dir aliased/symlinked as "standalone":
python -m unittest discover -s standalone/tests
```

## Architecture

**Two-container model**: The controller (this process) orchestrates everything. For each server to benchmark, it spawns a short-lived **worker container** (`worker.Dockerfile`) that runs OpenVPN, downloads a test file, and returns throughput as JSON on stdout.

### Flow

1. **Resolve candidates** — fetch Privado server catalog (cached 7 days), filter by region or explicit hostnames
2. **Benchmark sequentially** — current Gluetun server always benchmarked first as baseline, then candidates one-at-a-time via worker containers
3. **Pick winner** — threshold-based switching (default 1.10x): only switch if challenger exceeds current × threshold
4. **Apply** — rewrite Gluetun settings via `PUT /v1/vpn/settings`, poll status until running
5. **Persist + notify** — atomic JSON state write, optional Telegram message

### Key modules

| Module | Role |
|---|---|
| `__main__.py` | CLI entry point, argparse subcommands |
| `controller.py` | Orchestration: benchmark loop, pick_winner logic, switch |
| `gluetun_api.py` | HTTP client for Gluetun control API (urllib-based) |
| `privado.py` | Fetch + filter Privado server catalog |
| `probe.py` | Worker-side: run OpenVPN, measure download throughput |
| `runtime.py` | Container runtime abstraction (docker/podman), auto-builds worker image |
| `config.py` | TOML + env var config loading (`PICKER_*` prefix), frozen dataclasses |
| `state.py` | JSON state persistence with atomic writes |
| `models.py` | Data classes: ProbeResult, ServerCandidate, ProbeSpec |
| `openvpn.py` | Generate OpenVPN client config with embedded Privado CA cert |
| `regions.py` | Region definitions (north_america, europe, all) with country lists |
| `telegram.py` | Optional Telegram notifications |

## Design Conventions

- **Frozen dataclasses** for all config and model types — mutate via `dataclasses.replace()`
- **Dependency injection** in Controller: `client`, `runtime`, `state_store`, `catalog_fetcher`, `sleeper` are all injectable for testing
- **Startup vs normal mode**: first cycle in `run_forever()` uses `startup=True` (always switch to fastest); subsequent cycles use `startup=False` (threshold-based)
- **All commands emit JSON** to stdout for scripting/monitoring
- **Config precedence**: env vars (`PICKER_*`) override TOML file values

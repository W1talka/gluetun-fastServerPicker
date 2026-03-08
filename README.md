# Gluetun Privado Picker

A standalone Python controller that benchmarks Privado VPN servers using temporary OpenVPN probe containers and uses Gluetun's control API to pin Gluetun to the fastest hostname.

Before benchmarking candidates, the picker queries Gluetun to find the current server and benchmarks it first as a baseline — so you always know if a candidate is actually faster than what you already have.

## What it touches

- It reads and writes `GET/PUT /v1/vpn/settings`
- It polls `GET /v1/vpn/status`
- It does not modify Gluetun source code or require a custom Gluetun build

## Requirements

- Python 3.12 or newer on the machine running the controller
- `docker` or `podman`
- Gluetun control server enabled
- Privado credentials
- Access to `/dev/net/tun` for the probe containers

## Setup

1. Copy [.env.example](.env.example) to `.env` and fill in your values.
2. Build the probe image, or let the controller auto-build it:

```bash
docker build -f worker.Dockerfile -t gluetun-privado-probe:latest .
```

## Gluetun Authentication

Recent Gluetun versions require authentication for the control server API. Generate an API key and add this environment variable to your Gluetun container:

```bash
# Generate a key
docker run --rm qmcgaw/gluetun genkey
```

```
HTTP_CONTROL_SERVER_AUTH_DEFAULT_ROLE={"auth":"apikey","apikey":"your-generated-key"}
```

Then set the matching key in the picker's `.env`:

```
PICKER_GLUETUN_HEADERS=x-api-key=your-generated-key
```

If you use the [Homepage](https://gethomepage.dev/) dashboard, add the same key to the Gluetun widget:

```yaml
widget:
    type: gluetun
    url: http://your-gluetun-host:8000
    key: your-generated-key
    version: 2
```

Other auth options:
- **Basic auth**: `{"auth":"basic","username":"user","password":"pass"}` — set `PICKER_GLUETUN_USERNAME` and `PICKER_GLUETUN_PASSWORD` in the picker (note: Homepage's Gluetun widget does not support basic auth)
- **No auth** (not recommended): `{"auth":"none"}`

## Commands

Run one benchmark round without changing Gluetun:

```bash
uv run python -m gluetun_picker sweep
```

Run a pure benchmark and print the current fastest hostname with throughput in both `MB/s` and `Mbps`:

```bash
uv run python -m gluetun_picker fastest
```

Restrict the benchmark to Europe or North America:

```bash
uv run python -m gluetun_picker fastest --region europe
uv run python -m gluetun_picker fastest --region north_america
```

Limit the number of servers to benchmark (useful for quick testing):

```bash
uv run python -m gluetun_picker fastest --limit 5
```

Switch Gluetun to a specific hostname:

```bash
uv run python -m gluetun_picker switch --hostname us-nyc-001.privado.io
```

Run the periodic controller loop:

```bash
uv run python -m gluetun_picker run
```

Build the worker image explicitly:

```bash
uv run python -m gluetun_picker build-worker
```

## Docker Compose

If you want the picker in Docker while Gluetun runs somewhere else in your homelab:

1. Copy [.env.example](.env.example) to `.env`.
2. Set `PICKER_GLUETUN_BASE_URL` to your remote Gluetun control server.
3. Fill in your Privado credentials. Leave `PICKER_CANDIDATE_HOSTNAMES` empty to use the region filter instead.
4. Run one benchmark:

```bash
docker compose run --rm picker fastest --limit 5
```

Or start the periodic loop:

```bash
docker compose up -d
```

The Compose file only starts:

- `picker`: the standalone benchmarker, with access to the Docker socket so it can launch temporary probe containers

## Telegram Notifications

Get a message after each benchmark with the result. Set these in your `.env`:

```
PICKER_TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
PICKER_TELEGRAM_CHAT_ID=your-chat-id
```

If both are set, the picker sends a short message after each cycle — whether it switched or kept the current server.

## Notes

- The controller benchmarks candidates sequentially to avoid probe contention.
- The current Gluetun server is always benchmarked first as a baseline when reachable.
- If `PICKER_CANDIDATE_HOSTNAMES` is left empty, the picker fetches all Privado hostnames from the same export URL Gluetun's Privado updater uses and filters them by `region`.
- The raw Privado catalog is cached locally as `servers.json` next to the state file by default and refreshed when it is older than 7 days.
- If the live Privado catalog fetch fails, the picker falls back to the cached `servers.json` file when available.
- Supported region values are `north_america`, `europe`, and `all`. The default is `north_america`.
- If you set explicit hostnames, they override the region filter.
- During switching it rewrites Gluetun's VPN type to `openvpn`, provider to `privado`, and pins `provider.server_selection.hostnames` to the winning hostname.
- The state file stores the last sweep results and the last applied hostname.
- You can override the catalog cache location and age with `PICKER_CATALOG_FILEPATH`, `PICKER_CATALOG_MAX_AGE_SECONDS`, or the `[catalog]` table in the TOML config.

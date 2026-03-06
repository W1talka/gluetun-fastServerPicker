# Gluetun Privado Picker

This is a standalone Python controller that benchmarks a user-supplied list of Privado hostnames with temporary OpenVPN probe containers and then uses Gluetun's control API to pin Gluetun to the fastest hostname.

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

1. Copy [config.example.toml](/home/witalka/Documents/projects/gluetun/standalone/config.example.toml) to `standalone/config.toml` and fill in your values.
2. Build the probe image, or let the controller auto-build it:

```bash
docker build -f standalone/worker.Dockerfile -t gluetun-privado-probe:latest .
```

## Commands

Run one benchmark round without changing Gluetun:

```bash
python3 -m standalone.gluetun_picker --config standalone/config.toml sweep
```

Run a pure benchmark and print only the current fastest hostname and throughput:

```bash
python3 -m standalone.gluetun_picker --config standalone/config.toml fastest
```

Switch Gluetun to a specific hostname:

```bash
python3 -m standalone.gluetun_picker --config standalone/config.toml switch --hostname us-nyc-001.privado.io
```

Run the periodic controller loop:

```bash
python3 -m standalone.gluetun_picker --config standalone/config.toml run
```

Build the worker image explicitly:

```bash
python3 -m standalone.gluetun_picker --config standalone/config.toml build-worker
```

## Docker Compose

If you want the picker in Docker while Gluetun runs somewhere else in your homelab, use:

1. Copy [stack.env.example](/home/witalka/Documents/projects/gluetun/standalone/stack.env.example) to `standalone/stack.env`.
2. Set `PICKER_GLUETUN_BASE_URL` to your remote Gluetun control server.
3. Fill in your Privado credentials and shortlist.
4. Run one benchmark:

```bash
docker compose -f standalone/docker-compose.yml run --rm picker
```

The Compose file only starts:

- `picker`: the standalone benchmarker, with access to the Docker socket so it can launch temporary probe containers

## Notes

- The controller benchmarks candidates sequentially to avoid probe contention.
- If `PICKER_CANDIDATE_HOSTNAMES` is left empty, the picker fetches all Privado hostnames from the same export URL Gluetun's Privado updater uses.
- The `fastest` command does not call the Gluetun API. It only benchmarks and reports.
- During switching it rewrites Gluetun's VPN type to `openvpn`, provider to `privado`, and pins `provider.server_selection.hostnames` to the winning hostname.
- The state file stores the last sweep results and the last applied hostname.

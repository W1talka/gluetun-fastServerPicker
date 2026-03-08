from __future__ import annotations

import argparse
import json
import logging
import sys

from .config import load_config, override_region
from .controller import Controller, fastest_payload
from .probe import run_probe_from_env
from .regions import INPUT_REGIONS
from .runtime import ContainerRuntime


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.log_level)

    if args.command == "probe":
        return run_probe_from_env()

    config = override_region(load_config(args.config), getattr(args, "region", None))
    controller = Controller(config)

    limit = getattr(args, "limit", None)

    if args.command == "run":
        controller.run_forever(limit=limit)
        return 0

    if args.command == "fastest":
        benchmark_run = controller.benchmark_candidates(limit=limit)
        payload = fastest_payload(benchmark_run)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if payload["fastest_hostname"] is not None else 1

    if args.command == "auto":
        outcome = controller.run_cycle(startup=True, apply=True, limit=limit)
        print(json.dumps(outcome.to_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "sweep":
        outcome = controller.run_cycle(startup=True, apply=False, limit=limit)
        print(json.dumps(outcome.to_dict(), indent=2, sort_keys=True))
        return 0

    if args.command == "switch":
        controller.switch_to_hostname(args.hostname.lower())
        print(args.hostname.lower())
        return 0

    if args.command == "build-worker":
        ContainerRuntime(config.runtime).build_worker_image()
        return 0

    parser.error(f"unsupported command {args.command!r}")
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vpn-picker")
    parser.add_argument("--config", help="optional path to the TOML config file")
    parser.add_argument("--log-level", default="INFO", help="python logging level")

    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="run the periodic benchmark loop and switch Gluetun automatically")
    add_region_argument(run_parser)
    add_limit_argument(run_parser)
    fastest_parser = subparsers.add_parser(
        "fastest", help="benchmark once and print the fastest server with its download speed"
    )
    add_region_argument(fastest_parser)
    add_limit_argument(fastest_parser)
    auto_parser = subparsers.add_parser("auto", help="benchmark once and switch Gluetun if a faster server is found")
    add_region_argument(auto_parser)
    add_limit_argument(auto_parser)
    sweep_parser = subparsers.add_parser("sweep", help="benchmark once and print the results without changing Gluetun")
    add_region_argument(sweep_parser)
    add_limit_argument(sweep_parser)

    switch_parser = subparsers.add_parser("switch", help="force Gluetun to a specific configured hostname")
    switch_parser.add_argument("--hostname", required=True, help="Privado hostname to pin in Gluetun")

    subparsers.add_parser("build-worker", help="build the probe worker image")
    subparsers.add_parser("probe", help="internal worker entrypoint")
    return parser


def configure_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), None)
    if not isinstance(level, int):
        raise ValueError(f"invalid log level {level_name!r}")
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
def add_limit_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="max number of servers to benchmark (default: all)",
    )


def add_region_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--region",
        choices=INPUT_REGIONS,
        help="benchmark scope when no explicit hostname shortlist is configured",
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

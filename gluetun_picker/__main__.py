from __future__ import annotations

import argparse
import json
import logging
import sys

from .config import load_config
from .controller import Controller, best_result
from .probe import run_probe_from_env
from .runtime import ContainerRuntime


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    configure_logging(args.log_level)

    if args.command == "probe":
        return run_probe_from_env()

    config = load_config(args.config)
    controller = Controller(config)

    if args.command == "run":
        controller.run_forever()
        return 0

    if args.command == "fastest":
        results = controller.benchmark_candidates()
        winner = best_result(results)
        payload = {
            "fastest_hostname": winner.hostname if winner is not None else None,
            "throughput_bps": winner.throughput_bps if winner is not None else None,
            "benchmark_url": winner.benchmark_url if winner is not None else None,
            "results": [result.to_dict() for result in results],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if winner is not None else 1

    if args.command == "sweep":
        outcome = controller.run_cycle(startup=True, apply=False)
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

    subparsers.add_parser("run", help="run the periodic benchmark loop and switch Gluetun automatically")
    subparsers.add_parser("fastest", help="benchmark once and print the fastest server with its download speed")
    subparsers.add_parser("sweep", help="benchmark once and print the results without changing Gluetun")

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


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

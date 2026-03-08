from __future__ import annotations

import json
import logging
import urllib.request
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import TelegramConfig
    from .controller import SweepOutcome
    from .models import ProbeResult

LOGGER = logging.getLogger(__name__)


def send_notification(config: TelegramConfig, outcome: SweepOutcome) -> None:
    if not config.enabled:
        return
    try:
        text = _format_message(outcome)
        _send_message(config.bot_token, config.chat_id, text)
        LOGGER.info("sent Telegram notification")
    except Exception as exc:
        LOGGER.warning("failed to send Telegram notification: %s", exc)


def _format_message(outcome: SweepOutcome) -> str:
    current = _find_result(outcome.results, outcome.applied_hostname)
    winner = _find_result(outcome.results, outcome.recommended_hostname)

    if outcome.switched and winner:
        prev = _find_result(outcome.results, _previous_hostname(outcome))
        lines = [
            "\U0001f504 VPN Server Switched",
            f"Was: {_describe(prev)}",
            f"Now: {_describe(winner)}",
        ]
    elif winner:
        lines = [
            "\u2705 VPN Server Kept",
            f"Current: {_describe(current or winner)}",
        ]
    else:
        lines = [
            "\u26a0\ufe0f VPN Benchmark — no successful results",
        ]

    lines.append(f"Region: {outcome.region} | Tested: {outcome.candidate_count} servers")
    return "\n".join(lines)


def _describe(result: ProbeResult | None) -> str:
    if result is None:
        return "unknown"
    short = result.hostname.split(".")[0]
    return f"{short} ({result.city}) \u2014 {result.throughput_mbps:.0f} Mbps"


def _find_result(results: list[ProbeResult], hostname: str | None) -> ProbeResult | None:
    if hostname is None:
        return None
    return next((r for r in results if r.hostname == hostname), None)


def _previous_hostname(outcome: SweepOutcome) -> str | None:
    for r in outcome.results:
        if r.hostname != outcome.recommended_hostname and r.success:
            return r.hostname
    return None


def _send_message(bot_token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        response.read()

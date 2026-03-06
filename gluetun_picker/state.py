from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import tempfile
from typing import Any

from .models import ProbeResult


@dataclass
class AppState:
    last_sweep_at: str | None = None
    current_winner: str | None = None
    last_applied_gluetun_hostname: str | None = None
    results: dict[str, dict[str, Any]] = field(default_factory=dict)

    def update_results(self, probe_results: list[ProbeResult]) -> None:
        self.results = {result.hostname: result.to_dict() for result in probe_results}

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_sweep_at": self.last_sweep_at,
            "current_winner": self.current_winner,
            "last_applied_gluetun_hostname": self.last_applied_gluetun_hostname,
            "results": self.results,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppState":
        return cls(
            last_sweep_at=data.get("last_sweep_at"),
            current_winner=data.get("current_winner"),
            last_applied_gluetun_hostname=data.get("last_applied_gluetun_hostname"),
            results=dict(data.get("results", {})),
        )


class StateStore:
    def __init__(self, filepath: Path):
        self._filepath = filepath

    def load(self) -> AppState:
        if not self._filepath.exists():
            return AppState()
        data = json.loads(self._filepath.read_text(encoding="utf-8"))
        return AppState.from_dict(data)

    def save(self, state: AppState) -> None:
        self._filepath.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=self._filepath.parent,
            prefix=self._filepath.name + ".",
            suffix=".tmp",
        ) as handle:
            json.dump(state.to_dict(), handle, indent=2, sort_keys=True)
            handle.write("\n")
            temp_path = Path(handle.name)
        temp_path.replace(self._filepath)

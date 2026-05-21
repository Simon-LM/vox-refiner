#!/usr/bin/env python3
"""Pomodoro configuration — read/write ~/.local/share/vox-refiner/pomodoro.json.

Defaults match the standard Pomodoro technique (25 min work / 5 min break).
All durations are in minutes.

Public API
----------
    load()   -> PomodoroConfig
    save(cfg) -> None
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

_CONFIG_DIR = (
    Path(os.environ.get("XDG_DATA_HOME", ""))
    / "vox-refiner"
    if os.environ.get("XDG_DATA_HOME")
    else Path.home() / ".local" / "share" / "vox-refiner"
)
_CONFIG_PATH = _CONFIG_DIR / "pomodoro.json"


@dataclass
class PomodoroConfig:
    work_minutes: int = 25
    break_minutes: int = 5
    break_margin_minutes: int = 5
    break_locked: bool = True
    enabled: bool = False
    idle_reset_minutes: int = 0  # 0 = disabled

    @property
    def break_min(self) -> int:
        return max(1, self.break_minutes - self.break_margin_minutes)

    @property
    def break_max(self) -> int:
        return self.break_minutes + self.break_margin_minutes

    @property
    def break_default(self) -> int:
        return self.break_minutes


def load() -> PomodoroConfig:
    if not _CONFIG_PATH.exists():
        return PomodoroConfig()
    try:
        data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        return PomodoroConfig(
            work_minutes=int(data.get("work_minutes", 25)),
            break_minutes=int(data.get("break_minutes", 5)),
            break_margin_minutes=int(data.get("break_margin_minutes", 5)),
            break_locked=bool(data.get("break_locked", True)),
            enabled=bool(data.get("enabled", False)),
            idle_reset_minutes=int(data.get("idle_reset_minutes", 0)),
        )
    except (ValueError, KeyError, json.JSONDecodeError):
        return PomodoroConfig()


def save(cfg: PomodoroConfig) -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(
        json.dumps(asdict(cfg), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

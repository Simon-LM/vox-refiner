#!/usr/bin/env python3
"""Pomodoro engine for VoxRefiner.

State machine:  IDLE → WORK → BREAK → WORK → …

At each tick (called by the daemon):
  - WORK phase:  count down; when done, pick next physical task → start BREAK
  - BREAK phase: count down; fire overlay; when max exceeded or timer done,
                 close overlay and open reminder.sh --fire <id>

State is persisted in /tmp/vox-pomodoro-state.json so the daemon can restart
without losing the current cycle.

Public API
----------
    tick(now)             -> PomodoroState  (call every 60 s from daemon)
    start()               -> None
    stop()                -> None
    is_running()          -> bool
    current_state()       -> PomodoroState | None
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from src.reminder.pomodoro_config import PomodoroConfig, load as load_config

_STATE_FILE = Path("/tmp/vox-pomodoro-state.json")
_PID_FILE = Path("/tmp/vox-pomodoro.pid")

_PHYSICAL_CATEGORIES = {"task_short", "task_long", "errand"}


class Phase(str, Enum):
    WORK = "work"
    BREAK = "break"


class PomodoroState:
    def __init__(
        self,
        phase: Phase,
        phase_end_iso: str,
        break_hard_end_iso: str | None = None,
        task_id: int | None = None,
        task_title: str | None = None,
    ) -> None:
        self.phase = phase
        self.phase_end_iso = phase_end_iso
        self.break_hard_end_iso = break_hard_end_iso
        self.task_id = task_id
        self.task_title = task_title

    def to_dict(self) -> dict:
        return {
            "phase": self.phase.value,
            "phase_end_iso": self.phase_end_iso,
            "break_hard_end_iso": self.break_hard_end_iso,
            "task_id": self.task_id,
            "task_title": self.task_title,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PomodoroState":
        return cls(
            phase=Phase(data["phase"]),
            phase_end_iso=data["phase_end_iso"],
            break_hard_end_iso=data.get("break_hard_end_iso"),
            task_id=data.get("task_id"),
            task_title=data.get("task_title"),
        )


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _add_minutes(iso: str, minutes: int) -> str:
    from datetime import timedelta
    dt = datetime.fromisoformat(iso)
    return (dt + timedelta(minutes=minutes)).isoformat()


def _iso_to_dt(iso: str) -> datetime:
    return datetime.fromisoformat(iso)


def _save_state(state: PomodoroState) -> None:
    _STATE_FILE.write_text(json.dumps(state.to_dict()), encoding="utf-8")


def _load_state() -> PomodoroState | None:
    if not _STATE_FILE.exists():
        return None
    try:
        return PomodoroState.from_dict(json.loads(_STATE_FILE.read_text(encoding="utf-8")))
    except (ValueError, KeyError, json.JSONDecodeError):
        return None


def _clear_state() -> None:
    _STATE_FILE.unlink(missing_ok=True)


def _pick_physical_task() -> tuple[int, str, int] | None:
    """Return (id, title, estimated_minutes) of the most urgent due screen-free task, or None.

    Prefers tasks explicitly marked screen_free=True. Falls back to physical
    categories when screen_free is NULL (legacy tasks without the field).
    """
    try:
        from src.reminder.db import get_due
        now = _now_iso()[:19].replace("T", " ")
        due = get_due(now)
        # First pass: explicit screen_free=True
        for r in due:
            if r.get("screen_free") == 1:
                est = r.get("estimated_minutes") or 0
                return r["id"], r["title"], est
        # Second pass: legacy tasks in physical categories with no screen_free set
        for r in due:
            if r.get("screen_free") is None and r.get("category") in _PHYSICAL_CATEGORIES:
                est = r.get("estimated_minutes") or 0
                return r["id"], r["title"], est
    except Exception:
        pass
    return None


def _clamp_break(estimated: int, cfg: PomodoroConfig) -> int:
    if estimated <= 0:
        return cfg.break_default
    return max(cfg.break_min, min(cfg.break_max, estimated))


def _open_overlay(task_title: str, duration_minutes: int, locked: bool) -> None:
    """Launch the GTK overlay in background (non-blocking).

    Uses the system python3 interpreter so that python3-gi (a system package)
    is available even when the daemon runs inside a venv that lacks it.
    """
    from pathlib import Path
    script = Path(__file__).parent / "pomodoro_overlay.py"
    subprocess.Popen(
        ["python3", str(script),
         "--title", task_title,
         "--minutes", str(duration_minutes),
         "--locked" if locked else "--no-locked"],
        start_new_session=True,
    )


def _close_overlay() -> None:
    """Signal the overlay to close if running."""
    overlay_pid_file = Path("/tmp/vox-pomodoro-overlay.pid")
    if not overlay_pid_file.exists():
        return
    try:
        import signal as _signal
        import os
        pid = int(overlay_pid_file.read_text().strip())
        os.kill(pid, _signal.SIGTERM)
    except (ValueError, OSError):
        pass
    finally:
        overlay_pid_file.unlink(missing_ok=True)


def _fire_reminder(task_id: int) -> None:
    """Open reminder.sh --fire <id> in a terminal (reuses existing mechanism)."""
    try:
        from src.reminder.notify import open_terminal_fire
        open_terminal_fire(task_id)
    except Exception:
        pass


def _idle_seconds() -> int:
    """Return X11 idle time in seconds via xprintidle. Returns 0 on error or unavailable."""
    try:
        result = subprocess.run(
            ["xprintidle"], capture_output=True, text=True, timeout=2
        )
        return int(result.stdout.strip()) // 1000
    except (FileNotFoundError, ValueError, subprocess.TimeoutExpired, OSError):
        return 0


def _play_chime() -> None:
    """Play a short chime via TTS or system bell."""
    try:
        subprocess.Popen(
            ["paplay", "/usr/share/sounds/freedesktop/stereo/complete.oga"],
            start_new_session=True,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        pass


def start() -> None:
    """Start a new Pomodoro work phase."""
    cfg = load_config()
    now = _now_iso()
    state = PomodoroState(
        phase=Phase.WORK,
        phase_end_iso=_add_minutes(now, cfg.work_minutes),
    )
    _save_state(state)
    _PID_FILE.write_text(str(_get_self_pid()), encoding="utf-8")


def stop() -> None:
    """Abort the current Pomodoro cycle."""
    _close_overlay()
    _clear_state()
    _PID_FILE.unlink(missing_ok=True)


def is_running() -> bool:
    if not _PID_FILE.exists():
        return _STATE_FILE.exists()
    try:
        import os
        pid = int(_PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return True
    except (ValueError, OSError):
        _PID_FILE.unlink(missing_ok=True)
        return _STATE_FILE.exists()


def _get_self_pid() -> int:
    import os
    return os.getpid()


def current_state() -> PomodoroState | None:
    return _load_state()


def tick() -> PomodoroState | None:
    """Advance the Pomodoro by one daemon tick. Returns current state or None if idle."""
    cfg = load_config()
    if not cfg.enabled:
        return None

    state = _load_state()
    if state is None:
        return None

    now_dt = _iso_to_dt(_now_iso())
    phase_end_dt = _iso_to_dt(state.phase_end_iso)

    # Idle reset: if user was away long enough, restart work cycle silently
    if cfg.idle_reset_minutes > 0:
        idle = _idle_seconds()
        if idle >= cfg.idle_reset_minutes * 60:
            _close_overlay()
            now_iso = _now_iso()
            state = PomodoroState(
                phase=Phase.WORK,
                phase_end_iso=_add_minutes(now_iso, cfg.work_minutes),
            )
            _save_state(state)
            return state

    if state.phase == Phase.WORK:
        if now_dt >= phase_end_dt:
            _play_chime()
            task = _pick_physical_task()
            if task:
                task_id, task_title, estimated = task
                duration = _clamp_break(estimated, cfg)
            else:
                task_id, task_title = None, "Break"
                duration = cfg.break_default

            now_iso = _now_iso()
            hard_end = _add_minutes(now_iso, cfg.break_max)
            state = PomodoroState(
                phase=Phase.BREAK,
                phase_end_iso=_add_minutes(now_iso, duration),
                break_hard_end_iso=hard_end,
                task_id=task_id,
                task_title=task_title,
            )
            _save_state(state)
            _open_overlay(task_title or "Break", duration, cfg.break_locked)

    elif state.phase == Phase.BREAK:
        hard_end_dt = _iso_to_dt(state.break_hard_end_iso) if state.break_hard_end_iso else phase_end_dt
        break_over = now_dt >= phase_end_dt
        hard_exceeded = now_dt >= hard_end_dt

        if break_over or hard_exceeded:
            _close_overlay()
            if state.task_id is not None:
                _fire_reminder(state.task_id)
            _play_chime()
            now_iso = _now_iso()
            state = PomodoroState(
                phase=Phase.WORK,
                phase_end_iso=_add_minutes(now_iso, cfg.work_minutes),
            )
            _save_state(state)

    return state

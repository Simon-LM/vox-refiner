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
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path

from src.reminder.pomodoro_config import PomodoroConfig, load as load_config

_STATE_FILE = Path("/tmp/vox-pomodoro-state.json")
_PID_FILE = Path("/tmp/vox-pomodoro.pid")
_FIRE_RESULT_FILE = Path("/tmp/vox-pomodoro-fire-result.json")
_OVERLAY_PID_FILE = Path("/tmp/vox-pomodoro-overlay.pid")

_WARNING_BEFORE_SECONDS = 90  # show pre-break warning within this many seconds of break


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
        warned: bool = False,
    ) -> None:
        self.phase = phase
        self.phase_end_iso = phase_end_iso
        self.break_hard_end_iso = break_hard_end_iso
        self.task_id = task_id
        self.task_title = task_title
        self.warned = warned

    def to_dict(self) -> dict:
        return {
            "phase": self.phase.value,
            "phase_end_iso": self.phase_end_iso,
            "break_hard_end_iso": self.break_hard_end_iso,
            "task_id": self.task_id,
            "task_title": self.task_title,
            "warned": self.warned,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PomodoroState":
        return cls(
            phase=Phase(data["phase"]),
            phase_end_iso=data["phase_end_iso"],
            break_hard_end_iso=data.get("break_hard_end_iso"),
            task_id=data.get("task_id"),
            task_title=data.get("task_title"),
            warned=data.get("warned", False),
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
    """Return (id, title, estimated_minutes) of the best screen-free task, or None.

    Delegates filtering + ranking to `src.reminder.picker`, with the current
    scheduling context (weather, time of day, …). A rainy day pushes outdoor
    tasks out of the candidate set; a phone-only task outside its callable
    window is skipped, and so on.
    """
    try:
        from src.reminder.context import gather
        from src.reminder.db import get_due
        from src.reminder.picker import filter_screen_free, pick_best_task
        now = _now_iso()[:19].replace("T", " ")
        candidates = filter_screen_free(get_due(now))
        if not candidates:
            return None
        best = pick_best_task(candidates, gather())
        if best is None:
            return None
        est = best.get("estimated_minutes") or 0
        return best["id"], best["title"], est
    except Exception:
        return None


def _clamp_break(estimated: int, cfg: PomodoroConfig) -> int:
    if estimated <= 0:
        return cfg.break_default
    return max(cfg.break_min, min(cfg.break_max, estimated))


def _open_warning(seconds: int) -> None:
    """Launch the small pre-break warning window (non-blocking, no focus steal)."""
    from pathlib import Path
    script = Path(__file__).parent / "pomodoro_overlay.py"
    subprocess.Popen(
        ["python3", str(script), "--warning",
         "--minutes", str(round(seconds / 60, 3))],
        start_new_session=True,
    )


def _open_overlay(task_title: str, duration_minutes: int, locked: bool,
                   task_id: int | None = None) -> None:
    """Launch the GTK overlay in background (non-blocking).

    Uses the system python3 interpreter so that python3-gi (a system package)
    is available even when the daemon runs inside a venv that lacks it.
    When task_id is provided, the overlay shows a confirmation screen after the
    timer ends instead of auto-dismissing, and writes the user's choice to
    _FIRE_RESULT_FILE for the daemon to act on.
    """
    from pathlib import Path
    script = Path(__file__).parent / "pomodoro_overlay.py"
    cmd = [
        "python3", str(script),
        "--title", task_title,
        "--minutes", str(duration_minutes),
        "--locked" if locked else "--no-locked",
    ]
    if task_id is not None:
        cmd += ["--task-id", str(task_id)]
    subprocess.Popen(cmd, start_new_session=True)


def _close_overlay() -> None:
    """Signal the overlay to close if running."""
    if not _OVERLAY_PID_FILE.exists():
        return
    try:
        import signal as _signal
        import os
        pid = int(_OVERLAY_PID_FILE.read_text().strip())
        os.kill(pid, _signal.SIGTERM)
    except (ValueError, OSError):
        pass
    finally:
        _OVERLAY_PID_FILE.unlink(missing_ok=True)


def _overlay_still_running() -> bool:
    """Return True if the confirmation overlay subprocess is still alive.

    Used to suspend the BREAK→WORK transition while the user is away — if the
    overlay is still up, they haven't clicked any button yet, so launching a
    new cycle would just stack another overlay on top.
    """
    if not _OVERLAY_PID_FILE.exists():
        return False
    try:
        import os
        pid = int(_OVERLAY_PID_FILE.read_text().strip())
        os.kill(pid, 0)  # signal 0 → "does this process exist?"
        return True
    except (ValueError, OSError):
        _OVERLAY_PID_FILE.unlink(missing_ok=True)
        return False


def _check_fire_result() -> None:
    """Apply the confirmation choice written by the overlay to the reminder DB."""
    if not _FIRE_RESULT_FILE.exists():
        return
    try:
        data = json.loads(_FIRE_RESULT_FILE.read_text(encoding="utf-8"))
        task_id = data.get("task_id")
        action = data.get("action", "skip")
        if task_id is not None:
            _apply_fire_action(task_id, action)
    except (json.JSONDecodeError, OSError, KeyError):
        pass
    finally:
        _FIRE_RESULT_FILE.unlink(missing_ok=True)


def _apply_fire_action(task_id: int, action: str) -> None:
    """Update the DB based on the user's in-overlay choice.

    'done'   → complete_reminder: logs occurrence, advances recurring task or
               marks one-time task as done.
    'skip'   → log_occurrence('skipped'): records the miss, task stays in queue
               for the next break.
    'snooze' → snooze by 1 h: no occurrence log, just a delay.
    """
    try:
        from src.reminder.db import complete_reminder, log_occurrence, snooze
        now = datetime.now(tz=timezone.utc)
        if action == "done":
            complete_reminder(task_id)
        elif action == "skip":
            log_occurrence(task_id, "skipped")
        elif action == "snooze":
            next_t = (now + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
            snooze(task_id, next_t)
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
    _check_fire_result()

    cfg = load_config()
    if not cfg.enabled:
        return None

    state = _load_state()
    if state is None:
        return None

    now_dt = _iso_to_dt(_now_iso())
    phase_end_dt = _iso_to_dt(state.phase_end_iso)

    # Stale WORK state: if a WORK phase ended more than one full cycle ago
    # the daemon was likely suspended (laptop closed, system hibernated, …)
    # while WORK was active. Clear instead of triggering a phantom BREAK on
    # resume.
    #
    # No stale check on BREAK: a BREAK can legitimately stay in an "expired"
    # state for hours while the user is away — the confirmation overlay is
    # designed to wait indefinitely. When the user finally clicks, the normal
    # BREAK handler below sees the overlay is gone and transitions to a new
    # WORK cycle. Clearing here would silently end the Pomodoro session, which
    # is exactly the bug we hit before.
    stale_delta = timedelta(minutes=cfg.work_minutes + cfg.break_max)
    if state.phase == Phase.WORK and now_dt - phase_end_dt > stale_delta:
        _clear_state()
        return None

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
        remaining_seconds = (phase_end_dt - now_dt).total_seconds()

        # Pre-break warning: show a small non-blocking window before the break starts
        if not state.warned and 0 < remaining_seconds <= _WARNING_BEFORE_SECONDS:
            _open_warning(int(remaining_seconds))
            state.warned = True
            _save_state(state)

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
            _open_overlay(task_title or "Break", duration, cfg.break_locked,
                          task_id=task_id)

    elif state.phase == Phase.BREAK:
        hard_end_dt = _iso_to_dt(state.break_hard_end_iso) if state.break_hard_end_iso else phase_end_dt
        break_over = now_dt >= phase_end_dt
        hard_exceeded = now_dt >= hard_end_dt

        if break_over or hard_exceeded:
            # If the confirmation overlay is still up, the user hasn't returned.
            # Suspend the cycle until they click a button (or the overlay dies).
            if _overlay_still_running():
                return state
            _play_chime()
            now_iso = _now_iso()
            state = PomodoroState(
                phase=Phase.WORK,
                phase_end_iso=_add_minutes(now_iso, cfg.work_minutes),
            )
            _save_state(state)

    return state

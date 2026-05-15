#!/usr/bin/env python3
"""Scheduler daemon for the VoxRefiner reminder system.

Runs a loop every POLL_INTERVAL seconds (default 60). On each tick:
  1. Reads all reminders with next_trigger <= now and status pending/snoozed.
  2. For each, detects the desktop context.
  3. Chooses the intervention mode.
  4. Dispatches: notify (TTS + desktop notification), defer_unlock (skip),
     tts_only (no desktop banner), or queue (skip until context clears).
  5. Checks for screen unlock to ask about physical tasks fired during lock.

Pomodoro logic:
  - At screen lock: physical-category tasks (task_short, errand) are fired via TTS.
  - At unlock: a follow-up question is asked for each task fired during lock.

This module is designed to be run as a systemd user service.

Usage:
    python -m src.reminder_daemon            (runs forever)
    python -m src.reminder_daemon --once     (single tick, useful for testing)
"""

from __future__ import annotations

import json
import os
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.reminder_converse import compute_next_trigger
from src.reminder_db import bump_trigger, get_due, snooze, update_status
from src.reminder_notify import (
    Context,
    choose_intervention,
    close_terminal_fire,
    detect_context,
    open_terminal_fire,
    send_desktop_notification,
    send_tts_notification,
)
from src.ui_py import info, warn

_POLL_INTERVAL = 60  # seconds
_POMODORO_FOLLOW_UP_FILE = Path("/tmp/vox-reminder-pomodoro-pending.json")

_running = True


def _now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _write_pomodoro_pending(reminders: list[dict]) -> None:
    payload = [{"id": r["id"], "title": r["title"]} for r in reminders]
    _POMODORO_FOLLOW_UP_FILE.write_text(json.dumps(payload))


def _read_pomodoro_pending() -> list[dict]:
    if not _POMODORO_FOLLOW_UP_FILE.exists():
        return []
    try:
        return json.loads(_POMODORO_FOLLOW_UP_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _clear_pomodoro_pending() -> None:
    _POMODORO_FOLLOW_UP_FILE.unlink(missing_ok=True)


def _fire_reminder(reminder: dict, mode: str) -> None:
    title = reminder.get("title", "Reminder")
    rid = reminder["id"]

    if mode == "notify":
        category = reminder.get("category", "")
        send_desktop_notification("VoxRefiner — Reminder", f"{title} [{category}]")

        success = open_terminal_fire(rid)
        if not success:
            warn(f"No terminal emulator found — falling back to TTS for reminder #{rid}")
            send_tts_notification(title)
            next_trigger = compute_next_trigger(reminder, _now())
            snooze(rid, next_trigger)
        else:
            # Bump next_trigger without incrementing snooze_count
            grace = (datetime.now(tz=timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
            bump_trigger(rid, grace)

    elif mode == "tts_only":
        close_terminal_fire(rid)
        send_tts_notification(title)
        next_trigger = compute_next_trigger(reminder, _now())
        snooze(rid, next_trigger)


def dispatch_reminder(reminder: dict, context: Context) -> str:
    """Decide and execute the right action for *reminder* given *context*.

    Returns the mode string ("notify", "tts_only", "queue", "defer_unlock").
    """
    intervention = choose_intervention(context, reminder)
    mode = intervention.mode

    if mode in ("notify", "tts_only"):
        _fire_reminder(reminder, mode)
    # "queue" and "defer_unlock" are no-ops: leave next_trigger unchanged

    return mode


def tick(previous_context: Context | None = None) -> Context:
    """Run one scheduler tick. Returns the current context snapshot.

    Handles screen-unlock Pomodoro follow-up if the screen was previously locked.
    """
    now = _now()
    context = detect_context()

    # Unlock transition: ask about physical tasks fired during lock
    if previous_context is not None and previous_context.screen_locked and not context.screen_locked:
        pending = _read_pomodoro_pending()
        if pending:
            for item in pending:
                send_tts_notification(
                    f"You're back — were you able to complete: {item['title']}?"
                )
            _clear_pomodoro_pending()

    due = get_due(now)
    if not due:
        return context

    info(f"{len(due)} reminder(s) due — context: locked={context.screen_locked} dnd={context.dnd_enabled} fullscreen={context.fullscreen_app}")
    pomodoro_batch: list[dict] = []

    for i, reminder in enumerate(due):
        mode = dispatch_reminder(reminder, context)
        info(f"  → #{reminder['id']} '{reminder['title'][:40]}' [{reminder['category']}] mode={mode}")
        if mode == "tts_only" and context.screen_locked:
            pomodoro_batch.append(reminder)
        if mode == "notify" and i < len(due) - 1:
            time.sleep(12)

    if pomodoro_batch:
        _write_pomodoro_pending(pomodoro_batch)

    return context


def run_loop(poll_interval: int = _POLL_INTERVAL) -> None:
    """Main daemon loop. Runs until SIGTERM or SIGINT."""

    def _stop(signum, frame):  # noqa: ARG001
        global _running
        _running = False
        info("Reminder daemon stopping…")

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    info(f"Reminder daemon started — polling every {poll_interval}s. Ctrl+C or close this terminal to stop.")
    previous_context: Context | None = None
    tick_count = 0

    while _running:
        tick_count += 1
        info(f"Tick #{tick_count} — {_now()}")
        try:
            previous_context = tick(previous_context)
        except Exception as exc:  # noqa: BLE001
            warn(f"Daemon tick error: {exc}")
        if _running:
            time.sleep(poll_interval)


if __name__ == "__main__":
    if os.environ.get("REMINDER_ENABLED", "false").lower() not in ("true", "1", "yes"):
        warn("REMINDER_ENABLED is not set to true — daemon will not start.")
        warn("Set REMINDER_ENABLED=true in your .env file to activate reminders.")
        sys.exit(0)

    once = "--once" in sys.argv
    if once:
        tick()
    else:
        run_loop()

#!/usr/bin/env python3
"""AI conversation layer for the VoxRefiner reminder system.

Handles:
- Interpreting user responses to triggered reminders (done, snooze, cancel…)
- Logging unavailability declarations into the database
- Computing the next trigger time based on task type, history, and escalation
- ADHD-adapted coach persona (supportive, non-guilt-inducing, action-oriented)

Public API
----------
    interpret_response(reminder, user_text) -> Action  (named tuple)
    compute_next_trigger(reminder, now)     -> str      (ISO datetime)
    converse(reminder_id, user_text)        -> str      (assistant reply)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import NamedTuple

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from src.common import SECURITY_BLOCK, call_model, compute_timing, effective_timeout  # noqa: E402
from src.reminder_db import (  # noqa: E402
    add_unavailability,
    log_conversation,
    snooze,
    update_status,
)
from src.ui_py import warn  # noqa: E402

_MODEL = os.environ.get("REFINE_MODEL_SHORT", "mistral-small-latest")
_MODEL_FALLBACK = "mistral-medium-latest"

# ── Data types ────────────────────────────────────────────────────────────────

_ACTION_TYPES = frozenset(
    {"done", "snooze", "going_to_do", "cancel", "unavailable", "unknown"}
)


class Action(NamedTuple):
    action_type: str     # one of _ACTION_TYPES
    snooze_minutes: int  # 0 unless action_type in ("snooze", "going_to_do")
    unavailability: dict | None  # {"start_dt": ..., "end_dt": ..., "reason": ...}
    message: str         # short reply to speak/display to the user


# ── Escalation schedule (by category) ────────────────────────────────────────

_SNOOZE_DEFAULTS: dict[str, int] = {
    "task_short":  5,
    "errand":      5,
    "task_long":   15,
    "appointment": 30,
    "admin":       30,
    "deadline":    60,
}

_ESCALATION_SCHEDULE: list[tuple[int, int]] = [
    # (days_before_event, reminder_offset_minutes_before_midnight)
    (3, 480),   # D-3 morning at 08:00
    (1, 1080),  # D-1 evening at 18:00
    (0, 120),   # day of, 2h before
    (0, 30),    # day of, 30min before
]

# ── System prompt ─────────────────────────────────────────────────────────────

_COACH_SYSTEM_PROMPT = (
    "You are a supportive personal agenda assistant, specifically designed for people with ADHD.\n"
    "Your role is to help the user complete tasks without creating guilt or pressure.\n"
    "\n"
    "Tone and style:\n"
    "- Direct and neutral. Never guilt-inducing, never preachy.\n"
    "- Action-oriented: ask 'What is blocking you?' or 'Can you do this in 10 minutes right now?'\n"
    "- Short responses only — one or two sentences maximum.\n"
    "- One action at a time. Never list multiple things to do.\n"
    "- Remember declared contexts (unavailability, reasons) to avoid repeating the same questions.\n"
    "- Suggest concrete alternatives rather than repeating the same prompt in a loop.\n"
    "- Flag upcoming stressful tasks gently in advance.\n"
    "\n"
    "When interpreting a user response, output a single JSON object with these fields:\n"
    '  "action_type"     : one of: done / snooze / going_to_do / cancel / unavailable / unknown\n'
    '  "snooze_minutes"  : integer (0 if not a snooze/going_to_do action)\n'
    '  "unavailability"  : object with start_dt, end_dt, reason — or null\n'
    '  "message"         : short reply to speak aloud to the user (max 2 sentences)\n'
    "\n"
    "action_type rules:\n"
    "- done        : user confirms the task is completed\n"
    "- snooze      : user wants to postpone. Compute snooze_minutes as minutes from\n"
    "                \"Current local datetime\" to the time they specify.\n"
    "                Examples: \"dans 2h\" → 120. \"demain à 14h\" with current 21:31 →\n"
    "                minutes from 21:31 to next day 14:00 = 990.\n"
    "                If no specific time, use category default.\n"
    "- going_to_do : user is about to do it now (snooze_minutes = category default)\n"
    "- cancel      : user cancels the reminder permanently\n"
    "- unavailable : user declares they are unavailable (sick, away, busy)\n"
    "- unknown     : response is unclear\n"
    "\n"
    "Output ONLY valid JSON. No markdown. No explanation.\n"
    "\n"
    + SECURITY_BLOCK
)


# ── Core functions ────────────────────────────────────────────────────────────


def interpret_response(reminder: dict, user_text: str) -> Action:
    """Call Mistral to interpret *user_text* in the context of *reminder*.

    Returns an Action named tuple. Falls back to Action(unknown) on error.
    """
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        raise RuntimeError("MISTRAL_API_KEY is not set.")

    history = json.loads(reminder.get("conversation") or "[]")
    category = reminder.get("category", "task_short")
    default_snooze = _SNOOZE_DEFAULTS.get(category, 30)

    local_now = datetime.now().strftime("%Y-%m-%d %H:%M")
    context_block = (
        f"Reminder: {reminder.get('title', '')}\n"
        f"Category: {category}\n"
        f"Current local datetime: {local_now}\n"
        f"Snooze default for this category: {default_snooze} minutes\n"
        f"Snooze count so far: {reminder.get('snooze_count', 0)}\n"
    )
    if reminder.get("event_datetime"):
        context_block += f"Event scheduled: {reminder['event_datetime']}\n"

    messages = [
        {"role": "system", "content": _COACH_SYSTEM_PROMPT},
        {"role": "user", "content": context_block},
    ]
    for entry in history[-6:]:  # last 3 exchanges
        messages.append(entry)
    messages.append({"role": "user", "content": user_text})

    word_count = len(user_text.split())
    base_timeout, retry_delay = compute_timing(word_count)

    for model in (_MODEL, _MODEL_FALLBACK):
        try:
            timeout = effective_timeout(base_timeout, model)
            raw = call_model(
                model, messages, api_key,
                timeout=timeout,
                retry_delay=retry_delay,
                retries=2,
            )
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                if raw.endswith("```"):
                    raw = raw[:-3].rstrip()
            parsed = json.loads(raw)
            return Action(
                action_type=parsed.get("action_type", "unknown"),
                snooze_minutes=int(parsed.get("snooze_minutes", 0)),
                unavailability=parsed.get("unavailability"),
                message=parsed.get("message", ""),
            )
        except (json.JSONDecodeError, ValueError, KeyError):
            continue
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            if status in (429, 500, 502, 503):
                warn(f"{model} error ({status}) — switching model…")
                continue
            raise
        except requests.RequestException:
            warn(f"{model} unreachable, switching…")
            continue

    return Action(
        action_type="unknown",
        snooze_minutes=0,
        unavailability=None,
        message="I couldn't understand your response. You can press D for done, L for later.",
    )


def compute_next_trigger(reminder: dict, now: str | None = None) -> str:
    """Return the ISO datetime for the next reminder fire time.

    Uses escalation schedule for appointments; simple snooze logic for tasks.
    Accounts for snooze_count: increases urgency as deferrals accumulate.
    """
    if now is None:
        now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    now_dt = datetime.fromisoformat(now.replace(" ", "T")).replace(tzinfo=timezone.utc)
    category = reminder.get("category", "task_short")
    snooze_count = reminder.get("snooze_count", 0)
    event_dt_str = reminder.get("event_datetime")

    # For appointments with a known event date, use escalation schedule
    if event_dt_str and category == "appointment":
        event_dt = datetime.fromisoformat(
            event_dt_str.replace(" ", "T")
        ).replace(tzinfo=timezone.utc)
        days_left = (event_dt - now_dt).days

        # Walk escalation schedule — pick the next applicable milestone
        for days_before, offset_minutes in _ESCALATION_SCHEDULE:
            trigger_dt = event_dt - timedelta(days=days_before, minutes=offset_minutes)
            if trigger_dt > now_dt:
                return trigger_dt.strftime("%Y-%m-%d %H:%M:%S")

        # Past all escalation milestones — remind every 30 min
        return (now_dt + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")

    # For tasks, use progressive urgency based on snooze count
    base_minutes = _SNOOZE_DEFAULTS.get(category, 30)
    # Reduce snooze interval as count grows (min 5 min)
    urgency_factor = max(0.5 ** snooze_count, 5 / base_minutes)
    minutes = max(5, int(base_minutes * urgency_factor))
    return (now_dt + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M:%S")


def converse(reminder_id: int, reminder: dict, user_text: str) -> str:
    """Interpret the user's response, apply the action to the DB, return a reply.

    Logs the exchange to the reminder's conversation history.
    """
    action = interpret_response(reminder, user_text)

    # Log exchange
    log_conversation(reminder_id, {"role": "user", "content": user_text})
    log_conversation(reminder_id, {"role": "assistant", "content": action.message})

    if action.action_type == "done":
        update_status(reminder_id, "done")

    elif action.action_type in ("snooze", "going_to_do"):
        minutes = action.snooze_minutes or _SNOOZE_DEFAULTS.get(
            reminder.get("category", "task_short"), 30
        )
        now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        next_dt = (
            datetime.fromisoformat(now.replace(" ", "T")).replace(tzinfo=timezone.utc)
            + timedelta(minutes=minutes)
        ).strftime("%Y-%m-%d %H:%M:%S")
        snooze(reminder_id, next_dt)

    elif action.action_type == "cancel":
        update_status(reminder_id, "cancelled")

    elif action.action_type == "unavailable" and action.unavailability:
        u = action.unavailability
        if u.get("start_dt") and u.get("end_dt"):
            add_unavailability(
                start_dt=u["start_dt"],
                end_dt=u["end_dt"],
                reason=u.get("reason", "unavailable"),
            )
            # Defer to after the unavailability window
            next_dt = compute_next_trigger(reminder, now=u["end_dt"])
            snooze(reminder_id, next_dt)

    return action.message

#!/usr/bin/env python3
"""Context-aware task picker.

Pure logic: given a list of candidate tasks (already filtered for screen-free
where relevant) and a `SchedulingContext` snapshot, return the best one — or
None when every candidate is incompatible with the current context.

Filter rules (all permissive: a constraint only rejects a task when we have
explicit evidence it would be unsuitable):

  weather_requirement == "good_required":
      reject when context.weather is known AND context.weather_is_good is False.
      Unknown weather is *not* a rejection — we don't penalise missing data.
  location_type == "outdoor":
      same logic — only filter out when we know the weather is bad.
  time_constraint == { earliest_hour, latest_hour }:
      reject when context.now.hour falls outside [earliest, latest].
  requires_daylight == true:
      reject when context.weather.is_day is explicitly False.
      Missing weather or missing is_day is *not* a rejection.

Ranking (applied after filtering):
  - higher snooze_count first  (more deferred = more urgent)
  - then older next_trigger    (more overdue = more urgent)

Public API
----------
    filter_screen_free(tasks)            -> list[dict]
    pick_best_task(tasks, context)       -> dict | None
"""

from __future__ import annotations

import json
from typing import Any

from src.reminder.context import SchedulingContext

_PHYSICAL_CATEGORIES = frozenset({"task_short", "task_long", "errand"})


# ── Metadata helpers ─────────────────────────────────────────────────────────


def _parse_metadata(task: dict) -> dict:
    """Return the task's metadata as a dict (handles string-encoded JSON)."""
    raw = task.get("metadata")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


# ── Filtering helpers ────────────────────────────────────────────────────────


def filter_screen_free(tasks: list[dict]) -> list[dict]:
    """Return the subset of *tasks* suitable for off-screen work.

    Matches the legacy two-pass rule: explicit `screen_free=1`, or
    `screen_free is None` with category in the physical set
    (`task_short`, `task_long`, `errand`).
    """
    out: list[dict] = []
    for t in tasks:
        sf = t.get("screen_free")
        if sf == 1:
            out.append(t)
        elif sf is None and t.get("category") in _PHYSICAL_CATEGORIES:
            out.append(t)
    return out


def _matches_weather(metadata: dict, context: SchedulingContext) -> bool:
    """Permissive: only reject when weather is known AND unsuitable."""
    if context.weather is None:
        return True
    req = metadata.get("weather_requirement")
    if req == "good_required" and not context.weather_is_good:
        return False
    if metadata.get("location_type") == "outdoor" and not context.weather_is_good:
        return False
    return True


def _matches_time_constraint(metadata: dict, context: SchedulingContext) -> bool:
    tc = metadata.get("time_constraint")
    if tc is None:
        return True
    # Accept both a single dict and a list of dicts (split schedules).
    if isinstance(tc, dict):
        windows = [tc]
    elif isinstance(tc, list):
        windows = tc
    else:
        return True
    valid = [
        w for w in windows
        if isinstance(w, dict)
        and isinstance(w.get("earliest_hour"), int)
        and isinstance(w.get("latest_hour"), int)
    ]
    if not valid:
        return True  # permissive: no parseable constraint
    hour = context.now.hour
    return any(w["earliest_hour"] <= hour <= w["latest_hour"] for w in valid)


def _matches_daylight(metadata: dict, context: SchedulingContext) -> bool:
    """Permissive: only reject when is_day is explicitly False."""
    if not metadata.get("requires_daylight"):
        return True
    if context.weather is None:
        return True
    is_day = context.weather.get("is_day")
    if is_day is None:
        return True
    return bool(is_day)


def _task_matches_context(task: dict, context: SchedulingContext) -> bool:
    metadata = _parse_metadata(task)
    if not _matches_weather(metadata, context):
        return False
    if not _matches_time_constraint(metadata, context):
        return False
    if not _matches_daylight(metadata, context):
        return False
    return True


# ── Ranking ──────────────────────────────────────────────────────────────────


def _urgency_key(task: dict) -> tuple[Any, ...]:
    """Sort key: more snoozes first, then older next_trigger first."""
    snooze = task.get("snooze_count") or 0
    next_trigger = task.get("next_trigger") or "9999-12-31 23:59:59"
    return (-snooze, next_trigger)


# ── Public API ───────────────────────────────────────────────────────────────


def pick_best_task(
    tasks: list[dict],
    context: SchedulingContext,
) -> dict | None:
    """Choose the best task to propose right now, or return None.

    *tasks* is typically the output of `filter_screen_free(get_due(now))`.
    *context* comes from `src.reminder.context.gather()`.
    """
    if not tasks:
        return None
    candidates = [t for t in tasks if _task_matches_context(t, context)]
    if not candidates:
        return None
    candidates.sort(key=_urgency_key)
    return candidates[0]

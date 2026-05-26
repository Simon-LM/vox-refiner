#!/usr/bin/env python3
"""Scheduling context aggregator for the smart task picker.

`gather()` builds a single snapshot from the existing sources:
    - the current time (timezone-aware)
    - the user profile  (src/profile.py)
    - the weather       (src/weather.py — best-effort, may be absent)
    - the desktop state (src/reminder/notify.py)
    - the Pomodoro state (src/reminder/pomodoro.py)
    - the unavailability blocks (src/reminder/db.py)

The result is a `SchedulingContext` dataclass with a stable shape that the
picker (étape 6) consumes to filter and rank candidate tasks. Every external
call is wrapped in a try/except so a partial failure (no weather, no Pomodoro,
…) never breaks the whole snapshot — the failing field is simply None/False.

Public API
----------
    gather() -> SchedulingContext
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.profile import load_profile
from src.reminder.db import get_unavailability
from src.reminder.notify import detect_context
from src.reminder import pomodoro as _pomodoro
from src.weather import WeatherError, get_current, is_good_weather

try:
    from zoneinfo import ZoneInfo
    _ZONEINFO_AVAILABLE = True
except ImportError:
    _ZONEINFO_AVAILABLE = False


# ── Public types ─────────────────────────────────────────────────────────────


@dataclass
class SchedulingContext:
    """Snapshot of everything the picker needs to choose a task right now.

    Fields are guaranteed to exist (no AttributeError) but may be None/False
    when the underlying source is unavailable.
    """
    now: datetime                          # tz-aware, in the profile's tz when known
    weekday: int                            # 0=Monday … 6=Sunday
    profile: dict = field(default_factory=dict)
    location_hint: str | None = None
    weather: dict | None = None             # snapshot from src.weather (or None)
    weather_is_good: bool = False
    screen_locked: bool = False
    fullscreen_app: bool = False
    dnd_enabled: bool = False
    pomodoro_phase: str | None = None       # "work" | "break" | None
    currently_unavailable: bool = False
    unavailability_reason: str | None = None


# ── Helpers ──────────────────────────────────────────────────────────────────


def _safe_call(fn, *args, default=None, **kwargs) -> Any:
    """Run *fn* and swallow any exception, returning *default* on failure."""
    try:
        return fn(*args, **kwargs)
    except Exception:  # noqa: BLE001 — context must never propagate failures
        return default


def _profile_now(profile: dict) -> datetime:
    """Return current time in the profile's timezone (falls back to UTC)."""
    tz_name = profile.get("timezone")
    if tz_name and _ZONEINFO_AVAILABLE:
        try:
            return datetime.now(tz=ZoneInfo(tz_name))
        except Exception:  # noqa: BLE001 — invalid tz name
            pass
        # The profile sometimes stores a city ("Paris") instead of an IANA name.
        # Try a best-guess Europe/<city> resolution.
        if "/" not in tz_name:
            try:
                return datetime.now(tz=ZoneInfo(f"Europe/{tz_name}"))
            except Exception:  # noqa: BLE001
                pass
    return datetime.now().astimezone()


_IDENTITY_PREFIXES = (
    "Location:", "Lives in:", "City:", "Ville:", "Localisation:", "Habite:",
)


def _extract_location_hint(profile: dict) -> str | None:
    """Best-effort extraction of a city name suitable for the weather geocoder.

    Priority:
      1. An identity entry starting with one of the location prefixes
      2. The `timezone` top-level field (used loosely as a city by the
         profile AI — e.g. "Paris" rather than "Europe/Paris")
    """
    identity = profile.get("sections", {}).get("identity", [])
    for entry in identity:
        if not isinstance(entry, str):
            continue
        for prefix in _IDENTITY_PREFIXES:
            if entry.startswith(prefix):
                value = entry[len(prefix):].strip()
                if value:
                    return value
    tz = profile.get("timezone")
    if not tz or not isinstance(tz, str):
        return None
    return tz.split("/", 1)[1].replace("_", " ") if "/" in tz else tz


def _pomodoro_phase() -> str | None:
    state = _safe_call(_pomodoro.current_state)
    if state is None:
        return None
    phase = getattr(state, "phase", None)
    return getattr(phase, "value", None) if phase is not None else None


def _check_unavailable(now: datetime) -> tuple[bool, str | None]:
    """Return (is_currently_unavailable, reason)."""
    iso = now.strftime("%Y-%m-%d %H:%M:%S")
    blocks = _safe_call(get_unavailability, iso, iso, default=[])
    if not blocks:
        return False, None
    first = blocks[0]
    return True, first.get("reason")


def _weather_snapshot(location: str | None) -> dict | None:
    if not location:
        return None
    try:
        return get_current(location)
    except WeatherError:
        return None
    except Exception:  # noqa: BLE001 — never break context gathering
        return None


# ── Entry point ──────────────────────────────────────────────────────────────


def gather() -> SchedulingContext:
    """Build a snapshot of the current scheduling context."""
    profile = _safe_call(load_profile, default={}) or {}
    now = _profile_now(profile)
    desktop = _safe_call(detect_context)
    location = _extract_location_hint(profile)
    weather = _weather_snapshot(location)
    unavailable, reason = _check_unavailable(now)

    return SchedulingContext(
        now=now,
        weekday=now.weekday(),
        profile=profile,
        location_hint=location,
        weather=weather,
        weather_is_good=is_good_weather(weather) if weather else False,
        screen_locked=getattr(desktop, "screen_locked", False),
        fullscreen_app=getattr(desktop, "fullscreen_app", False),
        dnd_enabled=getattr(desktop, "dnd_enabled", False),
        pomodoro_phase=_pomodoro_phase(),
        currently_unavailable=unavailable,
        unavailability_reason=reason,
    )

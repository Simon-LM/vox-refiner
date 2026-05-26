"""Unit tests for src/reminder/context.py.

Every external source (profile, weather, notify, pomodoro, db) is mocked so
the tests run without network, X11 or DB access.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import src.reminder.context as ctx_mod
import src.reminder.pomodoro as pom_mod


# ── Helpers ──────────────────────────────────────────────────────────────────


def _desktop(locked=False, dnd=False, fullscreen=False):
    return SimpleNamespace(
        screen_locked=locked, dnd_enabled=dnd, fullscreen_app=fullscreen
    )


def _profile(**overrides):
    base = {
        "timezone": "Paris",
        "language": "fr",
        "sections": {
            "identity": [],
            "rhythm": [],
            "recurring_constraints": [],
            "preferences": [],
            "future_commitments": [],
            "other": [],
        },
        "pending_questions": [],
    }
    for k, v in overrides.items():
        if k == "identity":
            base["sections"]["identity"] = v
        else:
            base[k] = v
    return base


def _weather(temp=18.0, code=1, precip_mm=0.0, prob=10, wind=8.0, is_day=True):
    return {
        "location": "Paris, FR",
        "as_of": "2026-05-22T15:00",
        "temperature_c": temp,
        "precipitation_mm": precip_mm,
        "precipitation_probability": prob,
        "wind_speed_kmh": wind,
        "weather_code": code,
        "weather_description": "Mainly clear",
        "is_day": is_day,
    }


# ── _extract_location_hint ────────────────────────────────────────────────────


class TestExtractLocationHint:
    def test_returns_none_for_empty_profile(self):
        assert ctx_mod._extract_location_hint({}) is None

    def test_uses_timezone_field_when_simple_name(self):
        assert ctx_mod._extract_location_hint(_profile(timezone="Paris")) == "Paris"

    def test_strips_iana_prefix(self):
        assert ctx_mod._extract_location_hint(_profile(timezone="Europe/Paris")) == "Paris"

    def test_iana_underscore_becomes_space(self):
        result = ctx_mod._extract_location_hint(_profile(timezone="America/New_York"))
        assert result == "New York"

    def test_identity_prefix_wins_over_timezone(self):
        prof = _profile(
            timezone="Lyon",
            identity=["Location: Bordeaux"],
        )
        assert ctx_mod._extract_location_hint(prof) == "Bordeaux"

    def test_handles_french_prefix(self):
        prof = _profile(
            timezone="Lyon",
            identity=["Ville: Marseille"],
        )
        assert ctx_mod._extract_location_hint(prof) == "Marseille"

    def test_skips_non_string_identity_entries(self):
        prof = _profile(timezone="Paris", identity=[42, None, "Language: French"])
        assert ctx_mod._extract_location_hint(prof) == "Paris"


# ── gather() — full snapshot composition ─────────────────────────────────────


class TestGather:
    def test_returns_scheduling_context(self, monkeypatch):
        monkeypatch.setattr(ctx_mod, "load_profile", lambda: _profile())
        monkeypatch.setattr(ctx_mod, "detect_context", lambda: _desktop())
        monkeypatch.setattr(ctx_mod, "get_current", lambda loc: _weather())
        monkeypatch.setattr(pom_mod, "current_state", lambda: None)
        monkeypatch.setattr(ctx_mod, "get_unavailability", lambda *a: [])

        result = ctx_mod.gather()
        assert isinstance(result, ctx_mod.SchedulingContext)
        assert result.profile["timezone"] == "Paris"
        assert result.location_hint == "Paris"
        assert result.weather["temperature_c"] == 18.0
        assert result.weather_is_good is True
        assert result.screen_locked is False
        assert result.pomodoro_phase is None
        assert result.currently_unavailable is False

    def test_propagates_desktop_state(self, monkeypatch):
        monkeypatch.setattr(ctx_mod, "load_profile", lambda: _profile())
        monkeypatch.setattr(ctx_mod, "detect_context",
                            lambda: _desktop(locked=True, dnd=True, fullscreen=True))
        monkeypatch.setattr(ctx_mod, "get_current", lambda loc: None)
        monkeypatch.setattr(pom_mod, "current_state", lambda: None)
        monkeypatch.setattr(ctx_mod, "get_unavailability", lambda *a: [])

        result = ctx_mod.gather()
        assert result.screen_locked is True
        assert result.dnd_enabled is True
        assert result.fullscreen_app is True

    def test_pomodoro_phase_extracted(self, monkeypatch):
        monkeypatch.setattr(ctx_mod, "load_profile", lambda: _profile())
        monkeypatch.setattr(ctx_mod, "detect_context", lambda: _desktop())
        monkeypatch.setattr(ctx_mod, "get_current", lambda loc: None)
        monkeypatch.setattr(ctx_mod, "get_unavailability", lambda *a: [])

        fake_state = SimpleNamespace(
            phase=SimpleNamespace(value="break")
        )
        monkeypatch.setattr(pom_mod, "current_state", lambda: fake_state)

        result = ctx_mod.gather()
        assert result.pomodoro_phase == "break"

    def test_currently_unavailable_with_reason(self, monkeypatch):
        monkeypatch.setattr(ctx_mod, "load_profile", lambda: _profile())
        monkeypatch.setattr(ctx_mod, "detect_context", lambda: _desktop())
        monkeypatch.setattr(ctx_mod, "get_current", lambda loc: None)
        monkeypatch.setattr(pom_mod, "current_state", lambda: None)
        monkeypatch.setattr(
            ctx_mod, "get_unavailability",
            lambda *a: [{"id": 1, "start_dt": "x", "end_dt": "y",
                         "reason": "sick", "source": "user_declared"}],
        )

        result = ctx_mod.gather()
        assert result.currently_unavailable is True
        assert result.unavailability_reason == "sick"

    def test_no_location_means_no_weather(self, monkeypatch):
        monkeypatch.setattr(ctx_mod, "load_profile",
                            lambda: _profile(timezone=None))
        monkeypatch.setattr(ctx_mod, "detect_context", lambda: _desktop())
        called: list[str] = []
        monkeypatch.setattr(ctx_mod, "get_current",
                            lambda loc: called.append(loc) or _weather())
        monkeypatch.setattr(pom_mod, "current_state", lambda: None)
        monkeypatch.setattr(ctx_mod, "get_unavailability", lambda *a: [])

        result = ctx_mod.gather()
        assert result.location_hint is None
        assert result.weather is None
        assert called == []   # never queried

    def test_weather_failure_falls_back_to_none(self, monkeypatch):
        from src.weather import WeatherError
        monkeypatch.setattr(ctx_mod, "load_profile", lambda: _profile())
        monkeypatch.setattr(ctx_mod, "detect_context", lambda: _desktop())
        monkeypatch.setattr(
            ctx_mod, "get_current",
            lambda loc: (_ for _ in ()).throw(WeatherError("api down")),
        )
        monkeypatch.setattr(pom_mod, "current_state", lambda: None)
        monkeypatch.setattr(ctx_mod, "get_unavailability", lambda *a: [])

        result = ctx_mod.gather()
        assert result.weather is None
        assert result.weather_is_good is False

    def test_unexpected_weather_exception_swallowed(self, monkeypatch):
        monkeypatch.setattr(ctx_mod, "load_profile", lambda: _profile())
        monkeypatch.setattr(ctx_mod, "detect_context", lambda: _desktop())
        monkeypatch.setattr(
            ctx_mod, "get_current",
            lambda loc: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        monkeypatch.setattr(pom_mod, "current_state", lambda: None)
        monkeypatch.setattr(ctx_mod, "get_unavailability", lambda *a: [])

        result = ctx_mod.gather()
        assert result.weather is None

    def test_pomodoro_failure_yields_none_phase(self, monkeypatch):
        monkeypatch.setattr(ctx_mod, "load_profile", lambda: _profile())
        monkeypatch.setattr(ctx_mod, "detect_context", lambda: _desktop())
        monkeypatch.setattr(ctx_mod, "get_current", lambda loc: None)
        monkeypatch.setattr(
            pom_mod, "current_state",
            lambda: (_ for _ in ()).throw(RuntimeError("state corrupt")),
        )
        monkeypatch.setattr(ctx_mod, "get_unavailability", lambda *a: [])

        result = ctx_mod.gather()
        assert result.pomodoro_phase is None

    def test_db_failure_yields_available(self, monkeypatch):
        monkeypatch.setattr(ctx_mod, "load_profile", lambda: _profile())
        monkeypatch.setattr(ctx_mod, "detect_context", lambda: _desktop())
        monkeypatch.setattr(ctx_mod, "get_current", lambda loc: None)
        monkeypatch.setattr(pom_mod, "current_state", lambda: None)
        monkeypatch.setattr(
            ctx_mod, "get_unavailability",
            lambda *a: (_ for _ in ()).throw(RuntimeError("db dead")),
        )

        result = ctx_mod.gather()
        assert result.currently_unavailable is False
        assert result.unavailability_reason is None

    def test_weekday_matches_now(self, monkeypatch):
        monkeypatch.setattr(ctx_mod, "load_profile", lambda: _profile())
        monkeypatch.setattr(ctx_mod, "detect_context", lambda: _desktop())
        monkeypatch.setattr(ctx_mod, "get_current", lambda loc: None)
        monkeypatch.setattr(pom_mod, "current_state", lambda: None)
        monkeypatch.setattr(ctx_mod, "get_unavailability", lambda *a: [])

        result = ctx_mod.gather()
        assert result.weekday == result.now.weekday()
        assert 0 <= result.weekday <= 6

    def test_bad_weather_marks_weather_is_good_false(self, monkeypatch):
        monkeypatch.setattr(ctx_mod, "load_profile", lambda: _profile())
        monkeypatch.setattr(ctx_mod, "detect_context", lambda: _desktop())
        monkeypatch.setattr(ctx_mod, "get_current",
                            lambda loc: _weather(code=63, precip_mm=3.0, prob=90))
        monkeypatch.setattr(pom_mod, "current_state", lambda: None)
        monkeypatch.setattr(ctx_mod, "get_unavailability", lambda *a: [])

        result = ctx_mod.gather()
        assert result.weather_is_good is False

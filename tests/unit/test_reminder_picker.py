"""Unit tests for src/reminder/picker.py — pure logic, no I/O."""

import json
from datetime import datetime, timezone

import pytest

from src.reminder.context import SchedulingContext
from src.reminder import picker


# ── Helpers ──────────────────────────────────────────────────────────────────


def _ctx(**overrides) -> SchedulingContext:
    base = dict(
        now=datetime(2026, 5, 22, 15, 0, tzinfo=timezone.utc),
        weekday=4,
        profile={},
        location_hint=None,
        weather=None,
        weather_is_good=False,
        screen_locked=False,
        fullscreen_app=False,
        dnd_enabled=False,
        pomodoro_phase=None,
        currently_unavailable=False,
        unavailability_reason=None,
    )
    base.update(overrides)
    return SchedulingContext(**base)


def _task(**kw) -> dict:
    base = {
        "id": 1,
        "title": "Test",
        "category": "task_short",
        "screen_free": 1,
        "estimated_minutes": 10,
        "snooze_count": 0,
        "next_trigger": "2026-05-22 14:00:00",
        "metadata": None,
    }
    base.update(kw)
    return base


def _good_weather(is_day=True):
    return {
        "location": "Paris, FR", "as_of": "2026-05-22T15:00",
        "temperature_c": 18.0, "precipitation_mm": 0.0,
        "precipitation_probability": 10, "wind_speed_kmh": 8.0,
        "weather_code": 1, "weather_description": "Mainly clear",
        "is_day": is_day,
    }


def _bad_weather():
    return {
        "location": "Paris, FR", "as_of": "2026-05-22T15:00",
        "temperature_c": 12.0, "precipitation_mm": 3.0,
        "precipitation_probability": 90, "wind_speed_kmh": 25.0,
        "weather_code": 63, "weather_description": "Moderate rain",
        "is_day": True,
    }


# ── filter_screen_free ───────────────────────────────────────────────────────


class TestFilterScreenFree:
    def test_explicit_true_included(self):
        tasks = [_task(id=1, screen_free=1, category="appointment")]
        assert [t["id"] for t in picker.filter_screen_free(tasks)] == [1]

    def test_explicit_false_excluded(self):
        tasks = [_task(id=2, screen_free=0, category="task_short")]
        assert picker.filter_screen_free(tasks) == []

    def test_null_with_physical_category_included(self):
        tasks = [
            _task(id=3, screen_free=None, category="task_short"),
            _task(id=4, screen_free=None, category="task_long"),
            _task(id=5, screen_free=None, category="errand"),
        ]
        assert {t["id"] for t in picker.filter_screen_free(tasks)} == {3, 4, 5}

    def test_null_with_non_physical_category_excluded(self):
        tasks = [
            _task(id=6, screen_free=None, category="appointment"),
            _task(id=7, screen_free=None, category="admin"),
            _task(id=8, screen_free=None, category="deadline"),
        ]
        assert picker.filter_screen_free(tasks) == []

    def test_empty_input(self):
        assert picker.filter_screen_free([]) == []


# ── _parse_metadata ──────────────────────────────────────────────────────────


class TestParseMetadata:
    def test_handles_dict(self):
        t = _task(metadata={"weather_requirement": "good_required"})
        assert picker._parse_metadata(t) == {"weather_requirement": "good_required"}

    def test_handles_json_string(self):
        t = _task(metadata=json.dumps({"weather_requirement": "good_required"}))
        assert picker._parse_metadata(t)["weather_requirement"] == "good_required"

    def test_handles_none(self):
        assert picker._parse_metadata(_task(metadata=None)) == {}

    def test_handles_empty_string(self):
        assert picker._parse_metadata(_task(metadata="")) == {}

    def test_handles_invalid_json(self):
        assert picker._parse_metadata(_task(metadata="{not json")) == {}

    def test_handles_non_object_json(self):
        assert picker._parse_metadata(_task(metadata="[1, 2, 3]")) == {}


# ── pick_best_task — filters ─────────────────────────────────────────────────


class TestPickBestTaskFilters:
    def test_returns_none_for_empty_list(self):
        assert picker.pick_best_task([], _ctx()) is None

    def test_task_without_metadata_passes_through(self):
        result = picker.pick_best_task([_task(id=1, metadata=None)], _ctx())
        assert result["id"] == 1

    # Weather filter

    def test_good_required_passes_when_weather_good(self):
        t = _task(metadata={"weather_requirement": "good_required"})
        ctx = _ctx(weather=_good_weather(), weather_is_good=True)
        assert picker.pick_best_task([t], ctx)["id"] == 1

    def test_good_required_filtered_when_weather_bad(self):
        t = _task(metadata={"weather_requirement": "good_required"})
        ctx = _ctx(weather=_bad_weather(), weather_is_good=False)
        assert picker.pick_best_task([t], ctx) is None

    def test_good_required_not_filtered_when_weather_unknown(self):
        # Permissive: missing weather info must not penalise the task
        t = _task(metadata={"weather_requirement": "good_required"})
        ctx = _ctx(weather=None, weather_is_good=False)
        assert picker.pick_best_task([t], ctx)["id"] == 1

    def test_outdoor_filtered_when_weather_bad(self):
        t = _task(metadata={"location_type": "outdoor"})
        ctx = _ctx(weather=_bad_weather(), weather_is_good=False)
        assert picker.pick_best_task([t], ctx) is None

    def test_outdoor_passes_when_weather_good(self):
        t = _task(metadata={"location_type": "outdoor"})
        ctx = _ctx(weather=_good_weather(), weather_is_good=True)
        assert picker.pick_best_task([t], ctx)["id"] == 1

    def test_indoor_unaffected_by_bad_weather(self):
        t = _task(metadata={"location_type": "indoor"})
        ctx = _ctx(weather=_bad_weather(), weather_is_good=False)
        assert picker.pick_best_task([t], ctx)["id"] == 1

    # Time constraint filter

    def test_time_constraint_in_range(self):
        t = _task(metadata={"time_constraint": {"earliest_hour": 9, "latest_hour": 18}})
        ctx = _ctx(now=datetime(2026, 5, 22, 14, 0, tzinfo=timezone.utc))
        assert picker.pick_best_task([t], ctx)["id"] == 1

    def test_time_constraint_outside_range(self):
        t = _task(metadata={"time_constraint": {"earliest_hour": 9, "latest_hour": 12}})
        ctx = _ctx(now=datetime(2026, 5, 22, 15, 0, tzinfo=timezone.utc))
        assert picker.pick_best_task([t], ctx) is None

    def test_time_constraint_boundaries_inclusive(self):
        t = _task(metadata={"time_constraint": {"earliest_hour": 9, "latest_hour": 17}})
        ctx9 = _ctx(now=datetime(2026, 5, 22, 9, 0, tzinfo=timezone.utc))
        ctx17 = _ctx(now=datetime(2026, 5, 22, 17, 0, tzinfo=timezone.utc))
        assert picker.pick_best_task([t], ctx9)["id"] == 1
        assert picker.pick_best_task([t], ctx17)["id"] == 1

    def test_invalid_time_constraint_silently_ignored(self):
        t = _task(metadata={"time_constraint": {"earliest_hour": "morning"}})
        assert picker.pick_best_task([t], _ctx())["id"] == 1

    def test_time_constraint_list_matches_first_window(self):
        tc = [{"earliest_hour": 8, "latest_hour": 12}, {"earliest_hour": 14, "latest_hour": 18}]
        t = _task(metadata={"time_constraint": tc})
        ctx = _ctx(now=datetime(2026, 5, 22, 10, 0, tzinfo=timezone.utc))
        assert picker.pick_best_task([t], ctx)["id"] == 1

    def test_time_constraint_list_matches_second_window(self):
        tc = [{"earliest_hour": 8, "latest_hour": 12}, {"earliest_hour": 14, "latest_hour": 18}]
        t = _task(metadata={"time_constraint": tc})
        ctx = _ctx(now=datetime(2026, 5, 22, 15, 0, tzinfo=timezone.utc))
        assert picker.pick_best_task([t], ctx)["id"] == 1

    def test_time_constraint_list_filtered_in_gap(self):
        tc = [{"earliest_hour": 8, "latest_hour": 12}, {"earliest_hour": 14, "latest_hour": 18}]
        t = _task(metadata={"time_constraint": tc})
        ctx = _ctx(now=datetime(2026, 5, 22, 13, 0, tzinfo=timezone.utc))
        assert picker.pick_best_task([t], ctx) is None

    def test_time_constraint_list_all_invalid_windows_permissive(self):
        tc = [{"earliest_hour": "bad"}, {"latest_hour": 12}]
        t = _task(metadata={"time_constraint": tc})
        assert picker.pick_best_task([t], _ctx())["id"] == 1

    # Daylight filter

    def test_requires_daylight_passes_during_day(self):
        t = _task(metadata={"requires_daylight": True})
        ctx = _ctx(weather=_good_weather(is_day=True), weather_is_good=True)
        assert picker.pick_best_task([t], ctx)["id"] == 1

    def test_requires_daylight_filtered_at_night(self):
        t = _task(metadata={"requires_daylight": True})
        ctx = _ctx(weather=_good_weather(is_day=False), weather_is_good=True)
        assert picker.pick_best_task([t], ctx) is None

    def test_requires_daylight_passes_when_weather_unknown(self):
        # Permissive: no weather info → don't penalise
        t = _task(metadata={"requires_daylight": True})
        ctx = _ctx(weather=None)
        assert picker.pick_best_task([t], ctx)["id"] == 1

    def test_requires_daylight_passes_when_is_day_missing(self):
        # Permissive: API didn't return is_day → don't penalise
        weather_no_day = _good_weather(is_day=True)
        weather_no_day["is_day"] = None
        t = _task(metadata={"requires_daylight": True})
        ctx = _ctx(weather=weather_no_day, weather_is_good=True)
        assert picker.pick_best_task([t], ctx)["id"] == 1

    def test_task_without_requires_daylight_not_affected_at_night(self):
        t = _task(metadata={})
        ctx = _ctx(weather=_good_weather(is_day=False), weather_is_good=True)
        assert picker.pick_best_task([t], ctx)["id"] == 1


# ── pick_best_task — ranking ─────────────────────────────────────────────────


class TestPickBestTaskRanking:
    def test_higher_snooze_count_wins(self):
        t1 = _task(id=1, snooze_count=0, next_trigger="2026-05-22 10:00:00")
        t2 = _task(id=2, snooze_count=3, next_trigger="2026-05-22 14:00:00")
        result = picker.pick_best_task([t1, t2], _ctx())
        assert result["id"] == 2

    def test_older_next_trigger_wins_at_equal_snooze(self):
        t1 = _task(id=1, snooze_count=0, next_trigger="2026-05-22 14:00:00")
        t2 = _task(id=2, snooze_count=0, next_trigger="2026-05-22 10:00:00")
        result = picker.pick_best_task([t1, t2], _ctx())
        assert result["id"] == 2

    def test_filtered_tasks_dont_compete(self):
        # Snoozed-heavy outdoor task in bad weather → filtered → second pick wins
        t_outdoor = _task(id=1, snooze_count=5,
                          metadata={"location_type": "outdoor"})
        t_indoor = _task(id=2, snooze_count=0,
                         metadata={"location_type": "indoor"})
        ctx = _ctx(weather=_bad_weather(), weather_is_good=False)
        assert picker.pick_best_task([t_outdoor, t_indoor], ctx)["id"] == 2

    def test_handles_missing_snooze_count(self):
        t1 = _task(id=1)
        t1.pop("snooze_count")
        t2 = _task(id=2, snooze_count=2)
        assert picker.pick_best_task([t1, t2], _ctx())["id"] == 2

    def test_handles_missing_next_trigger(self):
        t1 = _task(id=1, next_trigger=None)
        t2 = _task(id=2, next_trigger="2020-01-01 00:00:00")
        # t2 has a real next_trigger, t1 sorts to the end (next_trigger=None → 9999…)
        assert picker.pick_best_task([t1, t2], _ctx())["id"] == 2

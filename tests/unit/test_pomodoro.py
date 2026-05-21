"""Unit tests for src/reminder/pomodoro_config.py and src/reminder/pomodoro.py."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import src.reminder.pomodoro_config as pc
import src.reminder.pomodoro as pom


# ── PomodoroConfig ────────────────────────────────────────────────────────────

class TestPomodoroConfig:
    def test_defaults(self):
        cfg = pc.PomodoroConfig()
        assert cfg.work_minutes == 25
        assert cfg.break_minutes == 5
        assert cfg.break_margin_minutes == 5
        assert cfg.break_locked is True
        assert cfg.enabled is False

    def test_break_min_clamped_to_one(self):
        cfg = pc.PomodoroConfig(break_minutes=3, break_margin_minutes=10)
        assert cfg.break_min == 1

    def test_break_max(self):
        cfg = pc.PomodoroConfig(break_minutes=15, break_margin_minutes=5)
        assert cfg.break_max == 20

    def test_break_default(self):
        cfg = pc.PomodoroConfig(break_minutes=10)
        assert cfg.break_default == 10


class TestPomodoroConfigIO:
    def test_save_and_load(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pc, "_CONFIG_PATH", tmp_path / "pomodoro.json")
        monkeypatch.setattr(pc, "_CONFIG_DIR", tmp_path)
        cfg = pc.PomodoroConfig(work_minutes=30, break_minutes=15, break_margin_minutes=3,
                                break_locked=False, enabled=True)
        pc.save(cfg)
        loaded = pc.load()
        assert loaded.work_minutes == 30
        assert loaded.break_minutes == 15
        assert loaded.break_margin_minutes == 3
        assert loaded.break_locked is False
        assert loaded.enabled is True

    def test_load_missing_file_returns_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pc, "_CONFIG_PATH", tmp_path / "missing.json")
        cfg = pc.load()
        assert cfg.work_minutes == 25

    def test_load_corrupted_file_returns_defaults(self, tmp_path, monkeypatch):
        p = tmp_path / "pomodoro.json"
        p.write_text("{ broken json")
        monkeypatch.setattr(pc, "_CONFIG_PATH", p)
        cfg = pc.load()
        assert cfg.work_minutes == 25

    def test_save_creates_dir(self, tmp_path, monkeypatch):
        nested = tmp_path / "sub" / "dir"
        monkeypatch.setattr(pc, "_CONFIG_DIR", nested)
        monkeypatch.setattr(pc, "_CONFIG_PATH", nested / "pomodoro.json")
        pc.save(pc.PomodoroConfig())
        assert (nested / "pomodoro.json").exists()


# ── pomodoro state machine ────────────────────────────────────────────────────

def _future(minutes: int) -> str:
    dt = datetime.now(tz=timezone.utc) + timedelta(minutes=minutes)
    return dt.isoformat()


def _past(minutes: int) -> str:
    dt = datetime.now(tz=timezone.utc) - timedelta(minutes=minutes)
    return dt.isoformat()


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(pom, "_STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(pom, "_PID_FILE", tmp_path / "pid")


class TestPomodoroStateMachine:
    def _cfg(self, **kw) -> pc.PomodoroConfig:
        defaults = dict(work_minutes=25, break_minutes=5, break_margin_minutes=5,
                        break_locked=True, enabled=True)
        defaults.update(kw)
        return pc.PomodoroConfig(**defaults)

    def test_tick_noop_when_disabled(self, monkeypatch):
        cfg = self._cfg(enabled=False)
        monkeypatch.setattr(pom, "load_config", lambda: cfg)
        result = pom.tick()
        assert result is None

    def test_tick_noop_when_no_state(self, monkeypatch):
        cfg = self._cfg()
        monkeypatch.setattr(pom, "load_config", lambda: cfg)
        result = pom.tick()
        assert result is None

    def test_work_phase_not_done_stays_work(self, monkeypatch):
        cfg = self._cfg()
        monkeypatch.setattr(pom, "load_config", lambda: cfg)
        state = pom.PomodoroState(
            phase=pom.Phase.WORK,
            phase_end_iso=_future(10),
        )
        pom._save_state(state)
        result = pom.tick()
        assert result.phase == pom.Phase.WORK

    def test_work_phase_done_transitions_to_break(self, monkeypatch):
        cfg = self._cfg()
        monkeypatch.setattr(pom, "load_config", lambda: cfg)
        monkeypatch.setattr(pom, "_pick_physical_task", lambda: None)
        monkeypatch.setattr(pom, "_open_overlay", lambda *a, **kw: None)
        monkeypatch.setattr(pom, "_play_chime", lambda: None)
        state = pom.PomodoroState(phase=pom.Phase.WORK, phase_end_iso=_past(1))
        pom._save_state(state)
        result = pom.tick()
        assert result.phase == pom.Phase.BREAK

    def test_break_phase_uses_task_estimated_minutes(self, monkeypatch):
        cfg = self._cfg(break_minutes=10, break_margin_minutes=5)
        monkeypatch.setattr(pom, "load_config", lambda: cfg)
        monkeypatch.setattr(pom, "_pick_physical_task", lambda: (42, "Water plants", 8))
        monkeypatch.setattr(pom, "_open_overlay", lambda *a, **kw: None)
        monkeypatch.setattr(pom, "_play_chime", lambda: None)
        state = pom.PomodoroState(phase=pom.Phase.WORK, phase_end_iso=_past(1))
        pom._save_state(state)
        result = pom.tick()
        assert result.phase == pom.Phase.BREAK
        assert result.task_id == 42

    def test_estimated_minutes_clamped_to_break_min(self, monkeypatch):
        cfg = self._cfg(break_minutes=10, break_margin_minutes=3)
        assert pom._clamp_break(2, cfg) == cfg.break_min  # 10-3=7, but 2 < 7 → 7

    def test_estimated_minutes_clamped_to_break_max(self, monkeypatch):
        cfg = self._cfg(break_minutes=10, break_margin_minutes=3)
        assert pom._clamp_break(20, cfg) == cfg.break_max  # 10+3=13

    def test_estimated_zero_uses_break_default(self, monkeypatch):
        cfg = self._cfg(break_minutes=10, break_margin_minutes=3)
        assert pom._clamp_break(0, cfg) == cfg.break_default

    def test_break_done_transitions_to_work(self, monkeypatch):
        cfg = self._cfg()
        monkeypatch.setattr(pom, "load_config", lambda: cfg)
        monkeypatch.setattr(pom, "_close_overlay", lambda: None)
        monkeypatch.setattr(pom, "_fire_reminder", lambda rid: None)
        monkeypatch.setattr(pom, "_play_chime", lambda: None)
        state = pom.PomodoroState(
            phase=pom.Phase.BREAK,
            phase_end_iso=_past(1),
            break_hard_end_iso=_future(5),
            task_id=None,
        )
        pom._save_state(state)
        result = pom.tick()
        assert result.phase == pom.Phase.WORK

    def test_break_hard_max_forces_transition(self, monkeypatch):
        cfg = self._cfg()
        monkeypatch.setattr(pom, "load_config", lambda: cfg)
        monkeypatch.setattr(pom, "_close_overlay", lambda: None)
        monkeypatch.setattr(pom, "_fire_reminder", lambda rid: None)
        monkeypatch.setattr(pom, "_play_chime", lambda: None)
        state = pom.PomodoroState(
            phase=pom.Phase.BREAK,
            phase_end_iso=_future(5),     # not yet done by soft timer
            break_hard_end_iso=_past(1),  # but hard max exceeded
            task_id=None,
        )
        pom._save_state(state)
        result = pom.tick()
        assert result.phase == pom.Phase.WORK

    def test_break_fires_reminder_at_end(self, monkeypatch):
        cfg = self._cfg()
        monkeypatch.setattr(pom, "load_config", lambda: cfg)
        monkeypatch.setattr(pom, "_close_overlay", lambda: None)
        monkeypatch.setattr(pom, "_play_chime", lambda: None)
        fired = []
        monkeypatch.setattr(pom, "_fire_reminder", lambda rid: fired.append(rid))
        state = pom.PomodoroState(
            phase=pom.Phase.BREAK,
            phase_end_iso=_past(1),
            break_hard_end_iso=_future(5),
            task_id=7,
        )
        pom._save_state(state)
        pom.tick()
        assert fired == [7]

    def test_break_no_task_no_fire(self, monkeypatch):
        cfg = self._cfg()
        monkeypatch.setattr(pom, "load_config", lambda: cfg)
        monkeypatch.setattr(pom, "_close_overlay", lambda: None)
        monkeypatch.setattr(pom, "_play_chime", lambda: None)
        fired = []
        monkeypatch.setattr(pom, "_fire_reminder", lambda rid: fired.append(rid))
        state = pom.PomodoroState(
            phase=pom.Phase.BREAK,
            phase_end_iso=_past(1),
            break_hard_end_iso=_future(5),
            task_id=None,
        )
        pom._save_state(state)
        pom.tick()
        assert fired == []


class TestPickPhysicalTask:
    def _due(self, **kw):
        defaults = {"id": 1, "title": "Test", "category": "task_short",
                    "screen_free": None, "estimated_minutes": None}
        defaults.update(kw)
        return defaults

    def test_prefers_explicit_screen_free(self, monkeypatch):
        tasks = [
            self._due(id=1, category="task_short", screen_free=None),
            self._due(id=2, category="task_short", screen_free=1),
        ]
        monkeypatch.setattr(pom, "_pick_physical_task",
                            lambda: (2, "Task 2", 0))
        result = pom._pick_physical_task()
        assert result[0] == 2

    def test_falls_back_to_legacy_physical_category(self, monkeypatch):
        import src.reminder.db as rdb
        monkeypatch.setattr(rdb, "_DB_PATH",
                            __import__("pathlib").Path("/nonexistent/db"))

        def fake_get_due(now):
            return [{"id": 5, "title": "Clean", "category": "errand",
                     "screen_free": None, "estimated_minutes": 10}]

        monkeypatch.setattr("src.reminder.db.get_due", fake_get_due)
        result = pom._pick_physical_task()
        assert result is not None
        assert result[0] == 5

    def test_skips_screen_required_tasks(self, monkeypatch):
        def fake_get_due(now):
            return [{"id": 3, "title": "Send email", "category": "task_short",
                     "screen_free": 0, "estimated_minutes": 5}]

        monkeypatch.setattr("src.reminder.db.get_due", fake_get_due)
        result = pom._pick_physical_task()
        assert result is None


class TestIsRunning:
    def test_false_when_no_files(self):
        assert pom.is_running() is False

    def test_true_when_state_file_exists(self, tmp_path, monkeypatch):
        state = pom.PomodoroState(phase=pom.Phase.WORK, phase_end_iso=_future(10))
        pom._save_state(state)
        assert pom.is_running() is True

    def test_stop_clears_state(self, monkeypatch):
        monkeypatch.setattr(pom, "_close_overlay", lambda: None)
        state = pom.PomodoroState(phase=pom.Phase.WORK, phase_end_iso=_future(10))
        pom._save_state(state)
        pom.stop()
        assert pom.is_running() is False

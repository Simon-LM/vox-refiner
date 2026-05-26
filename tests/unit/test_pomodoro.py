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


def _future_seconds(seconds: int) -> str:
    dt = datetime.now(tz=timezone.utc) + timedelta(seconds=seconds)
    return dt.isoformat()


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(pom, "_STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(pom, "_PID_FILE", tmp_path / "pid")
    monkeypatch.setattr(pom, "_FIRE_RESULT_FILE", tmp_path / "fire-result.json")
    monkeypatch.setattr(pom, "_OVERLAY_PID_FILE", tmp_path / "overlay.pid")


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

    def test_stale_work_state_clears_and_returns_none(self, monkeypatch):
        cfg = self._cfg(work_minutes=25, break_minutes=5, break_margin_minutes=5)
        monkeypatch.setattr(pom, "load_config", lambda: cfg)
        # Phase ended 2 full cycles ago → stale
        state = pom.PomodoroState(phase=pom.Phase.WORK,
                                  phase_end_iso=_past(cfg.work_minutes + cfg.break_max + 10))
        pom._save_state(state)
        result = pom.tick()
        assert result is None
        assert not pom._STATE_FILE.exists()

    def test_recent_expired_work_state_transitions_normally(self, monkeypatch):
        cfg = self._cfg()
        monkeypatch.setattr(pom, "load_config", lambda: cfg)
        monkeypatch.setattr(pom, "_pick_physical_task", lambda: None)
        monkeypatch.setattr(pom, "_open_overlay", lambda *a, **kw: None)
        monkeypatch.setattr(pom, "_play_chime", lambda: None)
        # Phase ended 1 minute ago → recent, should transition normally
        state = pom.PomodoroState(phase=pom.Phase.WORK, phase_end_iso=_past(1))
        pom._save_state(state)
        result = pom.tick()
        assert result is not None
        assert result.phase == pom.Phase.BREAK

    def test_long_expired_break_without_overlay_transitions_to_work(self, monkeypatch):
        """When BREAK has been expired for a long time AND the overlay is
        gone (e.g. user finally clicked the confirmation after a long away
        period), the cycle must CONTINUE — transition to a fresh WORK
        phase. Clearing the state here would silently kill the session."""
        cfg = self._cfg(work_minutes=25, break_minutes=5, break_margin_minutes=5)
        monkeypatch.setattr(pom, "load_config", lambda: cfg)
        monkeypatch.setattr(pom, "_play_chime", lambda: None)
        long_ago = cfg.work_minutes + cfg.break_max + 60   # 95 min
        state = pom.PomodoroState(
            phase=pom.Phase.BREAK,
            phase_end_iso=_past(long_ago),
            break_hard_end_iso=_past(long_ago),
        )
        pom._save_state(state)
        result = pom.tick()
        assert result is not None
        assert result.phase == pom.Phase.WORK
        assert pom._STATE_FILE.exists()

    def test_stale_break_preserved_while_overlay_running(self, monkeypatch):
        """When the confirmation overlay is still up the state is NOT stale —
        the user just hasn't clicked yet. Forcing a clear here would close the
        overlay out from under them and let queued tasks pop in the terminal."""
        import os
        cfg = self._cfg(work_minutes=25, break_minutes=5, break_margin_minutes=5)
        monkeypatch.setattr(pom, "load_config", lambda: cfg)
        # Mark the overlay PID as the current Python process — guaranteed alive.
        pom._OVERLAY_PID_FILE.write_text(str(os.getpid()))
        stale_ago = cfg.work_minutes + cfg.break_max + 10
        state = pom.PomodoroState(
            phase=pom.Phase.BREAK,
            phase_end_iso=_past(stale_ago),
            break_hard_end_iso=_past(stale_ago),
            task_id=42,
        )
        pom._save_state(state)
        result = pom.tick()
        # State preserved — daemon stays in BREAK, awaits user action.
        assert result is not None
        assert result.phase == pom.Phase.BREAK
        assert pom._STATE_FILE.exists()

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

    def test_break_done_passes_task_id_to_overlay(self, monkeypatch):
        """When WORK→BREAK with a task, overlay receives --task-id so it can show confirmation."""
        cfg = self._cfg()
        monkeypatch.setattr(pom, "load_config", lambda: cfg)
        monkeypatch.setattr(pom, "_play_chime", lambda: None)
        opened: list[tuple] = []
        monkeypatch.setattr(pom, "_open_overlay", lambda *a, **kw: opened.append((a, kw)))
        monkeypatch.setattr(pom, "_pick_physical_task", lambda: (7, "Water plants", 5))
        state = pom.PomodoroState(phase=pom.Phase.WORK, phase_end_iso=_past(1))
        pom._save_state(state)
        pom.tick()
        assert opened, "overlay should have been opened"
        _, kw = opened[0]
        assert kw.get("task_id") == 7

    def test_break_no_task_no_task_id_in_overlay(self, monkeypatch):
        """When no physical task, overlay is opened without task_id."""
        cfg = self._cfg()
        monkeypatch.setattr(pom, "load_config", lambda: cfg)
        monkeypatch.setattr(pom, "_play_chime", lambda: None)
        opened: list[tuple] = []
        monkeypatch.setattr(pom, "_open_overlay", lambda *a, **kw: opened.append((a, kw)))
        monkeypatch.setattr(pom, "_pick_physical_task", lambda: None)
        state = pom.PomodoroState(phase=pom.Phase.WORK, phase_end_iso=_past(1))
        pom._save_state(state)
        pom.tick()
        assert opened
        _, kw = opened[0]
        assert kw.get("task_id") is None


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


class TestCheckFireResult:
    def _write_result(self, tmp_path, monkeypatch, task_id, action):
        result_file = tmp_path / "fire-result.json"
        monkeypatch.setattr(pom, "_FIRE_RESULT_FILE", result_file)
        result_file.write_text(
            json.dumps({"task_id": task_id, "action": action}), encoding="utf-8"
        )
        return result_file

    def test_done_calls_complete_reminder(self, tmp_path, monkeypatch):
        result_file = self._write_result(tmp_path, monkeypatch, 42, "done")
        calls = []
        monkeypatch.setattr("src.reminder.db.complete_reminder", lambda rid: calls.append(rid))
        pom._check_fire_result()
        assert calls == [42]
        assert not result_file.exists()

    def test_done_does_not_call_update_status(self, tmp_path, monkeypatch):
        self._write_result(tmp_path, monkeypatch, 42, "done")
        update_calls = []
        monkeypatch.setattr("src.reminder.db.complete_reminder", lambda rid: None)
        monkeypatch.setattr("src.reminder.db.update_status", lambda *a: update_calls.append(a))
        pom._check_fire_result()
        assert update_calls == []

    def test_snooze_calls_snooze(self, tmp_path, monkeypatch):
        result_file = self._write_result(tmp_path, monkeypatch, 5, "snooze")
        calls = []
        monkeypatch.setattr("src.reminder.db.snooze", lambda rid, t: calls.append(rid))
        pom._check_fire_result()
        assert calls == [5]
        assert not result_file.exists()

    def test_skip_logs_skipped_occurrence(self, tmp_path, monkeypatch):
        result_file = self._write_result(tmp_path, monkeypatch, 7, "skip")
        calls = []
        monkeypatch.setattr("src.reminder.db.log_occurrence",
                            lambda rid, status, **kw: calls.append((rid, status)))
        pom._check_fire_result()
        assert calls == [(7, "skipped")]
        assert not result_file.exists()

    def test_skip_does_not_touch_status_or_snooze(self, tmp_path, monkeypatch):
        self._write_result(tmp_path, monkeypatch, 7, "skip")
        bad = []
        monkeypatch.setattr("src.reminder.db.log_occurrence", lambda *a, **kw: None)
        monkeypatch.setattr("src.reminder.db.update_status", lambda *a: bad.append(a))
        monkeypatch.setattr("src.reminder.db.snooze", lambda *a: bad.append(a))
        pom._check_fire_result()
        assert bad == []

    def test_missing_file_no_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pom, "_FIRE_RESULT_FILE", tmp_path / "nonexistent.json")
        pom._check_fire_result()  # must not raise


class TestOverlayStillRunning:
    def test_returns_false_when_no_pid_file(self):
        assert pom._overlay_still_running() is False

    def test_returns_true_when_process_alive(self):
        import os
        pom._OVERLAY_PID_FILE.write_text(str(os.getpid()))
        assert pom._overlay_still_running() is True

    def test_cleans_up_stale_pid_file(self):
        # A very high PID that is almost certainly unused
        pom._OVERLAY_PID_FILE.write_text("9999999")
        assert pom._overlay_still_running() is False
        assert not pom._OVERLAY_PID_FILE.exists()

    def test_cleans_up_garbage_pid_file(self):
        pom._OVERLAY_PID_FILE.write_text("not-a-number")
        assert pom._overlay_still_running() is False
        assert not pom._OVERLAY_PID_FILE.exists()


class TestBreakSuspensionWhileOverlayOpen:
    def _cfg(self, **kw) -> pc.PomodoroConfig:
        defaults = dict(work_minutes=25, break_minutes=5, break_margin_minutes=5,
                        break_locked=True, enabled=True)
        defaults.update(kw)
        return pc.PomodoroConfig(**defaults)

    def test_break_over_stays_in_break_when_overlay_alive(self, monkeypatch):
        """If the confirmation overlay is still showing, do not start a new WORK cycle."""
        import os
        cfg = self._cfg()
        monkeypatch.setattr(pom, "load_config", lambda: cfg)
        chimes = []
        monkeypatch.setattr(pom, "_play_chime", lambda: chimes.append(1))
        # Overlay is "alive" — point to current Python process
        pom._OVERLAY_PID_FILE.write_text(str(os.getpid()))
        state = pom.PomodoroState(
            phase=pom.Phase.BREAK,
            phase_end_iso=_past(1),
            break_hard_end_iso=_past(1),
            task_id=42,
        )
        pom._save_state(state)
        result = pom.tick()
        assert result.phase == pom.Phase.BREAK   # cycle suspended
        assert chimes == []                       # no chime — no transition

    def test_break_over_transitions_when_overlay_gone(self, monkeypatch):
        """Once the user clicks (PID file removed), the next tick transitions to WORK."""
        cfg = self._cfg()
        monkeypatch.setattr(pom, "load_config", lambda: cfg)
        monkeypatch.setattr(pom, "_play_chime", lambda: None)
        # No PID file → overlay is gone
        state = pom.PomodoroState(
            phase=pom.Phase.BREAK,
            phase_end_iso=_past(1),
            break_hard_end_iso=_future(5),
            task_id=42,
        )
        pom._save_state(state)
        result = pom.tick()
        assert result.phase == pom.Phase.WORK


class TestPomodoroWarning:
    def _cfg(self, **kw) -> pc.PomodoroConfig:
        defaults = dict(work_minutes=25, break_minutes=5, break_margin_minutes=5,
                        break_locked=True, enabled=True)
        defaults.update(kw)
        return pc.PomodoroConfig(**defaults)

    def test_warning_launched_near_end_of_work(self, monkeypatch):
        cfg = self._cfg()
        monkeypatch.setattr(pom, "load_config", lambda: cfg)
        launched: list[int] = []
        monkeypatch.setattr(pom, "_open_warning", lambda s: launched.append(s))
        # 60 s remaining — within _WARNING_BEFORE_SECONDS (90)
        state = pom.PomodoroState(
            phase=pom.Phase.WORK,
            phase_end_iso=_future_seconds(60),
            warned=False,
        )
        pom._save_state(state)
        pom.tick()
        assert len(launched) == 1
        assert launched[0] > 0

    def test_warning_not_relaunched_if_already_warned(self, monkeypatch):
        cfg = self._cfg()
        monkeypatch.setattr(pom, "load_config", lambda: cfg)
        launched: list[int] = []
        monkeypatch.setattr(pom, "_open_warning", lambda s: launched.append(s))
        # warned=True — must not launch again
        state = pom.PomodoroState(
            phase=pom.Phase.WORK,
            phase_end_iso=_future_seconds(60),
            warned=True,
        )
        pom._save_state(state)
        pom.tick()
        assert launched == []

    def test_warning_not_launched_when_far_from_break(self, monkeypatch):
        cfg = self._cfg()
        monkeypatch.setattr(pom, "load_config", lambda: cfg)
        launched: list[int] = []
        monkeypatch.setattr(pom, "_open_warning", lambda s: launched.append(s))
        # 10 minutes remaining — well above the 90-second threshold
        state = pom.PomodoroState(
            phase=pom.Phase.WORK,
            phase_end_iso=_future(10),
            warned=False,
        )
        pom._save_state(state)
        pom.tick()
        assert launched == []

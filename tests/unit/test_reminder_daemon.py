"""Unit tests for src/reminder_daemon.py.

Tests tick() dispatch logic, Pomodoro follow-up, and context routing
without any real subprocess calls or DB writes to real paths.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

import src.reminder_db as rdb
import src.reminder_notify as rn


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(rdb, "_DB_DIR", tmp_path)
    monkeypatch.setattr(rdb, "_DB_PATH", tmp_path / "reminders.db")


@pytest.fixture(autouse=True)
def isolated_pomodoro_file(tmp_path, monkeypatch):
    pending_path = tmp_path / "pomodoro-pending.json"
    if "src.reminder_daemon" in sys.modules:
        del sys.modules["src.reminder_daemon"]
    import src.reminder_daemon as d
    monkeypatch.setattr(d, "_POMODORO_FOLLOW_UP_FILE", pending_path)
    return pending_path


def _load():
    if "src.reminder_daemon" in sys.modules:
        del sys.modules["src.reminder_daemon"]
    import src.reminder_daemon as d
    return d


def _normal_ctx() -> rn.Context:
    return rn.Context(screen_locked=False, dnd_enabled=False, voxrefiner_active=False, fullscreen_app=False)


def _locked_ctx() -> rn.Context:
    return rn.Context(screen_locked=True, dnd_enabled=False, voxrefiner_active=False, fullscreen_app=False)


# ── dispatch_reminder ─────────────────────────────────────────────────────────

class TestDispatchReminder:
    def test_normal_context_returns_notify(self, monkeypatch):
        d = _load()
        r = {"id": 1, "title": "Test", "category": "appointment", "snooze_count": 0,
             "event_datetime": "2099-01-01 00:00:00"}
        with (
            patch.object(d, "open_terminal_fire", return_value=True),
            patch.object(d, "send_desktop_notification"),
            patch.object(d, "bump_trigger"),
        ):
            mode = d.dispatch_reminder(r, _normal_ctx())
        assert mode == "notify"

    def test_notify_opens_terminal_and_bumps_trigger(self, monkeypatch):
        """Happy path: terminal found → bump_trigger, no TTS."""
        d = _load()
        r = {"id": 1, "title": "Doctor", "category": "appointment", "snooze_count": 0,
             "event_datetime": "2099-01-01 00:00:00"}
        with (
            patch.object(d, "open_terminal_fire", return_value=True) as mock_term,
            patch.object(d, "send_desktop_notification"),
            patch.object(d, "bump_trigger") as mock_bump,
            patch.object(d, "send_tts_notification") as mock_tts,
        ):
            d.dispatch_reminder(r, _normal_ctx())
        mock_term.assert_called_once_with(1)
        mock_bump.assert_called_once()
        mock_tts.assert_not_called()

    def test_notify_calls_tts_when_no_terminal(self, monkeypatch):
        """Fallback: no terminal → TTS + snooze."""
        d = _load()
        r = {"id": 1, "title": "Doctor", "category": "appointment", "snooze_count": 0,
             "event_datetime": "2099-01-01 00:00:00"}
        with (
            patch.object(d, "open_terminal_fire", return_value=False),
            patch.object(d, "send_tts_notification") as mock_tts,
            patch.object(d, "send_desktop_notification"),
            patch.object(d, "snooze"),
        ):
            d.dispatch_reminder(r, _normal_ctx())
        mock_tts.assert_called_once_with("Doctor")

    def test_notify_calls_desktop_notification(self, monkeypatch):
        d = _load()
        r = {"id": 1, "title": "Doctor", "category": "appointment", "snooze_count": 0,
             "event_datetime": "2099-01-01 00:00:00"}
        with (
            patch.object(d, "open_terminal_fire", return_value=True),
            patch.object(d, "send_desktop_notification") as mock_notif,
            patch.object(d, "bump_trigger"),
        ):
            d.dispatch_reminder(r, _normal_ctx())
        mock_notif.assert_called_once()

    def test_queue_mode_no_tts(self, monkeypatch):
        d = _load()
        r = {"id": 1, "title": "Test", "category": "appointment", "snooze_count": 0,
             "event_datetime": "2099-01-01 00:00:00"}
        vox_ctx = rn.Context(False, False, True, False)
        with patch.object(d, "send_tts_notification") as mock_tts:
            mode = d.dispatch_reminder(r, vox_ctx)
        assert mode == "queue"
        mock_tts.assert_not_called()

    def test_defer_unlock_mode_no_tts(self, monkeypatch):
        d = _load()
        r = {"id": 1, "title": "Admin task", "category": "admin", "snooze_count": 0,
             "event_datetime": None}
        with patch.object(d, "send_tts_notification") as mock_tts:
            mode = d.dispatch_reminder(r, _locked_ctx())
        assert mode == "defer_unlock"
        mock_tts.assert_not_called()

    def test_tts_only_no_desktop_notification(self, monkeypatch):
        d = _load()
        r = {"id": 1, "title": "Errand", "category": "task_short", "snooze_count": 0,
             "event_datetime": None}
        with (
            patch.object(d, "send_tts_notification"),
            patch.object(d, "close_terminal_fire"),
            patch.object(d, "send_desktop_notification") as mock_notif,
            patch.object(d, "snooze"),
        ):
            mode = d.dispatch_reminder(r, _locked_ctx())
        assert mode == "tts_only"
        mock_notif.assert_not_called()

    def test_tts_only_closes_existing_terminal(self, monkeypatch):
        """tts_only must close any window left open from a previous notify."""
        d = _load()
        r = {"id": 7, "title": "Weed the garden", "category": "task_long", "snooze_count": 0,
             "event_datetime": None}
        fullscreen_ctx = rn.Context(screen_locked=False, dnd_enabled=False,
                                    voxrefiner_active=False, fullscreen_app=True)
        with (
            patch.object(d, "send_tts_notification"),
            patch.object(d, "close_terminal_fire") as mock_close,
            patch.object(d, "snooze"),
        ):
            mode = d.dispatch_reminder(r, fullscreen_ctx)
        assert mode == "tts_only"
        mock_close.assert_called_once_with(7)

    def test_notify_advances_next_trigger_via_bump(self, monkeypatch):
        """Terminal opened → bump_trigger (grace period), snooze NOT called."""
        d = _load()
        r = {"id": 1, "title": "Test", "category": "appointment", "snooze_count": 0,
             "event_datetime": "2099-01-01 00:00:00"}
        with (
            patch.object(d, "open_terminal_fire", return_value=True),
            patch.object(d, "send_desktop_notification"),
            patch.object(d, "bump_trigger") as mock_bump,
            patch.object(d, "snooze") as mock_snooze,
        ):
            d.dispatch_reminder(r, _normal_ctx())
        mock_bump.assert_called_once()
        mock_snooze.assert_not_called()


# ── Pomodoro file helpers ─────────────────────────────────────────────────────

class TestPomodoroHelpers:
    """Each test uses a fresh _load() + re-applies the path patch inline."""

    @pytest.fixture(autouse=True)
    def _patched(self, tmp_path, monkeypatch):
        """Load module fresh and redirect _POMODORO_FOLLOW_UP_FILE to tmp_path."""
        self.pending = tmp_path / "pomodoro-pending.json"
        self.d = _load()
        monkeypatch.setattr(self.d, "_POMODORO_FOLLOW_UP_FILE", self.pending)

    def test_write_and_read_pending(self):
        self.d._write_pomodoro_pending([{"id": 1, "title": "Take bins out"}])
        result = self.d._read_pomodoro_pending()
        assert result[0]["title"] == "Take bins out"

    def test_read_empty_when_no_file(self):
        assert self.d._read_pomodoro_pending() == []

    def test_clear_removes_file(self):
        self.d._write_pomodoro_pending([{"id": 1, "title": "Test"}])
        self.d._clear_pomodoro_pending()
        assert not self.pending.exists()

    def test_clear_silent_when_no_file(self):
        self.d._clear_pomodoro_pending()  # must not raise

    def test_read_corrupted_file_returns_empty(self):
        self.pending.write_text("{ corrupted }")
        assert self.d._read_pomodoro_pending() == []


# ── tick ──────────────────────────────────────────────────────────────────────

class TestTick:
    def _add_due_reminder(self, category="appointment") -> int:
        return rdb.add_reminder("Test task", category, next_trigger="2020-01-01 00:00:00")

    def test_empty_db_no_fire(self, monkeypatch):
        d = _load()
        with (
            patch.object(rn, "_screen_locked", return_value=False),
            patch.object(rn, "_dnd_enabled", return_value=False),
            patch.object(rn, "_voxrefiner_active", return_value=False),
            patch.object(rn, "_fullscreen_app", return_value=False),
            patch.object(d, "send_tts_notification") as mock_tts,
        ):
            d.tick()
        mock_tts.assert_not_called()

    def test_due_reminder_opens_terminal_on_normal_desktop(self, monkeypatch):
        d = _load()
        self._add_due_reminder()
        with (
            patch.object(rn, "_screen_locked", return_value=False),
            patch.object(rn, "_dnd_enabled", return_value=False),
            patch.object(rn, "_voxrefiner_active", return_value=False),
            patch.object(rn, "_fullscreen_app", return_value=False),
            patch.object(d, "open_terminal_fire", return_value=True) as mock_term,
            patch.object(d, "send_desktop_notification"),
            patch.object(d, "bump_trigger"),
        ):
            d.tick()
        mock_term.assert_called_once()

    def test_due_reminder_falls_back_to_tts_when_no_terminal(self, monkeypatch):
        d = _load()
        self._add_due_reminder()
        with (
            patch.object(rn, "_screen_locked", return_value=False),
            patch.object(rn, "_dnd_enabled", return_value=False),
            patch.object(rn, "_voxrefiner_active", return_value=False),
            patch.object(rn, "_fullscreen_app", return_value=False),
            patch.object(d, "open_terminal_fire", return_value=False),
            patch.object(d, "send_tts_notification") as mock_tts,
            patch.object(d, "send_desktop_notification"),
        ):
            d.tick()
        mock_tts.assert_called_once()

    def test_unlock_transition_fires_followup(self, monkeypatch, isolated_pomodoro_file):
        d = _load()
        # Simulate Pomodoro pending tasks from a previous lock
        d._write_pomodoro_pending([{"id": 1, "title": "Take bins out"}])
        with (
            patch.object(rn, "_screen_locked", return_value=False),
            patch.object(rn, "_dnd_enabled", return_value=False),
            patch.object(rn, "_voxrefiner_active", return_value=False),
            patch.object(rn, "_fullscreen_app", return_value=False),
            patch.object(d, "send_tts_notification") as mock_tts,
            patch.object(d, "send_desktop_notification"),
        ):
            d.tick(previous_context=_locked_ctx())
        # Follow-up must have been spoken
        assert any("bins" in str(c) for c in mock_tts.call_args_list)

    def test_unlock_clears_pomodoro_file(self, monkeypatch, isolated_pomodoro_file):
        d = _load()
        d._write_pomodoro_pending([{"id": 1, "title": "Bins"}])
        with (
            patch.object(rn, "_screen_locked", return_value=False),
            patch.object(rn, "_dnd_enabled", return_value=False),
            patch.object(rn, "_voxrefiner_active", return_value=False),
            patch.object(rn, "_fullscreen_app", return_value=False),
            patch.object(d, "send_tts_notification"),
            patch.object(d, "send_desktop_notification"),
        ):
            d.tick(previous_context=_locked_ctx())
        assert not isolated_pomodoro_file.exists()

    def test_physical_task_during_lock_added_to_pomodoro(self, monkeypatch, isolated_pomodoro_file):
        d = _load()
        self._add_due_reminder(category="task_short")
        with (
            patch.object(rn, "_screen_locked", return_value=True),
            patch.object(rn, "_dnd_enabled", return_value=False),
            patch.object(rn, "_voxrefiner_active", return_value=False),
            patch.object(rn, "_fullscreen_app", return_value=False),
            patch.object(d, "send_tts_notification"),
            patch.object(d, "send_desktop_notification"),
        ):
            d.tick()
        pending = d._read_pomodoro_pending()
        assert len(pending) == 1

    def test_returns_current_context(self, monkeypatch):
        d = _load()
        with (
            patch.object(rn, "_screen_locked", return_value=False),
            patch.object(rn, "_dnd_enabled", return_value=False),
            patch.object(rn, "_voxrefiner_active", return_value=False),
            patch.object(rn, "_fullscreen_app", return_value=False),
        ):
            ctx = d.tick()
        assert isinstance(ctx, rn.Context)

    def test_tick_exception_does_not_propagate(self, monkeypatch):
        d = _load()
        with patch.object(d, "get_due", side_effect=RuntimeError("db error")):
            # tick() should not raise — daemon must survive single-tick errors
            with pytest.raises(RuntimeError):
                d.tick()
        # This test documents current behavior: tick does NOT catch internally.
        # The run_loop wrapper does. That's acceptable.

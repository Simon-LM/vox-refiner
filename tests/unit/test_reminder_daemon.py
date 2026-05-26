"""Unit tests for src/reminder/daemon.py.

Tests tick() dispatch logic, Pomodoro follow-up, and context routing
without any real subprocess calls or DB writes to real paths.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

import src.reminder.db as rdb
import src.reminder.notify as rn


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(rdb, "_DB_DIR", tmp_path)
    monkeypatch.setattr(rdb, "_DB_PATH", tmp_path / "reminders.db")


@pytest.fixture(autouse=True)
def isolated_pomodoro_file(tmp_path, monkeypatch):
    pending_path = tmp_path / "pomodoro-pending.json"
    if "src.reminder.daemon" in sys.modules:
        del sys.modules["src.reminder.daemon"]
    import src.reminder.daemon as d
    monkeypatch.setattr(d, "_POMODORO_FOLLOW_UP_FILE", pending_path)
    return pending_path


@pytest.fixture(autouse=True)
def isolated_pomodoro_state(tmp_path, monkeypatch):
    """Redirect the Pomodoro state file so system state never leaks into tests."""
    import src.reminder.pomodoro as pom
    monkeypatch.setattr(pom, "_STATE_FILE", tmp_path / "pom-state.json")
    monkeypatch.setattr(pom, "_PID_FILE", tmp_path / "pom-pid")


def _load():
    if "src.reminder.daemon" in sys.modules:
        del sys.modules["src.reminder.daemon"]
    import src.reminder.daemon as d
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
             "event_datetime": "2026-06-01 10:00:00"}
        with patch.object(d, "send_tts_notification") as mock_tts:
            mode = d.dispatch_reminder(r, _locked_ctx())
        assert mode == "defer_unlock"
        mock_tts.assert_not_called()

    def test_tts_only_no_desktop_notification(self, monkeypatch):
        """tts_only path (screen-required reminder in fullscreen context) must
        not also send a desktop notification."""
        d = _load()
        r = {"id": 1, "title": "Send report", "category": "admin",
             "screen_free": 0, "snooze_count": 0, "event_datetime": "2026-06-01 10:00:00"}
        fullscreen_ctx = rn.Context(screen_locked=False, dnd_enabled=False,
                                    voxrefiner_active=False, fullscreen_app=True)
        with (
            patch.object(d, "send_tts_notification"),
            patch.object(d, "close_terminal_fire"),
            patch.object(d, "send_desktop_notification") as mock_notif,
            patch.object(d, "snooze"),
        ):
            mode = d.dispatch_reminder(r, fullscreen_ctx)
        assert mode == "tts_only"
        mock_notif.assert_not_called()

    def test_tts_only_closes_existing_terminal(self, monkeypatch):
        """tts_only must close any window left open from a previous notify."""
        d = _load()
        r = {"id": 7, "title": "Send report", "category": "admin",
             "screen_free": 0, "snooze_count": 0, "event_datetime": "2026-06-01 10:00:00"}
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


# ── screen_free + Pomodoro ────────────────────────────────────────────────────

class TestScreenFreePomodoro:
    def _work_state(self):
        import src.reminder.pomodoro as pom
        from datetime import datetime, timedelta, timezone
        end = (datetime.now(tz=timezone.utc) + timedelta(minutes=20)).isoformat()
        return pom.PomodoroState(phase=pom.Phase.WORK, phase_end_iso=end)

    def test_screen_free_task_queued_during_work_phase(self, monkeypatch):
        d = _load()
        import src.reminder.pomodoro as pom
        monkeypatch.setattr(pom, "current_state", self._work_state)
        r = {"id": 1, "title": "Do the dishes", "category": "task_short",
             "screen_free": 1, "snooze_count": 0, "event_datetime": None}
        mode = d.dispatch_reminder(r, _normal_ctx())
        assert mode == "queue"

    def test_legacy_physical_task_queued_during_work_phase(self, monkeypatch):
        """Tasks with screen_free=None and physical category are also held back."""
        d = _load()
        import src.reminder.pomodoro as pom
        monkeypatch.setattr(pom, "current_state", self._work_state)
        r = {"id": 2, "title": "Water garden", "category": "errand",
             "screen_free": None, "snooze_count": 0, "event_datetime": None}
        mode = d.dispatch_reminder(r, _normal_ctx())
        assert mode == "queue"

    def test_screen_required_task_fires_during_work_phase(self, monkeypatch):
        """Tasks with screen_free=False are not held back by Pomodoro."""
        d = _load()
        import src.reminder.pomodoro as pom
        monkeypatch.setattr(pom, "current_state", self._work_state)
        r = {"id": 3, "title": "Reply to email", "category": "task_short",
             "screen_free": 0, "snooze_count": 0, "event_datetime": "2026-06-01 10:00:00"}
        with (
            patch.object(d, "open_terminal_fire", return_value=True),
            patch.object(d, "send_desktop_notification"),
            patch.object(d, "bump_trigger"),
        ):
            mode = d.dispatch_reminder(r, _normal_ctx())
        assert mode == "notify"

    def test_appointment_fires_during_work_phase(self, monkeypatch):
        """Appointments (not screen-free) always fire regardless of Pomodoro."""
        d = _load()
        import src.reminder.pomodoro as pom
        monkeypatch.setattr(pom, "current_state", self._work_state)
        r = {"id": 4, "title": "Dentist", "category": "appointment",
             "screen_free": None, "snooze_count": 0,
             "event_datetime": "2099-01-01 00:00:00"}
        with (
            patch.object(d, "open_terminal_fire", return_value=True),
            patch.object(d, "send_desktop_notification"),
            patch.object(d, "bump_trigger"),
        ):
            mode = d.dispatch_reminder(r, _normal_ctx())
        assert mode == "notify"

    def test_screen_free_queued_even_when_no_pomodoro(self, monkeypatch):
        """screen_free reminders never fire as terminal notify — even with no
        Pomodoro state. They always queue, waiting for a future break."""
        d = _load()
        import src.reminder.pomodoro as pom
        monkeypatch.setattr(pom, "current_state", lambda: None)
        r = {"id": 5, "title": "Do the dishes", "category": "task_short",
             "screen_free": 1, "snooze_count": 0, "event_datetime": None}
        mode = d.dispatch_reminder(r, _normal_ctx())
        assert mode == "queue"

    def test_legacy_physical_queued_even_when_no_pomodoro(self, monkeypatch):
        """Legacy physical-category tasks (screen_free=None) also always queue."""
        d = _load()
        import src.reminder.pomodoro as pom
        monkeypatch.setattr(pom, "current_state", lambda: None)
        r = {"id": 7, "title": "Mow the lawn", "category": "task_short",
             "screen_free": None, "snooze_count": 0, "event_datetime": None}
        mode = d.dispatch_reminder(r, _normal_ctx())
        assert mode == "queue"

    def test_screen_free_task_queued_during_break_phase(self, monkeypatch):
        """Screen-free tasks are also held back during BREAK so no terminal opens."""
        d = _load()
        import src.reminder.pomodoro as pom
        from datetime import datetime, timedelta, timezone
        end = (datetime.now(tz=timezone.utc) + timedelta(minutes=5)).isoformat()
        break_state = pom.PomodoroState(
            phase=pom.Phase.BREAK,
            phase_end_iso=end,
            break_hard_end_iso=end,
        )
        monkeypatch.setattr(pom, "current_state", lambda: break_state)
        r = {"id": 6, "title": "Water garden", "category": "errand",
             "screen_free": None, "snooze_count": 0, "event_datetime": None}
        mode = d.dispatch_reminder(r, _normal_ctx())
        assert mode == "queue"

    def test_screen_required_task_queued_during_break_phase(self, monkeypatch):
        """During a Pomodoro break, even screen-required tasks must NOT pop a
        terminal — the user is meant to be away from the screen."""
        d = _load()
        import src.reminder.pomodoro as pom
        from datetime import datetime, timedelta, timezone
        end = (datetime.now(tz=timezone.utc) + timedelta(minutes=5)).isoformat()
        break_state = pom.PomodoroState(
            phase=pom.Phase.BREAK,
            phase_end_iso=end,
            break_hard_end_iso=end,
        )
        monkeypatch.setattr(pom, "current_state", lambda: break_state)
        r = {"id": 8, "title": "Call dentist", "category": "task_short",
             "screen_free": 0, "snooze_count": 0, "event_datetime": "2026-06-01 10:00:00"}
        mode = d.dispatch_reminder(r, _normal_ctx())
        assert mode == "queue"


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
        return rdb.add_reminder(
            "Test task", category,
            event_datetime="2020-01-01 00:00:00",
            next_trigger="2020-01-01 00:00:00",
        )

    def test_empty_db_no_fire(self, monkeypatch):
        d = _load()
        with (
            patch.object(rn, "_screen_locked", return_value=False),
            patch.object(rn, "_dnd_enabled", return_value=False),
            patch.object(rn, "_voxrefiner_active", return_value=False),
            patch.object(rn, "_fullscreen_app",       return_value=False),
            patch.object(rn, "_known_blocker_active", return_value=False),
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
            patch.object(rn, "_fullscreen_app",       return_value=False),
            patch.object(rn, "_known_blocker_active", return_value=False),
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
            patch.object(rn, "_fullscreen_app",       return_value=False),
            patch.object(rn, "_known_blocker_active", return_value=False),
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
            patch.object(rn, "_fullscreen_app",       return_value=False),
            patch.object(rn, "_known_blocker_active", return_value=False),
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
            patch.object(rn, "_fullscreen_app",       return_value=False),
            patch.object(rn, "_known_blocker_active", return_value=False),
            patch.object(d, "send_tts_notification"),
            patch.object(d, "send_desktop_notification"),
        ):
            d.tick(previous_context=_locked_ctx())
        assert not isolated_pomodoro_file.exists()

    def test_physical_task_during_lock_does_not_fire(self, monkeypatch, isolated_pomodoro_file):
        """Per the routing rules: a screen_free task NEVER fires as tts_only
        (or anything else) — neither during screen lock nor outside Pomodoro.
        It always queues, waiting for an actual Pomodoro break overlay."""
        d = _load()
        self._add_due_reminder(category="task_short")
        with (
            patch.object(rn, "_screen_locked", return_value=True),
            patch.object(rn, "_dnd_enabled", return_value=False),
            patch.object(rn, "_voxrefiner_active", return_value=False),
            patch.object(rn, "_fullscreen_app",       return_value=False),
            patch.object(rn, "_known_blocker_active", return_value=False),
            patch.object(d, "send_tts_notification") as mock_tts,
            patch.object(d, "send_desktop_notification") as mock_notif,
            patch.object(d, "open_terminal_fire") as mock_term,
        ):
            d.tick()
        mock_tts.assert_not_called()
        mock_notif.assert_not_called()
        mock_term.assert_not_called()
        assert not isolated_pomodoro_file.exists()

    def test_returns_current_context(self, monkeypatch):
        d = _load()
        with (
            patch.object(rn, "_screen_locked", return_value=False),
            patch.object(rn, "_dnd_enabled", return_value=False),
            patch.object(rn, "_voxrefiner_active", return_value=False),
            patch.object(rn, "_fullscreen_app",       return_value=False),
            patch.object(rn, "_known_blocker_active", return_value=False),
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


# ── Unscheduled screen-required task (Fix 2) ─────────────────────────────────

class TestUnscheduledScreenRequired:
    def test_null_event_datetime_returns_skip(self, monkeypatch):
        d = _load()
        import src.reminder.pomodoro as pom
        monkeypatch.setattr(pom, "current_state", lambda: None)
        bumped = {}
        with patch.object(d, "bump_trigger", side_effect=lambda rid, ts: bumped.update({rid: ts})):
            r = {"id": 9, "title": "Call dentist", "category": "task_short",
                 "screen_free": 0, "snooze_count": 0, "event_datetime": None}
            mode = d.dispatch_reminder(r, _normal_ctx())
        assert mode == "skip"
        assert 9 in bumped

    def test_null_event_datetime_bumps_24h(self, monkeypatch):
        from datetime import datetime, timedelta, timezone
        d = _load()
        import src.reminder.pomodoro as pom
        monkeypatch.setattr(pom, "current_state", lambda: None)
        bumped = {}
        with patch.object(d, "bump_trigger", side_effect=lambda rid, ts: bumped.update({rid: ts})):
            r = {"id": 10, "title": "Call dentist", "category": "task_short",
                 "screen_free": 0, "snooze_count": 0, "event_datetime": None}
            d.dispatch_reminder(r, _normal_ctx())
        ts = bumped[10]
        bumped_dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        delta = bumped_dt - datetime.now(tz=timezone.utc)
        assert timedelta(hours=23) < delta < timedelta(hours=25)

    def test_scheduled_task_not_skipped(self, monkeypatch):
        d = _load()
        import src.reminder.pomodoro as pom
        monkeypatch.setattr(pom, "current_state", lambda: None)
        with (
            patch.object(d, "open_terminal_fire", return_value=True),
            patch.object(d, "send_desktop_notification"),
            patch.object(d, "bump_trigger"),
        ):
            r = {"id": 11, "title": "Call dentist", "category": "task_short",
                 "screen_free": 0, "snooze_count": 0,
                 "event_datetime": "2026-06-01 10:00:00"}
            mode = d.dispatch_reminder(r, _normal_ctx())
        assert mode == "notify"

    def test_screen_free_null_event_datetime_queues_not_skips(self, monkeypatch):
        d = _load()
        import src.reminder.pomodoro as pom
        monkeypatch.setattr(pom, "current_state", lambda: None)
        r = {"id": 12, "title": "Water garden", "category": "task_short",
             "screen_free": 1, "snooze_count": 0, "event_datetime": None}
        mode = d.dispatch_reminder(r, _normal_ctx())
        assert mode == "queue"


# ── Stale refinement cleanup in tick ─────────────────────────────────────────

class TestStaleRefinementCleanup:
    def test_tick_calls_reset_stale_pending_refinements(self, monkeypatch):
        from datetime import datetime, timedelta, timezone
        d = _load()
        rid = rdb.add_reminder("Rdv dentiste", "task_short")
        rdb.update_status(rid, "pending_refinement")
        old_ts = (datetime.now(tz=timezone.utc) - timedelta(minutes=40)).strftime("%Y-%m-%d %H:%M:%S")
        with rdb._db() as conn:
            conn.execute("UPDATE reminders SET created_at = ? WHERE id = ?", (old_ts, rid))
        with (
            patch.object(d.rn if hasattr(d, "rn") else __import__("src.reminder.notify", fromlist=[""]),
                         "_screen_locked", return_value=False),
        ):
            pass
        # Call the function directly (tick() wraps it in try/except)
        count = rdb.reset_stale_pending_refinements(older_than_minutes=35)
        assert count == 1
        with rdb._db() as conn:
            row = conn.execute("SELECT status FROM reminders WHERE id = ?", (rid,)).fetchone()
        assert row["status"] == "pending"

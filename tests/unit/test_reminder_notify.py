"""Unit tests for src/reminder_notify.py.

All subprocess calls are mocked — no actual gdbus/gsettings/xdotool commands run.
"""

from unittest.mock import MagicMock, patch

import pytest

import src.reminder_notify as rn


# ── _screen_locked ────────────────────────────────────────────────────────────

class TestScreenLocked:
    def test_gdbus_true_returns_true(self):
        result = MagicMock()
        result.returncode = 0
        result.stdout = "(true,)\n"
        with patch("subprocess.run", return_value=result):
            assert rn._screen_locked() is True

    def test_gdbus_false_returns_false(self):
        result = MagicMock()
        result.stdout = "(false,)\n"
        with patch("subprocess.run", return_value=result):
            assert rn._screen_locked() is False

    def test_timeout_returns_false(self):
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("gdbus", 3)):
            assert rn._screen_locked() is False

    def test_file_not_found_returns_false(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert rn._screen_locked() is False


# ── _dnd_enabled ──────────────────────────────────────────────────────────────

class TestDndEnabled:
    def test_show_banners_false_means_dnd_on(self):
        result = MagicMock()
        result.stdout = "false\n"
        with patch("subprocess.run", return_value=result):
            assert rn._dnd_enabled() is True

    def test_show_banners_true_means_dnd_off(self):
        result = MagicMock()
        result.stdout = "true\n"
        with patch("subprocess.run", return_value=result):
            assert rn._dnd_enabled() is False

    def test_timeout_returns_false(self):
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("gsettings", 3)):
            assert rn._dnd_enabled() is False

    def test_file_not_found_returns_false(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert rn._dnd_enabled() is False


# ── _voxrefiner_active ────────────────────────────────────────────────────────

class TestVoxRefinerActive:
    def test_lock_file_exists_returns_true(self, tmp_path, monkeypatch):
        lock = tmp_path / "vox-refiner.lock"
        lock.touch()
        monkeypatch.setattr(rn, "_LOCK_FILE", lock)
        assert rn._voxrefiner_active() is True

    def test_no_lock_file_returns_false(self, tmp_path, monkeypatch):
        monkeypatch.setattr(rn, "_LOCK_FILE", tmp_path / "vox-refiner.lock")
        assert rn._voxrefiner_active() is False


# ── _fullscreen_app ───────────────────────────────────────────────────────────

class TestFullscreenApp:
    def _make_run(self, win_id="123", width=1920, height=1080, screen="1920 1080"):
        call_count = [0]

        def fake_run(cmd, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if "getactivewindow" in cmd:
                result.stdout = win_id
            elif "getwindowgeometry" in cmd:
                result.stdout = f"WIDTH={width}\nHEIGHT={height}\n"
            elif "getdisplaygeometry" in cmd:
                result.stdout = screen
            return result

        return fake_run

    def test_fullscreen_returns_true(self):
        with patch("subprocess.run", side_effect=self._make_run()):
            assert rn._fullscreen_app() is True

    def test_windowed_returns_false(self):
        with patch("subprocess.run", side_effect=self._make_run(width=800, height=600)):
            assert rn._fullscreen_app() is False

    def test_no_active_window_returns_false(self):
        with patch("subprocess.run", side_effect=self._make_run(win_id="")):
            assert rn._fullscreen_app() is False

    def test_xdotool_not_found_returns_false(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert rn._fullscreen_app() is False

    def test_timeout_returns_false(self):
        import subprocess
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("xdotool", 3)):
            assert rn._fullscreen_app() is False


# ── detect_context ────────────────────────────────────────────────────────────

class TestDetectContext:
    def test_returns_context_namedtuple(self):
        with (
            patch.object(rn, "_screen_locked", return_value=False),
            patch.object(rn, "_dnd_enabled", return_value=False),
            patch.object(rn, "_voxrefiner_active", return_value=False),
            patch.object(rn, "_fullscreen_app", return_value=False),
        ):
            ctx = rn.detect_context()
        assert isinstance(ctx, rn.Context)

    def test_all_false_normal_desktop(self):
        with (
            patch.object(rn, "_screen_locked", return_value=False),
            patch.object(rn, "_dnd_enabled", return_value=False),
            patch.object(rn, "_voxrefiner_active", return_value=False),
            patch.object(rn, "_fullscreen_app", return_value=False),
        ):
            ctx = rn.detect_context()
        assert ctx == rn.Context(False, False, False, False)

    def test_screen_locked_propagated(self):
        with (
            patch.object(rn, "_screen_locked", return_value=True),
            patch.object(rn, "_dnd_enabled", return_value=False),
            patch.object(rn, "_voxrefiner_active", return_value=False),
            patch.object(rn, "_fullscreen_app", return_value=False),
        ):
            ctx = rn.detect_context()
        assert ctx.screen_locked is True


# ── choose_intervention ───────────────────────────────────────────────────────

class TestChooseIntervention:
    def _ctx(self, locked=False, dnd=False, vox=False, fullscreen=False) -> rn.Context:
        return rn.Context(locked, dnd, vox, fullscreen)

    def _reminder(self, category="appointment") -> dict:
        return {"title": "Test", "category": category}

    def test_normal_desktop_returns_notify(self):
        result = rn.choose_intervention(self._ctx(), self._reminder())
        assert result.mode == "notify"

    def test_voxrefiner_active_returns_queue(self):
        result = rn.choose_intervention(self._ctx(vox=True), self._reminder())
        assert result.mode == "queue"

    def test_dnd_enabled_returns_queue(self):
        result = rn.choose_intervention(self._ctx(dnd=True), self._reminder())
        assert result.mode == "queue"

    def test_screen_locked_physical_task_returns_tts_only(self):
        result = rn.choose_intervention(self._ctx(locked=True), self._reminder("task_short"))
        assert result.mode == "tts_only"

    def test_screen_locked_errand_returns_tts_only(self):
        result = rn.choose_intervention(self._ctx(locked=True), self._reminder("errand"))
        assert result.mode == "tts_only"

    def test_screen_locked_appointment_returns_defer_unlock(self):
        result = rn.choose_intervention(self._ctx(locked=True), self._reminder("appointment"))
        assert result.mode == "defer_unlock"

    def test_screen_locked_admin_returns_defer_unlock(self):
        result = rn.choose_intervention(self._ctx(locked=True), self._reminder("admin"))
        assert result.mode == "defer_unlock"

    def test_fullscreen_app_returns_tts_only(self):
        result = rn.choose_intervention(self._ctx(fullscreen=True), self._reminder())
        assert result.mode == "tts_only"

    def test_voxrefiner_takes_priority_over_dnd(self):
        result = rn.choose_intervention(self._ctx(vox=True, dnd=True), self._reminder())
        assert result.mode == "queue"

    def test_result_is_intervention_namedtuple(self):
        result = rn.choose_intervention(self._ctx(), self._reminder())
        assert isinstance(result, rn.Intervention)

    def test_reason_non_empty(self):
        result = rn.choose_intervention(self._ctx(), self._reminder())
        assert result.reason

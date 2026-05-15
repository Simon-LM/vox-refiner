"""Unit tests for src/reminder_converse.py.

Covers pure functions (compute_next_trigger, interpret_response with mock,
converse side-effects) without network calls or real DB writes.
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

import src.reminder_db as rdb


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(rdb, "_DB_DIR", tmp_path)
    monkeypatch.setattr(rdb, "_DB_PATH", tmp_path / "reminders.db")


def _load(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    if "src.reminder_converse" in sys.modules:
        del sys.modules["src.reminder_converse"]
    import src.reminder_converse as m
    return m


def _reminder(**kwargs) -> dict:
    base = {
        "id": 1,
        "title": "Doctor appointment",
        "category": "appointment",
        "event_datetime": "2026-06-01 14:00:00",
        "snooze_count": 0,
        "conversation": "[]",
    }
    base.update(kwargs)
    return base


def _action_json(**kwargs) -> str:
    base = {
        "action_type": "done",
        "snooze_minutes": 0,
        "unavailability": None,
        "message": "Great, marked as done!",
    }
    base.update(kwargs)
    return json.dumps(base)


# ── System prompt ─────────────────────────────────────────────────────────────

class TestSystemPrompt:
    def test_contains_action_types(self, monkeypatch):
        m = _load(monkeypatch)
        for action in ("done", "snooze", "going_to_do", "cancel", "unavailable"):
            assert action in m._COACH_SYSTEM_PROMPT

    def test_non_guilt_tone_instruction(self, monkeypatch):
        m = _load(monkeypatch)
        assert "guilt" in m._COACH_SYSTEM_PROMPT.lower()

    def test_adhd_mentioned(self, monkeypatch):
        m = _load(monkeypatch)
        assert "ADHD" in m._COACH_SYSTEM_PROMPT

    def test_security_block_present(self, monkeypatch):
        m = _load(monkeypatch)
        assert "SECURITY" in m._COACH_SYSTEM_PROMPT

    def test_json_only_rule(self, monkeypatch):
        m = _load(monkeypatch)
        assert "valid JSON" in m._COACH_SYSTEM_PROMPT


# ── compute_next_trigger ──────────────────────────────────────────────────────

class TestComputeNextTrigger:
    def test_task_short_first_snooze(self, monkeypatch):
        m = _load(monkeypatch)
        r = _reminder(category="task_short", snooze_count=0)
        now = "2026-06-01 10:00:00"
        result = m.compute_next_trigger(r, now)
        result_dt = datetime.fromisoformat(result.replace(" ", "T")).replace(tzinfo=timezone.utc)
        now_dt = datetime.fromisoformat(now.replace(" ", "T")).replace(tzinfo=timezone.utc)
        diff = result_dt - now_dt
        assert timedelta(minutes=4) <= diff <= timedelta(minutes=6)

    def test_task_short_high_snooze_count_still_above_5min(self, monkeypatch):
        m = _load(monkeypatch)
        r = _reminder(category="task_short", snooze_count=10)
        now = "2026-06-01 10:00:00"
        result = m.compute_next_trigger(r, now)
        result_dt = datetime.fromisoformat(result.replace(" ", "T")).replace(tzinfo=timezone.utc)
        now_dt = datetime.fromisoformat(now.replace(" ", "T")).replace(tzinfo=timezone.utc)
        diff_minutes = (result_dt - now_dt).total_seconds() / 60
        assert diff_minutes >= 5

    def test_appointment_escalation_d3(self, monkeypatch):
        m = _load(monkeypatch)
        # Event in 5 days → D-3 milestone should fire
        event_dt = datetime.now(tz=timezone.utc) + timedelta(days=5)
        event_str = event_dt.strftime("%Y-%m-%d %H:%M:%S")
        r = _reminder(category="appointment", event_datetime=event_str, snooze_count=0)
        now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        result = m.compute_next_trigger(r, now)
        # Result should be before the event
        result_dt = datetime.fromisoformat(result.replace(" ", "T")).replace(tzinfo=timezone.utc)
        assert result_dt < event_dt

    def test_appointment_past_all_milestones_snoozes_30min(self, monkeypatch):
        m = _load(monkeypatch)
        # Event in 10 minutes — past all escalation milestones
        event_dt = datetime.now(tz=timezone.utc) + timedelta(minutes=10)
        event_str = event_dt.strftime("%Y-%m-%d %H:%M:%S")
        r = _reminder(category="appointment", event_datetime=event_str, snooze_count=0)
        now = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        result = m.compute_next_trigger(r, now)
        result_dt = datetime.fromisoformat(result.replace(" ", "T")).replace(tzinfo=timezone.utc)
        now_dt = datetime.fromisoformat(now.replace(" ", "T")).replace(tzinfo=timezone.utc)
        diff_minutes = (result_dt - now_dt).total_seconds() / 60
        assert 28 <= diff_minutes <= 32

    def test_returns_iso_datetime_string(self, monkeypatch):
        m = _load(monkeypatch)
        r = _reminder(category="task_short", snooze_count=0)
        result = m.compute_next_trigger(r, "2026-06-01 10:00:00")
        # Must be parseable
        datetime.fromisoformat(result.replace(" ", "T"))

    def test_uses_current_time_when_now_is_none(self, monkeypatch):
        m = _load(monkeypatch)
        r = _reminder(category="task_short", snooze_count=0)
        result = m.compute_next_trigger(r, now=None)
        result_dt = datetime.fromisoformat(result.replace(" ", "T")).replace(tzinfo=timezone.utc)
        assert result_dt > datetime.now(tz=timezone.utc)

    def test_urgency_increases_with_snooze_count(self, monkeypatch):
        m = _load(monkeypatch)
        now = "2026-06-01 10:00:00"
        low_snooze = m.compute_next_trigger(_reminder(category="task_long", snooze_count=0), now)
        high_snooze = m.compute_next_trigger(_reminder(category="task_long", snooze_count=5), now)
        low_dt = datetime.fromisoformat(low_snooze.replace(" ", "T"))
        high_dt = datetime.fromisoformat(high_snooze.replace(" ", "T"))
        assert high_dt <= low_dt


# ── interpret_response ────────────────────────────────────────────────────────

class TestInterpretResponse:
    def test_done_action_returned(self, monkeypatch):
        m = _load(monkeypatch)
        with patch.object(m, "call_model", return_value=_action_json(action_type="done")):
            result = m.interpret_response(_reminder(), "Done!")
        assert result.action_type == "done"

    def test_snooze_minutes_extracted(self, monkeypatch):
        m = _load(monkeypatch)
        with patch.object(m, "call_model", return_value=_action_json(
            action_type="snooze", snooze_minutes=45
        )):
            result = m.interpret_response(_reminder(), "In 45 minutes")
        assert result.snooze_minutes == 45

    def test_cancel_action(self, monkeypatch):
        m = _load(monkeypatch)
        with patch.object(m, "call_model", return_value=_action_json(action_type="cancel")):
            result = m.interpret_response(_reminder(), "Cancel this")
        assert result.action_type == "cancel"

    def test_unavailable_with_dates(self, monkeypatch):
        m = _load(monkeypatch)
        unavail = {
            "start_dt": "2026-06-01 00:00:00",
            "end_dt": "2026-06-01 23:59:59",
            "reason": "sick",
        }
        with patch.object(m, "call_model", return_value=_action_json(
            action_type="unavailable", unavailability=unavail
        )):
            result = m.interpret_response(_reminder(), "I'm sick today")
        assert result.action_type == "unavailable"
        assert result.unavailability["reason"] == "sick"

    def test_json_parse_error_falls_back_to_second_model(self, monkeypatch):
        m = _load(monkeypatch)
        call_count = [0]

        def fake_call(model, messages, api_key, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return "not json"
            return _action_json(action_type="done")

        with patch.object(m, "call_model", side_effect=fake_call):
            result = m.interpret_response(_reminder(), "done")
        assert result.action_type == "done"

    def test_all_models_fail_returns_unknown(self, monkeypatch):
        m = _load(monkeypatch)
        with patch.object(m, "call_model", return_value="bad {{{"):
            result = m.interpret_response(_reminder(), "something")
        assert result.action_type == "unknown"

    def test_missing_api_key_raises(self, monkeypatch):
        m = _load(monkeypatch)
        monkeypatch.delenv("MISTRAL_API_KEY")
        with pytest.raises(RuntimeError, match="MISTRAL_API_KEY"):
            m.interpret_response(_reminder(), "done")

    def test_result_is_action_namedtuple(self, monkeypatch):
        m = _load(monkeypatch)
        with patch.object(m, "call_model", return_value=_action_json()):
            result = m.interpret_response(_reminder(), "done")
        assert isinstance(result, m.Action)

    def test_markdown_fence_stripped(self, monkeypatch):
        m = _load(monkeypatch)
        fenced = "```json\n" + _action_json(action_type="done") + "\n```"
        with patch.object(m, "call_model", return_value=fenced):
            result = m.interpret_response(_reminder(), "done")
        assert result.action_type == "done"

    def test_message_field_returned(self, monkeypatch):
        m = _load(monkeypatch)
        with patch.object(m, "call_model", return_value=_action_json(message="Great job!")):
            result = m.interpret_response(_reminder(), "done")
        assert result.message == "Great job!"

    def test_context_includes_current_local_datetime(self, monkeypatch):
        """Current local datetime must be passed to the model so it can resolve relative times."""
        m = _load(monkeypatch)
        captured: list = []

        def fake_call(model, messages, api_key, **kwargs):
            captured.extend(messages)
            return _action_json()

        with patch.object(m, "call_model", side_effect=fake_call):
            m.interpret_response(_reminder(), "demain à 14h")

        context_text = " ".join(msg["content"] for msg in captured)
        assert "Current local datetime" in context_text


# ── converse (side-effects) ───────────────────────────────────────────────────

class TestConverse:
    def _add_reminder_to_db(self) -> tuple[int, dict]:
        reminder_id = rdb.add_reminder("Doctor", "appointment")
        r = rdb.get_due("9999-01-01 00:00:00")
        return reminder_id, next(x for x in r if x["id"] == reminder_id)

    def test_done_sets_status_done(self, monkeypatch):
        m = _load(monkeypatch)
        rid, r = self._add_reminder_to_db()
        with patch.object(m, "call_model", return_value=_action_json(action_type="done")):
            m.converse(rid, r, "All done!")
        due = rdb.get_due("9999-01-01 00:00:00")
        assert all(x["id"] != rid for x in due)

    def test_snooze_sets_status_snoozed(self, monkeypatch):
        m = _load(monkeypatch)
        rid, r = self._add_reminder_to_db()
        with patch.object(m, "call_model", return_value=_action_json(
            action_type="snooze", snooze_minutes=30
        )):
            m.converse(rid, r, "Later")
        due = rdb.get_due("9999-01-01 00:00:00")
        row = next(x for x in due if x["id"] == rid)
        assert row["status"] == "snoozed"

    def test_cancel_sets_status_cancelled(self, monkeypatch):
        m = _load(monkeypatch)
        rid, r = self._add_reminder_to_db()
        with patch.object(m, "call_model", return_value=_action_json(action_type="cancel")):
            m.converse(rid, r, "Cancel")
        due = rdb.get_due("9999-01-01 00:00:00")
        assert all(x["id"] != rid for x in due)

    def test_unavailable_logs_to_db(self, monkeypatch):
        m = _load(monkeypatch)
        rid, r = self._add_reminder_to_db()
        unavail = {
            "start_dt": "2026-06-01 00:00:00",
            "end_dt": "2026-06-01 23:59:59",
            "reason": "sick",
        }
        with patch.object(m, "call_model", return_value=_action_json(
            action_type="unavailable", unavailability=unavail
        )):
            m.converse(rid, r, "I'm sick today")
        blocks = rdb.get_unavailability("2026-05-31 00:00:00", "2026-06-02 00:00:00")
        assert len(blocks) == 1
        assert blocks[0]["reason"] == "sick"

    def test_snooze_uses_ai_minutes_not_escalation(self, monkeypatch):
        """converse() must use snooze_minutes from AI directly, not compute_next_trigger."""
        m = _load(monkeypatch)
        rid, r = self._add_reminder_to_db()
        now_before = datetime.now(tz=timezone.utc)
        with patch.object(m, "call_model", return_value=_action_json(
            action_type="snooze", snooze_minutes=990
        )):
            m.converse(rid, r, "Demain à 14h")
        due = rdb.get_due("9999-01-01 00:00:00")
        row = next(x for x in due if x["id"] == rid)
        next_trigger = datetime.fromisoformat(
            row["next_trigger"].replace(" ", "T")
        ).replace(tzinfo=timezone.utc)
        expected = now_before + timedelta(minutes=990)
        assert abs((next_trigger - expected).total_seconds()) < 5

    def test_conversation_logged(self, monkeypatch):
        m = _load(monkeypatch)
        rid, r = self._add_reminder_to_db()
        with patch.object(m, "call_model", return_value=_action_json(
            action_type="done", message="Marked done."
        )):
            m.converse(rid, r, "Done!")
        due = rdb.get_due("9999-01-01 00:00:00")
        # Done reminders are no longer due — query DB directly
        import sqlite3
        conn = sqlite3.connect(str(rdb._DB_PATH))
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT conversation FROM reminders WHERE id = ?", (rid,)).fetchone()
        conn.close()
        history = json.loads(row["conversation"])
        assert any(e["role"] == "user" for e in history)
        assert any(e["role"] == "assistant" for e in history)

    def test_returns_assistant_message(self, monkeypatch):
        m = _load(monkeypatch)
        rid, r = self._add_reminder_to_db()
        with patch.object(m, "call_model", return_value=_action_json(message="All good!")):
            reply = m.converse(rid, r, "Done!")
        assert reply == "All good!"

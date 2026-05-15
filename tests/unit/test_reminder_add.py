"""Unit tests for src/reminder_add.py.

Mocks call_model so no network calls are made.
Uses an isolated temporary SQLite database via monkeypatch on reminder_db.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

import src.reminder_db as rdb


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(rdb, "_DB_DIR", tmp_path)
    monkeypatch.setattr(rdb, "_DB_PATH", tmp_path / "reminders.db")


def _load(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    if "src.reminder_add" in sys.modules:
        del sys.modules["src.reminder_add"]
    import src.reminder_add as m
    return m


def _valid_extraction(**overrides) -> dict:
    base = {
        "title": "Doctor appointment",
        "category": "appointment",
        "event_datetime": "2026-06-01 14:00:00",
        "entities": {"person": "Dr Martin", "location": "Paris"},
        "missing_fields": [],
    }
    base.update(overrides)
    return base


def _as_array(*items) -> str:
    """Serialize one or more extraction dicts as a JSON array (model output format)."""
    return json.dumps(list(items))


# ── _build_system_prompt ──────────────────────────────────────────────────────

class TestBuildSystemPrompt:
    def test_contains_today_date(self, monkeypatch):
        m = _load(monkeypatch)
        from datetime import date
        prompt = m._build_system_prompt()
        assert date.today().isoformat() in prompt

    def test_contains_all_categories(self, monkeypatch):
        m = _load(monkeypatch)
        prompt = m._build_system_prompt()
        for cat in ("appointment", "task_short", "task_long", "admin", "deadline"):
            assert cat in prompt

    def test_contains_security_block(self, monkeypatch):
        m = _load(monkeypatch)
        prompt = m._build_system_prompt()
        assert "SECURITY" in prompt

    def test_output_only_valid_json_rule(self, monkeypatch):
        m = _load(monkeypatch)
        prompt = m._build_system_prompt()
        assert "valid JSON" in prompt


# ── extract_reminder ──────────────────────────────────────────────────────────

class TestExtractReminder:
    def test_returns_list_on_success(self, monkeypatch):
        m = _load(monkeypatch)
        with patch.object(m, "call_model", return_value=_as_array(_valid_extraction())):
            result = m.extract_reminder("Doctor appointment Friday 3pm Dr Martin")
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], dict)

    def test_single_dict_response_wrapped_in_list(self, monkeypatch):
        """Model returns a bare object instead of array — must be tolerated."""
        m = _load(monkeypatch)
        with patch.object(m, "call_model", return_value=json.dumps(_valid_extraction())):
            result = m.extract_reminder("Doctor appointment")
        assert isinstance(result, list)
        assert result[0]["title"] == "Doctor appointment"

    def test_title_extracted(self, monkeypatch):
        m = _load(monkeypatch)
        with patch.object(m, "call_model", return_value=_as_array(_valid_extraction(title="Dentist at 2pm"))):
            result = m.extract_reminder("Dentist at 2pm")
        assert result[0]["title"] == "Dentist at 2pm"

    def test_category_extracted(self, monkeypatch):
        m = _load(monkeypatch)
        with patch.object(m, "call_model", return_value=_as_array(_valid_extraction(category="admin"))):
            result = m.extract_reminder("File tax declaration")
        assert result[0]["category"] == "admin"

    def test_event_datetime_extracted(self, monkeypatch):
        m = _load(monkeypatch)
        with patch.object(m, "call_model", return_value=_as_array(_valid_extraction(event_datetime="2026-06-15 09:00:00"))):
            result = m.extract_reminder("Meeting June 15 at 9am")
        assert result[0]["event_datetime"] == "2026-06-15 09:00:00"

    def test_null_event_datetime_accepted(self, monkeypatch):
        m = _load(monkeypatch)
        data = _valid_extraction(event_datetime=None, missing_fields=["date", "time"])
        with patch.object(m, "call_model", return_value=_as_array(data)):
            result = m.extract_reminder("Call the dentist sometime")
        assert result[0]["event_datetime"] is None
        assert "date" in result[0]["missing_fields"]

    def test_entities_extracted(self, monkeypatch):
        m = _load(monkeypatch)
        data = _valid_extraction(entities={"person": "Dr Martin", "location": "Clinic"})
        with patch.object(m, "call_model", return_value=_as_array(data)):
            result = m.extract_reminder("See Dr Martin at the Clinic")
        assert result[0]["entities"]["person"] == "Dr Martin"

    def test_markdown_fence_stripped(self, monkeypatch):
        m = _load(monkeypatch)
        fenced = "```json\n" + _as_array(_valid_extraction()) + "\n```"
        with patch.object(m, "call_model", return_value=fenced):
            result = m.extract_reminder("Appointment")
        assert isinstance(result, list)
        assert "title" in result[0]

    def test_multiple_tasks_returned(self, monkeypatch):
        m = _load(monkeypatch)
        task1 = _valid_extraction(title="Mow the lawn")
        task2 = _valid_extraction(title="Pull weeds", category="task_short")
        with patch.object(m, "call_model", return_value=_as_array(task1, task2)):
            result = m.extract_reminder("Mow lawn and pull weeds")
        assert len(result) == 2
        assert result[0]["title"] == "Mow the lawn"
        assert result[1]["title"] == "Pull weeds"

    def test_missing_api_key_raises(self, monkeypatch):
        m = _load(monkeypatch)
        monkeypatch.delenv("MISTRAL_API_KEY")
        with pytest.raises(RuntimeError, match="MISTRAL_API_KEY"):
            m.extract_reminder("test")

    def test_json_parse_error_falls_back_to_second_model(self, monkeypatch):
        m = _load(monkeypatch)
        good_json = _as_array(_valid_extraction())
        call_count = [0]

        def fake_call_model(model, messages, api_key, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return "not valid json {"
            return good_json

        with patch.object(m, "call_model", side_effect=fake_call_model):
            result = m.extract_reminder("Appointment")
        assert result[0]["title"] == "Doctor appointment"
        assert call_count[0] == 2

    def test_all_models_fail_raises_runtime_error(self, monkeypatch):
        m = _load(monkeypatch)
        with patch.object(m, "call_model", return_value="bad json {{{"):
            with pytest.raises(RuntimeError, match="failed"):
                m.extract_reminder("test text")

    def test_502_triggers_fallback(self, monkeypatch):
        import requests as req
        m = _load(monkeypatch)
        call_count = [0]

        def fake_call(model, messages, api_key, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                r = req.models.Response()
                r.status_code = 502
                raise req.HTTPError(response=r)
            return _as_array(_valid_extraction())

        with patch.object(m, "call_model", side_effect=fake_call):
            result = m.extract_reminder("test")
        assert result[0]["title"] == "Doctor appointment"


# ── add_from_text ─────────────────────────────────────────────────────────────

class TestAddFromText:
    def test_returns_list_of_tuples(self, monkeypatch):
        m = _load(monkeypatch)
        with patch.object(m, "call_model", return_value=_as_array(_valid_extraction())):
            results = m.add_from_text("Doctor appointment")
        assert isinstance(results, list)
        assert len(results) == 1
        reminder_id, data = results[0]
        assert isinstance(reminder_id, int)
        assert isinstance(data, dict)

    def test_reminder_stored_in_db(self, monkeypatch):
        m = _load(monkeypatch)
        with patch.object(m, "call_model", return_value=_as_array(_valid_extraction())):
            results = m.add_from_text("Doctor appointment")
        reminder_id, _ = results[0]
        due = rdb.get_due("9999-01-01 00:00:00")
        assert any(r["id"] == reminder_id for r in due)

    def test_title_from_extraction_stored(self, monkeypatch):
        m = _load(monkeypatch)
        data = _valid_extraction(title="Tax declaration deadline")
        with patch.object(m, "call_model", return_value=_as_array(data)):
            results = m.add_from_text("File taxes before April 30")
        reminder_id, _ = results[0]
        due = rdb.get_due("9999-01-01 00:00:00")
        row = next(r for r in due if r["id"] == reminder_id)
        assert row["title"] == "Tax declaration deadline"

    def test_full_context_stored_as_original_text(self, monkeypatch):
        m = _load(monkeypatch)
        input_text = "File taxes before April 30 — important deadline"
        with patch.object(m, "call_model", return_value=_as_array(_valid_extraction())):
            results = m.add_from_text(input_text)
        reminder_id, _ = results[0]
        due = rdb.get_due("9999-01-01 00:00:00")
        row = next(r for r in due if r["id"] == reminder_id)
        assert row["full_context"] == input_text

    def test_category_stored(self, monkeypatch):
        m = _load(monkeypatch)
        data = _valid_extraction(category="deadline")
        with patch.object(m, "call_model", return_value=_as_array(data)):
            results = m.add_from_text("Submit report by Friday")
        reminder_id, _ = results[0]
        due = rdb.get_due("9999-01-01 00:00:00")
        row = next(r for r in due if r["id"] == reminder_id)
        assert row["category"] == "deadline"

    def test_title_falls_back_to_truncated_text_if_missing(self, monkeypatch):
        m = _load(monkeypatch)
        data = _valid_extraction()
        del data["title"]
        with patch.object(m, "call_model", return_value=_as_array(data)):
            results = m.add_from_text("A" * 100)
        reminder_id, _ = results[0]
        due = rdb.get_due("9999-01-01 00:00:00")
        row = next(r for r in due if r["id"] == reminder_id)
        assert len(row["title"]) <= 80

    def test_entities_stored_as_metadata(self, monkeypatch):
        m = _load(monkeypatch)
        data = _valid_extraction(entities={"person": "Dr Smith", "location": "Clinic"})
        with patch.object(m, "call_model", return_value=_as_array(data)):
            results = m.add_from_text("See Dr Smith at the clinic")
        reminder_id, _ = results[0]
        due = rdb.get_due("9999-01-01 00:00:00")
        row = next(r for r in due if r["id"] == reminder_id)
        import json as _json
        meta = _json.loads(row["metadata"])
        assert meta["person"] == "Dr Smith"

    def test_multiple_tasks_stored_separately(self, monkeypatch):
        m = _load(monkeypatch)
        task1 = _valid_extraction(title="Mow the lawn", category="task_short")
        task2 = _valid_extraction(title="Pull weeds", category="task_short")
        task3 = _valid_extraction(title="Water the garden", category="task_short")
        with patch.object(m, "call_model", return_value=_as_array(task1, task2, task3)):
            results = m.add_from_text("Mow lawn, pull weeds, and water garden")
        assert len(results) == 3
        ids = [r[0] for r in results]
        assert len(set(ids)) == 3, "each task must get a distinct DB id"
        due = rdb.get_due("9999-01-01 00:00:00")
        stored_ids = {r["id"] for r in due}
        for rid in ids:
            assert rid in stored_ids

    def test_multiple_tasks_share_same_full_context(self, monkeypatch):
        m = _load(monkeypatch)
        input_text = "Mow lawn and pull weeds tomorrow"
        task1 = _valid_extraction(title="Mow the lawn")
        task2 = _valid_extraction(title="Pull weeds")
        with patch.object(m, "call_model", return_value=_as_array(task1, task2)):
            results = m.add_from_text(input_text)
        due = rdb.get_due("9999-01-01 00:00:00")
        for rid, _ in results:
            row = next(r for r in due if r["id"] == rid)
            assert row["full_context"] == input_text

    def test_recurrence_end_stored_in_db(self, monkeypatch):
        m = _load(monkeypatch)
        data = _valid_extraction(recurrence="daily", recurrence_end="2026-08-31")
        with patch.object(m, "call_model", return_value=_as_array(data)):
            results = m.add_from_text("Water the garden every day until end of summer")
        reminder_id, _ = results[0]
        due = rdb.get_due("9999-01-01 00:00:00")
        row = next(r for r in due if r["id"] == reminder_id)
        assert row["recurrence_end"] == "2026-08-31"

    def test_null_recurrence_end_stored_as_none(self, monkeypatch):
        m = _load(monkeypatch)
        data = _valid_extraction(recurrence="daily", recurrence_end=None)
        with patch.object(m, "call_model", return_value=_as_array(data)):
            results = m.add_from_text("Walk every day")
        reminder_id, _ = results[0]
        due = rdb.get_due("9999-01-01 00:00:00")
        row = next(r for r in due if r["id"] == reminder_id)
        assert row["recurrence_end"] is None

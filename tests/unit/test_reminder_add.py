"""Unit tests for src/reminder/add.py.

Mocks call_model so no network calls are made.
Uses an isolated temporary SQLite database via monkeypatch on reminder_db.
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

import src.reminder.db as rdb


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(rdb, "_DB_DIR", tmp_path)
    monkeypatch.setattr(rdb, "_DB_PATH", tmp_path / "reminders.db")


def _load(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    if "src.reminder.add" in sys.modules:
        del sys.modules["src.reminder.add"]
    import src.reminder.add as m
    return m


def _valid_extraction(**overrides) -> dict:
    base = {
        "title": "Doctor appointment",
        "category": "appointment",
        "event_datetime": "2026-06-01 14:00:00",
        "metadata": {"person": "Dr Martin", "location": "Paris"},
        "pending_questions": [],
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

    def test_mentions_requires_daylight_metadata(self, monkeypatch):
        m = _load(monkeypatch)
        prompt = m._build_system_prompt()
        assert "requires_daylight" in prompt


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
        questions = [{"question": "À quelle date veux-tu y aller ?", "context": "no date given"}]
        data = _valid_extraction(event_datetime=None, pending_questions=questions)
        with patch.object(m, "call_model", return_value=_as_array(data)):
            result = m.extract_reminder("Call the dentist sometime")
        assert result[0]["event_datetime"] is None
        assert len(result[0]["pending_questions"]) == 1

    def test_entities_extracted(self, monkeypatch):
        m = _load(monkeypatch)
        data = _valid_extraction(metadata={"person": "Dr Martin", "location": "Clinic"})
        with patch.object(m, "call_model", return_value=_as_array(data)):
            result = m.extract_reminder("See Dr Martin at the Clinic")
        assert result[0]["metadata"]["person"] == "Dr Martin"

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
        data = _valid_extraction(metadata={"person": "Dr Smith", "location": "Clinic"})
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


# ── Metadata enrichment + pending_questions ───────────────────────────────────


def _meta_of(row):
    return json.loads(row["metadata"]) if row["metadata"] else {}


class TestMetadataEnrichment:
    def test_scheduling_hints_persisted(self, monkeypatch):
        m = _load(monkeypatch)
        data = _valid_extraction(metadata={
            "person": "Dr Martin",
            "weather_requirement": "any",
            "location_type": "indoor",
            "time_constraint": {"earliest_hour": 9, "latest_hour": 17},
            "requires": ["phone"],
            "history_search_terms": ["dentiste"],
        })
        with patch.object(m, "call_model", return_value=_as_array(data)):
            results = m.add_from_text("Prendre rdv dentiste")
        reminder_id, _ = results[0]
        row = next(r for r in rdb.get_due("9999-01-01 00:00:00") if r["id"] == reminder_id)
        meta = _meta_of(row)
        assert meta["weather_requirement"] == "any"
        assert meta["location_type"] == "indoor"
        assert meta["time_constraint"] == {"earliest_hour": 9, "latest_hour": 17}
        assert meta["requires"] == ["phone"]
        assert meta["history_search_terms"] == ["dentiste"]
        assert meta["person"] == "Dr Martin"  # entity at top level preserved

    def test_free_form_metadata_keys_preserved(self, monkeypatch):
        m = _load(monkeypatch)
        data = _valid_extraction(metadata={
            "person": "Dr Martin",
            "preferred_morning_slot": True,
            "social_anxiety_level": "medium",
        })
        with patch.object(m, "call_model", return_value=_as_array(data)):
            results = m.add_from_text("Prendre rdv dentiste")
        reminder_id, _ = results[0]
        row = next(r for r in rdb.get_due("9999-01-01 00:00:00") if r["id"] == reminder_id)
        meta = _meta_of(row)
        assert meta["preferred_morning_slot"] is True
        assert meta["social_anxiety_level"] == "medium"

    def test_pending_questions_get_uuid_and_timestamp(self, monkeypatch):
        m = _load(monkeypatch)
        questions = [
            {"question": "Quel est le nom du dentiste ?", "context": "needed to look up hours"},
            {"question": "Tu peux appeler entre midi et 14h ?", "context": "callable window"},
        ]
        data = _valid_extraction(pending_questions=questions)
        with patch.object(m, "call_model", return_value=_as_array(data)):
            results = m.add_from_text("Prendre rdv dentiste")
        reminder_id, item = results[0]
        # Stored in DB metadata
        row = next(r for r in rdb.get_due("9999-01-01 00:00:00") if r["id"] == reminder_id)
        stored = _meta_of(row).get("pending_questions") or []
        assert len(stored) == 2
        for q in stored:
            assert q["id"]  # uuid present
            assert len(q["id"]) >= 32  # uuid4 format
            assert "created_at" in q
            assert q["question"]
        # Echoed in the returned item for the CLI
        echoed = item.get("pending_questions") or []
        assert len(echoed) == 2
        assert echoed[0]["id"] == stored[0]["id"]

    def test_pending_questions_uuids_are_distinct(self, monkeypatch):
        m = _load(monkeypatch)
        questions = [
            {"question": "Q1 ?", "context": ""},
            {"question": "Q2 ?", "context": ""},
            {"question": "Q3 ?", "context": ""},
        ]
        data = _valid_extraction(pending_questions=questions)
        with patch.object(m, "call_model", return_value=_as_array(data)):
            results = m.add_from_text("Test")
        reminder_id, _ = results[0]
        row = next(r for r in rdb.get_due("9999-01-01 00:00:00") if r["id"] == reminder_id)
        ids = [q["id"] for q in (_meta_of(row).get("pending_questions") or [])]
        assert len(set(ids)) == 3

    def test_empty_pending_questions_not_stored(self, monkeypatch):
        m = _load(monkeypatch)
        data = _valid_extraction(pending_questions=[])
        with patch.object(m, "call_model", return_value=_as_array(data)):
            results = m.add_from_text("Test")
        reminder_id, _ = results[0]
        row = next(r for r in rdb.get_due("9999-01-01 00:00:00") if r["id"] == reminder_id)
        assert "pending_questions" not in _meta_of(row)

    def test_invalid_pending_question_entries_filtered(self, monkeypatch):
        m = _load(monkeypatch)
        questions = [
            {"question": "Valid ?", "context": "ok"},
            {"context": "no question text"},           # missing question
            "not even an object",                       # wrong shape
            {"question": "  ", "context": "blank"},     # blank question
        ]
        data = _valid_extraction(pending_questions=questions)
        with patch.object(m, "call_model", return_value=_as_array(data)):
            results = m.add_from_text("Test")
        reminder_id, _ = results[0]
        row = next(r for r in rdb.get_due("9999-01-01 00:00:00") if r["id"] == reminder_id)
        stored = _meta_of(row).get("pending_questions") or []
        assert len(stored) == 1
        assert stored[0]["question"] == "Valid ?"

    def test_null_metadata_with_questions_still_stores_questions(self, monkeypatch):
        m = _load(monkeypatch)
        data = _valid_extraction(
            metadata=None,
            pending_questions=[{"question": "Une question ?", "context": ""}],
        )
        with patch.object(m, "call_model", return_value=_as_array(data)):
            results = m.add_from_text("Test")
        reminder_id, _ = results[0]
        row = next(r for r in rdb.get_due("9999-01-01 00:00:00") if r["id"] == reminder_id)
        stored = _meta_of(row).get("pending_questions") or []
        assert len(stored) == 1

    def test_null_metadata_and_no_questions_stores_null(self, monkeypatch):
        m = _load(monkeypatch)
        data = _valid_extraction(metadata=None, pending_questions=[])
        with patch.object(m, "call_model", return_value=_as_array(data)):
            results = m.add_from_text("Test")
        reminder_id, _ = results[0]
        row = next(r for r in rdb.get_due("9999-01-01 00:00:00") if r["id"] == reminder_id)
        assert row["metadata"] is None


# ── History injection into the prompt ─────────────────────────────────────────


class TestHistoryInjection:
    def test_no_history_when_db_empty(self, monkeypatch):
        m = _load(monkeypatch)
        captured = {}

        def fake(model, messages, api_key, **kwargs):
            captured["messages"] = messages
            return _as_array(_valid_extraction())

        with patch.object(m, "call_model", side_effect=fake):
            m.extract_reminder("Prendre rendez-vous dentiste")
        # No second system message when there is no related history
        sys_msgs = [msg for msg in captured["messages"] if msg["role"] == "system"]
        assert len(sys_msgs) == 1

    def test_history_added_when_match_exists(self, monkeypatch):
        m = _load(monkeypatch)
        # Seed a related past reminder
        rdb.add_reminder(
            "Rendez-vous dentiste Dr Martin",
            "appointment",
            event_datetime="2025-09-15 14:00:00",
        )
        captured = {}

        def fake(model, messages, api_key, **kwargs):
            captured["messages"] = messages
            return _as_array(_valid_extraction())

        with patch.object(m, "call_model", side_effect=fake):
            m.extract_reminder("Prendre rendez-vous dentiste")
        sys_msgs = [msg for msg in captured["messages"] if msg["role"] == "system"]
        assert len(sys_msgs) == 2
        history = sys_msgs[1]["content"]
        assert "Past related reminders" in history
        assert "Dr Martin" in history
        assert "2025-09-15" in history

    def test_history_skipped_when_query_unrelated(self, monkeypatch):
        m = _load(monkeypatch)
        rdb.add_reminder("Rendez-vous dentiste", "appointment")
        captured = {}

        def fake(model, messages, api_key, **kwargs):
            captured["messages"] = messages
            return _as_array(_valid_extraction())

        with patch.object(m, "call_model", side_effect=fake):
            m.extract_reminder("Tondre la pelouse")
        sys_msgs = [msg for msg in captured["messages"] if msg["role"] == "system"]
        assert len(sys_msgs) == 1   # no overlap with "dentiste"

    def test_history_block_lists_status_and_category(self, monkeypatch):
        m = _load(monkeypatch)
        rid = rdb.add_reminder("Visite dentiste", "appointment",
                               event_datetime="2025-09-15 14:00:00")
        rdb.update_status(rid, "done")
        captured = {}

        def fake(model, messages, api_key, **kwargs):
            captured["messages"] = messages
            return _as_array(_valid_extraction())

        with patch.object(m, "call_model", side_effect=fake):
            m.extract_reminder("Visite dentiste")
        history = [msg for msg in captured["messages"] if msg["role"] == "system"][1]["content"]
        assert "appointment" in history
        assert "done" in history


# ── STT awareness (voice flag) ───────────────────────────────────────────────

class TestVoiceFlag:
    def test_voice_false_omits_warning(self, monkeypatch):
        m = _load(monkeypatch)
        captured = {}

        def fake(model, messages, api_key, **kwargs):
            captured["messages"] = messages
            return _as_array(_valid_extraction())

        with patch.object(m, "call_model", side_effect=fake):
            m.extract_reminder("Rendez-vous Dr Aurel")
        sys_contents = [msg["content"] for msg in captured["messages"] if msg["role"] == "system"]
        assert not any("speech-to-text" in c for c in sys_contents)

    def test_voice_true_inserts_warning(self, monkeypatch):
        m = _load(monkeypatch)
        captured = {}

        def fake(model, messages, api_key, **kwargs):
            captured["messages"] = messages
            return _as_array(_valid_extraction())

        with patch.object(m, "call_model", side_effect=fake):
            m.extract_reminder("Rendez-vous Dr Aurel", voice=True)
        sys_contents = [msg["content"] for msg in captured["messages"] if msg["role"] == "system"]
        warnings = [c for c in sys_contents if "speech-to-text" in c]
        assert len(warnings) == 1
        assert "mis-hears" in warnings[0]

    def test_add_from_text_propagates_voice(self, monkeypatch):
        m = _load(monkeypatch)
        captured = {}

        def fake(model, messages, api_key, **kwargs):
            captured["messages"] = messages
            return _as_array(_valid_extraction())

        with patch.object(m, "call_model", side_effect=fake):
            m.add_from_text("Rendez-vous Dr Aurel", voice=True)
        sys_contents = [msg["content"] for msg in captured["messages"] if msg["role"] == "system"]
        assert any("speech-to-text" in c for c in sys_contents)

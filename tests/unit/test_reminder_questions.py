"""Unit tests for src/reminder/questions.py.

Uses an isolated SQLite database under tmp_path.
"""

import json
import uuid

import pytest

import src.reminder.db as rdb
import src.reminder.questions as qmod


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(rdb, "_DB_DIR", tmp_path)
    monkeypatch.setattr(rdb, "_DB_PATH", tmp_path / "reminders.db")


def _make_reminder(metadata: dict | None = None, **kw) -> int:
    """Insert a reminder with given metadata. Returns its row id."""
    defaults = dict(
        title="Test reminder",
        category="task_short",
        full_context="raw text",
    )
    defaults.update(kw)
    return rdb.add_reminder(metadata=metadata, **defaults)


def _question(text: str, qid: str | None = None, created_at: str = "2026-05-22T10:00:00+00:00") -> dict:
    return {
        "id": qid or str(uuid.uuid4()),
        "question": text,
        "context": "",
        "created_at": created_at,
    }


def _meta_of(reminder_id: int) -> dict:
    with rdb._db() as conn:
        row = conn.execute(
            "SELECT metadata FROM reminders WHERE id = ?", (reminder_id,)
        ).fetchone()
    if row is None or row["metadata"] is None:
        return {}
    return json.loads(row["metadata"])


# ── get_pending_for_reminder ──────────────────────────────────────────────────


class TestGetPendingForReminder:
    def test_returns_empty_when_no_metadata(self):
        rid = _make_reminder(metadata=None)
        assert qmod.get_pending_for_reminder(rid) == []

    def test_returns_empty_when_no_pending_questions_key(self):
        rid = _make_reminder(metadata={"person": "Dr Martin"})
        assert qmod.get_pending_for_reminder(rid) == []

    def test_returns_pending_questions(self):
        q1 = _question("Q1 ?")
        q2 = _question("Q2 ?")
        rid = _make_reminder(metadata={"pending_questions": [q1, q2]})
        result = qmod.get_pending_for_reminder(rid)
        assert len(result) == 2
        assert result[0]["question"] == "Q1 ?"

    def test_filters_invalid_entries(self):
        q_valid = _question("Valid ?")
        rid = _make_reminder(metadata={"pending_questions": [
            q_valid,
            {"id": "", "question": "no id"},
            {"id": "x", "question": ""},
            "not even a dict",
        ]})
        result = qmod.get_pending_for_reminder(rid)
        assert len(result) == 1
        assert result[0]["question"] == "Valid ?"

    def test_returns_empty_for_unknown_reminder(self):
        assert qmod.get_pending_for_reminder(999_999) == []


# ── get_next_pending ──────────────────────────────────────────────────────────


class TestGetNextPending:
    def test_returns_none_when_no_reminders(self):
        assert qmod.get_next_pending() is None

    def test_returns_none_when_no_reminders_have_questions(self):
        _make_reminder(metadata={"person": "Dr Martin"})
        _make_reminder(metadata=None)
        assert qmod.get_next_pending() is None

    def test_returns_question_from_most_urgent_reminder(self):
        # Two reminders with questions; the one with earlier next_trigger wins
        q_late = _question("Late ?")
        q_early = _question("Early ?")
        _make_reminder(
            title="Future task",
            metadata={"pending_questions": [q_late]},
            next_trigger="2030-01-01 00:00:00",
        )
        _make_reminder(
            title="Soon task",
            metadata={"pending_questions": [q_early]},
            next_trigger="2026-01-01 00:00:00",
        )
        result = qmod.get_next_pending()
        assert result is not None
        assert result["question"] == "Early ?"
        assert result["reminder_title"] == "Soon task"

    def test_within_one_reminder_oldest_question_first(self):
        q_older = _question("Older ?", created_at="2026-05-01T10:00:00+00:00")
        q_newer = _question("Newer ?", created_at="2026-05-22T10:00:00+00:00")
        _make_reminder(metadata={"pending_questions": [q_newer, q_older]})
        result = qmod.get_next_pending()
        assert result["question"] == "Older ?"

    def test_returns_reminder_id_and_title(self):
        q = _question("Q ?")
        rid = _make_reminder(title="Mow lawn", metadata={"pending_questions": [q]})
        result = qmod.get_next_pending()
        assert result["reminder_id"] == rid
        assert result["reminder_title"] == "Mow lawn"

    def test_ignores_done_reminders(self):
        q = _question("Q ?")
        rid = _make_reminder(metadata={"pending_questions": [q]})
        rdb.update_status(rid, "done")
        assert qmod.get_next_pending() is None

    def test_ignores_cancelled_reminders(self):
        q = _question("Q ?")
        rid = _make_reminder(metadata={"pending_questions": [q]})
        rdb.update_status(rid, "cancelled")
        assert qmod.get_next_pending() is None

    def test_includes_snoozed_reminders(self):
        q = _question("Q ?")
        rid = _make_reminder(metadata={"pending_questions": [q]})
        rdb.snooze(rid, "2030-01-01 00:00:00")
        result = qmod.get_next_pending()
        assert result is not None
        assert result["reminder_id"] == rid


# ── resolve ───────────────────────────────────────────────────────────────────


class TestResolve:
    def test_moves_question_from_pending_to_answers(self):
        q = _question("Quel dentiste ?", qid="q-1")
        rid = _make_reminder(metadata={"pending_questions": [q]})
        qmod.resolve(rid, "q-1", "Dr Martin")
        meta = _meta_of(rid)
        assert meta.get("pending_questions") == []
        assert len(meta["answers"]) == 1
        ans = meta["answers"][0]
        assert ans["id"] == "q-1"
        assert ans["question"] == "Quel dentiste ?"
        assert ans["answer"] == "Dr Martin"
        assert "answered_at" in ans

    def test_preserves_other_pending_questions(self):
        q1 = _question("Q1 ?", qid="q-1")
        q2 = _question("Q2 ?", qid="q-2")
        rid = _make_reminder(metadata={"pending_questions": [q1, q2]})
        qmod.resolve(rid, "q-1", "answer 1")
        meta = _meta_of(rid)
        assert len(meta["pending_questions"]) == 1
        assert meta["pending_questions"][0]["id"] == "q-2"

    def test_appends_to_existing_answers(self):
        q = _question("Q3 ?", qid="q-3")
        existing = {"id": "old", "question": "old?", "answer": "old-ans",
                    "context": "", "answered_at": "2020-01-01T00:00:00+00:00"}
        rid = _make_reminder(metadata={
            "pending_questions": [q],
            "answers": [existing],
        })
        qmod.resolve(rid, "q-3", "fresh answer")
        meta = _meta_of(rid)
        ids = [a["id"] for a in meta["answers"]]
        assert ids == ["old", "q-3"]

    def test_preserves_other_metadata_keys(self):
        q = _question("Q ?", qid="q-1")
        rid = _make_reminder(metadata={
            "person": "Dr Martin",
            "weather_requirement": "any",
            "pending_questions": [q],
        })
        qmod.resolve(rid, "q-1", "answer")
        meta = _meta_of(rid)
        assert meta["person"] == "Dr Martin"
        assert meta["weather_requirement"] == "any"

    def test_unknown_question_id_is_noop(self):
        q = _question("Q ?", qid="real")
        rid = _make_reminder(metadata={"pending_questions": [q]})
        qmod.resolve(rid, "nonexistent", "answer")
        meta = _meta_of(rid)
        assert len(meta["pending_questions"]) == 1
        assert "answers" not in meta

    def test_unknown_reminder_id_is_noop(self):
        qmod.resolve(999_999, "any", "answer")  # must not raise

    def test_reminder_with_no_metadata_is_noop(self):
        rid = _make_reminder(metadata=None)
        qmod.resolve(rid, "any", "answer")  # must not raise
        assert _meta_of(rid) == {}

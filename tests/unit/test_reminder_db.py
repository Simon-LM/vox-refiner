"""Unit tests for src/reminder/db.py.

All tests operate on a temporary SQLite database injected via monkeypatch
(no writes to ~/.local/share/vox-refiner/).
"""

import json
import sqlite3
from pathlib import Path

import pytest

import src.reminder.db as rdb


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    """Redirect _DB_DIR and _DB_PATH to a per-test temp directory."""
    db_path = tmp_path / "test_reminders.db"
    monkeypatch.setattr(rdb, "_DB_DIR", tmp_path)
    monkeypatch.setattr(rdb, "_DB_PATH", db_path)
    yield db_path


# ── Schema / initialisation ───────────────────────────────────────────────────

class TestInitDb:
    def _table_names(self, db_path: Path) -> set[str]:
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        conn.close()
        return {r[0] for r in rows}

    def test_all_four_tables_created(self, isolated_db):
        rdb.add_reminder("ping", "task_short")
        tables = self._table_names(isolated_db)
        assert {"reminders", "unavailability", "business_cache", "briefing_config"} <= tables

    def test_init_idempotent(self, isolated_db):
        rdb.add_reminder("first", "task_short")
        rdb.add_reminder("second", "task_short")
        tables = self._table_names(isolated_db)
        assert "reminders" in tables


# ── add_reminder ──────────────────────────────────────────────────────────────

class TestAddReminder:
    def test_returns_integer_id(self):
        rid = rdb.add_reminder("Buy milk", "task_short")
        assert isinstance(rid, int)
        assert rid >= 1

    def test_sequential_ids(self):
        id1 = rdb.add_reminder("Task A", "task_short")
        id2 = rdb.add_reminder("Task B", "task_short")
        assert id2 == id1 + 1

    def test_default_status_is_pending(self):
        rid = rdb.add_reminder("Check status", "task_short")
        due = rdb.get_due("9999-01-01 00:00:00")
        row = next(r for r in due if r["id"] == rid)
        assert row["status"] == "pending"

    def test_title_stored(self):
        rid = rdb.add_reminder("Doctor appointment", "appointment")
        due = rdb.get_due("9999-01-01 00:00:00")
        row = next(r for r in due if r["id"] == rid)
        assert row["title"] == "Doctor appointment"

    def test_category_stored(self):
        rid = rdb.add_reminder("Filing taxes", "admin")
        due = rdb.get_due("9999-01-01 00:00:00")
        row = next(r for r in due if r["id"] == rid)
        assert row["category"] == "admin"

    def test_event_datetime_stored(self):
        rid = rdb.add_reminder("Meeting", "appointment", event_datetime="2026-06-01 14:00:00")
        due = rdb.get_due("9999-01-01 00:00:00")
        row = next(r for r in due if r["id"] == rid)
        assert row["event_datetime"] == "2026-06-01 14:00:00"

    def test_next_trigger_explicit(self):
        rid = rdb.add_reminder("Soon", "task_short", next_trigger="2026-01-01 08:00:00")
        due = rdb.get_due("9999-01-01 00:00:00")
        row = next(r for r in due if r["id"] == rid)
        assert row["next_trigger"] == "2026-01-01 08:00:00"

    def test_next_trigger_defaults_to_now(self):
        rid = rdb.add_reminder("Now", "task_short")
        due = rdb.get_due("9999-01-01 00:00:00")
        row = next(r for r in due if r["id"] == rid)
        assert row["next_trigger"] is not None

    def test_metadata_stored_as_json(self):
        meta = {"location": "Paris", "travel_minutes": 30}
        rid = rdb.add_reminder("Trip", "appointment", metadata=meta)
        due = rdb.get_due("9999-01-01 00:00:00")
        row = next(r for r in due if r["id"] == rid)
        stored = json.loads(row["metadata"])
        assert stored == meta

    def test_full_context_stored(self):
        rid = rdb.add_reminder("Context test", "task_short", full_context="raw OCR text here")
        due = rdb.get_due("9999-01-01 00:00:00")
        row = next(r for r in due if r["id"] == rid)
        assert row["full_context"] == "raw OCR text here"

    def test_initial_snooze_count_zero(self):
        rid = rdb.add_reminder("Snooze init", "task_short")
        due = rdb.get_due("9999-01-01 00:00:00")
        row = next(r for r in due if r["id"] == rid)
        assert row["snooze_count"] == 0

    def test_initial_conversation_empty_array(self):
        rid = rdb.add_reminder("Conv init", "task_short")
        due = rdb.get_due("9999-01-01 00:00:00")
        row = next(r for r in due if r["id"] == rid)
        assert json.loads(row["conversation"]) == []


# ── get_due ───────────────────────────────────────────────────────────────────

class TestGetDue:
    def test_empty_db_returns_empty_list(self):
        assert rdb.get_due("2026-01-01 00:00:00") == []

    def test_due_reminder_returned(self):
        rdb.add_reminder("Past", "task_short", next_trigger="2020-01-01 00:00:00")
        due = rdb.get_due("2026-01-01 00:00:00")
        assert len(due) == 1

    def test_future_reminder_not_returned(self):
        rdb.add_reminder("Future", "task_short", next_trigger="2099-01-01 00:00:00")
        due = rdb.get_due("2026-01-01 00:00:00")
        assert due == []

    def test_exact_boundary_included(self):
        rdb.add_reminder("Boundary", "task_short", next_trigger="2026-01-01 12:00:00")
        due = rdb.get_due("2026-01-01 12:00:00")
        assert len(due) == 1

    def test_done_reminder_excluded(self):
        rid = rdb.add_reminder("Done", "task_short", next_trigger="2020-01-01 00:00:00")
        rdb.update_status(rid, "done")
        due = rdb.get_due("2026-01-01 00:00:00")
        assert due == []

    def test_cancelled_reminder_excluded(self):
        rid = rdb.add_reminder("Cancelled", "task_short", next_trigger="2020-01-01 00:00:00")
        rdb.update_status(rid, "cancelled")
        due = rdb.get_due("2026-01-01 00:00:00")
        assert due == []

    def test_snoozed_reminder_included(self):
        rid = rdb.add_reminder("Snoozed", "task_short", next_trigger="2020-01-01 00:00:00")
        rdb.snooze(rid, "2021-01-01 00:00:00")
        due = rdb.get_due("2026-01-01 00:00:00")
        assert len(due) == 1

    def test_ordered_by_next_trigger_asc(self):
        rdb.add_reminder("Second", "task_short", next_trigger="2022-06-01 00:00:00")
        rdb.add_reminder("First", "task_short", next_trigger="2021-01-01 00:00:00")
        due = rdb.get_due("2026-01-01 00:00:00")
        assert due[0]["title"] == "First"
        assert due[1]["title"] == "Second"

    def test_returns_list_of_dicts(self):
        rdb.add_reminder("Dict check", "task_short", next_trigger="2020-01-01 00:00:00")
        due = rdb.get_due("2026-01-01 00:00:00")
        assert isinstance(due[0], dict)


# ── update_status ─────────────────────────────────────────────────────────────

class TestUpdateStatus:
    def test_set_done(self):
        rid = rdb.add_reminder("Set done", "task_short", next_trigger="2020-01-01 00:00:00")
        rdb.update_status(rid, "done")
        due = rdb.get_due("2026-01-01 00:00:00")
        assert all(r["id"] != rid for r in due)

    def test_set_cancelled(self):
        rid = rdb.add_reminder("Set cancel", "task_short", next_trigger="2020-01-01 00:00:00")
        rdb.update_status(rid, "cancelled")
        due = rdb.get_due("2026-01-01 00:00:00")
        assert all(r["id"] != rid for r in due)

    def test_set_in_progress(self):
        rid = rdb.add_reminder("In progress", "task_short", next_trigger="2020-01-01 00:00:00")
        rdb.update_status(rid, "in_progress")
        due = rdb.get_due("2026-01-01 00:00:00")
        assert all(r["id"] != rid for r in due)

    def test_unknown_id_is_silent(self):
        rdb.update_status(9999, "done")  # must not raise


# ── snooze ────────────────────────────────────────────────────────────────────

class TestSnooze:
    def test_status_becomes_snoozed(self):
        rid = rdb.add_reminder("Snooze me", "task_short", next_trigger="2020-01-01 00:00:00")
        rdb.snooze(rid, "2026-06-01 09:00:00")
        due = rdb.get_due("2026-01-01 00:00:00")
        assert all(r["id"] != rid for r in due)

    def test_next_trigger_updated(self):
        rid = rdb.add_reminder("Snooze trigger", "task_short", next_trigger="2020-01-01 00:00:00")
        rdb.snooze(rid, "2026-06-01 09:00:00")
        due = rdb.get_due("9999-01-01 00:00:00")
        row = next(r for r in due if r["id"] == rid)
        assert row["next_trigger"] == "2026-06-01 09:00:00"

    def test_snooze_count_incremented(self):
        rid = rdb.add_reminder("Count snooze", "task_short", next_trigger="2020-01-01 00:00:00")
        rdb.snooze(rid, "2026-06-01 09:00:00")
        due = rdb.get_due("9999-01-01 00:00:00")
        row = next(r for r in due if r["id"] == rid)
        assert row["snooze_count"] == 1

    def test_snooze_count_accumulates(self):
        rid = rdb.add_reminder("Repeat snooze", "task_short", next_trigger="2020-01-01 00:00:00")
        rdb.snooze(rid, "2022-01-01 09:00:00")
        rdb.snooze(rid, "2023-01-01 09:00:00")
        rdb.snooze(rid, "2026-06-01 09:00:00")
        due = rdb.get_due("9999-01-01 00:00:00")
        row = next(r for r in due if r["id"] == rid)
        assert row["snooze_count"] == 3

    def test_last_reminded_set(self):
        rid = rdb.add_reminder("Last reminded", "task_short", next_trigger="2020-01-01 00:00:00")
        rdb.snooze(rid, "2026-06-01 09:00:00")
        due = rdb.get_due("9999-01-01 00:00:00")
        row = next(r for r in due if r["id"] == rid)
        assert row["last_reminded"] is not None


# ── log_conversation ──────────────────────────────────────────────────────────

class TestLogConversation:
    def test_first_entry_appended(self):
        rid = rdb.add_reminder("Conv", "task_short")
        entry = {"role": "user", "text": "Done"}
        rdb.log_conversation(rid, entry)
        due = rdb.get_due("9999-01-01 00:00:00")
        row = next(r for r in due if r["id"] == rid)
        history = json.loads(row["conversation"])
        assert history == [entry]

    def test_multiple_entries_ordered(self):
        rid = rdb.add_reminder("Multi conv", "task_short")
        rdb.log_conversation(rid, {"role": "system", "text": "Reminder fired"})
        rdb.log_conversation(rid, {"role": "user", "text": "Later"})
        rdb.log_conversation(rid, {"role": "assistant", "text": "Snoozed 30min"})
        due = rdb.get_due("9999-01-01 00:00:00")
        row = next(r for r in due if r["id"] == rid)
        history = json.loads(row["conversation"])
        assert len(history) == 3
        assert history[1]["role"] == "user"

    def test_unicode_preserved(self):
        rid = rdb.add_reminder("Unicode conv", "task_short")
        rdb.log_conversation(rid, {"text": "Rendez-vous chez le médecin à 14h"})
        due = rdb.get_due("9999-01-01 00:00:00")
        row = next(r for r in due if r["id"] == rid)
        history = json.loads(row["conversation"])
        assert "médecin" in history[0]["text"]

    def test_unknown_id_is_silent(self):
        rdb.log_conversation(9999, {"role": "user", "text": "test"})  # must not raise


# ── Unavailability ────────────────────────────────────────────────────────────

class TestUnavailability:
    def test_add_returns_id(self):
        uid = rdb.add_unavailability("2026-05-10 00:00:00", "2026-05-10 23:59:59", "sick")
        assert isinstance(uid, int)
        assert uid >= 1

    def test_overlapping_block_returned(self):
        rdb.add_unavailability("2026-05-10 08:00:00", "2026-05-10 17:00:00", "video call")
        results = rdb.get_unavailability("2026-05-10 10:00:00", "2026-05-10 12:00:00")
        assert len(results) == 1

    def test_non_overlapping_block_excluded(self):
        rdb.add_unavailability("2026-05-01 00:00:00", "2026-05-01 23:59:59", "away")
        results = rdb.get_unavailability("2026-05-10 00:00:00", "2026-05-10 23:59:59")
        assert results == []

    def test_adjacent_block_excluded(self):
        # Block ends exactly when window starts — not overlapping
        rdb.add_unavailability("2026-05-09 00:00:00", "2026-05-10 00:00:00", "holiday")
        results = rdb.get_unavailability("2026-05-10 00:00:00", "2026-05-10 23:59:59")
        assert results == []

    def test_reason_stored(self):
        rdb.add_unavailability("2026-05-10 00:00:00", "2026-05-10 23:59:59", "sick")
        results = rdb.get_unavailability("2026-05-09 00:00:00", "2026-05-11 00:00:00")
        assert results[0]["reason"] == "sick"

    def test_source_default_user_declared(self):
        rdb.add_unavailability("2026-05-10 00:00:00", "2026-05-10 23:59:59", "sick")
        results = rdb.get_unavailability("2026-05-09 00:00:00", "2026-05-11 00:00:00")
        assert results[0]["source"] == "user_declared"

    def test_source_custom(self):
        rdb.add_unavailability(
            "2026-05-10 00:00:00", "2026-05-10 23:59:59", "calendar", source="calendar_import"
        )
        results = rdb.get_unavailability("2026-05-09 00:00:00", "2026-05-11 00:00:00")
        assert results[0]["source"] == "calendar_import"

    def test_ordered_by_start_asc(self):
        rdb.add_unavailability("2026-05-12 00:00:00", "2026-05-12 23:59:59", "second")
        rdb.add_unavailability("2026-05-10 00:00:00", "2026-05-10 23:59:59", "first")
        results = rdb.get_unavailability("2026-05-09 00:00:00", "2026-05-13 00:00:00")
        assert results[0]["reason"] == "first"
        assert results[1]["reason"] == "second"


# ── Business cache ────────────────────────────────────────────────────────────

class TestBusinessCache:
    def test_get_unknown_returns_none(self):
        assert rdb.get_cached_business("Unknown Place") is None

    def test_cache_and_retrieve(self):
        rdb.cache_business(
            "Dr Martin",
            "Dr Martin dentist Paris",
            {"monday": "9h-18h", "tuesday": "9h-18h"},
            "12 rue de la Paix, Paris",
        )
        result = rdb.get_cached_business("Dr Martin")
        assert result is not None
        assert result["name"] == "Dr Martin"

    def test_opening_hours_deserialized(self):
        hours = {"monday": "9h-18h", "saturday": "closed"}
        rdb.cache_business("Test Shop", "test shop query", hours, "123 Street")
        result = rdb.get_cached_business("Test Shop")
        assert result["opening_hours"] == hours

    def test_address_stored(self):
        rdb.cache_business("Clinic", "clinic query", {}, "42 Health Rd")
        result = rdb.get_cached_business("Clinic")
        assert result["address"] == "42 Health Rd"

    def test_upsert_updates_existing(self):
        rdb.cache_business("Place", "query 1", {"monday": "old"}, "old address")
        rdb.cache_business("Place", "query 2", {"monday": "new"}, "new address")
        result = rdb.get_cached_business("Place")
        assert result["opening_hours"]["monday"] == "new"
        assert result["address"] == "new address"

    def test_upsert_does_not_duplicate(self):
        rdb.cache_business("Place", "q", {"monday": "9h-18h"}, "addr")
        rdb.cache_business("Place", "q2", {"monday": "updated"}, "addr2")
        # Only one entry per name
        import sqlite3 as _sqlite3
        conn = _sqlite3.connect(str(rdb._DB_PATH))
        count = conn.execute(
            "SELECT COUNT(*) FROM business_cache WHERE name = 'Place'"
        ).fetchone()[0]
        conn.close()
        assert count == 1

    def test_fetched_at_set(self):
        rdb.cache_business("Timestamped", "q", {}, "addr")
        result = rdb.get_cached_business("Timestamped")
        assert result["fetched_at"] is not None


# ── recurrence ────────────────────────────────────────────────────────────────

class TestRecurrence:
    def test_recurrence_stored(self):
        rid = rdb.add_reminder("Daily walk", "task_short", recurrence="daily")
        due = rdb.get_due("9999-01-01 00:00:00")
        row = next(r for r in due if r["id"] == rid)
        assert row["recurrence"] == "daily"

    def test_no_recurrence_is_null(self):
        rid = rdb.add_reminder("One-time", "task_short")
        due = rdb.get_due("9999-01-01 00:00:00")
        row = next(r for r in due if r["id"] == rid)
        assert row["recurrence"] is None


class TestCompleteReminder:
    def test_one_time_returns_none_and_marks_done(self):
        rid = rdb.add_reminder("One-time task", "task_short", next_trigger="2020-01-01 00:00:00")
        result = rdb.complete_reminder(rid)
        assert result is None
        due = rdb.get_due("9999-01-01 00:00:00")
        assert all(r["id"] != rid for r in due)

    def test_daily_returns_next_trigger_string(self):
        rid = rdb.add_reminder(
            "Daily walk", "task_short",
            next_trigger="2020-01-01 08:00:00",
            recurrence="daily",
        )
        result = rdb.complete_reminder(rid)
        assert result is not None
        assert isinstance(result, str)
        # Must be a future datetime
        from datetime import datetime, timezone
        next_dt = datetime.strptime(result, "%Y-%m-%d %H:%M:%S")
        assert next_dt > datetime(2020, 1, 1)

    def test_daily_reminder_stays_pending_after_done(self):
        rid = rdb.add_reminder(
            "Daily walk", "task_short",
            next_trigger="2020-01-01 08:00:00",
            recurrence="daily",
        )
        rdb.complete_reminder(rid)
        due = rdb.get_due("9999-01-01 00:00:00")
        row = next((r for r in due if r["id"] == rid), None)
        assert row is not None
        assert row["status"] == "pending"

    def test_daily_snooze_count_reset_to_zero(self):
        rid = rdb.add_reminder(
            "Daily walk", "task_short",
            next_trigger="2020-01-01 08:00:00",
            recurrence="daily",
        )
        rdb.snooze(rid, "2020-01-02 08:00:00")
        rdb.snooze(rid, "2020-01-03 08:00:00")
        rdb.complete_reminder(rid)
        due = rdb.get_due("9999-01-01 00:00:00")
        row = next(r for r in due if r["id"] == rid)
        assert row["snooze_count"] == 0

    def test_weekly_next_trigger_approx_7_days_ahead(self):
        from datetime import datetime, timedelta, timezone
        rid = rdb.add_reminder(
            "Weekly review", "task_long",
            event_datetime="2020-01-01 10:00:00",
            next_trigger="2020-01-01 10:00:00",
            recurrence="weekly",
        )
        result = rdb.complete_reminder(rid)
        assert result is not None
        next_dt = datetime.strptime(result, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        now = datetime.now(tz=timezone.utc)
        diff = (next_dt - now).days
        assert 6 <= diff <= 8

    def test_monthly_next_trigger_approx_30_days_ahead(self):
        from datetime import datetime, timedelta, timezone
        rid = rdb.add_reminder(
            "Monthly report", "task_long",
            event_datetime="2020-01-15 09:00:00",
            next_trigger="2020-01-15 09:00:00",
            recurrence="monthly",
        )
        result = rdb.complete_reminder(rid)
        assert result is not None
        next_dt = datetime.strptime(result, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        now = datetime.now(tz=timezone.utc)
        diff = (next_dt - now).days
        assert 0 <= diff <= 32

    def test_unknown_id_returns_none(self):
        result = rdb.complete_reminder(9999)
        assert result is None

    def test_complete_one_time_logs_done_occurrence(self):
        rid = rdb.add_reminder("Buy milk", "task_short")
        rdb.complete_reminder(rid)
        occ = rdb.get_occurrences(rid)
        assert len(occ) == 1
        assert occ[0]["status"] == "done"
        assert occ[0]["reminder_id"] == rid

    def test_complete_recurring_logs_done_occurrence(self):
        rid = rdb.add_reminder("Water garden", "task_short", recurrence="1")
        rdb.complete_reminder(rid)
        occ = rdb.get_occurrences(rid)
        assert len(occ) == 1
        assert occ[0]["status"] == "done"

    def test_complete_recurring_multiple_times_accumulates(self):
        rid = rdb.add_reminder("Daily walk", "task_short", recurrence="1")
        rdb.complete_reminder(rid)
        rdb.complete_reminder(rid)
        rdb.complete_reminder(rid)
        occ = rdb.get_occurrences(rid)
        assert len(occ) == 3
        assert all(o["status"] == "done" for o in occ)


# ── TestOccurrences ───────────────────────────────────────────────────────────

class TestOccurrences:
    def test_log_occurrence_done(self):
        rid = rdb.add_reminder("Water plants", "task_short")
        oid = rdb.log_occurrence(rid, "done")
        assert isinstance(oid, int)
        occ = rdb.get_occurrences(rid)
        assert len(occ) == 1
        assert occ[0]["status"] == "done"
        assert occ[0]["reminder_id"] == rid

    def test_log_occurrence_skipped(self):
        rid = rdb.add_reminder("Water plants", "task_short")
        rdb.log_occurrence(rid, "skipped")
        occ = rdb.get_occurrences(rid)
        assert occ[0]["status"] == "skipped"

    def test_log_occurrence_custom_date(self):
        rid = rdb.add_reminder("Water plants", "task_short")
        rdb.log_occurrence(rid, "done", scheduled_for="2026-05-20")
        occ = rdb.get_occurrences(rid)
        assert occ[0]["scheduled_for"] == "2026-05-20"

    def test_get_occurrences_returns_most_recent_first(self):
        rid = rdb.add_reminder("Water plants", "task_short")
        rdb.log_occurrence(rid, "done", scheduled_for="2026-05-20")
        rdb.log_occurrence(rid, "skipped", scheduled_for="2026-05-21")
        rdb.log_occurrence(rid, "done", scheduled_for="2026-05-22")
        occ = rdb.get_occurrences(rid)
        assert occ[0]["scheduled_for"] == "2026-05-22"
        assert occ[-1]["scheduled_for"] == "2026-05-20"

    def test_get_occurrences_empty_for_new_reminder(self):
        rid = rdb.add_reminder("New task", "task_short")
        assert rdb.get_occurrences(rid) == []

    def test_get_occurrences_isolated_by_reminder(self):
        rid_a = rdb.add_reminder("Task A", "task_short")
        rid_b = rdb.add_reminder("Task B", "task_short")
        rdb.log_occurrence(rid_a, "done")
        rdb.log_occurrence(rid_b, "skipped")
        assert len(rdb.get_occurrences(rid_a)) == 1
        assert rdb.get_occurrences(rid_a)[0]["status"] == "done"
        assert len(rdb.get_occurrences(rid_b)) == 1
        assert rdb.get_occurrences(rid_b)[0]["status"] == "skipped"


# ── TestNumericRecurrence ────────────────────────────────────────────────────

class TestNumericRecurrence:
    def _next_days(self, recurrence: str) -> int:
        from datetime import datetime, timezone
        rid = rdb.add_reminder(
            "Test", "task_short",
            event_datetime="2020-01-01 09:00:00",
            next_trigger="2020-01-01 09:00:00",
            recurrence=recurrence,
        )
        result = rdb.complete_reminder(rid)
        assert result is not None
        next_dt = datetime.strptime(result, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=timezone.utc
        )
        return (next_dt - datetime.now(tz=timezone.utc)).days

    def test_numeric_1_behaves_like_daily(self):
        diff = self._next_days("1")
        assert 0 <= diff <= 2

    def test_numeric_7_behaves_like_weekly(self):
        diff = self._next_days("7")
        assert 6 <= diff <= 8

    def test_numeric_14_biweekly(self):
        diff = self._next_days("14")
        assert 13 <= diff <= 15

    def test_numeric_21_triweekly(self):
        diff = self._next_days("21")
        assert 20 <= diff <= 22

    def test_numeric_10_days(self):
        diff = self._next_days("10")
        assert 9 <= diff <= 11

    def test_named_daily_alias_still_works(self):
        diff = self._next_days("daily")
        assert 0 <= diff <= 2

    def test_named_weekly_alias_still_works(self):
        diff = self._next_days("weekly")
        assert 6 <= diff <= 8

    def test_named_biweekly_alias_still_works(self):
        diff = self._next_days("biweekly")
        assert 13 <= diff <= 15

    def test_invalid_recurrence_returns_none(self):
        rid = rdb.add_reminder(
            "Bad recurrence", "task_short",
            next_trigger="2020-01-01 09:00:00",
            recurrence="unknown_value",
        )
        result = rdb.complete_reminder(rid)
        assert result is None


# ── TestRecurrenceEnd ─────────────────────────────────────────────────────────

class TestRecurrenceEnd:
    def test_add_reminder_stores_recurrence_end(self):
        rid = rdb.add_reminder(
            "Garden watering", "task_short",
            recurrence="daily",
            recurrence_end="2026-08-31",
        )
        due = rdb.get_due("9999-01-01 00:00:00")
        row = next(r for r in due if r["id"] == rid)
        assert row["recurrence_end"] == "2026-08-31"

    def test_null_recurrence_end_stored_as_none(self):
        rid = rdb.add_reminder("Infinite task", "task_short", recurrence="daily")
        due = rdb.get_due("9999-01-01 00:00:00")
        row = next(r for r in due if r["id"] == rid)
        assert row["recurrence_end"] is None

    def test_complete_returns_none_when_today_past_end_date(self):
        """recurrence_end in the past → complete_reminder returns None (no more occurrences)."""
        rid = rdb.add_reminder(
            "Spring task", "task_short",
            event_datetime="2020-05-01 09:00:00",
            next_trigger="2020-05-01 09:00:00",
            recurrence="daily",
            recurrence_end="2020-06-01",  # well in the past
        )
        result = rdb.complete_reminder(rid)
        assert result is None

    def test_complete_marks_done_when_end_date_past(self):
        import sqlite3 as _sqlite3
        rid = rdb.add_reminder(
            "Summer task", "task_short",
            event_datetime="2020-06-01 09:00:00",
            next_trigger="2020-06-01 09:00:00",
            recurrence="daily",
            recurrence_end="2020-06-02",
        )
        rdb.complete_reminder(rid)
        with _sqlite3.connect(str(rdb._DB_PATH)) as conn:
            conn.row_factory = _sqlite3.Row
            row = conn.execute("SELECT status FROM reminders WHERE id=?", (rid,)).fetchone()
        assert row["status"] == "done"

    def test_complete_returns_next_trigger_before_end_date(self):
        """recurrence_end far in the future → complete_reminder returns a next trigger."""
        rid = rdb.add_reminder(
            "Long-term task", "task_short",
            event_datetime="2020-01-01 09:00:00",
            next_trigger="2020-01-01 09:00:00",
            recurrence="daily",
            recurrence_end="9999-12-31",
        )
        result = rdb.complete_reminder(rid)
        assert result is not None

    def test_weekly_stops_when_next_occurrence_past_end_date(self):
        """Weekly recurrence: if the next occurrence (7 days away) is past recurrence_end, stop."""
        from datetime import datetime, timedelta, timezone
        tomorrow = (datetime.now(tz=timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
        rid = rdb.add_reminder(
            "Weekly task", "task_short",
            event_datetime="2020-01-01 09:00:00",
            next_trigger="2020-01-01 09:00:00",
            recurrence="weekly",
            recurrence_end=tomorrow,  # end is tomorrow — 7 days away is past end
        )
        result = rdb.complete_reminder(rid)
        assert result is None

    def test_none_recurrence_end_means_indefinite(self):
        """No recurrence_end → same behaviour as before this feature."""
        rid = rdb.add_reminder(
            "Indefinite task", "task_short",
            event_datetime="2020-01-01 09:00:00",
            next_trigger="2020-01-01 09:00:00",
            recurrence="daily",
            recurrence_end=None,
        )
        result = rdb.complete_reminder(rid)
        assert result is not None


# ── Migration ─────────────────────────────────────────────────────────────────

class TestMigration:
    def test_migration_adds_recurrence_end_to_existing_db(self, isolated_db):
        """A DB without recurrence_end column should be migrated transparently."""
        import sqlite3 as _sqlite3
        conn = _sqlite3.connect(str(isolated_db))
        conn.execute(
            """CREATE TABLE IF NOT EXISTS reminders (
               id INTEGER PRIMARY KEY, title TEXT NOT NULL,
               full_context TEXT, category TEXT, status TEXT DEFAULT 'pending',
               event_datetime DATETIME, next_trigger DATETIME,
               snooze_count INTEGER DEFAULT 0, created_at DATETIME,
               last_reminded DATETIME, metadata TEXT,
               conversation TEXT DEFAULT '[]'
            )"""
        )
        conn.commit()
        conn.close()
        rid = rdb.add_reminder("Migrated with end", "task_short",
                               recurrence="daily", recurrence_end="2099-12-31")
        due = rdb.get_due("9999-01-01 00:00:00")
        row = next(r for r in due if r["id"] == rid)
        assert row["recurrence_end"] == "2099-12-31"

    def test_migration_adds_column_to_existing_db(self, isolated_db):
        """A DB created without recurrence column should be migrated transparently."""
        import sqlite3 as _sqlite3
        conn = _sqlite3.connect(str(isolated_db))
        conn.execute(
            """CREATE TABLE IF NOT EXISTS reminders (
               id INTEGER PRIMARY KEY, title TEXT NOT NULL,
               full_context TEXT, category TEXT, status TEXT DEFAULT 'pending',
               event_datetime DATETIME, next_trigger DATETIME,
               snooze_count INTEGER DEFAULT 0, created_at DATETIME,
               last_reminded DATETIME, metadata TEXT,
               conversation TEXT DEFAULT '[]'
            )"""
        )
        conn.commit()
        conn.close()
        # Opening via rdb should migrate silently
        rid = rdb.add_reminder("Migrated", "task_short")
        due = rdb.get_due("9999-01-01 00:00:00")
        row = next(r for r in due if r["id"] == rid)
        assert "recurrence" in row


# ── Keyword extraction ────────────────────────────────────────────────────────

class TestExtractHistoryKeywords:
    def test_empty_text_returns_empty(self):
        assert rdb._extract_history_keywords("") == []

    def test_short_tokens_filtered(self):
        # Tokens < 3 chars removed (le, à, du, etc.)
        result = rdb._extract_history_keywords("Le du à de")
        assert result == []

    def test_stop_words_filtered(self):
        # Common 4+ letter stop words also dropped
        result = rdb._extract_history_keywords("avec dans pour about with that")
        assert result == []

    def test_keeps_relevant_tokens(self):
        result = rdb._extract_history_keywords("Prendre rendez-vous chez le dentiste")
        # "prendre" survives the 3-char threshold and is not in the stop list
        assert "prendre" in result
        assert "rendez" in result
        assert "vous" in result
        assert "dentiste" in result
        assert "chez" not in result  # stop word
        assert "le" not in result    # too short

    def test_case_insensitive(self):
        result = rdb._extract_history_keywords("DENTISTE Dentiste dentiste")
        assert result == ["dentiste"]  # deduplicated, lower-cased

    def test_handles_accents(self):
        result = rdb._extract_history_keywords("rétablir équilibre")
        assert "rétablir" in result
        assert "équilibre" in result

    def test_preserves_first_seen_order(self):
        result = rdb._extract_history_keywords("zebra alpha alpha zebra")
        assert result == ["zebra", "alpha"]


# ── search_history ────────────────────────────────────────────────────────────

class TestSearchHistory:
    def _seed(self, *titles_and_dates):
        """Insert reminders with explicit created_at via direct UPDATE."""
        ids = []
        for title, created_at, context in titles_and_dates:
            rid = rdb.add_reminder(title, "task_short", full_context=context)
            with rdb._db() as conn:
                conn.execute(
                    "UPDATE reminders SET created_at = ?, event_datetime = NULL WHERE id = ?",
                    (created_at, rid),
                )
            ids.append(rid)
        return ids

    def test_empty_query_returns_empty(self):
        rdb.add_reminder("Rendez-vous dentiste", "appointment")
        assert rdb.search_history("") == []
        assert rdb.search_history("le à du") == []  # only short tokens

    def test_empty_db_returns_empty(self):
        assert rdb.search_history("dentiste") == []

    def test_finds_by_title_keyword(self):
        rdb.add_reminder("Rendez-vous chez le dentiste", "appointment")
        rdb.add_reminder("Tondre la pelouse", "task_short")
        result = rdb.search_history("dentiste")
        assert len(result) == 1
        assert "dentiste" in result[0]["title"].lower()

    def test_finds_by_full_context_keyword(self):
        rdb.add_reminder("Appel", "task_short", full_context="Appeler Dr Martin du cabinet dentaire")
        result = rdb.search_history("dentaire")
        assert len(result) == 1
        assert result[0]["full_context"].lower().find("dentaire") >= 0

    def test_case_insensitive_matching(self):
        rdb.add_reminder("Visite DENTISTE", "appointment")
        result = rdb.search_history("dentiste")
        assert len(result) == 1

    def test_or_semantics_multiple_keywords(self):
        rdb.add_reminder("Tondre pelouse", "task_short")
        rdb.add_reminder("Visite dentiste", "appointment")
        rdb.add_reminder("Rien à voir", "task_short")
        result = rdb.search_history("pelouse dentiste")
        ids = {r["id"] for r in result}
        assert len(ids) == 2

    def test_respects_limit(self):
        for i in range(7):
            rdb.add_reminder(f"Tâche jardin {i}", "task_short")
        result = rdb.search_history("jardin", limit=3)
        assert len(result) == 3

    def test_orders_most_recent_first(self):
        ids = self._seed(
            ("Vieille tâche dentiste", "2024-01-01 10:00:00", ""),
            ("Tâche dentiste récente", "2026-01-01 10:00:00", ""),
            ("Tâche dentiste moyenne", "2025-06-01 10:00:00", ""),
        )
        result = rdb.search_history("dentiste")
        assert [r["title"] for r in result] == [
            "Tâche dentiste récente",
            "Tâche dentiste moyenne",
            "Vieille tâche dentiste",
        ]

    def test_event_datetime_takes_priority_over_created_at(self):
        # Created long ago but scheduled for the future → ranks highest
        rid_future = rdb.add_reminder(
            "Future dentiste", "appointment",
            event_datetime="2030-01-01 10:00:00",
        )
        rid_recent = rdb.add_reminder("Recent dentiste", "appointment")
        with rdb._db() as conn:
            conn.execute("UPDATE reminders SET created_at = ? WHERE id = ?",
                         ("2020-01-01 00:00:00", rid_future))
        result = rdb.search_history("dentiste")
        assert result[0]["id"] == rid_future
        assert result[1]["id"] == rid_recent

    def test_includes_done_and_cancelled_reminders(self):
        rid_done = rdb.add_reminder("Visite dentiste", "appointment")
        rdb.update_status(rid_done, "done")
        rid_cancel = rdb.add_reminder("Autre visite dentiste", "appointment")
        rdb.update_status(rid_cancel, "cancelled")
        rdb.add_reminder("Encore dentiste", "appointment")
        result = rdb.search_history("dentiste")
        statuses = {r["status"] for r in result}
        assert statuses == {"done", "cancelled", "pending"}

    def test_returns_status_and_dates(self):
        rdb.add_reminder("Visite dentiste", "appointment",
                         event_datetime="2026-06-01 14:00:00")
        result = rdb.search_history("dentiste")
        assert result[0]["status"] == "pending"
        assert result[0]["event_datetime"] == "2026-06-01 14:00:00"
        assert result[0]["category"] == "appointment"


# ── reset_stale_pending_refinements ──────────────────────────────────────────

class TestResetStalePendingRefinements:
    def test_does_not_touch_recent_pending_refinement(self):
        rid = rdb.add_reminder("Rdv dentiste", "task_short")
        rdb.update_status(rid, "pending_refinement")
        # created_at is "now" — well within the TTL
        count = rdb.reset_stale_pending_refinements(older_than_minutes=35)
        assert count == 0
        with rdb._db() as conn:
            row = conn.execute("SELECT status FROM reminders WHERE id = ?", (rid,)).fetchone()
        assert row["status"] == "pending_refinement"

    def test_resets_old_pending_refinement(self):
        from datetime import datetime, timedelta, timezone
        rid = rdb.add_reminder("Rdv dentiste", "task_short")
        rdb.update_status(rid, "pending_refinement")
        old_ts = (datetime.now(tz=timezone.utc) - timedelta(minutes=40)).strftime("%Y-%m-%d %H:%M:%S")
        with rdb._db() as conn:
            conn.execute("UPDATE reminders SET created_at = ? WHERE id = ?", (old_ts, rid))
        count = rdb.reset_stale_pending_refinements(older_than_minutes=35)
        assert count == 1
        with rdb._db() as conn:
            row = conn.execute("SELECT status FROM reminders WHERE id = ?", (rid,)).fetchone()
        assert row["status"] == "pending"

    def test_does_not_touch_other_statuses(self):
        rid = rdb.add_reminder("Rdv dentiste", "task_short")
        # status stays 'pending' — must not be touched
        count = rdb.reset_stale_pending_refinements(older_than_minutes=0)
        assert count == 0

    def test_returns_count_of_reset_rows(self):
        from datetime import datetime, timedelta, timezone
        old_ts = (datetime.now(tz=timezone.utc) - timedelta(minutes=40)).strftime("%Y-%m-%d %H:%M:%S")
        for title in ("Task A", "Task B", "Task C"):
            rid = rdb.add_reminder(title, "task_short")
            rdb.update_status(rid, "pending_refinement")
            with rdb._db() as conn:
                conn.execute("UPDATE reminders SET created_at = ? WHERE id = ?", (old_ts, rid))
        count = rdb.reset_stale_pending_refinements(older_than_minutes=35)
        assert count == 3

#!/usr/bin/env python3
"""SQLite access layer for the VoxRefiner reminder system.

Database path: $XDG_DATA_HOME/vox-refiner/reminders.db
               (default: ~/.local/share/vox-refiner/reminders.db)

All four tables are created on first use via _init_db().

Public API
----------
    add_reminder(title, category, ...)    -> int  (new row id)
    get_due(now)                          -> list[dict]
    complete_reminder(id)                 -> str | None  (logs occurrence + advances recurrence)
    log_occurrence(id, status)            -> int  (record done/skipped without touching reminder)
    get_occurrences(id)                   -> list[dict]
    update_status(id, status)             -> None
    snooze(id, next_trigger)              -> None
    log_conversation(id, entry)           -> None
    add_unavailability(start, end, ...)   -> int
    get_unavailability(start, end)        -> list[dict]
    cache_business(name, query, hours, address) -> None
    get_cached_business(name)             -> dict | None
"""

from __future__ import annotations

import calendar
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

_DB_DIR = (
    Path(os.environ.get("XDG_DATA_HOME", ""))
    / "vox-refiner"
    if os.environ.get("XDG_DATA_HOME")
    else Path.home() / ".local" / "share" / "vox-refiner"
)
_DB_PATH = _DB_DIR / "reminders.db"


def _db() -> sqlite3.Connection:
    _DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    _init_db(conn)
    return conn


def _init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS reminders (
            id                INTEGER PRIMARY KEY,
            title             TEXT NOT NULL,
            full_context      TEXT,
            category          TEXT,
            status            TEXT DEFAULT 'pending',
            event_datetime    DATETIME,
            next_trigger      DATETIME,
            snooze_count      INTEGER DEFAULT 0,
            created_at        DATETIME,
            last_reminded     DATETIME,
            metadata          TEXT,
            conversation      TEXT DEFAULT '[]',
            recurrence        TEXT,
            recurrence_end    TEXT,
            estimated_minutes INTEGER,
            screen_free       INTEGER DEFAULT NULL
        );
        CREATE TABLE IF NOT EXISTS unavailability (
            id         INTEGER PRIMARY KEY,
            start_dt   DATETIME NOT NULL,
            end_dt     DATETIME NOT NULL,
            reason     TEXT,
            created_at DATETIME,
            source     TEXT DEFAULT 'user_declared'
        );
        CREATE TABLE IF NOT EXISTS business_cache (
            id            INTEGER PRIMARY KEY,
            name          TEXT NOT NULL,
            search_query  TEXT,
            opening_hours TEXT,
            address       TEXT,
            fetched_at    DATETIME
        );
        CREATE TABLE IF NOT EXISTS briefing_config (
            id          INTEGER PRIMARY KEY,
            type        TEXT NOT NULL,
            time        TEXT,
            enabled     INTEGER DEFAULT 1,
            day_of_week INTEGER
        );
        CREATE TABLE IF NOT EXISTS occurrences (
            id            INTEGER PRIMARY KEY,
            reminder_id   INTEGER NOT NULL,
            scheduled_for DATE,
            completed_at  DATETIME,
            status        TEXT
        );
        """
    )
    conn.commit()
    for _col, _type in (
        ("recurrence", "TEXT"),
        ("recurrence_end", "TEXT"),
        ("estimated_minutes", "INTEGER"),
        ("screen_free", "INTEGER"),
    ):
        try:
            conn.execute(f"ALTER TABLE reminders ADD COLUMN {_col} {_type}")
            conn.commit()
        except sqlite3.OperationalError:
            pass  # column already exists


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


# ── Reminders ─────────────────────────────────────────────────────────────────

def add_reminder(
    title: str,
    category: str,
    event_datetime: str | None = None,
    next_trigger: str | None = None,
    full_context: str = "",
    metadata: dict | None = None,
    recurrence: str | None = None,
    recurrence_end: str | None = None,
    estimated_minutes: int | None = None,
    screen_free: bool | None = None,
) -> int:
    now = _now_iso()
    if next_trigger is None:
        if event_datetime and event_datetime > now:
            next_trigger = event_datetime
        else:
            next_trigger = now
    with _db() as conn:
        cur = conn.execute(
            """
            INSERT INTO reminders
                (title, full_context, category, status, event_datetime,
                 next_trigger, snooze_count, created_at, metadata, conversation,
                 recurrence, recurrence_end, estimated_minutes, screen_free)
            VALUES (?, ?, ?, 'pending', ?, ?, 0, ?, ?, '[]', ?, ?, ?, ?)
            """,
            (
                title,
                full_context,
                category,
                event_datetime,
                next_trigger,
                now,
                json.dumps(metadata, ensure_ascii=False) if metadata else None,
                recurrence,
                recurrence_end,
                estimated_minutes,
                int(screen_free) if screen_free is not None else None,
            ),
        )
        return cur.lastrowid


def log_occurrence(reminder_id: int, status: str,
                   scheduled_for: str | None = None) -> int:
    """Record one occurrence of a reminder without touching the reminder row.

    *status*: 'done' | 'skipped'.
    *scheduled_for*: ISO date (YYYY-MM-DD); defaults to today.

    Returns the new occurrence id.
    """
    now = _now_iso()
    with _db() as conn:
        cur = conn.execute(
            "INSERT INTO occurrences (reminder_id, scheduled_for, completed_at, status)"
            " VALUES (?, ?, ?, ?)",
            (reminder_id, scheduled_for or now[:10], now, status),
        )
        return cur.lastrowid


def get_occurrences(reminder_id: int) -> list[dict]:
    """Return all logged occurrences for *reminder_id*, most recent first."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT * FROM occurrences WHERE reminder_id = ?"
            " ORDER BY scheduled_for DESC, completed_at DESC",
            (reminder_id,),
        ).fetchall()
    return [dict(r) for r in rows]


_NAMED_TO_DAYS = {"daily": 1, "weekly": 7, "biweekly": 14}


def _recurrence_delta(recurrence: str) -> timedelta | None:
    """Return the timedelta for a fixed-interval recurrence string, or None for monthly/unknown."""
    if recurrence in _NAMED_TO_DAYS:
        return timedelta(days=_NAMED_TO_DAYS[recurrence])
    try:
        days = int(recurrence)
        if days > 0:
            return timedelta(days=days)
    except (ValueError, TypeError):
        pass
    return None


def _next_recurring_trigger(reminder: dict) -> str | None:
    """Compute the next occurrence for a recurring reminder."""
    recurrence = reminder.get("recurrence")
    if not recurrence:
        return None

    now = datetime.now(tz=timezone.utc)

    # Parse recurrence_end once; None means indefinite
    end_dt: datetime | None = None
    raw_end = reminder.get("recurrence_end")
    if raw_end:
        try:
            end_dt = datetime.strptime(raw_end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pass

    # Today is already past the end date → recurrence has expired
    if end_dt and now.date() > end_dt.date():
        return None

    # Derive the preferred time-of-day from event_datetime, else current time
    base_time = now
    raw = reminder.get("event_datetime") or reminder.get("next_trigger")
    if raw:
        try:
            base_time = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pass

    next_dt: datetime | None = None
    delta = _recurrence_delta(recurrence)

    if delta is not None:
        candidate = now + delta
        next_dt = candidate.replace(
            hour=base_time.hour, minute=base_time.minute, second=0, microsecond=0
        )
        if next_dt <= now:
            next_dt += delta

    elif recurrence == "monthly":
        day = base_time.day
        month = now.month + 1 if now.day >= day else now.month
        year = now.year
        if month > 12:
            month, year = 1, year + 1
        day = min(day, calendar.monthrange(year, month)[1])
        next_dt = now.replace(
            year=year, month=month, day=day,
            hour=base_time.hour, minute=base_time.minute, second=0, microsecond=0,
        )
        if next_dt <= now:
            month += 1
            if month > 12:
                month, year = 1, year + 1
            day = min(day, calendar.monthrange(year, month)[1])
            next_dt = next_dt.replace(year=year, month=month, day=day)

    if next_dt is None:
        return None

    # Next computed occurrence is past the end date → recurrence expires
    if end_dt and next_dt.date() > end_dt.date():
        return None

    return next_dt.strftime("%Y-%m-%d %H:%M:%S")


def complete_reminder(reminder_id: int) -> str | None:
    """Mark a reminder as completed for this occurrence.

    Always logs a row in the `occurrences` table (status='done').
    - Recurring reminders: advance next_trigger and stay 'pending'.
    - One-time reminders: set status to 'done'.

    Returns the next_trigger string if recurring, None if one-time.
    """
    now = _now_iso()
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM reminders WHERE id = ?", (reminder_id,)
        ).fetchone()
        if row is None:
            return None
        reminder = dict(row)
        conn.execute(
            "INSERT INTO occurrences (reminder_id, scheduled_for, completed_at, status)"
            " VALUES (?, ?, ?, 'done')",
            (reminder_id, now[:10], now),
        )
        next_t = _next_recurring_trigger(reminder)
        if next_t:
            conn.execute(
                """UPDATE reminders
                   SET status = 'pending', next_trigger = ?, snooze_count = 0,
                       last_reminded = ?
                   WHERE id = ?""",
                (next_t, now, reminder_id),
            )
            return next_t
        conn.execute(
            "UPDATE reminders SET status = 'done' WHERE id = ?", (reminder_id,)
        )
        return None


def get_due(now: str | None = None) -> list[dict]:
    """Return all reminders with next_trigger <= *now* and status pending/snoozed.

    'pending_refinement' is intentionally excluded — those reminders have an
    active conversation session in progress and must not be triggered.
    """
    if now is None:
        now = _now_iso()
    with _db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM reminders
            WHERE next_trigger <= ?
              AND status IN ('pending', 'snoozed')
            ORDER BY next_trigger ASC
            """,
            (now,),
        ).fetchall()
    return [dict(r) for r in rows]


def reset_stale_pending_refinements(older_than_minutes: int = 35) -> int:
    """Reset reminders stuck in 'pending_refinement' for more than *older_than_minutes*.

    Called by the daemon on each tick as a safety net for conversations that were
    abandoned without calling finalize() (terminal killed, crash, API failure).
    The conversation session TTL is 30 min, so 35 min is a safe margin.

    Returns the number of rows updated.
    """
    threshold = (
        datetime.now(tz=timezone.utc) - timedelta(minutes=older_than_minutes)
    ).strftime("%Y-%m-%d %H:%M:%S")
    with _db() as conn:
        cur = conn.execute(
            "UPDATE reminders SET status = 'pending' "
            "WHERE status = 'pending_refinement' AND created_at <= ?",
            (threshold,),
        )
        return cur.rowcount


def update_status(reminder_id: int, status: str) -> None:
    with _db() as conn:
        conn.execute(
            "UPDATE reminders SET status = ? WHERE id = ?",
            (status, reminder_id),
        )


def bump_trigger(reminder_id: int, next_trigger: str) -> None:
    """Advance next_trigger only — no status change, no snooze_count increment."""
    with _db() as conn:
        conn.execute(
            "UPDATE reminders SET next_trigger = ? WHERE id = ?",
            (next_trigger, reminder_id),
        )


def snooze(reminder_id: int, next_trigger: str) -> None:
    with _db() as conn:
        conn.execute(
            """
            UPDATE reminders
            SET status = 'snoozed',
                next_trigger = ?,
                snooze_count = snooze_count + 1,
                last_reminded = ?
            WHERE id = ?
            """,
            (next_trigger, _now_iso(), reminder_id),
        )


def log_conversation(reminder_id: int, entry: dict) -> None:
    """Append *entry* to the conversation JSON array stored on the reminder."""
    with _db() as conn:
        row = conn.execute(
            "SELECT conversation FROM reminders WHERE id = ?", (reminder_id,)
        ).fetchone()
        if row is None:
            return
        history: list = json.loads(row["conversation"] or "[]")
        history.append(entry)
        conn.execute(
            "UPDATE reminders SET conversation = ? WHERE id = ?",
            (json.dumps(history, ensure_ascii=False), reminder_id),
        )


# ── Unavailability ────────────────────────────────────────────────────────────

def add_unavailability(
    start_dt: str,
    end_dt: str,
    reason: str,
    source: str = "user_declared",
) -> int:
    with _db() as conn:
        cur = conn.execute(
            """
            INSERT INTO unavailability (start_dt, end_dt, reason, created_at, source)
            VALUES (?, ?, ?, ?, ?)
            """,
            (start_dt, end_dt, reason, _now_iso(), source),
        )
        return cur.lastrowid


def get_unavailability(start_dt: str, end_dt: str) -> list[dict]:
    """Return unavailability blocks that overlap with the [start_dt, end_dt] window."""
    with _db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM unavailability
            WHERE start_dt < ? AND end_dt > ?
            ORDER BY start_dt ASC
            """,
            (end_dt, start_dt),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Business cache ────────────────────────────────────────────────────────────

def cache_business(
    name: str,
    search_query: str,
    opening_hours: dict,
    address: str,
) -> None:
    """Insert or update a business entry (upsert by name)."""
    payload = json.dumps(opening_hours, ensure_ascii=False)
    with _db() as conn:
        existing = conn.execute(
            "SELECT id FROM business_cache WHERE name = ?", (name,)
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE business_cache
                SET search_query = ?, opening_hours = ?, address = ?, fetched_at = ?
                WHERE id = ?
                """,
                (search_query, payload, address, _now_iso(), existing["id"]),
            )
        else:
            conn.execute(
                """
                INSERT INTO business_cache
                    (name, search_query, opening_hours, address, fetched_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (name, search_query, payload, address, _now_iso()),
            )


def get_cached_business(name: str) -> dict | None:
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM business_cache WHERE name = ?", (name,)
        ).fetchone()
    if row is None:
        return None
    result = dict(row)
    if result.get("opening_hours"):
        result["opening_hours"] = json.loads(result["opening_hours"])
    return result


# ── History search ────────────────────────────────────────────────────────────

# Short stop words (FR + EN). Kept tiny on purpose: anything below the
# length threshold is filtered out, this list only catches the few common
# 4+ letter fillers that still slip through.
_HISTORY_STOP_WORDS = frozenset({
    # FR
    "alors", "ainsi", "avec", "aussi", "celle", "celles", "celui", "ceux",
    "chez", "comme", "dans", "demain", "donc", "encore", "hier", "jamais",
    "leur", "leurs", "lorsque", "mais", "même", "moins", "plus", "pour",
    "puis", "quand", "rien", "sans", "sous", "souvent", "toujours", "tout",
    "tous", "toute", "toutes", "trop", "très",
    # EN
    "about", "above", "after", "again", "below", "been", "before", "could",
    "from", "have", "here", "into", "just", "less", "many", "more", "most",
    "much", "none", "onto", "should", "some", "still", "than", "that",
    "their", "them", "then", "there", "these", "they", "this", "those",
    "very", "what", "when", "where", "which", "will", "with", "without",
    "would",
})


def _extract_history_keywords(text: str) -> list[str]:
    """Return unique 3+ char keywords from *text*, lower-cased, stop words removed."""
    tokens = re.findall(r"[a-zà-ÿ0-9]+", text.lower())
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        if len(t) < 3 or t in _HISTORY_STOP_WORDS or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def search_history(query: str, limit: int = 5) -> list[dict]:
    """Find past reminders related to *query* via keyword LIKE matching.

    Returns up to *limit* matching reminders, most recent first (event_datetime
    if set, else created_at). All statuses are included so the caller can see
    completed/cancelled context alongside active tasks. Returns [] when *query*
    contains no usable keywords.
    """
    keywords = _extract_history_keywords(query)
    if not keywords:
        return []
    clauses: list[str] = []
    params: list[object] = []
    for kw in keywords:
        like = f"%{kw}%"
        clauses.append("(LOWER(title) LIKE ? OR LOWER(full_context) LIKE ?)")
        params.append(like)
        params.append(like)
    where = " OR ".join(clauses)
    sql = (
        "SELECT id, title, category, status, event_datetime, created_at, full_context "
        "FROM reminders "
        f"WHERE {where} "
        "ORDER BY COALESCE(event_datetime, created_at) DESC "
        "LIMIT ?"
    )
    params.append(limit)
    with _db() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]

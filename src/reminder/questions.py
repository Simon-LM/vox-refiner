#!/usr/bin/env python3
"""Per-reminder follow-up question management.

When a reminder is created, the AI may emit a `pending_questions` list to help
schedule it better later (e.g. "Quel est le nom du dentiste ?"). Each question
is stamped with a UUID by `src/reminder/add.py` and stored inside the
reminder's `metadata` JSON column.

This module exposes the lookup + resolution layer used by `reminder.sh`:
    - surface the next pending question (across all active reminders)
    - list pending questions for one reminder (after creation, ask them)
    - record an answer (move the question from `pending_questions` to `answers`)

Storage layout inside `reminders.metadata`:
    {
      "person": ...,                            ← entities / hints / free-form
      "weather_requirement": ...,
      ...
      "pending_questions": [
        { "id": "<uuid>", "question": "...", "context": "...", "created_at": "..." },
        ...
      ],
      "answers": [
        { "id": "<uuid>", "question": "...", "answer": "...",
          "context": "...", "answered_at": "..." },
        ...
      ]
    }

Public API
----------
    get_pending_for_reminder(reminder_id) -> list[dict]
    get_next_pending()                    -> dict | None
    resolve(reminder_id, question_id, answer) -> None

CLI
---
    python -m src.reminder.questions next
    python -m src.reminder.questions for-reminder <reminder_id>
    python -m src.reminder.questions resolve <reminder_id> <question_id> "<answer>"
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timezone

from src.reminder.db import _db


def _load_metadata(conn: sqlite3.Connection, reminder_id: int) -> tuple[dict, str] | None:
    """Return (metadata_dict, title) for *reminder_id*, or None if not found."""
    row = conn.execute(
        "SELECT metadata, title FROM reminders WHERE id = ?", (reminder_id,)
    ).fetchone()
    if row is None:
        return None
    raw = row["metadata"]
    try:
        meta = json.loads(raw) if raw else {}
    except (json.JSONDecodeError, TypeError):
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    return meta, row["title"]


def _save_metadata(conn: sqlite3.Connection, reminder_id: int, metadata: dict) -> None:
    conn.execute(
        "UPDATE reminders SET metadata = ? WHERE id = ?",
        (json.dumps(metadata, ensure_ascii=False), reminder_id),
    )


def get_pending_for_reminder(reminder_id: int) -> list[dict]:
    """Return all valid pending questions attached to *reminder_id*."""
    with _db() as conn:
        loaded = _load_metadata(conn, reminder_id)
    if loaded is None:
        return []
    meta, _ = loaded
    questions = meta.get("pending_questions") or []
    return [
        q for q in questions
        if isinstance(q, dict) and q.get("id") and q.get("question")
    ]


def get_next_pending() -> dict | None:
    """Return the most urgent pending question across all active reminders.

    Ordered by next_trigger ASC, then by question's created_at ASC within a
    reminder. Returns:
        { "reminder_id": int, "reminder_title": str,
          "id": str, "question": str, "context": str }
    or None if no pending question exists.
    """
    with _db() as conn:
        rows = conn.execute(
            """
            SELECT id, title, metadata
            FROM reminders
            WHERE status IN ('pending', 'snoozed')
              AND metadata IS NOT NULL
            ORDER BY next_trigger ASC
            """,
        ).fetchall()
    for row in rows:
        try:
            meta = json.loads(row["metadata"])
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(meta, dict):
            continue
        questions = meta.get("pending_questions") or []
        valid = [q for q in questions if isinstance(q, dict) and q.get("id") and q.get("question")]
        if not valid:
            continue
        valid.sort(key=lambda q: q.get("created_at") or "")
        q = valid[0]
        return {
            "reminder_id": row["id"],
            "reminder_title": row["title"],
            "id": q["id"],
            "question": q["question"],
            "context": q.get("context", ""),
        }
    return None


def resolve(reminder_id: int, question_id: str, answer: str) -> None:
    """Record the user's answer and move the question to the `answers` list.

    No-op if the question is not found.
    """
    with _db() as conn:
        loaded = _load_metadata(conn, reminder_id)
        if loaded is None:
            return
        meta, _ = loaded
        questions = meta.get("pending_questions") or []
        entry = next(
            (q for q in questions
             if isinstance(q, dict) and q.get("id") == question_id),
            None,
        )
        if entry is None:
            return
        meta["pending_questions"] = [
            q for q in questions
            if not (isinstance(q, dict) and q.get("id") == question_id)
        ]
        answers = meta.get("answers")
        if not isinstance(answers, list):
            answers = []
        answers.append({
            "id": question_id,
            "question": entry.get("question", ""),
            "answer": answer,
            "context": entry.get("context", ""),
            "answered_at": datetime.now(tz=timezone.utc).isoformat(),
        })
        meta["answers"] = answers
        _save_metadata(conn, reminder_id, meta)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Per-reminder follow-up questions")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("next", help="Print the next pending question across all reminders")

    p_for = sub.add_parser("for-reminder", help="List pending questions for one reminder")
    p_for.add_argument("reminder_id", type=int)

    p_res = sub.add_parser("resolve", help="Record the user's answer")
    p_res.add_argument("reminder_id", type=int)
    p_res.add_argument("question_id")
    p_res.add_argument("answer")

    args = parser.parse_args()

    if args.cmd == "next":
        entry = get_next_pending()
        if entry:
            print(json.dumps(entry, ensure_ascii=False))

    elif args.cmd == "for-reminder":
        questions = get_pending_for_reminder(args.reminder_id)
        if questions:
            print(json.dumps(questions, ensure_ascii=False))

    elif args.cmd == "resolve":
        resolve(args.reminder_id, args.question_id, args.answer)

    else:
        parser.print_help(sys.stderr)
        sys.exit(1)

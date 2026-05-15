#!/usr/bin/env python3
"""Parse raw text into a structured reminder and store it in the database.

Accepts free-form text (typed, OCR, or voice transcript) and calls Mistral
to extract: title, category, event datetime, and named entities. The result
is stored via reminder_db and returned as JSON so the caller (shell script)
can voice-confirm and ask follow-up questions for missing fields.

Usage:
    python -m src.reminder_add "Doctor appointment Friday 3pm Dr Martin"
    echo "..." | python -m src.reminder_add --stdin

Exit codes:
    0  — reminder stored; extracted JSON printed to stdout
    1  — empty input, missing API key, or all models failed
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from src.common import SECURITY_BLOCK, call_model, compute_timing, effective_timeout  # noqa: E402
from src.reminder_db import add_reminder, complete_reminder  # noqa: E402, F401
from src.ui_py import error, process, warn  # noqa: E402

_MODEL = os.environ.get("REFINE_MODEL_SHORT", "mistral-small-latest")
_MODEL_FALLBACK = "mistral-medium-latest"

def _build_system_prompt() -> str:
    from datetime import date
    today = date.today().isoformat()
    return (
        "You are a personal agenda assistant.\n"
        "You will receive a raw text describing a task, appointment, or reminder.\n"
        "Extract all tasks and return them as a JSON array — one object per task.\n"
        "If the input contains only one task, return an array with one element.\n"
        "\n"
        "Each object in the array must have these fields:\n"
        '  "title"          : string — short summary (max 80 chars), without recurrence wording\n'
        '  "category"       : one of: appointment / task_short / task_long / admin / deadline\n'
        '  "event_datetime" : ISO datetime string "YYYY-MM-DD HH:MM:SS" or null if unknown\n'
        '  "recurrence"     : number of days as a string, "monthly", or null\n'
        '                     "1"=daily  "7"=weekly  "14"=every 2 weeks  "21"=every 3 weeks\n'
        '                     "monthly"=calendar month (variable length)  null=one-time\n'
        '  "recurrence_end" : "YYYY-MM-DD" or null — last date for recurrence; null if indefinite\n'
        '  "entities"       : object with any of: person, location, phone — null if none\n'
        '  "missing_fields" : list of fields the user should be asked about (e.g. ["date","time"])\n'
        "\n"
        "Rules:\n"
        "- Output ONLY a valid JSON array. No markdown, no explanation, no code block.\n"
        "- Split distinct actions into separate objects even if described in one sentence.\n"
        "- category=appointment for in-person meetings, medical, admin rendez-vous.\n"
        "- category=task_short for quick tasks under 30 minutes (calls, errands, emails).\n"
        "- category=task_long for multi-hour tasks (reports, projects, travel preparation).\n"
        "- category=admin for paperwork, forms, declarations.\n"
        "- category=deadline for submission or payment deadlines.\n"
        f"- If the date is relative (today, tomorrow, next Monday), resolve it relative to today which is {today}.\n"
        '- recurrence: express as number of days between occurrences (string integer).\n'
        '  "1" for daily / chaque jour / tous les jours.\n'
        '  "7" for weekly / chaque semaine / toutes les semaines.\n'
        '  "14" for every 2 weeks / une semaine sur deux / tous les 15 jours.\n'
        '  "21" for every 3 weeks / toutes les 3 semaines.\n'
        '  "10" for every 10 days / tous les 10 jours. Any positive integer is valid.\n'
        '  "monthly" for calendar months only (chaque mois / tous les mois / every month).\n'
        "- recurrence=null for one-time reminders (no repetition keyword in the text).\n"
        "- The title should describe the action itself, without repeating the recurrence wording.\n"
        f"- recurrence_end: resolve from seasonal or duration expressions relative to today ({today}).\n"
        "  Meteorological seasons: spring=March–May (ends MM-05-31), summer=June–August (ends MM-08-31),\n"
        "  autumn=September–November (ends MM-11-30), winter=December–February (ends next year MM-02-28 or 29).\n"
        '  "au printemps" → recurrence_end=YYYY-05-31; "en été" → YYYY-08-31;\n'
        '  "au printemps et en été" → YYYY-08-31; "en automne" → YYYY-11-30;\n'
        '  "jusqu\'à fin septembre" → YYYY-09-30; "pour 3 mois" → today + 3 months (last day of that month).\n'
        "  If no end date or season is specified, recurrence_end=null.\n"
        "\n"
        + SECURITY_BLOCK
    )


def extract_reminder(text: str) -> list[dict]:
    """Call Mistral to extract structured reminder data from *text*.

    Returns a list of dicts (one per task). Always a list, even for single tasks.
    Raises RuntimeError if all models fail.
    """
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        raise RuntimeError("MISTRAL_API_KEY is not set. Check your .env file.")

    system_prompt = _build_system_prompt()
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": text},
    ]

    word_count = len(text.split())
    base_timeout, retry_delay = compute_timing(word_count)

    for model in (_MODEL, _MODEL_FALLBACK):
        try:
            timeout = effective_timeout(base_timeout, model)
            if model == _MODEL:
                process(f"Extracting reminder via {model}...")
            else:
                warn(f"{_MODEL} unavailable — switching to fallback: {model}")
            raw = call_model(
                model, messages, api_key,
                timeout=timeout,
                retry_delay=retry_delay,
                retries=2,
            )
            raw = raw.strip()
            # Strip markdown code fences if the model echoed them despite the instruction
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                if raw.endswith("```"):
                    raw = raw[:-3].rstrip()
            result = json.loads(raw)
            # Tolerate a model that returns a single object instead of an array
            if isinstance(result, dict):
                result = [result]
            return result
        except (json.JSONDecodeError, ValueError) as exc:
            warn(f"JSON parse error from {model}: {exc} — retrying with fallback...")
            continue
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            if status in (429, 500, 502, 503):
                warn(f"{model} error ({status}) — switching model…")
                continue
            raise
        except requests.RequestException:
            warn(f"{model} unreachable, switching…")
            continue

    raise RuntimeError("All extraction models failed.")


def add_from_text(text: str) -> list[tuple[int, dict]]:
    """Extract reminders from *text*, store each in DB, return list of (id, extracted_data)."""
    items = extract_reminder(text)
    results = []
    for item in items:
        reminder_id = add_reminder(
            title=item.get("title", text[:80]),
            category=item.get("category", "task_short"),
            event_datetime=item.get("event_datetime"),
            full_context=text,
            metadata=item.get("entities"),
            recurrence=item.get("recurrence"),
            recurrence_end=item.get("recurrence_end"),
        )
        results.append((reminder_id, item))
    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Add a reminder from text")
    parser.add_argument("text", nargs="?", help="Reminder text")
    parser.add_argument("--stdin", action="store_true", help="Read text from stdin")
    args = parser.parse_args()

    if args.stdin:
        input_text = sys.stdin.read().strip()
    elif args.text:
        input_text = args.text.strip()
    else:
        error("No input text provided.")
        parser.print_help(sys.stderr)
        sys.exit(1)

    if not input_text:
        error("Empty input.")
        sys.exit(1)

    try:
        results = add_from_text(input_text)
        output = []
        for reminder_id, data in results:
            data["id"] = reminder_id
            output.append(data)
        print(json.dumps(output, ensure_ascii=False))
    except RuntimeError as exc:
        error(str(exc))
        sys.exit(1)

#!/usr/bin/env python3
"""Parse raw text into a structured reminder and store it in the database.

Accepts free-form text (typed, OCR, or voice transcript) and calls Mistral
to extract: title, category, event datetime, and named entities. The result
is stored via reminder_db and returned as JSON so the caller (shell script)
can voice-confirm and ask follow-up questions for missing fields.

Usage:
    python -m src.reminder.add "Doctor appointment Friday 3pm Dr Martin"
    echo "..." | python -m src.reminder.add --stdin

Exit codes:
    0  — reminder stored; extracted JSON printed to stdout
    1  — empty input, missing API key, or all models failed
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

from src.common import SECURITY_BLOCK, call_model, compute_timing, effective_timeout  # noqa: E402
from src.reminder.db import add_reminder, complete_reminder, search_history  # noqa: E402, F401
from src.ui_py import error, process, warn  # noqa: E402

_MODEL = os.environ.get("REFINE_MODEL_SHORT", "mistral-small-latest")
_MODEL_FALLBACK = "mistral-medium-latest"

_VOICE_WARNING = (
    "NOTE: the user request below was produced by speech-to-text (the user\n"
    "dictated it; they did not type it). Speech-to-text frequently mis-hears:\n"
    "  - proper nouns (people's names, doctors, business names, street names)\n"
    "  - numbers (phone numbers, dates, hours, addresses)\n"
    "  - homophones and rare words\n"
    "Apply extra caution on any of these elements you need to ACT on (use for\n"
    "a web search, store as the canonical contact, etc.):\n"
    "  - If the user spelled a name letter-by-letter, that spelling overrides\n"
    "    any phonetic version that came before it.\n"
    "  - If a critical identifier (doctor surname, exact street, phone number)\n"
    "    was NOT spelled out and you suspect a mishearing risk, add a\n"
    "    pending_questions entry asking the user to spell or confirm it.\n"
)

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
        '  "estimated_minutes" : integer — realistic duration of the physical task in minutes, or null\n'
        '                        Only set for physical tasks (task_short, task_long, errand).\n'
        '                        Examples: "do the dishes"=15, "water the garden"=20, "take out bins"=5.\n'
        '                        null for appointments, admin, deadline categories.\n'
        '  "screen_free"       : true if the task can be done without a screen (cleaning, gardening, dishes, shopping,\n'
        '                        errands, physical chores) — false if it requires the screen (calls, emails, agenda,\n'
        '                        any task needing computer or phone interaction). null if genuinely ambiguous.\n'
        '  "metadata"          : object — task-specific data the scheduler will read later, or null.\n'
        '                        May contain any of these predefined keys (omit irrelevant ones):\n'
        '                          Named entities:\n'
        '                            "person"        : full name (e.g. "Dr Martin")\n'
        '                            "location"      : address or place name\n'
        '                            "phone"         : phone number\n'
        '                            "business_name" : commercial entity (e.g. "Boulangerie du coin")\n'
        '                          Scheduling hints (used by the picker to choose the right moment):\n'
        '                            "weather_requirement" : "good_required" | "bad_ok" | "any"\n'
        '                                good_required → outdoor garden, walk, sport outside\n'
        '                                bad_ok        → indoor cleaning, paperwork, calls\n'
        '                                any           → weather is irrelevant\n'
        '                            "location_type" : "indoor" | "outdoor" | "any"\n'
        '                            "time_constraint" : { "earliest_hour": 0-23, "latest_hour": 0-23 }\n'
        '                                Use only when the task has a natural time window\n'
        '                                (callable hours, store opening hours, …).\n'
        '                                Do NOT use this to encode daylight — use requires_daylight instead.\n'
        '                            "requires_daylight" : true if the task needs daylight to be done\n'
        '                                (gardening, mowing, car wash, hiking, outdoor sport).\n'
        '                                false or omitted for tasks doable in the dark\n'
        '                                (taking out bins, walking the dog, phone calls, indoor work).\n'
        '                            "requires" : array of strings, any of "phone", "computer", "transport", "tools"\n'
        '                            "history_search_terms" : array of up to 3 short keywords used to find\n'
        '                                related past reminders (e.g. ["dentiste"] for a dentist appointment).\n'
        '                        You MAY add any other free-form keys if they help future scheduling.\n'
        '                        Use lowercase_snake_case for keys.\n'
        '                        Return null when there is nothing scheduling-relevant to store.\n'
        '  "pending_questions" : array of follow-up questions to ask the user later.\n'
        '                        Each entry: { "question": "<question text in the user language>",\n'
        '                                      "context":  "<short explanation of why it helps>" }\n'
        '                        Add a question ONLY when the information would genuinely help schedule\n'
        '                        the task at the right moment (callable hours, exact name of a business,\n'
        '                        missing date, weather sensitivity, …). Empty array [] if the task is\n'
        '                        complete and ready to be scheduled.\n'
        "\n"
        "Rules:\n"
        "- Output ONLY a valid JSON array. No markdown, no explanation, no code block.\n"
        "- Split distinct actions into separate objects even if described in one sentence.\n"
        '- Spelled-out names: when the input contains a letter sequence separated by\n'
        '  dashes, spaces, or written out ("H-O-R-E-L", "H O R E L", "H comme Henri,\n'
        '  O comme Oscar, …"), treat those letters as the CANONICAL spelling of the\n'
        '  immediately preceding proper noun. Voice transcription often mis-hears\n'
        '  surnames and business names, and the user spells them out to correct.\n'
        '  REPLACE the preceding phonetic guess with the spelled form in the title\n'
        '  and metadata — do NOT concatenate both.\n'
        '  Example: "Rendez-vous chez le dentiste Christophe Aurel. H-O-R-E-L."\n'
        '    → title: "Rendez-vous chez le dentiste Christophe Horel"\n'
        '    → metadata.person: "Christophe Horel"\n'
        '    (the spelled letters CORRECT "Aurel" — they do not add a second name)\n'
        '  When unsure whether a spelling corrects a preceding name or is a separate\n'
        '  identifier, add a pending_questions entry to confirm.\n'
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


def _related_history_block(text: str, limit: int = 5) -> str:
    """Format up to *limit* past related reminders as a system-message block.

    Returns the empty string when there is nothing to share (keeps the prompt
    short for unrelated requests).
    """
    matches = search_history(text, limit=limit)
    if not matches:
        return ""
    lines = [
        "Past related reminders (most recent first). Use this context to",
        "personalise follow-up questions and pre-fill metadata when applicable.",
        "If the new request is a recurrence of a past one, ask sharper",
        "questions (e.g. 'Toujours Dr Martin ?' rather than 'Quel dentiste ?').",
        "Do NOT copy past data blindly — only when the user clearly refers to",
        "the same subject or entity.",
        "",
    ]
    for m in matches:
        when = (m.get("event_datetime") or m.get("created_at") or "")
        when_short = when.split(" ")[0] if when else "?"
        lines.append(
            f"  - \"{m['title']}\" ({m.get('category') or '?'})"
            f" on {when_short} — status: {m.get('status') or '?'}"
        )
    return "\n".join(lines)


def extract_reminder(text: str, voice: bool = False) -> list[dict]:
    """Call Mistral to extract structured reminder data from *text*.

    When *voice* is True, prepend a system note warning the model that the
    input came from speech-to-text (heightened risk of mistranscribed proper
    nouns / numbers).

    Returns a list of dicts (one per task). Always a list, even for single tasks.
    Raises RuntimeError if all models fail.
    """
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        raise RuntimeError("MISTRAL_API_KEY is not set. Check your .env file.")

    system_prompt = _build_system_prompt()
    history_block = _related_history_block(text)
    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    if voice:
        messages.append({"role": "system", "content": _VOICE_WARNING})
    if history_block:
        messages.append({"role": "system", "content": history_block})
    messages.append({"role": "user", "content": text})

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


def _build_pending_questions(raw: object) -> list[dict]:
    """Stamp each AI-produced question with a UUID and a creation timestamp.

    Discards entries missing the "question" field. Returns an empty list when
    *raw* is not a non-empty list.
    """
    if not isinstance(raw, list) or not raw:
        return []
    now_iso = datetime.now(tz=timezone.utc).isoformat()
    stamped: list[dict] = []
    for q in raw:
        if not isinstance(q, dict):
            continue
        question = (q.get("question") or "").strip()
        if not question:
            continue
        stamped.append({
            "id": str(uuid.uuid4()),
            "question": question,
            "context": (q.get("context") or "").strip(),
            "created_at": now_iso,
        })
    return stamped


def add_from_text(text: str, voice: bool = False) -> list[tuple[int, dict]]:
    """Extract reminders from *text*, store each in DB, return list of (id, extracted_data).

    *voice* propagates to `extract_reminder` to enable the STT-aware system note.
    """
    items = extract_reminder(text, voice=voice)
    results = []
    for item in items:
        est = item.get("estimated_minutes")
        sf = item.get("screen_free")

        # Build the final metadata blob: predefined + free-form fields, plus
        # any pending_questions we stamp with UUIDs.
        raw_metadata = item.get("metadata")
        metadata: dict = raw_metadata if isinstance(raw_metadata, dict) else {}

        questions = _build_pending_questions(item.get("pending_questions"))
        if questions:
            metadata["pending_questions"] = questions
            # Echo the stamped list back into *item* so the CLI caller (reminder.sh)
            # can surface the questions immediately after creation.
            item["pending_questions"] = questions

        reminder_id = add_reminder(
            title=item.get("title", text[:80]),
            category=item.get("category", "task_short"),
            event_datetime=item.get("event_datetime"),
            full_context=text,
            metadata=metadata if metadata else None,
            recurrence=item.get("recurrence"),
            recurrence_end=item.get("recurrence_end"),
            estimated_minutes=int(est) if est is not None else None,
            screen_free=bool(sf) if sf is not None else None,
        )
        results.append((reminder_id, item))
    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Add a reminder from text")
    parser.add_argument("text", nargs="?", help="Reminder text")
    parser.add_argument("--stdin", action="store_true", help="Read text from stdin")
    parser.add_argument("--voice", action="store_true",
                        help="Mark input as speech-to-text output (raises caution on names/numbers)")
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
        results = add_from_text(input_text, voice=args.voice)
        output = []
        for reminder_id, data in results:
            data["id"] = reminder_id
            output.append(data)
        print(json.dumps(output, ensure_ascii=False))
    except RuntimeError as exc:
        error(str(exc))
        sys.exit(1)

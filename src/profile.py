#!/usr/bin/env python3
"""User profile management for the VoxRefiner reminder system.

Stores durable, generalizable facts about the user so the AI can make
better scheduling and task proposals. The profile is enriched automatically
by a lightweight context AI that runs after conversations.

File location: ~/.local/share/vox-refiner/user_profile.json

Structure
---------
{
  "timezone": "Europe/Paris",   ← machine-readable, top-level
  "language": "fr",             ← machine-readable, top-level
  "sections": {
    "identity":              [...],
    "rhythm":                [...],
    "recurring_constraints": [...],
    "preferences":           [...],
    "future_commitments":    [...],
    "other":                 [...]
  },
  "pending_questions": [
    {
      "id":            "<uuid>",
      "question":      "...",
      "context":       "...",
      "original_text": "...",
      "created_at":    "2026-05-14T10:30:00+00:00"
    }
  ]
}

Public API
----------
    load_profile()                                      -> dict
    save_profile(profile)                               -> None
    update_from_conversation(text, profile=None)        -> dict | None
    resolve_pending_question(qid, answer, profile=None) -> None
    pop_pending_question(profile=None)                  -> dict | None

CLI
---
    python -m src.profile update  "<text>"
    python -m src.profile resolve "<id>" "<answer>"
    python -m src.profile pending
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

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from src.common import SECURITY_BLOCK, call_model, compute_timing, effective_timeout  # noqa: E402
from src.ui_py import warn  # noqa: E402

_MODEL = os.environ.get("REFINE_MODEL_SHORT", "mistral-small-latest")
_MODEL_FALLBACK = "mistral-medium-latest"

_MIN_WORDS = 5

_PROFILE_DIR = Path.home() / ".local" / "share" / "vox-refiner"
_PROFILE_PATH = _PROFILE_DIR / "user_profile.json"

_EMPTY_PROFILE: dict = {
    "timezone": None,
    "language": None,
    "sections": {
        "identity": [],
        "rhythm": [],
        "recurring_constraints": [],
        "preferences": [],
        "future_commitments": [],
        "other": [],
    },
    "pending_questions": [],
}

_SECTIONS = list(_EMPTY_PROFILE["sections"].keys())

# ── System prompts ────────────────────────────────────────────────────────────

_EXTRACT_SYSTEM_PROMPT = (
    "You are a profile manager for a personal assistant.\n"
    "\n"
    "Your task: analyze a user message and determine whether it explicitly reveals\n"
    "durable, generalizable facts about the person to store in their profile.\n"
    "\n"
    "Store a fact ONLY if ALL three conditions are met:\n"
    "  1. Explicitly stated — not inferred or assumed from context\n"
    "  2. About the person themselves — not about a specific one-time task\n"
    "  3. Useful for future scheduling decisions in unrelated conversations\n"
    "\n"
    "Facts can be:\n"
    "  - Permanent (no dates): stable long-term facts\n"
    "  - Time-bounded (include start and end dates): temporary but worth storing\n"
    "\n"
    "Available profile sections:\n"
    "  identity              — location, timezone, language, basic personal info\n"
    "  rhythm                — work hours, sleep patterns, daily/weekly routines\n"
    "  recurring_constraints — fixed regular obligations (meetings, school pickup…)\n"
    "  preferences           — working style, what they avoid or prefer\n"
    "  future_commitments    — upcoming engagements not already in the reminder database\n"
    "  other                 — anything that does not fit the sections above\n"
    "\n"
    "When a message contradicts an existing profile entry:\n"
    "  - Clearly a permanent change  → update the existing entry\n"
    "  - Clearly a temporary change  → add a time-bounded entry alongside\n"
    "  - Ambiguous                   → generate ONE short clarifying question\n"
    "\n"
    "Conservative rules (strictly enforce):\n"
    "  - When in doubt → action must be \"none\"\n"
    "  - Never infer what is not explicitly stated in the message\n"
    "  - Ignore task-specific details (those belong in the reminder database)\n"
    "  - Ignore ephemeral states: \"tired today\", \"busy this afternoon\"\n"
    "  - Never add a fact already present in the profile\n"
    "  - Do not add task content itself (title, date, category) to the profile\n"
    "\n"
    "If timezone or language is detected with confidence, also update the\n"
    "top-level \"timezone\" and \"language\" fields.\n"
    "\n"
    "Output ONLY valid JSON with this exact structure:\n"
    "{\n"
    "  \"action\": \"none\" | \"update\" | \"question\",\n"
    "  \"profile\": <full updated profile object>  (only when action == \"update\"),\n"
    "  \"question\": \"<one short clarifying question>\"  (only when action == \"question\"),\n"
    "  \"question_context\": \"<brief reason for the question>\"  (only when action == \"question\")\n"
    "}\n"
    "\n"
    + SECURITY_BLOCK
)

_RESOLVE_SYSTEM_PROMPT = (
    "You are a profile manager for a personal assistant.\n"
    "\n"
    "A clarifying question was asked after a user message. The user has now answered.\n"
    "Based on the original message and the user's answer, update the profile.\n"
    "\n"
    "Available sections: identity, rhythm, recurring_constraints, preferences,\n"
    "future_commitments, other.\n"
    "\n"
    "Rules:\n"
    "  - Only update what the answer clarifies\n"
    "  - If the answer is still ambiguous or uninformative → action: \"none\"\n"
    "  - Never add a fact already present in the profile\n"
    "\n"
    "Output ONLY valid JSON:\n"
    "{\n"
    "  \"action\": \"none\" | \"update\",\n"
    "  \"profile\": <full updated profile object>  (only when action == \"update\")\n"
    "}\n"
    "\n"
    + SECURITY_BLOCK
)


# ── File management ───────────────────────────────────────────────────────────


def load_profile() -> dict:
    """Return the current profile, or an empty profile if not yet created."""
    if not _PROFILE_PATH.exists():
        return json.loads(json.dumps(_EMPTY_PROFILE))
    try:
        data = json.loads(_PROFILE_PATH.read_text(encoding="utf-8"))
        data.setdefault("timezone", None)
        data.setdefault("language", None)
        data.setdefault("sections", {})
        for section in _SECTIONS:
            data["sections"].setdefault(section, [])
        data.setdefault("pending_questions", [])
        return data
    except (json.JSONDecodeError, OSError):
        return json.loads(json.dumps(_EMPTY_PROFILE))


def save_profile(profile: dict) -> None:
    """Write profile to disk, creating parent directories as needed."""
    _PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    _PROFILE_PATH.write_text(
        json.dumps(profile, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ── AI call ───────────────────────────────────────────────────────────────────


def _call_ai(messages: list[dict]) -> dict | None:
    """Call the context AI. Returns parsed JSON dict, or None on failure."""
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        return None

    word_count = sum(len(m["content"].split()) for m in messages)
    base_timeout, retry_delay = compute_timing(word_count, background=True)

    for model in (_MODEL, _MODEL_FALLBACK):
        try:
            timeout = effective_timeout(base_timeout, model)
            raw = call_model(
                model, messages, api_key,
                timeout=timeout,
                retry_delay=retry_delay,
                retries=1,
            )
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
                if raw.endswith("```"):
                    raw = raw[:-3].rstrip()
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            if status in (429, 500, 502, 503):
                warn(f"Profile AI {model} ({status}) — switching…")
                continue
            raise
        except requests.RequestException:
            warn(f"Profile AI {model} unreachable, switching…")
            continue

    return None


# ── Public API ────────────────────────────────────────────────────────────────


def update_from_conversation(
    text: str,
    profile: dict | None = None,
) -> dict | None:
    """Analyze *text* and update the profile if warranted.

    Returns the pending question entry (dict with 'id' and 'question') if
    a clarifying question needs to be asked, or None for silent updates.

    The question is also written to pending_questions so it survives if the
    caller cannot surface it immediately.
    """
    if len(text.split()) < _MIN_WORDS:
        return None

    if profile is None:
        profile = load_profile()

    messages = [
        {"role": "system", "content": _EXTRACT_SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"Current profile:\n{json.dumps(profile, ensure_ascii=False, indent=2)}\n\n"
            f"User message:\n{text}"
        )},
    ]

    result = _call_ai(messages)
    if result is None:
        return None

    action = result.get("action", "none")

    if action == "update" and "profile" in result:
        updated = result["profile"]
        # Preserve pending questions — AI does not know about them
        updated["pending_questions"] = profile.get("pending_questions", [])
        save_profile(updated)
        return None

    if action == "question":
        question = result.get("question", "").strip()
        context = result.get("question_context", "").strip()
        if question:
            entry = {
                "id": str(uuid.uuid4()),
                "question": question,
                "context": context,
                "original_text": text,
                "created_at": datetime.now(tz=timezone.utc).isoformat(),
            }
            profile.setdefault("pending_questions", [])
            profile["pending_questions"].append(entry)
            save_profile(profile)
            return entry

    return None


def resolve_pending_question(
    question_id: str,
    user_answer: str,
    profile: dict | None = None,
) -> None:
    """Process the user's answer to a pending question and update the profile.

    The question is removed from pending_questions regardless of outcome.
    """
    if profile is None:
        profile = load_profile()

    pending = profile.get("pending_questions", [])
    entry = next((q for q in pending if q["id"] == question_id), None)

    # Remove question before any write so it's gone even if the AI call fails
    profile["pending_questions"] = [q for q in pending if q["id"] != question_id]

    if entry is None:
        save_profile(profile)
        return

    messages = [
        {"role": "system", "content": _RESOLVE_SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"Current profile:\n{json.dumps(profile, ensure_ascii=False, indent=2)}\n\n"
            f"Original user message: {entry['original_text']}\n"
            f"Question asked: {entry['question']}\n"
            f"User's answer: {user_answer}"
        )},
    ]

    result = _call_ai(messages)

    if result and result.get("action") == "update" and "profile" in result:
        updated = result["profile"]
        # Re-attach remaining pending questions (AI returns profile without them)
        updated["pending_questions"] = profile["pending_questions"]
        save_profile(updated)
    else:
        save_profile(profile)


def pop_pending_question(profile: dict | None = None) -> dict | None:
    """Return the oldest pending question entry, or None if the queue is empty."""
    if profile is None:
        profile = load_profile()
    questions = profile.get("pending_questions", [])
    return questions[0] if questions else None


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="User profile context manager")
    sub = parser.add_subparsers(dest="cmd")

    p_update = sub.add_parser("update", help="Analyze text and update profile")
    p_update.add_argument("text", help="User message to analyze")

    p_resolve = sub.add_parser("resolve", help="Resolve a pending question")
    p_resolve.add_argument("question_id", help="UUID of the pending question")
    p_resolve.add_argument("answer", help="User's answer")

    p_pending = sub.add_parser("pending", help="Print first pending question")

    args = parser.parse_args()

    if args.cmd == "update":
        question_entry = update_from_conversation(args.text)
        if question_entry:
            print(json.dumps({
                "id": question_entry["id"],
                "question": question_entry["question"],
            }, ensure_ascii=False))

    elif args.cmd == "resolve":
        resolve_pending_question(args.question_id, args.answer)

    elif args.cmd == "pending":
        entry = pop_pending_question()
        if entry:
            print(json.dumps({
                "id": entry["id"],
                "question": entry["question"],
            }, ensure_ascii=False))

    else:
        parser.print_help(sys.stderr)
        sys.exit(1)

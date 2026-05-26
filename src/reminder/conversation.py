#!/usr/bin/env python3
"""Multi-turn reminder refinement with profile awareness + web search.

After `src.reminder.add` has performed the initial single-shot extraction
and stored the reminder, this module runs a conversation to enrich it:

  - Mistral asks ONE question at a time (up to MAX_QUESTIONS turns).
  - Each turn sees the full message history, the user profile (durable
    facts) and any web-search results gathered so far.
  - Mistral may request a web search at any turn — the search runs
    transparently inside the same step (the bash side only ever sees
    "ask" or "done").

State is persisted in /tmp/vox-reminder-conv-<id>.json so the bash CLI can
drive the loop turn by turn (each call is one Mistral round-trip + at
most one web search). Sessions expire after 30 min of inactivity.

Public API
----------
    start(reminder_id, original_text, initial_metadata) -> dict
    answer(session_id, user_text)                       -> dict
    finalize(session_id)                                -> dict

CLI
---
    python -m src.reminder.conversation start <reminder_id> \
        --text "<original>" --metadata '<json>'
    python -m src.reminder.conversation answer <session_id> "<user reply>"
    python -m src.reminder.conversation finalize <session_id>
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
from src.profile import load_profile  # noqa: E402
from src.reminder.db import _db, search_history, update_status  # noqa: E402
from src.ui_py import warn  # noqa: E402

_MODEL = os.environ.get("REFINE_MODEL_SHORT", "mistral-small-latest")
_MODEL_FALLBACK = os.environ.get("REFINE_MODEL_SHORT_FALLBACK", "mistral-medium-latest")

_SESSION_DIR = Path("/tmp")
_SESSION_PREFIX = "vox-reminder-conv-"
_SESSION_TTL_SECONDS = 30 * 60        # sessions die after 30 min of inactivity
_MAX_QUESTIONS = 5                     # absolute cap on user-facing questions
_MAX_WEB_SEARCHES_PER_TURN = 2         # safety net against AI loops
_MAX_WEB_SEARCHES_PER_SESSION = 4
_MAX_ADVANCE_ITERATIONS = 12           # hard ceiling on the inner loop per call

_VOICE_WARNING_INIT = (
    "NOTE: the user request below was produced by speech-to-text (the user\n"
    "dictated it; they did not type it). Speech-to-text frequently mis-hears:\n"
    "  - proper nouns (people's names, doctors, business names, street names)\n"
    "  - numbers (phone numbers, dates, hours, addresses)\n"
    "  - homophones and rare words\n"
    "Apply extra caution: when you need to act on a critical identifier\n"
    "(name for a web search, phone, exact address) AND the user did not\n"
    "spell it letter-by-letter, ASK the user to spell or confirm it before\n"
    "moving on. If they spell it, that spelling is canonical and overrides\n"
    "any earlier phonetic version — never concatenate the two forms."
)

_VOICE_WARNING_ANSWER = (
    "(System note: the user's reply that follows came from speech-to-text — "
    "apply the same caution about possible mishearings of names, numbers and "
    "dates as for the initial request.)"
)

_SEARCH_SOURCE_PRIORITY = (
    "[Source priority: when both Google Business Profile / Google Maps data "
    "(identifiable by 'Google Maps', 'fiche établissement Google', 'maps.google.com') "
    "and third-party booking directories (mondocteur.fr, doctolib.fr, etc.) are present, "
    "use the Google source as authoritative. "
    "Always present the hours you found to the user and indicate the source — "
    "then proceed to help them schedule. "
    "You are a text assistant: you cannot verify information by phone call or any "
    "real-world action, so never offer to do so.]"
)


def _pomodoro_context_note() -> str:
    """Return a brief system note about the Pomodoro timer if it is enabled, else ''."""
    try:
        from src.reminder.pomodoro_config import load as _load_cfg
        cfg = _load_cfg()
        if not cfg.enabled:
            return ""
        return (
            f"Pomodoro timer context: the timer is active — "
            f"work={cfg.work_minutes} min / break={cfg.break_default} min "
            f"(range {cfg.break_min}–{cfg.break_max} min). "
            "Tasks with screen_free=true in metadata are automatically offered "
            "to the user during Pomodoro breaks."
        )
    except Exception:
        return ""


# ── Prompt ───────────────────────────────────────────────────────────────────


def _build_system_prompt() -> str:
    return (
        "You are a personal agenda assistant in a multi-turn conversation with\n"
        "the user to refine a single reminder that was just created. Each turn\n"
        "you see the full conversation so far and decide ONE next action.\n"
        "\n"
        "You are a text-only assistant: you can ask questions and trigger web\n"
        "searches. You CANNOT perform any real-world action (phone calls,\n"
        "bookings, emails, etc.) — never offer to do so.\n"
        "\n"
        "Output exactly ONE JSON object per turn:\n"
        "{\n"
        '  "metadata": { ... full updated scheduling metadata for the reminder ... },\n'
        '  "action":   "ask" | "web_search" | "done",\n'
        '  "question": "<the question to ask>",  (only when action == "ask")\n'
        '  "context":  "<short reason>",         (only when action == "ask")\n'
        '  "web_search_query": "<query>"         (only when action == "web_search")\n'
        "}\n"
        "\n"
        "Conversation rules (strict):\n"
        f"  - Ask AT MOST {_MAX_QUESTIONS} questions in total across the conversation.\n"
        "  - Ask ONE question per turn, the most blocking one first\n"
        "    (location, contact info, missing date/time) before secondary preferences.\n"
        "  - Do NOT ask for information that is already in the user profile (see below).\n"
        "  - Make NO assumptions about what the user can or cannot do. If a\n"
        "    lifestyle or availability fact relevant to scheduling is absent from\n"
        "    the profile — whether they can act on a task during work hours, leave\n"
        "    home, how long a task can last, any personal constraint — ask once.\n"
        "    Phrase the question so the answer remains useful for all future\n"
        "    reminders of the same kind.\n"
        "  - Do NOT ask the user to confirm something they explicitly stated in this\n"
        "    conversation (e.g. don't ask 'Toujours Dr X?' if they just named Dr X).\n"
        "  - For tasks involving a professional or commercial entity in an unknown\n"
        "    city, ASK FOR THE CITY FIRST. Only trigger a web search once you have\n"
        "    enough info to make it useful.\n"
        "  - When the task involves contacting or visiting a real entity (person,\n"
        "    business, office), search for their hours and contact details BEFORE\n"
        "    asking about scheduling preference. Once you have the information,\n"
        "    present it together with the scheduling question in a single combined\n"
        "    message (e.g. \"The dentist is open Mon–Fri 9h–12h and 14h–18h.\n"
        "    Would you like a reminder during your Pomodoro breaks, or a specific\n"
        "    time?\").\n"
        "  - To trigger a web search, return action=\"web_search\" with a precise\n"
        "    web_search_query. The system runs the search and feeds the result back\n"
        "    into the conversation, then you continue.\n"
        "    For business hours or address queries, append \"fiche établissement Google\"\n"
        "    to the query (e.g. \"Dr Horel Lécousse dentiste horaires fiche établissement\n"
        "    Google\") to surface the Google Business Profile, which is the most\n"
        "    reliable source.\n"
        "  - After a web search returns useful info, you MUST:\n"
        "      1. Report the relevant facts to the user in your next question\n"
        "         (opening hours, address, closed days, …).\n"
        "      2. Then ask the user to choose a moment that is INSIDE the opening\n"
        "         hours AND compatible with their profile (working hours,\n"
        "         availability). NEVER suggest a time when the business is closed.\n"
        "      3. If the user's profile makes some windows obviously good or bad,\n"
        "         say so (e.g. \"tu es libre entre 12h et 14h mais le cabinet est\n"
        "         fermé à ce moment — soit avant 12h, soit après 14h conviennent\").\n"
        "      4. When the result contains data from multiple sources, prefer the\n"
        "         Google Business Profile (identifiable as \"Google Maps\", \"fiche\n"
        "         établissement Google\", or a maps.google.com URL) over third-party\n"
        "         booking directories (mondocteur.fr, doctolib.fr, etc.). In all\n"
        "         cases, present the hours you found and indicate the source —\n"
        "         then proceed to help the user schedule.\n"
        "  - When you have enough info to schedule the reminder well, return\n"
        "    action=\"done\".\n"
        "  - The \"metadata\" field MUST always reflect the full current state of\n"
        "    the reminder's metadata. Merge with what was already extracted — do NOT\n"
        "    drop previously stored keys. Add or update keys as you learn new info\n"
        "    (e.g. city, business_info, callable_hours, requires_daylight, etc.).\n"
        "  - Do NOT include conversation-tracking fields in metadata: never write\n"
        "    \"pending_questions\" or \"answers\" — these are managed by the system,\n"
        "    not by you. Your follow-up questions go in the top-level \"question\"\n"
        "    field via action=\"ask\".\n"
        "  - Spelled names: if the user or the original request contains a letter\n"
        "    sequence (\"H-O-R-E-L\", \"H O R E L\", \"H comme Henri, O comme Oscar…\"),\n"
        "    treat it as the CANONICAL spelling of the preceding proper noun. The\n"
        "    user is correcting a voice-transcription mishearing. REPLACE the prior\n"
        "    phonetic version in the metadata — do NOT concatenate the two forms.\n"
        "    If the user has not yet spelled an ambiguous name and you suspect a\n"
        "    mishearing risk (e.g. a doctor's surname needed for a web lookup),\n"
        "    ask them to spell it.\n"
        "\n"
        "Screen-free task scheduling (Pomodoro breaks):\n"
        "  The app has a Pomodoro timer that can offer screen-free tasks to the user\n"
        "  during breaks. In the metadata, screen_free=true means the task will be\n"
        "  proposed automatically during a Pomodoro break. Follow these rules:\n"
        "  - If the user EXPLICITLY mentions Pomodoro breaks as their preferred time\n"
        "    (\"pendant les pauses Pomodoro\", \"during my breaks\", \"entre deux sessions\n"
        "    de travail\", or equivalent) → set screen_free=true in metadata.\n"
        "    If they ALSO mention a time-of-day qualifier (\"en fin de journée\",\n"
        "    \"le matin\", \"l'après-midi\", \"après Xh\", etc.), ALSO set\n"
        "    time_constraint: {\"earliest_hour\": N, \"latest_hour\": N} where N\n"
        "    is an integer 0–23. Typical mappings:\n"
        "      \"fin de journée\" / \"en soirée\"  → {\"earliest_hour\": 17, \"latest_hour\": 20}\n"
        "      \"le matin\"                       → {\"earliest_hour\": 8,  \"latest_hour\": 12}\n"
        "      \"l'après-midi\"                   → {\"earliest_hour\": 13, \"latest_hour\": 17}\n"
        "      \"après 15h\"                      → {\"earliest_hour\": 15, \"latest_hour\": 20}\n"
        "    For SPLIT schedules (e.g. \"pendant mes heures de travail\" when the\n"
        "    profile shows two windows such as 8h–12h and 14h–18h), use a list:\n"
        "      [{\"earliest_hour\": 8, \"latest_hour\": 12},\n"
        "       {\"earliest_hour\": 14, \"latest_hour\": 18}]\n"
        "    The task passes the filter when the current hour falls in ANY window.\n"
        "    Return action=\"done\" — no extra question needed.\n"
        "  - If the user states ANY explicit time preference (\"le matin\", \"le soir\",\n"
        "    a specific hour, \"avant le travail\", \"après le travail\", a day of the\n"
        "    week, etc.) → respect that preference. Do NOT redirect to Pomodoro.\n"
        "    Set event_datetime or time_constraint accordingly.\n"
        "  - If the task is physical/screen-free but the user has NOT expressed any\n"
        "    timing preference yet → first complete any needed web search (hours,\n"
        "    contact info for a business or professional), then ask ONE combined\n"
        "    question: present what you found and offer the choice between a\n"
        "    Pomodoro break or a specific time. Act on their answer per the rules\n"
        "    above.\n"
        "  - NEVER assume Pomodoro scheduling just because a task is physical. Only\n"
        "    apply screen_free=true when the user explicitly requests it or confirms\n"
        "    the Pomodoro option.\n"
        "\n"
        "Speak the user's language (inferred from the original request).\n"
        "Output ONLY the JSON object — no markdown, no prose, no code fence.\n"
        "\n"
        + SECURITY_BLOCK
    )


def _profile_summary(profile: dict) -> str:
    """Compact bullet-list of durable user facts, or empty if nothing useful."""
    sections = profile.get("sections") or {}
    lines: list[str] = []
    if profile.get("timezone"):
        lines.append(f"- Timezone: {profile['timezone']}")
    if profile.get("language"):
        lines.append(f"- Language: {profile['language']}")
    for key, label in (
        ("rhythm", "Rhythm"),
        ("recurring_constraints", "Recurring constraints"),
        ("preferences", "Preferences"),
        ("future_commitments", "Future commitments"),
    ):
        items = [
            i for i in (sections.get(key) or [])
            if isinstance(i, str) and i.strip()
        ]
        if items:
            lines.append(f"- {label}:")
            lines.extend(f"  • {i}" for i in items)
    if not lines:
        return ""
    return "USER PROFILE (durable facts; do not ask the user to repeat these):\n" + "\n".join(lines)


def _history_block(text: str) -> str:
    matches = search_history(text, limit=5)
    if not matches:
        return ""
    lines = ["Related past reminders (most recent first), for context only:"]
    for m in matches:
        when = (m.get("event_datetime") or m.get("created_at") or "")
        when_short = when.split(" ")[0] if when else "?"
        lines.append(
            f"  - \"{m['title']}\" ({m.get('category') or '?'})"
            f" on {when_short} — status: {m.get('status') or '?'}"
        )
    return "\n".join(lines)


def _initial_user_message(text: str, metadata: dict, profile: dict) -> str:
    parts = [f"User request:\n{text}"]
    if metadata:
        parts.append(
            "Already extracted metadata (start from this — merge, do not lose keys):\n"
            + json.dumps(metadata, ensure_ascii=False, indent=2)
        )
    profile_block = _profile_summary(profile)
    if profile_block:
        parts.append(profile_block)
    history = _history_block(text)
    if history:
        parts.append(history)
    return "\n\n".join(parts)


# ── Mistral wrapper ──────────────────────────────────────────────────────────


def _parse_ai_response(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3].rstrip()
    return json.loads(raw)


def _call_ai(messages: list[dict]) -> dict | None:
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        return None
    word_count = sum(len(m["content"].split()) for m in messages)
    base_timeout, retry_delay = compute_timing(word_count)
    for model in (_MODEL, _MODEL_FALLBACK):
        try:
            timeout = effective_timeout(base_timeout, model)
            raw = call_model(
                model, messages, api_key,
                timeout=timeout, retry_delay=retry_delay, retries=2,
            )
            return _parse_ai_response(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            if status in (429, 500, 502, 503):
                warn(f"Conversation AI {model} ({status}) — switching…")
                continue
            raise
        except requests.RequestException:
            warn(f"Conversation AI {model} unreachable — switching…")
            continue
    return None


# ── Web search hook ──────────────────────────────────────────────────────────


def _do_web_search(query: str) -> str:
    """Best-effort web search via src.search. Returns the answer text or ''."""
    if not query.strip():
        return ""
    try:
        from src import search as _search
        return _search.search(query)
    except Exception as exc:  # noqa: BLE001 — never crash the conversation
        warn(f"Web search failed for {query!r}: {exc}")
        return ""


# ── Session persistence ─────────────────────────────────────────────────────


def _session_path(session_id: str) -> Path:
    return _SESSION_DIR / f"{_SESSION_PREFIX}{session_id}.json"


def _save_session(state: dict) -> None:
    state["updated_at"] = datetime.now(tz=timezone.utc).isoformat()
    _session_path(state["session_id"]).write_text(
        json.dumps(state, ensure_ascii=False), encoding="utf-8",
    )


def _load_session(session_id: str) -> dict | None:
    path = _session_path(session_id)
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    timestamp = state.get("updated_at") or state.get("created_at")
    if not timestamp:
        return None
    try:
        dt = datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    if (datetime.now(tz=timezone.utc) - dt).total_seconds() > _SESSION_TTL_SECONDS:
        path.unlink(missing_ok=True)
        return None
    return state


def _delete_session(session_id: str) -> None:
    _session_path(session_id).unlink(missing_ok=True)


def _clear_db_pending_questions(reminder_id: int) -> None:
    """Strip `pending_questions` from the reminder's stored metadata.

    Called at the start of every conversation so the legacy
    `_task_ask_next_pending` flow does not resurface stale questions if this
    conversation is interrupted — the conversation supersedes that mechanism.
    """
    with _db() as conn:
        row = conn.execute(
            "SELECT metadata FROM reminders WHERE id = ?", (reminder_id,)
        ).fetchone()
        if row is None or not row["metadata"]:
            return
        try:
            meta = json.loads(row["metadata"])
        except (json.JSONDecodeError, TypeError):
            return
        if not isinstance(meta, dict) or "pending_questions" not in meta:
            return
        meta.pop("pending_questions", None)
        conn.execute(
            "UPDATE reminders SET metadata = ? WHERE id = ?",
            (json.dumps(meta, ensure_ascii=False), reminder_id),
        )


# ── Conversation engine ──────────────────────────────────────────────────────


def _advance(state: dict) -> dict:
    """Run AI loop until the next user question or 'done'. Mutates and saves state.

    Returns the bash-facing result: { action, question?, context?, session_id }.
    """
    iterations = 0
    while True:
        iterations += 1
        if iterations > _MAX_ADVANCE_ITERATIONS:
            # Hard safety net: should never trigger in practice; if it does,
            # there's a logic bug somewhere — fail closed by ending the turn.
            warn("Conversation _advance hit the iteration cap — forcing done.")
            state["finished"] = True
            _save_session(state)
            return {"action": "done", "session_id": state["session_id"]}
        ai = _call_ai(state["messages"])
        if ai is None or not isinstance(ai, dict):
            # AI unavailable or response malformed — gracefully end the conversation.
            state["finished"] = True
            _save_session(state)
            return {"action": "done", "session_id": state["session_id"]}

        # Update metadata (full replacement allowed; the AI is told to merge itself)
        new_meta = ai.get("metadata")
        if isinstance(new_meta, dict):
            state["metadata"] = new_meta

        # Always record the assistant turn so the AI sees its own history
        state["messages"].append({
            "role": "assistant",
            "content": json.dumps(ai, ensure_ascii=False),
        })

        action = ai.get("action", "done")

        if action == "ask":
            question = (ai.get("question") or "").strip()
            if not question or state["questions_asked"] >= _MAX_QUESTIONS:
                state["finished"] = True
                _save_session(state)
                return {"action": "done", "session_id": state["session_id"]}
            state["questions_asked"] += 1
            state["pending_question"] = {
                "id": str(uuid.uuid4()),
                "question": question,
                "context": (ai.get("context") or "").strip(),
            }
            _save_session(state)
            return {
                "action": "ask",
                "session_id": state["session_id"],
                "question": question,
                "context": state["pending_question"]["context"],
            }

        if action == "web_search":
            # Session-wide budget: hard stop. Return done immediately.
            if state["web_searches_total"] >= _MAX_WEB_SEARCHES_PER_SESSION:
                state["finished"] = True
                _save_session(state)
                return {"action": "done", "session_id": state["session_id"]}
            # Per-turn limit: nudge the AI once; if it still asks for a search,
            # we end the turn rather than risk a tight loop.
            if state["web_searches_this_turn"] >= _MAX_WEB_SEARCHES_PER_TURN:
                if state.get("turn_nudge_sent"):
                    state["finished"] = True
                    _save_session(state)
                    return {"action": "done", "session_id": state["session_id"]}
                state["turn_nudge_sent"] = True
                state["messages"].append({
                    "role": "user",
                    "content": "(System: web-search limit for this turn reached. "
                               "Use action=\"ask\" or action=\"done\" — do not "
                               "request more searches.)",
                })
                continue
            query = (ai.get("web_search_query") or "").strip()
            if not query:
                state["finished"] = True
                _save_session(state)
                return {"action": "done", "session_id": state["session_id"]}
            # Append "fiche établissement Google" (French GMB terminology) to
            # help Perplexity surface the Google Business Profile rather than
            # third-party booking directories (mondocteur.fr, etc.).
            if "fiche établissement" not in query.lower() and "google maps" not in query.lower():
                query = query + " fiche établissement Google"
            state["web_searches_this_turn"] += 1
            state["web_searches_total"] += 1
            result_text = _do_web_search(query)
            state.setdefault("web_search_log", []).append({
                "query": query,
                "result": result_text,
                "at": datetime.now(tz=timezone.utc).isoformat(),
            })
            state["messages"].append({
                "role": "user",
                "content": (
                    f"Search result for {query!r}:\n\n"
                    f"{_SEARCH_SOURCE_PRIORITY}\n\n"
                    f"{result_text or '(no result)'}"
                ),
            })
            continue

        # action == "done" or unknown
        state["finished"] = True
        _save_session(state)
        return {"action": "done", "session_id": state["session_id"]}


# ── Public API ───────────────────────────────────────────────────────────────


def start(reminder_id: int, original_text: str, initial_metadata: dict,
          voice: bool = False) -> dict:
    """Open a new conversational session.

    When *voice* is True, the original user request came from speech-to-text;
    inject a system note warning the AI about possible mishearings.

    Returns the first bash-facing event: an "ask" with a question, or "done"
    if Mistral decides no follow-up is needed (or is unreachable).
    """
    profile = load_profile()
    # Drop any pending_questions emitted by the single-shot extractor — the
    # conversation supersedes that mechanism (both in the DB and in the
    # metadata we hand off to the AI).
    clean_metadata = dict(initial_metadata or {})
    clean_metadata.pop("pending_questions", None)
    _clear_db_pending_questions(reminder_id)
    session_id = uuid.uuid4().hex
    now = datetime.now(tz=timezone.utc).isoformat()
    messages: list[dict] = [
        {"role": "system", "content": _build_system_prompt()},
    ]
    if voice:
        messages.append({"role": "system", "content": _VOICE_WARNING_INIT})
    pomo_note = _pomodoro_context_note()
    if pomo_note:
        messages.append({"role": "system", "content": pomo_note})
    messages.append({
        "role": "user",
        "content": _initial_user_message(original_text, clean_metadata, profile),
    })
    state = {
        "session_id": session_id,
        "reminder_id": reminder_id,
        "original_text": original_text,
        "metadata": clean_metadata,
        "questions_asked": 0,
        "answers": [],
        "web_searches_this_turn": 0,
        "web_searches_total": 0,
        "web_search_log": [],
        "pending_question": None,
        "finished": False,
        "created_at": now,
        "updated_at": now,
        "messages": messages,
    }
    state["web_searches_this_turn"] = 0  # reset per turn
    update_status(reminder_id, "pending_refinement")
    return _advance(state)


def answer(session_id: str, user_text: str, voice: bool = False) -> dict:
    """Provide an answer to the pending question; advance the conversation.

    When *voice* is True, the user dictated this reply via speech-to-text;
    prepend a system note so the AI applies extra caution on names/numbers.
    """
    state = _load_session(session_id)
    if state is None:
        return {"action": "done", "session_id": session_id}
    pending = state.get("pending_question")
    if pending:
        state.setdefault("answers", []).append({
            "id": pending["id"],
            "question": pending["question"],
            "context": pending.get("context", ""),
            "answer": user_text,
            "answered_at": datetime.now(tz=timezone.utc).isoformat(),
        })
        state["pending_question"] = None
    if voice:
        state["messages"].append({
            "role": "system", "content": _VOICE_WARNING_ANSWER,
        })
    state["messages"].append({"role": "user", "content": user_text})
    state["web_searches_this_turn"] = 0
    state.pop("turn_nudge_sent", None)
    return _advance(state)


def finalize(session_id: str) -> dict:
    """Persist the final metadata + answers to the DB and discard the session."""
    state = _load_session(session_id)
    if state is None:
        return {"reminder_id": None}
    reminder_id = state["reminder_id"]
    final_metadata = state.get("metadata") or {}
    answers = state.get("answers") or []

    with _db() as conn:
        row = conn.execute(
            "SELECT metadata FROM reminders WHERE id = ?", (reminder_id,),
        ).fetchone()
        existing = {}
        if row and row["metadata"]:
            try:
                parsed = json.loads(row["metadata"])
                existing = parsed if isinstance(parsed, dict) else {}
            except json.JSONDecodeError:
                existing = {}
        merged = {**existing, **final_metadata}
        existing_answers = merged.get("answers")
        existing_answers = existing_answers if isinstance(existing_answers, list) else []
        merged["answers"] = existing_answers + answers
        # Once the conversation is closed, pending_questions are obsolete for the
        # creation flow — the AI either asked them (now in answers) or decided
        # they were not blocking. Keep any older pending_questions that pre-existed.
        conn.execute(
            "UPDATE reminders SET metadata = ? WHERE id = ?",
            (json.dumps(merged, ensure_ascii=False), reminder_id),
        )
    update_status(reminder_id, "pending")
    _delete_session(session_id)
    answers_text = " ".join(
        f"{a.get('question', '')} {a.get('answer', '')}".strip()
        for a in answers
        if a.get("answer", "").strip()
    ).strip()
    return {
        "reminder_id": reminder_id,
        "questions_asked": state.get("questions_asked", 0),
        "answers_text": answers_text,
    }


# ── CLI ──────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Conversational reminder refinement")
    sub = parser.add_subparsers(dest="cmd")

    p_start = sub.add_parser("start", help="Begin a new conversation")
    p_start.add_argument("reminder_id", type=int)
    p_start.add_argument("--text", required=True, help="Original user request")
    p_start.add_argument("--metadata", default="{}", help="Initial metadata as JSON")
    p_start.add_argument("--voice", action="store_true",
                         help="Mark the original request as speech-to-text output")

    p_ans = sub.add_parser("answer", help="Submit the user's answer to the pending question")
    p_ans.add_argument("session_id")
    p_ans.add_argument("text")
    p_ans.add_argument("--voice", action="store_true",
                       help="Mark the user's reply as speech-to-text output")

    p_fin = sub.add_parser("finalize", help="Persist results and close the session")
    p_fin.add_argument("session_id")

    args = parser.parse_args()
    if args.cmd == "start":
        try:
            meta = json.loads(args.metadata) if args.metadata else {}
        except json.JSONDecodeError:
            meta = {}
        result = start(
            args.reminder_id, args.text,
            meta if isinstance(meta, dict) else {},
            voice=args.voice,
        )
        print(json.dumps(result, ensure_ascii=False))
    elif args.cmd == "answer":
        print(json.dumps(
            answer(args.session_id, args.text, voice=args.voice),
            ensure_ascii=False,
        ))
    elif args.cmd == "finalize":
        print(json.dumps(finalize(args.session_id), ensure_ascii=False))
    else:
        parser.print_help(sys.stderr)
        sys.exit(1)

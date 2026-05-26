"""Unit tests for src/reminder/conversation.py.

Mocks:
  - call_model (Mistral)        — no network
  - src.search.search           — no Perplexity/Grok call
  - profile.load_profile        — controlled profile snippets
  - DB and session files        — redirected to tmp_path
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

import src.reminder.db as rdb


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setattr(rdb, "_DB_DIR", tmp_path)
    monkeypatch.setattr(rdb, "_DB_PATH", tmp_path / "reminders.db")
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    # Force a re-import so any module-level model lookups read our test env
    sys.modules.pop("src.reminder.conversation", None)
    import src.reminder.conversation as conv
    monkeypatch.setattr(conv, "_SESSION_DIR", tmp_path / "sessions")
    (tmp_path / "sessions").mkdir()
    yield conv


def _seed_reminder(metadata: dict | None = None, **kw) -> int:
    defaults = dict(title="Prendre rdv dentiste", category="task_short",
                    full_context="prendre un rdv chez le dentiste")
    defaults.update(kw)
    return rdb.add_reminder(metadata=metadata, **defaults)


def _meta_of(reminder_id: int) -> dict:
    with rdb._db() as conn:
        row = conn.execute(
            "SELECT metadata FROM reminders WHERE id = ?", (reminder_id,)
        ).fetchone()
    return json.loads(row["metadata"]) if row and row["metadata"] else {}


def _ai_reply(*payloads):
    """Return a side_effect that returns each payload as a JSON string in sequence."""
    iter_payloads = iter(payloads)
    def _next(*args, **kwargs):
        return json.dumps(next(iter_payloads), ensure_ascii=False)
    return _next


# ── start / answer / done ────────────────────────────────────────────────────


class TestStartAsk:
    def test_first_ai_call_returns_question(self, isolated_env):
        conv = isolated_env
        rid = _seed_reminder()
        with patch.object(conv, "call_model", side_effect=_ai_reply({
            "metadata": {"person": "Dr Horel"},
            "action": "ask",
            "question": "Dans quelle ville ?",
            "context": "City needed for any later lookup.",
        })):
            result = conv.start(rid, "rdv dentiste Dr Horel", {})
        assert result["action"] == "ask"
        assert result["question"] == "Dans quelle ville ?"
        assert result["session_id"]

    def test_first_ai_call_can_immediately_be_done(self, isolated_env):
        conv = isolated_env
        rid = _seed_reminder()
        with patch.object(conv, "call_model",
                          side_effect=_ai_reply({"metadata": {}, "action": "done"})):
            result = conv.start(rid, "Tondre le gazon", {})
        assert result["action"] == "done"

    def test_metadata_updated_in_session_after_start(self, isolated_env):
        conv = isolated_env
        rid = _seed_reminder()
        with patch.object(conv, "call_model", side_effect=_ai_reply({
            "metadata": {"person": "Dr Horel", "location": "Quimper"},
            "action": "ask",
            "question": "Quel jour ?",
        })):
            result = conv.start(rid, "rdv dentiste", {})
        state = conv._load_session(result["session_id"])
        assert state["metadata"]["person"] == "Dr Horel"
        assert state["metadata"]["location"] == "Quimper"

    def test_start_clears_legacy_pending_questions_from_db(self, isolated_env):
        """The conversation supersedes static pending_questions: wipe them at start."""
        conv = isolated_env
        rid = _seed_reminder(metadata={
            "person": "Dr Horel",
            "pending_questions": [
                {"id": "old-1", "question": "Toujours Dr Horel ?", "context": ""},
            ],
        })
        with patch.object(conv, "call_model", side_effect=_ai_reply({
            "metadata": {"person": "Dr Horel"},
            "action": "done",
        })):
            conv.start(rid, "rdv dentiste Dr Horel", {})
        # DB: pending_questions removed, other keys preserved
        meta = _meta_of(rid)
        assert "pending_questions" not in meta
        assert meta.get("person") == "Dr Horel"

    def test_start_strips_pending_questions_before_ai_sees_them(self, isolated_env):
        """The AI must never see the legacy pending_questions in the seed metadata —
        otherwise it might replay them instead of asking smarter follow-ups."""
        conv = isolated_env
        rid = _seed_reminder()
        captured: list[list[dict]] = []

        def fake(model, messages, api_key, **kw):
            captured.append([m.copy() for m in messages])
            return json.dumps({"metadata": {}, "action": "done"})

        sentinel = "ZZZ_legacy_pending_marker_ZZZ"
        with patch.object(conv, "call_model", side_effect=fake):
            conv.start(rid, "test", {
                "person": "Dr X",
                "pending_questions": [
                    {"id": "x", "question": sentinel, "context": ""},
                ],
            })
        seed_msg = "\n".join(m["content"] for m in captured[0])
        assert sentinel not in seed_msg
        assert "Dr X" in seed_msg   # entity itself is still passed


class TestAnswer:
    def test_answer_advances_to_next_question(self, isolated_env):
        conv = isolated_env
        rid = _seed_reminder()
        with patch.object(conv, "call_model", side_effect=_ai_reply(
            {"metadata": {}, "action": "ask", "question": "Quelle ville ?", "context": ""},
            {"metadata": {"location": "Quimper"}, "action": "ask",
             "question": "Tu peux appeler entre 12h et 14h ?", "context": ""},
        )):
            first = conv.start(rid, "rdv dentiste", {})
            second = conv.answer(first["session_id"], "Quimper")
        assert second["action"] == "ask"
        assert "appeler" in second["question"]

    def test_answer_recorded_in_session(self, isolated_env):
        conv = isolated_env
        rid = _seed_reminder()
        with patch.object(conv, "call_model", side_effect=_ai_reply(
            {"metadata": {}, "action": "ask", "question": "Quelle ville ?", "context": ""},
            {"metadata": {"location": "Quimper"}, "action": "done"},
        )):
            first = conv.start(rid, "rdv dentiste", {})
            conv.answer(first["session_id"], "Quimper")
        state = conv._load_session(first["session_id"])
        assert state is not None
        assert len(state["answers"]) == 1
        assert state["answers"][0]["answer"] == "Quimper"
        assert state["answers"][0]["question"] == "Quelle ville ?"
        assert "answered_at" in state["answers"][0]

    def test_answer_on_unknown_session_returns_done(self, isolated_env):
        conv = isolated_env
        result = conv.answer("nonexistent-id", "anything")
        assert result["action"] == "done"


class TestQuestionCap:
    def test_stops_at_max_questions(self, isolated_env):
        conv = isolated_env
        # AI keeps asking forever
        question_payload = {"metadata": {}, "action": "ask",
                            "question": "Encore ?", "context": ""}
        rid = _seed_reminder()
        with patch.object(conv, "call_model",
                          side_effect=lambda *a, **kw: json.dumps(question_payload)):
            current = conv.start(rid, "test", {})
            asked = 1
            while current["action"] == "ask":
                current = conv.answer(current["session_id"], "ok")
                if current["action"] == "ask":
                    asked += 1
        assert current["action"] == "done"
        assert asked == conv._MAX_QUESTIONS


# ── Web search integration ───────────────────────────────────────────────────


class TestWebSearch:
    def test_web_search_runs_transparently(self, isolated_env):
        conv = isolated_env
        rid = _seed_reminder()
        with patch.object(conv, "_do_web_search",
                          return_value="Cabinet ouvert 9h-12h / 14h-19h"):
            with patch.object(conv, "call_model", side_effect=_ai_reply(
                {"metadata": {"location": "Quimper"},
                 "action": "web_search",
                 "web_search_query": "Dr Horel Quimper horaires"},
                {"metadata": {"location": "Quimper",
                              "business_info": {"hours": "9-12/14-19"}},
                 "action": "ask",
                 "question": "Tu peux appeler entre 12h et 14h ?",
                 "context": ""},
            )):
                result = conv.start(rid, "rdv dentiste Quimper", {})
        # Bash side never sees the web_search step
        assert result["action"] == "ask"
        assert "appeler" in result["question"]
        state = conv._load_session(result["session_id"])
        assert state["web_searches_total"] == 1
        assert "Dr Horel Quimper horaires" in state["web_search_log"][0]["query"]
        assert "fiche établissement" in state["web_search_log"][0]["query"]

    def test_web_search_result_added_to_messages(self, isolated_env):
        conv = isolated_env
        rid = _seed_reminder()
        with patch.object(conv, "_do_web_search",
                          return_value="Hours: Mon-Fri 9-18"):
            with patch.object(conv, "call_model", side_effect=_ai_reply(
                {"metadata": {}, "action": "web_search", "web_search_query": "q"},
                {"metadata": {}, "action": "done"},
            )):
                result = conv.start(rid, "test", {})
        state = conv._load_session(result["session_id"])
        msgs_after_search = [m for m in state["messages"]
                             if m["role"] == "user" and "Search result" in m["content"]]
        assert len(msgs_after_search) == 1
        assert "Mon-Fri 9-18" in msgs_after_search[0]["content"]
        assert "Source priority" in msgs_after_search[0]["content"]

    def test_web_search_failure_does_not_break_conversation(self, isolated_env):
        conv = isolated_env
        rid = _seed_reminder()
        with patch.object(conv, "_do_web_search", return_value=""):
            with patch.object(conv, "call_model", side_effect=_ai_reply(
                {"metadata": {}, "action": "web_search", "web_search_query": "q"},
                {"metadata": {}, "action": "ask",
                 "question": "Sans info, tu préfères matin ou après-midi ?", "context": ""},
            )):
                result = conv.start(rid, "test", {})
        assert result["action"] == "ask"

    def test_web_search_session_budget_enforced(self, isolated_env):
        """AI that keeps requesting web_search must NOT cause an infinite loop."""
        conv = isolated_env
        rid = _seed_reminder()
        with patch.object(conv, "_do_web_search", return_value="some result"):
            with patch.object(conv, "call_model",
                              side_effect=lambda *a, **kw: json.dumps({
                                  "metadata": {}, "action": "web_search",
                                  "web_search_query": "q"})):
                result = conv.start(rid, "test", {})
        assert result["action"] == "done"   # must terminate
        state = conv._load_session(result["session_id"])
        assert state["web_searches_total"] <= conv._MAX_WEB_SEARCHES_PER_SESSION
        assert state["finished"] is True


# ── Profile injection ────────────────────────────────────────────────────────


class TestProfileInjection:
    def test_profile_included_in_initial_message(self, isolated_env, monkeypatch):
        conv = isolated_env
        profile = {
            "timezone": "Paris",
            "language": "fr",
            "sections": {
                "rhythm": ["Working hours: 08:00 to 12:00 and 14:00 to 18:00"],
                "recurring_constraints": [], "preferences": [],
                "future_commitments": [], "identity": [], "other": [],
            },
        }
        monkeypatch.setattr(conv, "load_profile", lambda: profile)
        captured: list[list[dict]] = []

        def fake(model, messages, api_key, **kwargs):
            captured.append([m.copy() for m in messages])
            return json.dumps({"metadata": {}, "action": "done"})

        with patch.object(conv, "call_model", side_effect=fake):
            _seed_reminder()
            conv.start(1, "rdv dentiste", {})
        all_text = "\n".join(m["content"] for m in captured[0])
        assert "USER PROFILE" in all_text
        assert "Working hours: 08:00 to 12:00" in all_text

    def test_empty_profile_no_section_added(self, isolated_env, monkeypatch):
        conv = isolated_env
        monkeypatch.setattr(conv, "load_profile", lambda: {})
        captured: list[list[dict]] = []

        def fake(model, messages, api_key, **kwargs):
            captured.append([m.copy() for m in messages])
            return json.dumps({"metadata": {}, "action": "done"})

        with patch.object(conv, "call_model", side_effect=fake):
            _seed_reminder()
            conv.start(1, "rdv dentiste", {})
        all_text = "\n".join(m["content"] for m in captured[0])
        assert "USER PROFILE" not in all_text


# ── finalize ─────────────────────────────────────────────────────────────────


class TestFinalize:
    def test_writes_merged_metadata_to_db(self, isolated_env):
        conv = isolated_env
        rid = _seed_reminder(metadata={"person": "Dr Horel"})
        with patch.object(conv, "call_model", side_effect=_ai_reply(
            {"metadata": {"person": "Dr Horel", "location": "Quimper"},
             "action": "ask", "question": "Quand ?", "context": ""},
            {"metadata": {"person": "Dr Horel", "location": "Quimper",
                          "callable_hours": "12:00-14:00"},
             "action": "done"},
        )):
            first = conv.start(rid, "rdv dentiste", {"person": "Dr Horel"})
            conv.answer(first["session_id"], "demain matin")
            result = conv.finalize(first["session_id"])
        assert result["reminder_id"] == rid
        assert result["questions_asked"] == 1
        meta = _meta_of(rid)
        assert meta["location"] == "Quimper"
        assert meta["callable_hours"] == "12:00-14:00"

    def test_appends_answers_to_metadata(self, isolated_env):
        conv = isolated_env
        rid = _seed_reminder()
        with patch.object(conv, "call_model", side_effect=_ai_reply(
            {"metadata": {}, "action": "ask",
             "question": "Quelle ville ?", "context": ""},
            {"metadata": {"location": "Quimper"}, "action": "done"},
        )):
            first = conv.start(rid, "rdv dentiste", {})
            conv.answer(first["session_id"], "Quimper")
            conv.finalize(first["session_id"])
        meta = _meta_of(rid)
        answers = meta.get("answers", [])
        assert len(answers) == 1
        assert answers[0]["question"] == "Quelle ville ?"
        assert answers[0]["answer"] == "Quimper"

    def test_session_file_deleted_after_finalize(self, isolated_env):
        conv = isolated_env
        rid = _seed_reminder()
        with patch.object(conv, "call_model",
                          side_effect=_ai_reply({"metadata": {}, "action": "done"})):
            first = conv.start(rid, "test", {})
        conv.finalize(first["session_id"])
        assert conv._load_session(first["session_id"]) is None

    def test_finalize_unknown_session_returns_none(self, isolated_env):
        conv = isolated_env
        result = conv.finalize("nope")
        assert result == {"reminder_id": None}

    def test_finalize_includes_answers_text(self, isolated_env):
        conv = isolated_env
        rid = _seed_reminder()
        with patch.object(conv, "call_model", side_effect=_ai_reply(
            {"metadata": {}, "action": "ask",
             "question": "Peux-tu agir sur cette tâche pendant tes heures de travail ?",
             "context": ""},
            {"metadata": {}, "action": "done"},
        )):
            first = conv.start(rid, "rdv dentiste", {})
            conv.answer(first["session_id"], "Oui, en télétravail c'est possible")
            result = conv.finalize(first["session_id"])
        assert "answers_text" in result
        assert "télétravail" in result["answers_text"]
        assert "Peux-tu agir" in result["answers_text"]

    def test_finalize_answers_text_empty_when_no_questions(self, isolated_env):
        conv = isolated_env
        rid = _seed_reminder()
        with patch.object(conv, "call_model",
                          side_effect=_ai_reply({"metadata": {}, "action": "done"})):
            first = conv.start(rid, "rdv dentiste", {})
            result = conv.finalize(first["session_id"])
        assert result.get("answers_text") == ""


# ── Error handling ───────────────────────────────────────────────────────────


class TestErrorHandling:
    def test_ai_returns_invalid_json_ends_gracefully(self, isolated_env):
        conv = isolated_env
        rid = _seed_reminder()
        with patch.object(conv, "call_model",
                          side_effect=lambda *a, **kw: "not json {{{"):
            result = conv.start(rid, "test", {})
        assert result["action"] == "done"

    def test_missing_api_key_ends_gracefully(self, isolated_env, monkeypatch):
        conv = isolated_env
        monkeypatch.delenv("MISTRAL_API_KEY")
        rid = _seed_reminder()
        result = conv.start(rid, "test", {})
        assert result["action"] == "done"

    def test_session_expired_returns_done_on_answer(self, isolated_env):
        conv = isolated_env
        rid = _seed_reminder()
        with patch.object(conv, "call_model", side_effect=_ai_reply(
            {"metadata": {}, "action": "ask", "question": "Q?", "context": ""},
        )):
            first = conv.start(rid, "test", {})
        # Manually age the session past the TTL
        state = conv._load_session(first["session_id"])
        old = (datetime.now(tz=timezone.utc) - timedelta(hours=2)).isoformat()
        state["updated_at"] = old
        state["created_at"] = old
        conv._session_path(first["session_id"]).write_text(
            json.dumps(state), encoding="utf-8",
        )
        result = conv.answer(first["session_id"], "answer")
        assert result["action"] == "done"


# ── pending_refinement lifecycle ─────────────────────────────────────────────


class TestPendingRefinementStatus:
    def test_start_sets_pending_refinement(self, isolated_env):
        conv = isolated_env
        rid = _seed_reminder()
        with patch.object(conv, "call_model", side_effect=_ai_reply(
            {"metadata": {}, "action": "ask", "question": "Q?", "context": ""},
        )):
            conv.start(rid, "rdv dentiste", {})
        assert _get_status(rid) == "pending_refinement"

    def test_finalize_resets_to_pending(self, isolated_env):
        conv = isolated_env
        rid = _seed_reminder()
        with patch.object(conv, "call_model", side_effect=_ai_reply(
            {"metadata": {}, "action": "ask", "question": "Q?", "context": ""},
        )):
            first = conv.start(rid, "rdv dentiste", {})
        with patch.object(conv, "call_model", side_effect=_ai_reply(
            {"metadata": {}, "action": "done"},
        )):
            conv.answer(first["session_id"], "Paris")
        conv.finalize(first["session_id"])
        assert _get_status(rid) == "pending"

    def test_get_due_skips_pending_refinement(self, isolated_env):
        rid = _seed_reminder()
        rdb.update_status(rid, "pending_refinement")
        due = rdb.get_due("9999-01-01 00:00:00")
        assert all(r["id"] != rid for r in due)


def _get_status(reminder_id: int) -> str:
    with rdb._db() as conn:
        row = conn.execute(
            "SELECT status FROM reminders WHERE id = ?", (reminder_id,)
        ).fetchone()
    return row["status"] if row else ""


# ── STT awareness (voice flag) ───────────────────────────────────────────────


class TestVoiceFlag:
    def test_start_voice_false_omits_warning(self, isolated_env):
        conv = isolated_env
        rid = _seed_reminder()
        captured = {}

        def fake(model, messages, api_key, **kwargs):
            captured["messages"] = list(messages)
            return json.dumps({"metadata": {}, "action": "done"})

        with patch.object(conv, "call_model", side_effect=fake):
            conv.start(rid, "rdv dentiste Dr Aurel", {})
        sys_contents = [m["content"] for m in captured["messages"] if m["role"] == "system"]
        assert not any("speech-to-text" in c for c in sys_contents)

    def test_start_voice_true_injects_warning(self, isolated_env):
        conv = isolated_env
        rid = _seed_reminder()
        captured = {}

        def fake(model, messages, api_key, **kwargs):
            captured["messages"] = list(messages)
            return json.dumps({"metadata": {}, "action": "done"})

        with patch.object(conv, "call_model", side_effect=fake):
            conv.start(rid, "rdv dentiste Dr Aurel", {}, voice=True)
        sys_contents = [m["content"] for m in captured["messages"] if m["role"] == "system"]
        warnings = [c for c in sys_contents if "speech-to-text" in c]
        assert len(warnings) == 1
        assert "mis-hears" in warnings[0]

    def test_answer_voice_true_prepends_system_note(self, isolated_env):
        conv = isolated_env
        rid = _seed_reminder()
        seen = []

        def fake(model, messages, api_key, **kwargs):
            seen.append([dict(m) for m in messages])
            if len(seen) == 1:
                return json.dumps({
                    "metadata": {}, "action": "ask",
                    "question": "Quelle ville ?", "context": "",
                })
            return json.dumps({"metadata": {}, "action": "done"})

        with patch.object(conv, "call_model", side_effect=fake):
            first = conv.start(rid, "rdv dentiste", {})
            conv.answer(first["session_id"], "Marseille", voice=True)

        # The second AI call should see a system note flagging the answer as STT.
        second_call_msgs = seen[1]
        roles = [m["role"] for m in second_call_msgs]
        # Find the system note immediately before the user's "Marseille" reply.
        try:
            user_idx = next(
                i for i, m in enumerate(second_call_msgs)
                if m["role"] == "user" and m["content"] == "Marseille"
            )
        except StopIteration:
            pytest.fail(f"User reply not found in messages; roles={roles}")
        assert second_call_msgs[user_idx - 1]["role"] == "system"
        assert "speech-to-text" in second_call_msgs[user_idx - 1]["content"]

    def test_answer_voice_false_does_not_inject_note(self, isolated_env):
        conv = isolated_env
        rid = _seed_reminder()
        seen = []

        def fake(model, messages, api_key, **kwargs):
            seen.append([dict(m) for m in messages])
            if len(seen) == 1:
                return json.dumps({
                    "metadata": {}, "action": "ask",
                    "question": "Quelle ville ?", "context": "",
                })
            return json.dumps({"metadata": {}, "action": "done"})

        with patch.object(conv, "call_model", side_effect=fake):
            first = conv.start(rid, "rdv dentiste", {})
            conv.answer(first["session_id"], "Marseille")

        second_call_msgs = seen[1]
        # No system message should contain the STT warning text.
        assert not any(
            m["role"] == "system" and "speech-to-text" in m["content"]
            for m in second_call_msgs
        )


# ── Pomodoro awareness (Option A+B) ─────────────────────────────────────────


class TestPomodoroAwareness:
    def test_system_prompt_contains_pomodoro_rules(self, isolated_env):
        conv = isolated_env
        prompt = conv._build_system_prompt()
        assert "screen_free" in prompt
        assert "Pomodoro" in prompt

    def test_system_prompt_documents_time_constraint_format(self, isolated_env):
        conv = isolated_env
        prompt = conv._build_system_prompt()
        assert "time_constraint" in prompt
        assert "earliest_hour" in prompt
        assert "latest_hour" in prompt

    def test_system_prompt_documents_split_schedule_list_format(self, isolated_env):
        conv = isolated_env
        prompt = conv._build_system_prompt()
        assert "SPLIT" in prompt or "split" in prompt.lower()
        assert "list" in prompt.lower() or "liste" in prompt.lower()

    def test_start_injects_pomodoro_note_when_enabled(self, isolated_env):
        conv = isolated_env
        rid = _seed_reminder()
        captured = {}

        def fake(model, messages, api_key, **kwargs):
            captured["messages"] = list(messages)
            return json.dumps({"metadata": {}, "action": "done"})

        enabled_note = (
            "Pomodoro timer context: the timer is active — "
            "work=25 min / break=5 min (range 1–10 min). "
            "Tasks with screen_free=true in metadata are automatically offered "
            "to the user during Pomodoro breaks."
        )
        with patch.object(conv, "_pomodoro_context_note", return_value=enabled_note):
            with patch.object(conv, "call_model", side_effect=fake):
                conv.start(rid, "aspirer le salon", {})

        sys_contents = [m["content"] for m in captured["messages"] if m["role"] == "system"]
        assert any("Pomodoro timer context" in c for c in sys_contents)
        assert any("work=25 min" in c for c in sys_contents)

    def test_start_no_pomodoro_note_when_disabled(self, isolated_env):
        conv = isolated_env
        rid = _seed_reminder()
        captured = {}

        def fake(model, messages, api_key, **kwargs):
            captured["messages"] = list(messages)
            return json.dumps({"metadata": {}, "action": "done"})

        with patch.object(conv, "_pomodoro_context_note", return_value=""):
            with patch.object(conv, "call_model", side_effect=fake):
                conv.start(rid, "aspirer le salon", {})

        sys_contents = [m["content"] for m in captured["messages"] if m["role"] == "system"]
        assert not any("Pomodoro timer context" in c for c in sys_contents)

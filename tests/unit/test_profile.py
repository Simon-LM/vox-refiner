"""Unit tests for src/profile.py.

Covers file management, context AI update/question/none flows,
pending question resolution, and pre-filter — without network calls.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import src.profile as profile_mod


@pytest.fixture(autouse=True)
def isolated_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(profile_mod, "_PROFILE_DIR", tmp_path)
    monkeypatch.setattr(profile_mod, "_PROFILE_PATH", tmp_path / "user_profile.json")
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")


def _empty() -> dict:
    return json.loads(json.dumps(profile_mod._EMPTY_PROFILE))


def _profile(**kwargs) -> dict:
    p = _empty()
    p.update(kwargs)
    return p


def _ai_none() -> str:
    return json.dumps({"action": "none"})


def _ai_update(updated_profile: dict) -> str:
    return json.dumps({"action": "update", "profile": updated_profile})


def _ai_question(question: str = "Changement permanent ou temporaire ?",
                 context: str = "Contradiction horaires") -> str:
    return json.dumps({
        "action": "question",
        "question": question,
        "question_context": context,
    })


# ── load_profile ──────────────────────────────────────────────────────────────

class TestLoadProfile:
    def test_returns_empty_when_file_missing(self):
        p = profile_mod.load_profile()
        assert p["timezone"] is None
        assert p["sections"]["identity"] == []
        assert p["pending_questions"] == []

    def test_loads_existing_profile(self, tmp_path):
        data = _profile(timezone="Europe/Paris", language="fr")
        (tmp_path / "user_profile.json").write_text(
            json.dumps(data), encoding="utf-8"
        )
        p = profile_mod.load_profile()
        assert p["timezone"] == "Europe/Paris"
        assert p["language"] == "fr"

    def test_handles_corrupt_file_gracefully(self, tmp_path):
        (tmp_path / "user_profile.json").write_text("not json", encoding="utf-8")
        p = profile_mod.load_profile()
        assert p["sections"] == _empty()["sections"]

    def test_backfills_missing_sections(self, tmp_path):
        data = {"timezone": "UTC", "language": "en", "sections": {}, "pending_questions": []}
        (tmp_path / "user_profile.json").write_text(json.dumps(data), encoding="utf-8")
        p = profile_mod.load_profile()
        for section in profile_mod._SECTIONS:
            assert section in p["sections"]

    def test_backfills_missing_pending_questions(self, tmp_path):
        data = {"timezone": "UTC", "language": "en", "sections": {k: [] for k in profile_mod._SECTIONS}}
        (tmp_path / "user_profile.json").write_text(json.dumps(data), encoding="utf-8")
        p = profile_mod.load_profile()
        assert "pending_questions" in p


# ── save_profile ──────────────────────────────────────────────────────────────

class TestSaveProfile:
    def test_creates_directory_and_writes_json(self, tmp_path):
        nested = tmp_path / "a" / "b"
        profile_mod._PROFILE_DIR = nested
        profile_mod._PROFILE_PATH = nested / "user_profile.json"
        p = _profile(timezone="America/New_York")
        profile_mod.save_profile(p)
        assert profile_mod._PROFILE_PATH.exists()
        loaded = json.loads(profile_mod._PROFILE_PATH.read_text(encoding="utf-8"))
        assert loaded["timezone"] == "America/New_York"

    def test_writes_valid_json(self):
        profile_mod.save_profile(_profile(timezone="Asia/Tokyo"))
        raw = profile_mod._PROFILE_PATH.read_text(encoding="utf-8")
        parsed = json.loads(raw)
        assert parsed["timezone"] == "Asia/Tokyo"


# ── update_from_conversation ──────────────────────────────────────────────────

class TestUpdateFromConversation:
    def test_pre_filter_returns_none_for_short_text(self):
        result = profile_mod.update_from_conversation("ok")
        assert result is None

    def test_pre_filter_exact_threshold(self):
        short = " ".join(["mot"] * (profile_mod._MIN_WORDS - 1))
        assert profile_mod.update_from_conversation(short) is None

    def test_action_none_returns_none_and_no_file_written(self):
        with patch.object(profile_mod, "call_model", return_value=_ai_none()):
            result = profile_mod.update_from_conversation("je travaille le matin de préférence")
        assert result is None
        assert not profile_mod._PROFILE_PATH.exists()

    def test_action_update_saves_profile(self):
        updated = _profile(timezone="Europe/Paris", language="fr")
        updated["sections"]["rhythm"] = ["Travaille de 9h à 18h du lundi au vendredi"]
        with patch.object(profile_mod, "call_model", return_value=_ai_update(updated)):
            result = profile_mod.update_from_conversation(
                "je travaille de neuf heures à dix-huit heures du lundi au vendredi"
            )
        assert result is None
        saved = profile_mod.load_profile()
        assert "Travaille de 9h à 18h du lundi au vendredi" in saved["sections"]["rhythm"]

    def test_action_update_preserves_existing_pending_questions(self):
        existing = _profile()
        existing["pending_questions"] = [{"id": "abc", "question": "?", "context": "", "original_text": "x", "created_at": "2026-01-01T00:00:00+00:00"}]
        profile_mod.save_profile(existing)

        updated = _profile(timezone="Europe/Paris")
        with patch.object(profile_mod, "call_model", return_value=_ai_update(updated)):
            profile_mod.update_from_conversation(
                "je suis basé à Paris donc c'est le fuseau Europe Paris"
            )

        saved = profile_mod.load_profile()
        assert len(saved["pending_questions"]) == 1
        assert saved["pending_questions"][0]["id"] == "abc"

    def test_action_question_returns_entry_with_id_and_question(self):
        with patch.object(profile_mod, "call_model", return_value=_ai_question()):
            result = profile_mod.update_from_conversation(
                "je finis maintenant à dix-sept heures au lieu de dix-huit"
            )
        assert result is not None
        assert "id" in result
        assert result["question"] == "Changement permanent ou temporaire ?"

    def test_action_question_stored_in_pending_questions(self):
        with patch.object(profile_mod, "call_model", return_value=_ai_question()):
            profile_mod.update_from_conversation(
                "je finis maintenant à dix-sept heures au lieu de dix-huit"
            )
        saved = profile_mod.load_profile()
        assert len(saved["pending_questions"]) == 1
        assert saved["pending_questions"][0]["question"] == "Changement permanent ou temporaire ?"

    def test_missing_api_key_returns_none(self, monkeypatch):
        monkeypatch.delenv("MISTRAL_API_KEY")
        result = profile_mod.update_from_conversation(
            "je travaille de neuf heures à dix-huit heures"
        )
        assert result is None

    def test_json_parse_failure_returns_none(self):
        with patch.object(profile_mod, "call_model", return_value="not json {{"):
            result = profile_mod.update_from_conversation(
                "je travaille de neuf heures à dix-huit heures"
            )
        assert result is None

    def test_markdown_fence_stripped(self):
        updated = _profile(timezone="Europe/Paris")
        fenced = "```json\n" + _ai_update(updated) + "\n```"
        with patch.object(profile_mod, "call_model", return_value=fenced):
            result = profile_mod.update_from_conversation(
                "je suis basé à Paris donc c'est le fuseau Europe Paris"
            )
        assert result is None
        assert profile_mod.load_profile()["timezone"] == "Europe/Paris"

    def test_uses_loaded_profile_when_none_given(self):
        existing = _profile(timezone="Europe/Paris")
        profile_mod.save_profile(existing)
        captured = []

        def fake_call(model, messages, api_key, **kwargs):
            captured.extend(messages)
            return _ai_none()

        with patch.object(profile_mod, "call_model", side_effect=fake_call):
            profile_mod.update_from_conversation(
                "je travaille de neuf heures à dix-huit heures"
            )

        context = " ".join(m["content"] for m in captured)
        assert "Europe/Paris" in context


# ── resolve_pending_question ──────────────────────────────────────────────────

class TestResolvePendingQuestion:
    def _with_pending(self) -> tuple[dict, str]:
        p = _profile()
        qid = str(__import__("uuid").uuid4())
        p["pending_questions"] = [{
            "id": qid,
            "question": "Changement permanent ou temporaire ?",
            "context": "Contradiction horaires",
            "original_text": "je finis à 17h maintenant",
            "created_at": "2026-05-14T10:00:00+00:00",
        }]
        profile_mod.save_profile(p)
        return p, qid

    def test_removes_question_from_pending(self):
        p, qid = self._with_pending()
        with patch.object(profile_mod, "call_model", return_value=json.dumps({"action": "none"})):
            profile_mod.resolve_pending_question(qid, "c'est permanent")
        saved = profile_mod.load_profile()
        assert all(q["id"] != qid for q in saved["pending_questions"])

    def test_action_update_saves_profile(self):
        p, qid = self._with_pending()
        updated = _profile()
        updated["sections"]["rhythm"] = ["Travaille de 9h à 17h du lundi au vendredi"]
        with patch.object(profile_mod, "call_model", return_value=json.dumps({"action": "update", "profile": updated})):
            profile_mod.resolve_pending_question(qid, "c'est permanent")
        saved = profile_mod.load_profile()
        assert "Travaille de 9h à 17h du lundi au vendredi" in saved["sections"]["rhythm"]

    def test_action_none_still_removes_question(self):
        p, qid = self._with_pending()
        with patch.object(profile_mod, "call_model", return_value=json.dumps({"action": "none"})):
            profile_mod.resolve_pending_question(qid, "je ne sais pas")
        assert len(profile_mod.load_profile()["pending_questions"]) == 0

    def test_unknown_id_does_not_crash(self):
        profile_mod.save_profile(_profile())
        with patch.object(profile_mod, "call_model", return_value=json.dumps({"action": "none"})):
            profile_mod.resolve_pending_question("nonexistent-id", "answer")

    def test_other_pending_questions_preserved_after_update(self):
        p = _profile()
        import uuid
        qid1 = str(uuid.uuid4())
        qid2 = str(uuid.uuid4())
        p["pending_questions"] = [
            {"id": qid1, "question": "Q1?", "context": "", "original_text": "x", "created_at": "2026-01-01T00:00:00+00:00"},
            {"id": qid2, "question": "Q2?", "context": "", "original_text": "y", "created_at": "2026-01-01T00:00:00+00:00"},
        ]
        profile_mod.save_profile(p)
        updated = _profile()
        with patch.object(profile_mod, "call_model", return_value=json.dumps({"action": "update", "profile": updated})):
            profile_mod.resolve_pending_question(qid1, "answer")
        saved = profile_mod.load_profile()
        assert len(saved["pending_questions"]) == 1
        assert saved["pending_questions"][0]["id"] == qid2


# ── pop_pending_question ──────────────────────────────────────────────────────

class TestPopPendingQuestion:
    def test_returns_first_question(self):
        p = _profile()
        p["pending_questions"] = [
            {"id": "first", "question": "Q?", "context": "", "original_text": "x", "created_at": ""},
            {"id": "second", "question": "R?", "context": "", "original_text": "y", "created_at": ""},
        ]
        profile_mod.save_profile(p)
        entry = profile_mod.pop_pending_question()
        assert entry["id"] == "first"

    def test_returns_none_when_empty(self):
        profile_mod.save_profile(_profile())
        assert profile_mod.pop_pending_question() is None

    def test_does_not_remove_question(self):
        p = _profile()
        p["pending_questions"] = [{"id": "q1", "question": "?", "context": "", "original_text": "x", "created_at": ""}]
        profile_mod.save_profile(p)
        profile_mod.pop_pending_question()
        assert len(profile_mod.load_profile()["pending_questions"]) == 1

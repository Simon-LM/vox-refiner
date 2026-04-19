"""Unit tests for OpenAI-adapter response content parsing.

Covers both shapes returned by the Mistral chat API:
  - Standard models return content as a plain string.
  - Reasoning models (magistral) return content as a list of blocks
    (e.g. [{"type": "text", "text": "..."}]).

The parsing logic lives in src.providers._call_openai_adapter; we exercise
it through providers.call() so the tests are insensitive to the internal
helper boundary.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


def _fake_post(content):
    """Return a requests.post mock whose JSON body carries *content*."""
    resp = MagicMock()
    resp.status_code = 200
    resp.ok = True
    resp.json.return_value = {
        "choices": [{"message": {"role": "assistant", "content": content}}]
    }
    return MagicMock(return_value=resp)


def _call_refine(monkeypatch, content):
    """Invoke providers.call('refine', ...) with a fake HTTP response."""
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    import src.providers as providers  # noqa: PLC0415
    monkeypatch.setattr(providers.requests, "post", _fake_post(content))
    result = providers.call(
        "refine",
        [{"role": "user", "content": "ping"}],
        model="mistral-small-latest",
        timeout=5,
    )
    return result.text


class TestContentParsingString:
    def test_plain_string_returned_as_is(self, monkeypatch):
        assert _call_refine(monkeypatch, "Hello world.") == "Hello world."

    def test_plain_string_stripped(self, monkeypatch):
        assert _call_refine(monkeypatch, "  Hello world.  \n") == "Hello world."

    def test_empty_string_returned(self, monkeypatch):
        assert _call_refine(monkeypatch, "") == ""


class TestContentParsingList:
    def test_list_of_text_dicts_joined(self, monkeypatch):
        """Magistral returns content as [{"type": "text", "text": "..."}]."""
        content = [
            {"type": "text", "text": "First part. "},
            {"type": "text", "text": "Second part."},
        ]
        assert _call_refine(monkeypatch, content) == "First part. Second part."

    def test_list_of_plain_strings_joined(self, monkeypatch):
        """Fallback: list contains raw strings (not dicts)."""
        assert _call_refine(monkeypatch, ["Hello ", "world."]) == "Hello world."

    def test_list_with_missing_text_key(self, monkeypatch):
        """Block dict without 'text' key should contribute an empty string."""
        content = [{"type": "thinking"}, {"type": "text", "text": "Answer."}]
        assert _call_refine(monkeypatch, content) == "Answer."

    def test_single_item_list(self, monkeypatch):
        assert _call_refine(monkeypatch, [{"type": "text", "text": "Only."}]) == "Only."

    def test_list_result_stripped(self, monkeypatch):
        content = [{"type": "text", "text": "  Trimmed.  "}]
        assert _call_refine(monkeypatch, content) == "Trimmed."

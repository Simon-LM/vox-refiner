"""Unit tests for _call_model() content parsing.

Covers:
- Standard models returning content as a plain string
- Reasoning models (magistral) returning content as a list of blocks
"""

import sys
from unittest.mock import MagicMock

import pytest
import requests


def _get_refine(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    if "src.refine" in sys.modules:
        del sys.modules["src.refine"]
    import src.refine as refine
    return refine


def _mock_response(monkeypatch, refine, content):
    """Patch requests.post to return a response with the given content."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"role": "assistant", "content": content}}]
    }
    monkeypatch.setattr(requests, "post", MagicMock(return_value=mock_resp))
    return mock_resp


class TestContentParsingString:
    def test_plain_string_returned_as_is(self, monkeypatch):
        refine = _get_refine(monkeypatch)
        _mock_response(monkeypatch, refine, "Hello world.")
        result = refine._call_model("some-model", [], "test-key", timeout=5, retry_delay=1.0)
        assert result == "Hello world."

    def test_plain_string_stripped(self, monkeypatch):
        refine = _get_refine(monkeypatch)
        _mock_response(monkeypatch, refine, "  Hello world.  \n")
        result = refine._call_model("some-model", [], "test-key", timeout=5, retry_delay=1.0)
        assert result == "Hello world."

    def test_empty_string_returned(self, monkeypatch):
        refine = _get_refine(monkeypatch)
        _mock_response(monkeypatch, refine, "")
        result = refine._call_model("some-model", [], "test-key", timeout=5, retry_delay=1.0)
        assert result == ""


class TestContentParsingList:
    def test_list_of_text_dicts_joined(self, monkeypatch):
        """Magistral returns content as [{"type": "text", "text": "..."}]."""
        refine = _get_refine(monkeypatch)
        content = [
            {"type": "text", "text": "First part. "},
            {"type": "text", "text": "Second part."},
        ]
        _mock_response(monkeypatch, refine, content)
        result = refine._call_model("magistral-small-latest", [], "test-key", timeout=5, retry_delay=1.0)
        assert result == "First part. Second part."

    def test_list_of_plain_strings_joined(self, monkeypatch):
        """Fallback: list contains raw strings (not dicts)."""
        refine = _get_refine(monkeypatch)
        _mock_response(monkeypatch, refine, ["Hello ", "world."])
        result = refine._call_model("magistral-small-latest", [], "test-key", timeout=5, retry_delay=1.0)
        assert result == "Hello world."

    def test_list_with_missing_text_key(self, monkeypatch):
        """Block dict without 'text' key should contribute an empty string."""
        refine = _get_refine(monkeypatch)
        content = [{"type": "thinking"}, {"type": "text", "text": "Answer."}]
        _mock_response(monkeypatch, refine, content)
        result = refine._call_model("magistral-small-latest", [], "test-key", timeout=5, retry_delay=1.0)
        assert result == "Answer."

    def test_single_item_list(self, monkeypatch):
        refine = _get_refine(monkeypatch)
        _mock_response(monkeypatch, refine, [{"type": "text", "text": "Only."}])
        result = refine._call_model("magistral-small-latest", [], "test-key", timeout=5, retry_delay=1.0)
        assert result == "Only."

    def test_list_result_stripped(self, monkeypatch):
        refine = _get_refine(monkeypatch)
        _mock_response(monkeypatch, refine, [{"type": "text", "text": "  Trimmed.  "}])
        result = refine._call_model("magistral-small-latest", [], "test-key", timeout=5, retry_delay=1.0)
        assert result == "Trimmed."

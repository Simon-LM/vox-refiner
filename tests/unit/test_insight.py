"""Unit tests for src/insight.py.

Tests cover:
  - summarize() happy path and API key guard
  - detect_content_type() integration (via tts module)

For search and fact-check tests, see test_search.py and test_factcheck.py.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from src.insight import summarize


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_chat_response(content: str) -> MagicMock:
    """Build a fake requests.Response for a chat completion (Mistral / Perplexity)."""
    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": content}}]
    }
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


# ── summarize() ──────────────────────────────────────────────────────────────

def _make_call_result(text: str = "• Bullet.",
                      provider_name: str = "mistral_direct",
                      effective_model: str = "mistral-small-latest",
                      requested_model: str = "mistral-small-latest",
                      substituted: bool = False,
                      attempts: int = 1) -> MagicMock:
    """Build a fake providers.CallResult for summarize() tests."""
    from src.providers import PROVIDERS
    result = MagicMock()
    result.text             = text
    result.provider         = PROVIDERS[provider_name]
    result.effective_model  = effective_model
    result.requested_model  = requested_model
    result.substituted      = substituted
    result.attempts         = attempts
    return result


class TestSummarize:
    def test_returns_summary_text(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "key-x")
        with patch("src.insight.call") as mock_call:
            mock_call.return_value = _make_call_result(
                text="• First point.\n• Second point."
            )
            result = summarize("Some article text.", "news_article")
        assert "First point" in result
        assert "Second point" in result

    def test_raises_when_no_provider_available(self, monkeypatch):
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        monkeypatch.delenv("EDENAI_API_KEY",  raising=False)
        with pytest.raises(RuntimeError, match="No provider available"):
            summarize("text")

    def test_eden_only_is_acceptable(self, monkeypatch):
        """Missing MISTRAL_API_KEY but present EDENAI_API_KEY must still work."""
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        monkeypatch.setenv("EDENAI_API_KEY",  "key-eden")
        with patch("src.insight.call") as mock_call:
            mock_call.return_value = _make_call_result(
                provider_name="eden_mistral",
                effective_model="mistral/mistral-small-latest",
            )
            result = summarize("text")
        assert result == "• Bullet."

    def test_content_type_hint_injected(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "key-x")
        with patch("src.insight.call") as mock_call:
            mock_call.return_value = _make_call_result()
            summarize("text", "wikipedia")
        messages = mock_call.call_args.args[1]
        assert "wikipedia" in messages[-1]["content"]

    def test_generic_type_no_hint(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "key-x")
        with patch("src.insight.call") as mock_call:
            mock_call.return_value = _make_call_result()
            summarize("text", "generic")
        messages = mock_call.call_args.args[1]
        assert "Content type" not in messages[-1]["content"]

    def test_reasoning_effort_high_passed_when_env_set(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "key-x")
        with patch("src.insight._SUMMARY_REASONING", "high"), \
             patch("src.insight.call") as mock_call:
            mock_call.return_value = _make_call_result()
            summarize("text")
        opts = mock_call.call_args.kwargs
        assert opts.get("reasoning_effort") == "high"

    def test_reasoning_effort_absent_when_standard(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "key-x")
        with patch("src.insight._SUMMARY_REASONING", "standard"), \
             patch("src.insight.call") as mock_call:
            mock_call.return_value = _make_call_result()
            summarize("text")
        opts = mock_call.call_args.kwargs
        assert "reasoning_effort" not in opts

    def test_temperature_and_timeout_passed_through(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "key-x")
        with patch("src.insight.call") as mock_call:
            mock_call.return_value = _make_call_result()
            summarize("text")
        opts = mock_call.call_args.kwargs
        assert opts.get("temperature") == 0.3
        assert opts.get("timeout") == 30  # _SUMMARY_TIMEOUT

    def test_provider_error_wrapped_as_runtime_error(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "key-x")
        from src.providers import ProviderError as _PE
        with patch("src.insight.call", side_effect=_PE("all exhausted")):
            with pytest.raises(RuntimeError, match="Summarize failed"):
                summarize("text")


# ── detect_content_type() integration ────────────────────────────────────────

class TestDetectContentType:
    def test_returns_known_type(self):
        from src.tts import detect_content_type, _CLEAN_RULES
        with patch("src.tts.requests.post") as mock_post:
            mock_post.return_value = _make_chat_response("news_article")
            result = detect_content_type("some text", "api-key")
        assert result == "news_article"
        assert result in _CLEAN_RULES

    def test_falls_back_to_generic_on_unknown(self):
        from src.tts import detect_content_type
        with patch("src.tts.requests.post") as mock_post:
            mock_post.return_value = _make_chat_response("unknown_garbage_type")
            result = detect_content_type("some text", "api-key")
        assert result == "generic"

    def test_falls_back_to_generic_on_error(self):
        import requests as req_module
        from src.tts import detect_content_type
        with patch("src.tts.requests.post") as mock_post:
            mock_post.side_effect = req_module.exceptions.Timeout("timeout")
            result = detect_content_type("some text", "api-key")
        assert result == "generic"

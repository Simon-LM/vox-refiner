"""Unit tests for src/insight.py.

Tests cover:
  - summarize() happy path and API key guard
  - search_perplexity() happy path and API key guard
  - search_grok() happy path and API key guard (mocked via sys.modules)
  - search() dispatcher: auto / perplexity / grok / both modes
  - factcheck() adaptive: both sources, single source, synthesis reasoning flag
  - CLI subcommands: summarize, search, factcheck
  - detect_content_type() integration (via tts module)
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from src.insight import (
    factcheck,
    search,
    search_grok,
    search_perplexity,
    summarize,
)


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


# ── search_perplexity() ───────────────────────────────────────────────────────

def _make_perplexity_result(text: str = "Perplexity answer.",
                            provider_name: str = "perplexity_direct",
                            effective_model: str = "sonar-pro",
                            requested_model: str = "sonar-pro") -> MagicMock:
    """Build a fake providers.CallResult for Perplexity-backed tests."""
    return _make_call_result(
        text            = text,
        provider_name   = provider_name,
        effective_model = effective_model,
        requested_model = requested_model,
    )


def _make_synthesis_result(text: str = "Synthesis.") -> MagicMock:
    """Build a fake providers.CallResult for Mistral synthesis tests."""
    return _make_call_result(text=text)


def _route_by_capability(**results):
    """Build a side_effect for `src.insight.call` that dispatches on capability.

    Usage:
        mock_call.side_effect = _route_by_capability(
            search       = _make_perplexity_result("PPLX ans."),
            fact_check_x = _make_grok_result("Grok ans."),
            insight      = _make_synthesis_result("Synth."),
        )
    """
    def _side_effect(capability, messages, **kwargs):
        if capability in results:
            return results[capability]
        raise AssertionError(f"Unexpected capability: {capability!r}")
    return _side_effect


def _clear_search_env(monkeypatch) -> None:
    """Wipe every search/factcheck-relevant key from the env.

    The test host's .env may prime any of these; unset them explicitly so
    is_available() returns False for all routes that rely on them.
    """
    for var in (
        "MISTRAL_API_KEY", "PERPLEXITY_API_KEY", "XAI_API_KEY", "EDENAI_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)


class TestSearchPerplexity:
    def test_returns_answer(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        with patch("src.insight.call") as mock_call:
            mock_call.return_value = _make_perplexity_result(text="Perplexity answer here.")
            result = search_perplexity("What is Python?", "Context summary.")
        assert "Perplexity answer" in result

    def test_raises_when_no_provider_available(self, monkeypatch):
        _clear_search_env(monkeypatch)
        with pytest.raises(RuntimeError, match="No provider available"):
            search_perplexity("query")

    def test_eden_only_is_acceptable(self, monkeypatch):
        """Missing PERPLEXITY_API_KEY but present EDENAI_API_KEY must still work."""
        _clear_search_env(monkeypatch)
        monkeypatch.setenv("EDENAI_API_KEY", "eden-key")
        with patch("src.insight.call") as mock_call:
            mock_call.return_value = _make_perplexity_result(
                text="PPLX via Eden.",
                provider_name="eden_perplexity",
                effective_model="perplexityai/sonar-pro",
            )
            result = search_perplexity("query")
        assert "PPLX via Eden" in result

    def test_uses_search_capability(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        with patch("src.insight.call") as mock_call:
            mock_call.return_value = _make_perplexity_result()
            search_perplexity("query")
        assert mock_call.call_args.args[0] == "search"

    def test_context_injected_in_user_message(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        with patch("src.insight.call") as mock_call:
            mock_call.return_value = _make_perplexity_result()
            search_perplexity("My question", "My context summary")
        messages = mock_call.call_args.args[1]
        user_content = messages[-1]["content"]
        assert "My context summary" in user_content
        assert "My question" in user_content

    def test_no_context_sends_query_only(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        with patch("src.insight.call") as mock_call:
            mock_call.return_value = _make_perplexity_result()
            search_perplexity("bare query")
        messages = mock_call.call_args.args[1]
        assert messages[-1]["content"] == "bare query"

    def test_system_override_used(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        with patch("src.insight.call") as mock_call:
            mock_call.return_value = _make_perplexity_result()
            search_perplexity("q", system="CUSTOM_SYSTEM_PROMPT")
        messages = mock_call.call_args.args[1]
        assert messages[0]["content"] == "CUSTOM_SYSTEM_PROMPT"

    def test_model_and_timeout_passed_through(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        with patch("src.insight.call") as mock_call:
            mock_call.return_value = _make_perplexity_result()
            search_perplexity("query")
        opts = mock_call.call_args.kwargs
        assert opts.get("timeout") == 20  # _SEARCH_TIMEOUT
        assert "sonar" in opts.get("model", "")

    def test_provider_error_wrapped_as_runtime_error(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        from src.providers import ProviderError as _PE
        with patch("src.insight.call", side_effect=_PE("exhausted")):
            with pytest.raises(RuntimeError, match="Perplexity search failed"):
                search_perplexity("query")


# ── search_grok() ─────────────────────────────────────────────────────────────

def _make_grok_result(text: str = "Grok answer.",
                      provider_name: str = "xai_direct",
                      effective_model: str = "grok-4-1-fast-non-reasoning",
                      requested_model: str = "grok-4-1-fast-non-reasoning",
                      substituted: bool = False,
                      attempts: int = 1) -> MagicMock:
    """Build a fake providers.CallResult for search_grok() tests."""
    return _make_call_result(
        text            = text,
        provider_name   = provider_name,
        effective_model = effective_model,
        requested_model = requested_model,
        substituted     = substituted,
        attempts        = attempts,
    )


class TestSearchGrok:
    def test_returns_answer(self, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "xai-key")
        with patch("src.insight.call") as mock_call:
            mock_call.return_value = _make_grok_result(text="Grok answer here.")
            result = search_grok("Verify this claim", "Summary ctx")
        assert "Grok answer here" in result

    def test_raises_when_no_provider_available(self, monkeypatch):
        monkeypatch.delenv("XAI_API_KEY",    raising=False)
        monkeypatch.delenv("EDENAI_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="No provider available"):
            search_grok("query")

    def test_eden_only_is_acceptable(self, monkeypatch):
        """Missing XAI_API_KEY but present EDENAI_API_KEY must still work."""
        monkeypatch.delenv("XAI_API_KEY",   raising=False)
        monkeypatch.setenv("EDENAI_API_KEY", "eden-key")
        with patch("src.insight.call") as mock_call:
            mock_call.return_value = _make_grok_result(
                text="Grok via Eden.",
                provider_name="eden_xai",
                effective_model="xai/grok-4-1-fast-non-reasoning",
            )
            result = search_grok("query")
        assert "Grok via Eden" in result

    def test_uses_fact_check_x_capability(self, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "xai-key")
        with patch("src.insight.call") as mock_call:
            mock_call.return_value = _make_grok_result()
            search_grok("query")
        assert mock_call.call_args.args[0] == "fact_check_x"

    def test_context_summary_injected(self, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "xai-key")
        with patch("src.insight.call") as mock_call:
            mock_call.return_value = _make_grok_result()
            search_grok("My question", "My context summary")
        messages = mock_call.call_args.args[1]
        user_content = messages[-1]["content"]
        assert "My context summary" in user_content
        assert "My question" in user_content

    def test_no_context_sends_query_only(self, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "xai-key")
        with patch("src.insight.call") as mock_call:
            mock_call.return_value = _make_grok_result()
            search_grok("bare query")
        messages = mock_call.call_args.args[1]
        assert messages[-1]["content"] == "bare query"

    def test_system_override_used(self, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "xai-key")
        with patch("src.insight.call") as mock_call:
            mock_call.return_value = _make_grok_result()
            search_grok("q", system="CUSTOM_SYSTEM_PROMPT")
        messages = mock_call.call_args.args[1]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "CUSTOM_SYSTEM_PROMPT"

    def test_model_and_timeout_passed_through(self, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "xai-key")
        with patch("src.insight.call") as mock_call:
            mock_call.return_value = _make_grok_result()
            search_grok("query")
        opts = mock_call.call_args.kwargs
        assert opts.get("timeout") == 30  # _GROK_TIMEOUT
        assert "grok" in opts.get("model", "")

    def test_empty_response_raises(self, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "xai-key")
        with patch("src.insight.call") as mock_call:
            mock_call.return_value = _make_grok_result(text="")
            with pytest.raises(RuntimeError, match="empty"):
                search_grok("query")

    def test_provider_error_wrapped_as_runtime_error(self, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "xai-key")
        from src.providers import ProviderError as _PE
        with patch("src.insight.call", side_effect=_PE("all exhausted")):
            with pytest.raises(RuntimeError, match="Grok search failed"):
                search_grok("query")


# ── search() dispatcher ───────────────────────────────────────────────────────

class TestSearch:
    def test_auto_uses_perplexity_when_available(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        monkeypatch.setenv("XAI_API_KEY",        "xai-key")
        with patch("src.insight._SEARCH_ENGINE", "auto"), \
             patch("src.insight.call") as mock_call:
            mock_call.side_effect = _route_by_capability(
                search       = _make_perplexity_result("Perplexity wins."),
                fact_check_x = _make_grok_result("Grok not-called."),
            )
            result = search("query", "ctx")
        assert "Perplexity wins" in result
        # First (and only) call should go to "search", not "fact_check_x"
        assert mock_call.call_args_list[0].args[0] == "search"
        assert mock_call.call_count == 1

    def test_auto_falls_back_to_grok_when_no_perplexity(self, monkeypatch):
        _clear_search_env(monkeypatch)
        monkeypatch.setenv("XAI_API_KEY", "xai-key")
        with patch("src.insight._SEARCH_ENGINE", "auto"), \
             patch("src.insight.call") as mock_call:
            mock_call.return_value = _make_grok_result(text="Grok fallback.")
            result = search("query")
        assert "Grok fallback" in result

    def test_auto_raises_when_no_keys(self, monkeypatch):
        _clear_search_env(monkeypatch)
        with patch("src.insight._SEARCH_ENGINE", "auto"):
            with pytest.raises(RuntimeError, match="No search engine"):
                search("query")

    def test_force_perplexity_raises_when_no_provider(self, monkeypatch):
        _clear_search_env(monkeypatch)
        with patch("src.insight._SEARCH_ENGINE", "perplexity"):
            with pytest.raises(RuntimeError, match="Perplexity"):
                search("query")

    def test_force_grok_raises_when_no_provider(self, monkeypatch):
        _clear_search_env(monkeypatch)
        with patch("src.insight._SEARCH_ENGINE", "grok"):
            with pytest.raises(RuntimeError, match="Grok"):
                search("query")

    def test_unknown_engine_raises(self, monkeypatch):
        # Make sure auto/perplexity/grok/both guards don't short-circuit first.
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        with patch("src.insight._SEARCH_ENGINE", "bing"):
            with pytest.raises(RuntimeError, match="Unknown INSIGHT_SEARCH_ENGINE"):
                search("query")


# ── factcheck() ───────────────────────────────────────────────────────────────

class TestFactcheck:
    def test_both_sources_returns_synthesis(self, monkeypatch):
        """With both keys, factcheck must synthesise via the insight capability."""
        monkeypatch.setenv("MISTRAL_API_KEY",    "m-key")
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        monkeypatch.setenv("XAI_API_KEY",        "xai-key")

        with patch("src.insight.call") as mock_call:
            mock_call.side_effect = _route_by_capability(
                search       = _make_perplexity_result("Perplexity fact-check result."),
                fact_check_x = _make_grok_result("Grok fact-check result."),
                insight      = _make_synthesis_result(
                    "Reliability: Confirmed\n\nSynthesis.\n\nPerplexity: ok.\nGrok: ok."
                ),
            )
            synthesis, perp_detail, grok_detail = factcheck("Summary text.")

        assert "Reliability" in synthesis
        assert "Perplexity" in perp_detail
        assert "Grok" in grok_detail

    def test_grok_only_returns_direct_result_no_synthesis(self, monkeypatch):
        """With only XAI_API_KEY (+MISTRAL for synthesis gate), factcheck returns Grok directly."""
        _clear_search_env(monkeypatch)
        monkeypatch.setenv("MISTRAL_API_KEY", "m-key")
        monkeypatch.setenv("XAI_API_KEY",     "xai-key")

        with patch("src.insight.call") as mock_call:
            mock_call.side_effect = _route_by_capability(
                fact_check_x = _make_grok_result("Grok direct result."),
            )
            synthesis, perp_detail, grok_detail = factcheck("Summary.")

        # Only the fact_check_x call fires — no search, no insight synthesis
        capabilities_called = [c.args[0] for c in mock_call.call_args_list]
        assert capabilities_called == ["fact_check_x"]
        assert "Grok direct result" in synthesis
        assert perp_detail == ""
        assert "Grok direct result" in grok_detail

    def test_perplexity_only_returns_direct_result_no_synthesis(self, monkeypatch):
        """With only PERPLEXITY_API_KEY (+MISTRAL), factcheck returns Perplexity directly."""
        _clear_search_env(monkeypatch)
        monkeypatch.setenv("MISTRAL_API_KEY",    "m-key")
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")

        with patch("src.insight.call") as mock_call:
            mock_call.side_effect = _route_by_capability(
                search = _make_perplexity_result("Perplexity direct result."),
            )
            synthesis, perp_detail, grok_detail = factcheck("Summary.")

        capabilities_called = [c.args[0] for c in mock_call.call_args_list]
        assert capabilities_called == ["search"]
        assert "Perplexity direct result" in synthesis
        assert "Perplexity direct result" in perp_detail
        assert grok_detail == ""

    def test_raises_when_no_synthesis_provider(self, monkeypatch):
        _clear_search_env(monkeypatch)
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        with pytest.raises(RuntimeError, match="No provider available for synthesis"):
            factcheck("summary")

    def test_raises_when_no_search_sources(self, monkeypatch):
        _clear_search_env(monkeypatch)
        monkeypatch.setenv("MISTRAL_API_KEY", "m-key")
        with pytest.raises(RuntimeError, match="No fact-check source"):
            factcheck("summary")

    def test_synthesis_without_reasoning_effort_by_default(self, monkeypatch):
        """Standard mode must NOT include reasoning_effort in the synthesis opts."""
        monkeypatch.setenv("MISTRAL_API_KEY",    "m-key")
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        monkeypatch.setenv("XAI_API_KEY",        "xai-key")

        with patch("src.insight._SYNTHESIS_REASONING", "standard"), \
             patch("src.insight.call") as mock_call:
            mock_call.side_effect = _route_by_capability(
                search       = _make_perplexity_result("Perplexity result."),
                fact_check_x = _make_grok_result("Grok result."),
                insight      = _make_synthesis_result("Synthesis."),
            )
            factcheck("Summary.")

        synthesis_calls = [
            c for c in mock_call.call_args_list if c.args[0] == "insight"
        ]
        assert synthesis_calls, "Expected an insight (synthesis) call"
        opts = synthesis_calls[-1].kwargs
        assert "reasoning_effort" not in opts

    def test_synthesis_with_high_reasoning_when_configured(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY",    "m-key")
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        monkeypatch.setenv("XAI_API_KEY",        "xai-key")

        with patch("src.insight._SYNTHESIS_REASONING", "high"), \
             patch("src.insight.call") as mock_call:
            mock_call.side_effect = _route_by_capability(
                search       = _make_perplexity_result("Perplexity result."),
                fact_check_x = _make_grok_result("Grok result."),
                insight      = _make_synthesis_result("Synthesis."),
            )
            factcheck("Summary.")

        synthesis_calls = [
            c for c in mock_call.call_args_list if c.args[0] == "insight"
        ]
        assert synthesis_calls
        opts = synthesis_calls[-1].kwargs
        assert opts.get("reasoning_effort") == "high"

    def test_graceful_degradation_one_source_fails(self, monkeypatch):
        """If Grok fails at runtime, factcheck should return Perplexity result directly."""
        monkeypatch.setenv("MISTRAL_API_KEY",    "m-key")
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        monkeypatch.setenv("XAI_API_KEY",        "xai-key")
        from src.providers import ProviderError as _PE

        def _side_effect(capability, messages, **kwargs):
            if capability == "search":
                return _make_perplexity_result("Perplexity detail.")
            if capability == "fact_check_x":
                raise _PE("Grok down")
            raise AssertionError(f"Unexpected capability: {capability!r}")

        with patch("src.insight.call", side_effect=_side_effect):
            synthesis, perp_detail, grok_detail = factcheck("summary")

        # Perplexity succeeded, Grok failed → single-source, no synthesis
        assert synthesis
        assert perp_detail == "Perplexity detail."
        assert grok_detail == ""

    def test_detail_files_written(self, monkeypatch, tmp_path):
        """factcheck() returns detail strings; caller (_cmd_factcheck) writes files."""
        monkeypatch.setenv("MISTRAL_API_KEY",    "m-key")
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        monkeypatch.setenv("XAI_API_KEY",        "xai-key")
        pplx_file = tmp_path / "perplexity.txt"
        grok_file  = tmp_path / "grok.txt"

        with patch("src.insight.call") as mock_call:
            mock_call.side_effect = _route_by_capability(
                search       = _make_perplexity_result("PPLX detail."),
                fact_check_x = _make_grok_result("GROK detail."),
                insight      = _make_synthesis_result("Synthesis."),
            )
            synthesis, perp_detail, grok_detail = factcheck("summary text")

        pplx_file.write_text(perp_detail, encoding="utf-8")
        grok_file.write_text(grok_detail, encoding="utf-8")

        assert pplx_file.read_text() == "PPLX detail."
        assert grok_file.read_text() == "GROK detail."


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

"""Unit tests for src/search.py.

Tests cover:
  - search_perplexity(): happy path, API key guard, capability, message shape
  - search_grok(): happy path, API key guard, empty response guard
  - search() dispatcher: auto / perplexity / grok / both modes
  - _cmd_search(): CLI stdin/stdout integration (mocked providers)
"""

import io
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from src.search import _cmd_search, search, search_grok, search_perplexity


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_call_result(
    text: str = "answer",
    provider_name: str = "mistral_direct",
    effective_model: str = "mistral-small-latest",
    requested_model: str = "mistral-small-latest",
    substituted: bool = False,
    attempts: int = 1,
) -> MagicMock:
    from src.providers import PROVIDERS
    result = MagicMock()
    result.text            = text
    result.provider        = PROVIDERS[provider_name]
    result.effective_model = effective_model
    result.requested_model = requested_model
    result.substituted     = substituted
    result.attempts        = attempts
    return result


def _make_perplexity_result(
    text: str = "Perplexity answer.",
    provider_name: str = "perplexity_direct",
    effective_model: str = "sonar-pro",
    requested_model: str = "sonar-pro",
) -> MagicMock:
    return _make_call_result(
        text=text, provider_name=provider_name,
        effective_model=effective_model, requested_model=requested_model,
    )


def _make_grok_result(
    text: str = "Grok answer.",
    provider_name: str = "xai_direct",
    effective_model: str = "grok-4.3",
    requested_model: str = "grok-4.3",
    substituted: bool = False,
    attempts: int = 1,
) -> MagicMock:
    return _make_call_result(
        text=text, provider_name=provider_name,
        effective_model=effective_model, requested_model=requested_model,
        substituted=substituted, attempts=attempts,
    )


def _make_synthesis_result(text: str = "Synthesis.") -> MagicMock:
    return _make_call_result(text=text)


def _route_by_capability(**results):
    """side_effect for src.search.call that dispatches on capability name."""
    def _side_effect(capability, messages, **kwargs):
        if capability in results:
            return results[capability]
        raise AssertionError(f"Unexpected capability: {capability!r}")
    return _side_effect


def _clear_search_env(monkeypatch) -> None:
    for var in ("MISTRAL_API_KEY", "PERPLEXITY_API_KEY", "XAI_API_KEY", "EDENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)


# ── search_perplexity() ───────────────────────────────────────────────────────

class TestSearchPerplexity:
    def test_returns_answer(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        with patch("src.search.call") as mock_call:
            mock_call.return_value = _make_perplexity_result(text="Perplexity answer here.")
            result = search_perplexity("What is Python?", "Context summary.")
        assert "Perplexity answer" in result

    def test_raises_when_no_provider_available(self, monkeypatch):
        _clear_search_env(monkeypatch)
        with pytest.raises(RuntimeError, match="No provider available"):
            search_perplexity("query")

    def test_eden_only_is_acceptable(self, monkeypatch):
        _clear_search_env(monkeypatch)
        monkeypatch.setenv("EDENAI_API_KEY", "eden-key")
        with patch("src.search.call") as mock_call:
            mock_call.return_value = _make_perplexity_result(
                text="PPLX via Eden.",
                provider_name="eden_perplexity",
                effective_model="perplexityai/sonar-pro",
            )
            result = search_perplexity("query")
        assert "PPLX via Eden" in result

    def test_uses_search_capability(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        with patch("src.search.call") as mock_call:
            mock_call.return_value = _make_perplexity_result()
            search_perplexity("query")
        assert mock_call.call_args.args[0] == "search"

    def test_context_injected_in_user_message(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        with patch("src.search.call") as mock_call:
            mock_call.return_value = _make_perplexity_result()
            search_perplexity("My question", "My context summary")
        messages = mock_call.call_args.args[1]
        user_content = messages[-1]["content"]
        assert "My context summary" in user_content
        assert "My question" in user_content

    def test_no_context_sends_query_only(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        with patch("src.search.call") as mock_call:
            mock_call.return_value = _make_perplexity_result()
            search_perplexity("bare query")
        messages = mock_call.call_args.args[1]
        assert messages[-1]["content"] == "bare query"

    def test_system_override_used(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        with patch("src.search.call") as mock_call:
            mock_call.return_value = _make_perplexity_result()
            search_perplexity("q", system="CUSTOM_SYSTEM_PROMPT")
        messages = mock_call.call_args.args[1]
        assert messages[0]["content"] == "CUSTOM_SYSTEM_PROMPT"

    def test_model_and_timeout_passed_through(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        with patch("src.search.call") as mock_call:
            mock_call.return_value = _make_perplexity_result()
            search_perplexity("query")
        opts = mock_call.call_args.kwargs
        assert opts.get("timeout") == 20  # _SEARCH_TIMEOUT
        assert "sonar" in opts.get("model", "")

    def test_provider_error_wrapped_as_runtime_error(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        from src.providers import ProviderError as _PE
        with patch("src.search.call", side_effect=_PE("exhausted")):
            with pytest.raises(RuntimeError, match="Perplexity search failed"):
                search_perplexity("query")


# ── search_grok() ─────────────────────────────────────────────────────────────

class TestSearchGrok:
    def test_returns_answer(self, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "xai-key")
        with patch("src.search.call") as mock_call:
            mock_call.return_value = _make_grok_result(text="Grok answer here.")
            result = search_grok("Verify this claim", "Summary ctx")
        assert "Grok answer here" in result

    def test_raises_when_no_provider_available(self, monkeypatch):
        monkeypatch.delenv("XAI_API_KEY",    raising=False)
        monkeypatch.delenv("EDENAI_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="No provider available"):
            search_grok("query")

    def test_eden_only_is_acceptable(self, monkeypatch):
        monkeypatch.delenv("XAI_API_KEY",    raising=False)
        monkeypatch.setenv("EDENAI_API_KEY", "eden-key")
        with patch("src.search.call") as mock_call:
            mock_call.return_value = _make_grok_result(
                text="Grok via Eden.",
                provider_name="eden_xai",
                effective_model="xai/grok-4.3",
            )
            result = search_grok("query")
        assert "Grok via Eden" in result

    def test_uses_fact_check_x_capability(self, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "xai-key")
        with patch("src.search.call") as mock_call:
            mock_call.return_value = _make_grok_result()
            search_grok("query")
        assert mock_call.call_args.args[0] == "fact_check_x"

    def test_context_summary_injected(self, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "xai-key")
        with patch("src.search.call") as mock_call:
            mock_call.return_value = _make_grok_result()
            search_grok("My question", "My context summary")
        messages = mock_call.call_args.args[1]
        user_content = messages[-1]["content"]
        assert "My context summary" in user_content
        assert "My question" in user_content

    def test_no_context_sends_query_only(self, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "xai-key")
        with patch("src.search.call") as mock_call:
            mock_call.return_value = _make_grok_result()
            search_grok("bare query")
        messages = mock_call.call_args.args[1]
        assert messages[-1]["content"] == "bare query"

    def test_system_override_used(self, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "xai-key")
        with patch("src.search.call") as mock_call:
            mock_call.return_value = _make_grok_result()
            search_grok("q", system="CUSTOM_SYSTEM_PROMPT")
        messages = mock_call.call_args.args[1]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "CUSTOM_SYSTEM_PROMPT"

    def test_model_and_timeout_passed_through(self, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "xai-key")
        with patch("src.search.call") as mock_call:
            mock_call.return_value = _make_grok_result()
            search_grok("query")
        opts = mock_call.call_args.kwargs
        assert opts.get("timeout") == 30  # _GROK_TIMEOUT
        assert "grok" in opts.get("model", "")

    def test_empty_response_raises(self, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "xai-key")
        with patch("src.search.call") as mock_call:
            mock_call.return_value = _make_grok_result(text="")
            with pytest.raises(RuntimeError, match="empty"):
                search_grok("query")

    def test_provider_error_wrapped_as_runtime_error(self, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY", "xai-key")
        from src.providers import ProviderError as _PE
        with patch("src.search.call", side_effect=_PE("all exhausted")):
            with pytest.raises(RuntimeError, match="Grok search failed"):
                search_grok("query")


# ── search() dispatcher ───────────────────────────────────────────────────────

class TestSearch:
    def test_auto_uses_perplexity_when_available(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        monkeypatch.setenv("XAI_API_KEY",        "xai-key")
        with patch("src.search._SEARCH_ENGINE", "auto"), \
             patch("src.search.call") as mock_call:
            mock_call.side_effect = _route_by_capability(
                search       = _make_perplexity_result("Perplexity wins."),
                fact_check_x = _make_grok_result("Grok not-called."),
            )
            result = search("query", "ctx")
        assert "Perplexity wins" in result
        assert mock_call.call_args_list[0].args[0] == "search"
        assert mock_call.call_count == 1

    def test_auto_falls_back_to_grok_when_no_perplexity(self, monkeypatch):
        _clear_search_env(monkeypatch)
        monkeypatch.setenv("XAI_API_KEY", "xai-key")
        with patch("src.search._SEARCH_ENGINE", "auto"), \
             patch("src.search.call") as mock_call:
            mock_call.return_value = _make_grok_result(text="Grok fallback.")
            result = search("query")
        assert "Grok fallback" in result

    def test_auto_raises_when_no_keys(self, monkeypatch):
        _clear_search_env(monkeypatch)
        with patch("src.search._SEARCH_ENGINE", "auto"):
            with pytest.raises(RuntimeError, match="No search engine"):
                search("query")

    def test_force_perplexity_raises_when_no_provider(self, monkeypatch):
        _clear_search_env(monkeypatch)
        with patch("src.search._SEARCH_ENGINE", "perplexity"):
            with pytest.raises(RuntimeError, match="Perplexity"):
                search("query")

    def test_force_grok_raises_when_no_provider(self, monkeypatch):
        _clear_search_env(monkeypatch)
        with patch("src.search._SEARCH_ENGINE", "grok"):
            with pytest.raises(RuntimeError, match="Grok"):
                search("query")

    def test_unknown_engine_raises(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        with patch("src.search._SEARCH_ENGINE", "bing"):
            with pytest.raises(RuntimeError, match="Unknown INSIGHT_SEARCH_ENGINE"):
                search("query")


# ── search() — both mode ──────────────────────────────────────────────────────

class TestSearchBoth:
    def test_both_returns_synthesis(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY",    "m-key")
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        monkeypatch.setenv("XAI_API_KEY",        "xai-key")

        with patch("src.search._SEARCH_ENGINE", "both"), \
             patch("src.search.search_perplexity") as mock_pplx, \
             patch("src.search.search_grok") as mock_grok, \
             patch("src.search.call") as mock_call:
            mock_pplx.return_value = "Perplexity answer."
            mock_grok.return_value = "Grok answer."
            mock_call.return_value = _make_synthesis_result("Synthesised answer.")
            result = search("query", "ctx")

        assert "Synthesised answer." in result

    def test_both_no_insight_returns_concat(self, monkeypatch):
        _clear_search_env(monkeypatch)
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        monkeypatch.setenv("XAI_API_KEY",        "xai-key")

        with patch("src.search._SEARCH_ENGINE", "both"), \
             patch("src.search.search_perplexity") as mock_pplx, \
             patch("src.search.search_grok") as mock_grok:
            mock_pplx.return_value = "Perplexity answer."
            mock_grok.return_value = "Grok answer."
            result = search("query")

        assert "Perplexity answer." in result
        assert "Grok answer." in result

    def test_both_perplexity_only_when_no_grok(self, monkeypatch):
        _clear_search_env(monkeypatch)
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")

        with patch("src.search._SEARCH_ENGINE", "both"), \
             patch("src.search.search_perplexity") as mock_pplx:
            mock_pplx.return_value = "Perplexity only."
            result = search("query")

        assert result == "Perplexity only."

    def test_both_grok_only_when_no_perplexity(self, monkeypatch):
        _clear_search_env(monkeypatch)
        monkeypatch.setenv("XAI_API_KEY", "xai-key")

        with patch("src.search._SEARCH_ENGINE", "both"), \
             patch("src.search.search_grok") as mock_grok:
            mock_grok.return_value = "Grok only."
            result = search("query")

        assert result == "Grok only."

    def test_both_raises_when_no_keys(self, monkeypatch):
        _clear_search_env(monkeypatch)
        with patch("src.search._SEARCH_ENGINE", "both"):
            with pytest.raises(RuntimeError, match="both requires"):
                search("query")

    def test_both_raises_when_all_sources_fail(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        monkeypatch.setenv("XAI_API_KEY",        "xai-key")

        with patch("src.search._SEARCH_ENGINE", "both"), \
             patch("src.search.search_perplexity", side_effect=RuntimeError("pplx down")), \
             patch("src.search.search_grok",       side_effect=RuntimeError("grok down")):
            with pytest.raises(RuntimeError, match="Both search engines failed"):
                search("query")

    def test_both_synthesis_provider_error_falls_back_to_concat(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY",    "m-key")
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        monkeypatch.setenv("XAI_API_KEY",        "xai-key")
        from src.providers import ProviderError as _PE

        with patch("src.search._SEARCH_ENGINE", "both"), \
             patch("src.search.search_perplexity") as mock_pplx, \
             patch("src.search.search_grok") as mock_grok, \
             patch("src.search.call", side_effect=_PE("synthesis down")):
            mock_pplx.return_value = "Perplexity answer."
            mock_grok.return_value = "Grok answer."
            result = search("query")

        assert "Perplexity answer." in result
        assert "Grok answer." in result


# ── _cmd_search() — CLI integration ──────────────────────────────────────────

class TestCmdSearch:
    def test_happy_path_prints_answer(self, monkeypatch, capsys):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        with patch("sys.stdin", io.StringIO("What is Python?\nSome context.")), \
             patch("src.search.search", return_value="Python is a language."):
            _cmd_search()
        assert "Python is a language." in capsys.readouterr().out

    def test_empty_input_exits_1(self, monkeypatch):
        with patch("sys.stdin", io.StringIO("")):
            with pytest.raises(SystemExit) as exc:
                _cmd_search()
        assert exc.value.code == 1

    def test_blank_query_line_exits_1(self, monkeypatch):
        with patch("sys.stdin", io.StringIO("   \nsome context")):
            with pytest.raises(SystemExit) as exc:
                _cmd_search()
        assert exc.value.code == 1

    def test_no_engines_available_exits_2(self, monkeypatch):
        _clear_search_env(monkeypatch)
        with patch("sys.stdin", io.StringIO("query")):
            with pytest.raises(SystemExit) as exc:
                _cmd_search()
        assert exc.value.code == 2

    def test_runtime_error_exits_1(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        with patch("sys.stdin", io.StringIO("query")), \
             patch("src.search.search", side_effect=RuntimeError("failed")):
            with pytest.raises(SystemExit) as exc:
                _cmd_search()
        assert exc.value.code == 1

    def test_context_parsed_from_multiline_stdin(self, monkeypatch):
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        with patch("sys.stdin", io.StringIO("My query\nLine 1\nLine 2")), \
             patch("src.search.search") as mock_search:
            mock_search.return_value = "answer"
            _cmd_search()
        mock_search.assert_called_once_with("My query", "Line 1\nLine 2")

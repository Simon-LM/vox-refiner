"""Unit tests for src/factcheck.py.

Tests cover:
  - factcheck(): both sources → synthesis
  - factcheck(): single source (Grok-only, Perplexity-only) → direct result
  - factcheck(): error guards (no synthesis provider, no search sources)
  - factcheck(): reasoning_effort flag (standard vs high)
  - factcheck(): graceful degradation when one source fails at runtime
  - factcheck(): returned (synthesis, perp_detail, grok_detail) tuple
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from src.factcheck import factcheck


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


def _clear_search_env(monkeypatch) -> None:
    for var in ("MISTRAL_API_KEY", "PERPLEXITY_API_KEY", "XAI_API_KEY", "EDENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)


# ── factcheck() ───────────────────────────────────────────────────────────────

class TestFactcheck:
    def test_both_sources_returns_synthesis(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY",    "m-key")
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        monkeypatch.setenv("XAI_API_KEY",        "xai-key")

        with patch("src.factcheck.search_perplexity") as mock_pplx, \
             patch("src.factcheck.search_grok") as mock_grok, \
             patch("src.factcheck.call") as mock_call:
            mock_pplx.return_value = "Perplexity fact-check result."
            mock_grok.return_value = "Grok fact-check result."
            mock_call.return_value = _make_call_result(
                text="Reliability: Confirmed\n\nSynthesis.\n\nPerplexity: ok.\nGrok: ok."
            )
            synthesis, perp_detail, grok_detail = factcheck("Summary text.")

        assert "Reliability" in synthesis
        assert "Perplexity" in perp_detail
        assert "Grok" in grok_detail

    def test_grok_only_returns_direct_result_no_synthesis(self, monkeypatch):
        _clear_search_env(monkeypatch)
        monkeypatch.setenv("MISTRAL_API_KEY", "m-key")
        monkeypatch.setenv("XAI_API_KEY",     "xai-key")

        with patch("src.factcheck.search_grok") as mock_grok, \
             patch("src.factcheck.call") as mock_call:
            mock_grok.return_value = "Grok direct result."
            synthesis, perp_detail, grok_detail = factcheck("Summary.")

        mock_call.assert_not_called()
        assert "Grok direct result" in synthesis
        assert perp_detail == ""
        assert "Grok direct result" in grok_detail

    def test_perplexity_only_returns_direct_result_no_synthesis(self, monkeypatch):
        _clear_search_env(monkeypatch)
        monkeypatch.setenv("MISTRAL_API_KEY",    "m-key")
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")

        with patch("src.factcheck.search_perplexity") as mock_pplx, \
             patch("src.factcheck.call") as mock_call:
            mock_pplx.return_value = "Perplexity direct result."
            synthesis, perp_detail, grok_detail = factcheck("Summary.")

        mock_call.assert_not_called()
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
        monkeypatch.setenv("MISTRAL_API_KEY",    "m-key")
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        monkeypatch.setenv("XAI_API_KEY",        "xai-key")

        with patch("src.factcheck._SYNTHESIS_REASONING", "standard"), \
             patch("src.factcheck.search_perplexity") as mock_pplx, \
             patch("src.factcheck.search_grok") as mock_grok, \
             patch("src.factcheck.call") as mock_call:
            mock_pplx.return_value = "Perplexity result."
            mock_grok.return_value = "Grok result."
            mock_call.return_value = _make_call_result(text="Synthesis.")
            factcheck("Summary.")

        opts = mock_call.call_args.kwargs
        assert "reasoning_effort" not in opts

    def test_synthesis_with_high_reasoning_when_configured(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY",    "m-key")
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        monkeypatch.setenv("XAI_API_KEY",        "xai-key")

        with patch("src.factcheck._SYNTHESIS_REASONING", "high"), \
             patch("src.factcheck.search_perplexity") as mock_pplx, \
             patch("src.factcheck.search_grok") as mock_grok, \
             patch("src.factcheck.call") as mock_call:
            mock_pplx.return_value = "Perplexity result."
            mock_grok.return_value = "Grok result."
            mock_call.return_value = _make_call_result(text="Synthesis.")
            factcheck("Summary.")

        opts = mock_call.call_args.kwargs
        assert opts.get("reasoning_effort") == "high"

    def test_graceful_degradation_one_source_fails(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY",    "m-key")
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        monkeypatch.setenv("XAI_API_KEY",        "xai-key")

        with patch("src.factcheck.search_perplexity") as mock_pplx, \
             patch("src.factcheck.search_grok") as mock_grok:
            mock_pplx.return_value = "Perplexity detail."
            mock_grok.side_effect  = RuntimeError("Grok down")
            synthesis, perp_detail, grok_detail = factcheck("summary")

        assert synthesis
        assert perp_detail == "Perplexity detail."
        assert grok_detail == ""

    def test_detail_values_returned(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MISTRAL_API_KEY",    "m-key")
        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-key")
        monkeypatch.setenv("XAI_API_KEY",        "xai-key")

        with patch("src.factcheck.search_perplexity") as mock_pplx, \
             patch("src.factcheck.search_grok") as mock_grok, \
             patch("src.factcheck.call") as mock_call:
            mock_pplx.return_value = "PPLX detail."
            mock_grok.return_value = "GROK detail."
            mock_call.return_value = _make_call_result(text="Synthesis.")
            synthesis, perp_detail, grok_detail = factcheck("summary text")

        assert perp_detail == "PPLX detail."
        assert grok_detail == "GROK detail."

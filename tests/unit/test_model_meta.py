"""Unit tests for the provider/model metadata file plumbing.

Two files write a small plain-text "meta" file that the shell scripts read
to show the actual provider + effective model in result headers:

  * src.insight._write_model_meta(result)   → INSIGHT_MODEL_META_FILE
  * src.refine.refine(...)                  → VOXTRAL_MODELS_FILE (lines 3-5)

These tests lock the on-disk format so shell readers stay in sync.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


def _make_result(
    *,
    provider_name: str = "mistral_direct",
    requested_model: str = "mistral-small-latest",
    effective_model: str = "mistral-small-latest",
    substituted: bool = False,
    text: str = "ok",
    attempts: int = 1,
):
    """Build a fake providers.CallResult with the fields used by meta writers."""
    from src.providers import PROVIDERS
    result = MagicMock()
    result.text             = text
    result.provider         = PROVIDERS[provider_name]
    result.requested_model  = requested_model
    result.effective_model  = effective_model
    result.substituted      = substituted
    result.attempts         = attempts
    return result


class TestInsightModelMeta:
    """src.insight._write_model_meta writes 5-line meta when env is set."""

    def test_writes_five_lines_on_happy_path(self, monkeypatch, tmp_path):
        from src.insight import _write_model_meta

        meta = tmp_path / "model_meta"
        monkeypatch.setenv("INSIGHT_MODEL_META_FILE", str(meta))

        _write_model_meta(_make_result())

        lines = meta.read_text(encoding="utf-8").splitlines()
        assert lines == [
            "mistral-small-latest",   # requested
            "mistral-small-latest",   # effective
            "mistral_direct",         # provider internal name
            "Mistral (direct)",       # provider display
            "0",                      # substituted
        ]

    def test_writes_substituted_flag_when_eden_substitutes(self, monkeypatch, tmp_path):
        from src.insight import _write_model_meta

        meta = tmp_path / "model_meta"
        monkeypatch.setenv("INSIGHT_MODEL_META_FILE", str(meta))

        _write_model_meta(_make_result(
            provider_name="eden_mistral",
            requested_model="magistral-small-latest",
            effective_model="mistral/mistral-small-latest",
            substituted=True,
        ))

        lines = meta.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "magistral-small-latest"
        assert lines[1] == "mistral/mistral-small-latest"
        assert lines[2] == "eden_mistral"
        assert lines[4] == "1"

    def test_silent_when_env_not_set(self, monkeypatch, tmp_path):
        from src.insight import _write_model_meta

        monkeypatch.delenv("INSIGHT_MODEL_META_FILE", raising=False)
        # Must not raise when env var is absent.
        _write_model_meta(_make_result())

    def test_summarize_writes_meta(self, monkeypatch, tmp_path):
        """End-to-end: summarize() writes meta via _log_call_result."""
        from src.insight import summarize

        meta = tmp_path / "summary_meta"
        monkeypatch.setenv("MISTRAL_API_KEY", "k")
        monkeypatch.setenv("INSIGHT_MODEL_META_FILE", str(meta))

        with patch("src.insight.call") as mock_call:
            mock_call.return_value = _make_result(text="• bullet.")
            summarize("text")

        assert meta.exists()
        lines = meta.read_text(encoding="utf-8").splitlines()
        assert lines[2] == "mistral_direct"
        assert lines[3] == "Mistral (direct)"


class TestRefineModelsFile:
    """src.refine.refine extends VOXTRAL_MODELS_FILE with lines 3-6."""

    def test_models_file_contains_effective_and_provider(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MISTRAL_API_KEY", "k")
        monkeypatch.setenv("REFINE_COMPARE_MODELS", "false")
        monkeypatch.setenv("REFINE_MODEL_SHORT", "mistral-small-latest")

        if "src.refine" in sys.modules:
            del sys.modules["src.refine"]
        import src.refine as refine

        models_file = tmp_path / "models_info"
        monkeypatch.setenv("VOXTRAL_MODELS_FILE", str(models_file))

        with patch("src.refine.call") as mock_call:
            mock_call.return_value = _make_result(
                provider_name="mistral_direct",
                requested_model="mistral-small-latest",
                effective_model="mistral-small-latest",
                text="refined.",
            )
            refine.refine("hello world")

        lines = models_file.read_text(encoding="utf-8").splitlines()
        assert len(lines) >= 6
        # line 1: requested; line 3: effective; line 4: provider name;
        # line 5: provider display; line 6: substituted
        assert lines[0] == "mistral-small-latest"
        assert lines[2] == "mistral-small-latest"
        assert lines[3] == "mistral_direct"
        assert lines[4] == "Mistral (direct)"
        assert lines[5] == "0"

    def test_models_file_reflects_substitution(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MISTRAL_API_KEY", "k")
        monkeypatch.setenv("REFINE_COMPARE_MODELS", "false")

        if "src.refine" in sys.modules:
            del sys.modules["src.refine"]
        import src.refine as refine

        models_file = tmp_path / "models_info"
        monkeypatch.setenv("VOXTRAL_MODELS_FILE", str(models_file))

        with patch("src.refine.call") as mock_call:
            mock_call.return_value = _make_result(
                provider_name="eden_mistral",
                requested_model="magistral-small-latest",
                effective_model="mistral/mistral-small-latest",
                substituted=True,
                text="refined.",
            )
            refine.refine("hello world")

        lines = models_file.read_text(encoding="utf-8").splitlines()
        assert lines[2] == "mistral/mistral-small-latest"
        assert lines[3] == "eden_mistral"
        assert lines[5] == "1"

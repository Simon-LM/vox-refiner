"""Integration tests for the shell helper _model_label_suffix in src/text_flows.sh.

Locks the on-screen label format so it stays aligned with the meta-file layout
written by src/insight.py::_write_model_meta and src/refine.py.
"""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "src" / "text_flows.sh"


def _run(meta_content: str, tmp_path: Path) -> str:
    """Source text_flows.sh, call _model_label_suffix <meta_file>, capture stdout."""
    meta = tmp_path / "meta"
    meta.write_text(meta_content, encoding="utf-8")
    # Minimal stubs for symbols the sourced file references during its load time.
    # text_flows.sh only defines functions at source time — no side effects — so
    # sourcing alone should not require any caller-provided globals.
    cmd = f'source "{SCRIPT}" && _model_label_suffix "{meta}"'
    proc = subprocess.run(
        ["bash", "-c", cmd], check=True, capture_output=True, text=True
    )
    return proc.stdout


class TestModelLabelSuffix:
    def test_happy_path_mistral_direct(self, tmp_path):
        meta = "\n".join([
            "mistral-small-latest",
            "mistral-small-latest",
            "mistral_direct",
            "Mistral (direct)",
            "0",
        ])
        assert _run(meta, tmp_path) == " — mistral-small-latest"

    def test_happy_path_any_direct_provider(self, tmp_path):
        """xai_direct / perplexity_direct also get the plain "— model" treatment."""
        meta = "\n".join([
            "grok-4-1-fast-non-reasoning",
            "grok-4-1-fast-non-reasoning",
            "xai_direct",
            "xAI / Grok (direct)",
            "0",
        ])
        assert _run(meta, tmp_path) == " — grok-4-1-fast-non-reasoning"

    def test_eden_provider(self, tmp_path):
        meta = "\n".join([
            "mistral-small-latest",
            "mistral/mistral-small-latest",
            "eden_mistral",
            "Mistral via Eden AI",
            "0",
        ])
        assert _run(meta, tmp_path) == " — mistral/mistral-small-latest (via Eden AI)"

    def test_eden_substitution_still_shows_eden_tag(self, tmp_path):
        """Substitution is Eden-only; format stays the Eden one, not a 'substituted from' hint."""
        meta = "\n".join([
            "magistral-small-latest",
            "mistral/mistral-small-latest",
            "eden_mistral",
            "Mistral via Eden AI",
            "1",
        ])
        assert _run(meta, tmp_path) == " — mistral/mistral-small-latest (via Eden AI)"

    def test_direct_provider_with_substituted_flag_from_different_model(self, tmp_path):
        """Direct provider + substituted=1 (theoretical) — show a substitution note."""
        meta = "\n".join([
            "magistral-small-latest",
            "mistral-small-latest",
            "mistral_direct",
            "Mistral (direct)",
            "1",
        ])
        assert _run(meta, tmp_path) == " — mistral-small-latest (substituted from magistral-small-latest)"

    def test_empty_file_returns_empty(self, tmp_path):
        # Empty file: helper returns nothing.
        assert _run("", tmp_path) == ""

    def test_missing_provider_fields_falls_back_to_plain_model(self, tmp_path):
        """Meta file with only requested+effective (no provider info) uses the empty
        provider-name branch — plain '— model' output, no provider suffix."""
        meta = "\n".join([
            "mistral-small-latest",
            "mistral-small-latest",
            "",  # provider name missing
            "",  # provider display missing
            "0",
        ])
        assert _run(meta, tmp_path) == " — mistral-small-latest"

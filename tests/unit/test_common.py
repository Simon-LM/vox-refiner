"""Unit tests for src/common.py — pure functions and constants.

Covers:
  SECURITY_BLOCK             — content sanity
  MODEL_SPEED_FACTOR         — known model entries and unknown fallback
  REASONING_CAPABLE_MODEL    — value
  REASONING_EFFORT_TIMEOUT_FACTOR — value
  compute_timing()           — all 10 brackets, boundary values, background flag
  effective_timeout()        — ENABLE_TIMEOUT=False → None, factor application,
                               reasoning_effort multiplier, max() guarantee
  load_context()             — file present, file absent
"""

from pathlib import Path
from unittest.mock import patch

import pytest

import src.common as common
from src.common import (
    REASONING_CAPABLE_MODEL,
    REASONING_EFFORT_TIMEOUT_FACTOR,
    SECURITY_BLOCK,
    compute_timing,
    effective_timeout,
    load_context,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_security_block_non_empty(self):
        assert SECURITY_BLOCK and isinstance(SECURITY_BLOCK, str)

    def test_security_block_mentions_transcription(self):
        assert "transcription" in SECURITY_BLOCK.lower()

    def test_security_block_warns_about_prompt_injection(self):
        assert "ignore previous instructions" in SECURITY_BLOCK.lower() \
            or "ignore" in SECURITY_BLOCK.lower()

    def test_reasoning_capable_model_is_mistral_small(self):
        assert REASONING_CAPABLE_MODEL == "mistral-small-latest"

    def test_reasoning_effort_factor_is_1_8(self):
        assert REASONING_EFFORT_TIMEOUT_FACTOR == pytest.approx(1.8)


# ---------------------------------------------------------------------------
# MODEL_SPEED_FACTOR
# ---------------------------------------------------------------------------

class TestModelSpeedFactor:
    def test_mistral_small_factor_is_1(self):
        assert common.MODEL_SPEED_FACTOR["mistral-small-latest"] == pytest.approx(1.0)

    def test_mistral_medium_factor_greater_than_1(self):
        assert common.MODEL_SPEED_FACTOR["mistral-medium-latest"] > 1.0

    def test_magistral_medium_factor_greater_than_small(self):
        assert common.MODEL_SPEED_FACTOR["magistral-medium-latest"] > \
               common.MODEL_SPEED_FACTOR["mistral-small-latest"]

    def test_magistral_small_factor_present(self):
        assert "magistral-small-latest" in common.MODEL_SPEED_FACTOR

    def test_devstral_latest_present(self):
        assert "devstral-latest" in common.MODEL_SPEED_FACTOR

    def test_unknown_model_not_in_table(self):
        assert "nonexistent-model" not in common.MODEL_SPEED_FACTOR

    def test_all_factors_positive(self):
        for model, factor in common.MODEL_SPEED_FACTOR.items():
            assert factor > 0, f"Non-positive factor for {model}"


# ---------------------------------------------------------------------------
# compute_timing
# ---------------------------------------------------------------------------

class TestComputeTimingBrackets:
    """Verify (timeout, delay) for each bracket using boundary values."""

    @pytest.mark.parametrize("words,expected_t,expected_d", [
        (0,     3,  1.0),   # < 30
        (1,     3,  1.0),
        (29,    3,  1.0),   # last in bracket
        (30,    4,  1.0),   # first in next bracket
        (89,    4,  1.0),   # last in bracket
        (90,    6,  1.5),   # < 180
        (179,   6,  1.5),
        (180,   8,  2.0),   # < 240
        (239,   8,  2.0),
        (240,   11, 2.0),   # < 400
        (399,   11, 2.0),
        (400,   15, 2.0),   # < 600
        (599,   15, 2.0),
        (600,   20, 3.0),   # < 1000
        (999,   20, 3.0),
        (1000,  30, 4.0),   # < 2000
        (1999,  30, 4.0),
        (2000,  50, 5.0),   # < 4000
        (3999,  50, 5.0),
        (4000,  80, 8.0),   # ≥ 4000
        (10000, 80, 8.0),
    ])
    def test_bracket(self, words, expected_t, expected_d):
        t, d = compute_timing(words)
        assert t == expected_t, f"words={words}: timeout {t} != {expected_t}"
        assert d == pytest.approx(expected_d), f"words={words}: delay {d} != {expected_d}"

    def test_returns_tuple_of_two(self):
        result = compute_timing(50)
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_timeout_is_int(self):
        t, _ = compute_timing(50)
        assert isinstance(t, int)

    def test_delay_is_float(self):
        _, d = compute_timing(50)
        assert isinstance(d, float)


class TestComputeTimingBackground:
    def test_background_doubles_timeout(self):
        t_normal, d_normal = compute_timing(50)
        t_bg, d_bg = compute_timing(50, background=True)
        assert t_bg == t_normal * 2

    def test_background_keeps_delay_unchanged(self):
        _, d_normal = compute_timing(50)
        _, d_bg = compute_timing(50, background=True)
        assert d_bg == pytest.approx(d_normal)

    def test_background_doubles_across_all_brackets(self):
        for words in (0, 30, 90, 180, 240, 400, 600, 1000, 2000, 4000):
            t_fg, _ = compute_timing(words)
            t_bg, _ = compute_timing(words, background=True)
            assert t_bg == t_fg * 2, f"words={words}"

    def test_background_false_is_default(self):
        assert compute_timing(50) == compute_timing(50, background=False)


# ---------------------------------------------------------------------------
# effective_timeout
# ---------------------------------------------------------------------------

class TestEffectiveTimeoutDisabled:
    """When ENABLE_TIMEOUT is False, always return None."""

    def test_returns_none_by_default(self, monkeypatch):
        monkeypatch.setattr(common, "ENABLE_TIMEOUT", False)
        assert effective_timeout(10, "mistral-small-latest") is None

    def test_returns_none_regardless_of_model(self, monkeypatch):
        monkeypatch.setattr(common, "ENABLE_TIMEOUT", False)
        for model in ("mistral-small-latest", "magistral-medium-latest", "unknown"):
            assert effective_timeout(10, model) is None

    def test_returns_none_with_reasoning_effort(self, monkeypatch):
        monkeypatch.setattr(common, "ENABLE_TIMEOUT", False)
        assert effective_timeout(10, "mistral-small-latest",
                                 {"reasoning_effort": "high"}) is None


class TestEffectiveTimeoutEnabled:
    """When ENABLE_TIMEOUT is True, apply speed factors."""

    def test_factor_1_returns_base_timeout(self, monkeypatch):
        monkeypatch.setattr(common, "ENABLE_TIMEOUT", True)
        # mistral-small-latest has factor 1.0 → max(10, 10) = 10
        assert effective_timeout(10, "mistral-small-latest") == 10

    def test_medium_model_increases_timeout(self, monkeypatch):
        monkeypatch.setattr(common, "ENABLE_TIMEOUT", True)
        # factor = 1.2 → round(10 * 1.2) = 12
        assert effective_timeout(10, "mistral-medium-latest") == 12

    def test_magistral_medium_large_factor(self, monkeypatch):
        monkeypatch.setattr(common, "ENABLE_TIMEOUT", True)
        # factor = 4.5 → round(10 * 4.5) = 45
        assert effective_timeout(10, "magistral-medium-latest") == 45

    def test_unknown_model_uses_factor_1(self, monkeypatch):
        monkeypatch.setattr(common, "ENABLE_TIMEOUT", True)
        assert effective_timeout(10, "some-unknown-model") == 10

    def test_result_never_less_than_base(self, monkeypatch):
        monkeypatch.setattr(common, "ENABLE_TIMEOUT", True)
        # If factor < 1 were ever introduced, max() must still protect base
        assert effective_timeout(20, "mistral-small-latest") >= 20

    def test_reasoning_effort_applies_extra_factor(self, monkeypatch):
        monkeypatch.setattr(common, "ENABLE_TIMEOUT", True)
        # factor=1.0, reasoning_effort → *1.8 → round(10*1.8)=18
        result = effective_timeout(10, "mistral-small-latest",
                                   {"reasoning_effort": "high"})
        assert result == 18

    def test_reasoning_effort_stacks_with_model_factor(self, monkeypatch):
        monkeypatch.setattr(common, "ENABLE_TIMEOUT", True)
        # factor=1.2 (medium), *1.8 reasoning → round(10*1.2*1.8)=22
        result = effective_timeout(10, "mistral-medium-latest",
                                   {"reasoning_effort": "high"})
        assert result == round(10 * 1.2 * 1.8)

    def test_no_reasoning_effort_key_no_extra_factor(self, monkeypatch):
        monkeypatch.setattr(common, "ENABLE_TIMEOUT", True)
        plain = effective_timeout(10, "mistral-small-latest", {"temperature": 0.2})
        with_effort = effective_timeout(10, "mistral-small-latest",
                                        {"reasoning_effort": "high"})
        assert with_effort > plain

    def test_empty_model_params_no_extra_factor(self, monkeypatch):
        monkeypatch.setattr(common, "ENABLE_TIMEOUT", True)
        assert effective_timeout(10, "mistral-small-latest", {}) == 10

    def test_none_model_params_no_extra_factor(self, monkeypatch):
        monkeypatch.setattr(common, "ENABLE_TIMEOUT", True)
        assert effective_timeout(10, "mistral-small-latest", None) == 10

    def test_returns_int(self, monkeypatch):
        monkeypatch.setattr(common, "ENABLE_TIMEOUT", True)
        result = effective_timeout(10, "mistral-medium-latest")
        assert isinstance(result, int)


# ---------------------------------------------------------------------------
# load_context
# ---------------------------------------------------------------------------

class TestLoadContext:
    def test_returns_no_context_string_when_file_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(common, "_CONTEXT_FILE",
                            tmp_path / "nonexistent_context.txt")
        assert load_context() == "No context defined."

    def test_returns_file_content_when_present(self, monkeypatch, tmp_path):
        ctx_file = tmp_path / "context.txt"
        ctx_file.write_text("my domain terms: pytest, VoxRefiner", encoding="utf-8")
        monkeypatch.setattr(common, "_CONTEXT_FILE", ctx_file)
        assert load_context() == "my domain terms: pytest, VoxRefiner"

    def test_strips_surrounding_whitespace(self, monkeypatch, tmp_path):
        ctx_file = tmp_path / "context.txt"
        ctx_file.write_text("  padded content  \n", encoding="utf-8")
        monkeypatch.setattr(common, "_CONTEXT_FILE", ctx_file)
        assert load_context() == "padded content"

    def test_empty_file_returns_empty_string(self, monkeypatch, tmp_path):
        ctx_file = tmp_path / "context.txt"
        ctx_file.write_text("", encoding="utf-8")
        monkeypatch.setattr(common, "_CONTEXT_FILE", ctx_file)
        assert load_context() == ""

    def test_multiline_content_preserved(self, monkeypatch, tmp_path):
        ctx_file = tmp_path / "context.txt"
        ctx_file.write_text("line one\nline two\nline three", encoding="utf-8")
        monkeypatch.setattr(common, "_CONTEXT_FILE", ctx_file)
        result = load_context()
        assert "line one" in result
        assert "line two" in result
        assert "line three" in result

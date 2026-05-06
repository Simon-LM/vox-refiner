"""Unit tests for _refine_timing() — timeout tier logic and background multiplier.

The background=True flag was added so that history updates (which run after
the text is already in the clipboard) can use doubled timeouts without
penalising the user experience.

The specific bug that prompted this: a 124-word text hit the < 180-word tier.
History extraction with the same text was timing out. With background=True
the base timeout is doubled; additionally the model speed factor is applied.
"""

import sys
import pytest


def _load_refine(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    monkeypatch.setenv("ENABLE_TIMEOUT", "true")
    if "src.refine" in sys.modules:
        del sys.modules["src.refine"]
    import src.refine as rm
    return rm


class TestEffectiveTimeout:
    def test_standard_model_no_factor(self, monkeypatch):
        """devstral-small-latest has factor 1.0 — timeout unchanged."""
        rm = _load_refine(monkeypatch)
        assert rm._effective_timeout(8, "devstral-small-latest") == 8

    def test_reasoning_model_multiplied(self, monkeypatch):
        """magistral-medium-latest has factor 4.5."""
        rm = _load_refine(monkeypatch)
        assert rm._effective_timeout(8, "magistral-medium-latest") == 36

    def test_magistral_small_factor_2_5(self, monkeypatch):
        """magistral-small-latest has factor 3.0."""
        rm = _load_refine(monkeypatch)
        assert rm._effective_timeout(11, "magistral-small-latest") == 33

    def test_unknown_model_defaults_to_1(self, monkeypatch):
        """Unknown model name → factor 1.0, timeout unchanged."""
        rm = _load_refine(monkeypatch)
        assert rm._effective_timeout(10, "some-unknown-model") == 10

    def test_real_world_bug_case(self, monkeypatch):
        """202 words + magistral-medium: base 8s × 4.5 = 36s.

        The real-world failure was 12s with old base; current factors provide
        significantly more headroom for reasoning models.
        """
        rm = _load_refine(monkeypatch)
        base_timeout, _ = rm._refine_timing(202)   # < 240 → 8s
        effective = rm._effective_timeout(base_timeout, "magistral-medium-latest")
        assert base_timeout == 8
        assert effective == 36

    def test_reasoning_effort_uses_compound_key(self, monkeypatch):
        """reasoning_effort=high on mistral-small: compound key → ×3.0."""
        rm = _load_refine(monkeypatch)
        params = {"reasoning_effort": "high"}
        effective = rm._effective_timeout(10, "mistral-small-latest", params)
        assert effective == 30  # 10 × 3.0 (compound key)

    def test_no_reasoning_effort_no_extra_factor(self, monkeypatch):
        """Without reasoning_effort, mistral-small keeps factor 1.0."""
        rm = _load_refine(monkeypatch)
        effective = rm._effective_timeout(10, "mistral-small-latest")
        assert effective == 10

    def test_reasoning_effort_compound_key_medium_latest(self, monkeypatch):
        """reasoning_effort on mistral-medium-latest: compound key → ×4.0."""
        rm = _load_refine(monkeypatch)
        params = {"reasoning_effort": "high"}
        effective = rm._effective_timeout(10, "mistral-medium-latest", params)
        assert effective == 40  # 10 × 4.0 (compound key)

    def test_reasoning_effort_compound_key_medium_35(self, monkeypatch):
        """reasoning_effort on mistral-medium-3.5: compound key → ×4.0."""
        rm = _load_refine(monkeypatch)
        params = {"reasoning_effort": "high"}
        effective = rm._effective_timeout(10, "mistral-medium-3.5", params)
        assert effective == 40  # 10 × 4.0 (compound key)

    def test_reasoning_effort_fallback_for_unknown_model(self, monkeypatch):
        """Unknown model with reasoning_effort falls back to base × 1.8."""
        rm = _load_refine(monkeypatch)
        params = {"reasoning_effort": "high"}
        # "unknown-model" not in _MODEL_SPEED_FACTOR → base 1.0 × 1.8 = 1.8
        effective = rm._effective_timeout(10, "unknown-future-model", params)
        assert effective == 18  # 10 × 1.0 × 1.8 (generic fallback)


class TestRefineTiming:
    def test_short_text_foreground_timeout(self, monkeypatch):
        """< 90 words → 4s timeout in normal mode (Option A)."""
        rm = _load_refine(monkeypatch)
        timeout, _ = rm._refine_timing(50)
        assert timeout == 4

    def test_medium_text_foreground_timeout(self, monkeypatch):
        """< 400 words → 11s timeout in normal mode (Option A)."""
        rm = _load_refine(monkeypatch)
        timeout, _ = rm._refine_timing(300)
        assert timeout == 11

    def test_background_doubles_timeout(self, monkeypatch):
        """background=True must double the timeout for any tier."""
        rm = _load_refine(monkeypatch)
        fg_timeout, _ = rm._refine_timing(300)
        bg_timeout, _ = rm._refine_timing(300, background=True)
        assert bg_timeout == fg_timeout * 2

    def test_background_does_not_change_retry_delay(self, monkeypatch):
        """retry_delay should be unchanged by the background flag."""
        rm = _load_refine(monkeypatch)
        _, fg_delay = rm._refine_timing(300)
        _, bg_delay = rm._refine_timing(300, background=True)
        assert bg_delay == fg_delay

    def test_bug_fix_124_words_background(self, monkeypatch):
        """124 words + background=True must double the foreground timeout.

        With Option A the < 180-word tier gives 6s foreground → 12s background.
        """
        rm = _load_refine(monkeypatch)
        fg_timeout, _ = rm._refine_timing(124)
        bg_timeout, _ = rm._refine_timing(124, background=True)
        assert fg_timeout == 6
        assert bg_timeout == 12

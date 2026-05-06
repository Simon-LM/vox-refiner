"""Unit tests for refine.py — _parse_model_spec and _build_tier_params.

These two helpers implement the '+reasoning' suffix syntax used in all
REFINE_MODEL_* env vars. They are pure functions that deserve their own
targeted test file (routing thresholds, prompts, and timing are in other files).

Also covers:
  - _REASONING_CAPABLE_MODELS membership
  - _HISTORY_MAX_BULLETS default value (80, not 100)
  - Default _PARAMS_* dicts built from default env
"""

import sys
from typing import Any, Dict

import pytest


# ---------------------------------------------------------------------------
# Module loader
# ---------------------------------------------------------------------------

def _load_refine(monkeypatch, **env):
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    for mod in list(sys.modules):
        if mod in ("src.refine",):
            del sys.modules[mod]
    import src.refine as refine
    return refine


# ---------------------------------------------------------------------------
# _parse_model_spec
# ---------------------------------------------------------------------------

class TestParseModelSpec:
    def _fn(self, monkeypatch):
        return _load_refine(monkeypatch)._parse_model_spec

    def test_plain_name_returns_name_and_false(self, monkeypatch):
        parse = self._fn(monkeypatch)
        model, has_reasoning = parse("mistral-small-latest")
        assert model == "mistral-small-latest"
        assert has_reasoning is False

    def test_reasoning_suffix_stripped_and_flag_true(self, monkeypatch):
        parse = self._fn(monkeypatch)
        model, has_reasoning = parse("mistral-small-latest+reasoning")
        assert model == "mistral-small-latest"
        assert has_reasoning is True

    def test_medium_model_with_suffix(self, monkeypatch):
        parse = self._fn(monkeypatch)
        model, has_reasoning = parse("mistral-medium-3.5+reasoning")
        assert model == "mistral-medium-3.5"
        assert has_reasoning is True

    def test_suffix_in_middle_not_stripped(self, monkeypatch):
        # "+reasoning" must be at the very end to match
        parse = self._fn(monkeypatch)
        model, has_reasoning = parse("mistral+reasoning-extra")
        assert model == "mistral+reasoning-extra"
        assert has_reasoning is False

    def test_empty_string_returns_empty_and_false(self, monkeypatch):
        parse = self._fn(monkeypatch)
        model, has_reasoning = parse("")
        assert model == ""
        assert has_reasoning is False

    def test_only_suffix_returns_empty_model(self, monkeypatch):
        parse = self._fn(monkeypatch)
        model, has_reasoning = parse("+reasoning")
        assert model == ""
        assert has_reasoning is True

    def test_returns_tuple_of_str_and_bool(self, monkeypatch):
        parse = self._fn(monkeypatch)
        result = parse("some-model")
        assert isinstance(result, tuple)
        assert isinstance(result[0], str)
        assert isinstance(result[1], bool)

    @pytest.mark.parametrize("spec,expected_model,expected_flag", [
        ("magistral-medium-latest",           "magistral-medium-latest",  False),
        ("magistral-medium-latest+reasoning", "magistral-medium-latest",  True),
        ("mistral-large-latest",              "mistral-large-latest",     False),
        ("mistral-large-latest+reasoning",    "mistral-large-latest",     True),
    ])
    def test_parametrize_known_models(self, monkeypatch, spec, expected_model, expected_flag):
        parse = self._fn(monkeypatch)
        model, flag = parse(spec)
        assert model == expected_model
        assert flag == expected_flag


# ---------------------------------------------------------------------------
# _build_tier_params
# ---------------------------------------------------------------------------

class TestBuildTierParams:
    def _fn(self, monkeypatch):
        return _load_refine(monkeypatch)._build_tier_params

    def test_no_reasoning_keeps_base_unchanged(self, monkeypatch):
        build = self._fn(monkeypatch)
        base = {"temperature": 0.2, "top_p": 0.85}
        result = build(base, has_reasoning=False)
        assert result["temperature"] == pytest.approx(0.2)
        assert result["top_p"] == pytest.approx(0.85)
        assert "reasoning_effort" not in result

    def test_with_reasoning_adds_high(self, monkeypatch):
        build = self._fn(monkeypatch)
        result = build({"temperature": 0.3}, has_reasoning=True)
        assert result["reasoning_effort"] == "high"

    def test_with_reasoning_preserves_base_keys(self, monkeypatch):
        build = self._fn(monkeypatch)
        result = build({"temperature": 0.3, "top_p": 0.9}, has_reasoning=True)
        assert result["temperature"] == pytest.approx(0.3)
        assert result["top_p"] == pytest.approx(0.9)

    def test_does_not_mutate_original_base(self, monkeypatch):
        build = self._fn(monkeypatch)
        base: Dict[str, Any] = {"temperature": 0.2}
        build(base, has_reasoning=True)
        assert "reasoning_effort" not in base

    def test_empty_base_with_reasoning(self, monkeypatch):
        build = self._fn(monkeypatch)
        result = build({}, has_reasoning=True)
        assert result == {"reasoning_effort": "high"}

    def test_empty_base_without_reasoning(self, monkeypatch):
        build = self._fn(monkeypatch)
        result = build({}, has_reasoning=False)
        assert result == {}


# ---------------------------------------------------------------------------
# Default _PARAMS_* dicts (built from default env vars)
# ---------------------------------------------------------------------------

class TestDefaultTierParams:
    def test_params_short_has_no_reasoning_effort_by_default(self, monkeypatch):
        # Default: REFINE_MODEL_SHORT=mistral-small-latest (no +reasoning)
        refine = _load_refine(monkeypatch)
        assert "reasoning_effort" not in refine._PARAMS_SHORT

    def test_params_medium_has_reasoning_effort_by_default(self, monkeypatch):
        # Default: REFINE_MODEL_MEDIUM=mistral-small-latest+reasoning
        refine = _load_refine(monkeypatch)
        assert refine._PARAMS_MEDIUM.get("reasoning_effort") == "high"

    def test_params_short_temperature(self, monkeypatch):
        refine = _load_refine(monkeypatch)
        assert refine._PARAMS_SHORT["temperature"] == pytest.approx(0.2)

    def test_params_medium_temperature(self, monkeypatch):
        refine = _load_refine(monkeypatch)
        assert refine._PARAMS_MEDIUM["temperature"] == pytest.approx(0.3)

    def test_params_long_temperature(self, monkeypatch):
        refine = _load_refine(monkeypatch)
        assert refine._PARAMS_LONG["temperature"] == pytest.approx(0.4)

    def test_reasoning_short_flag_is_false_by_default(self, monkeypatch):
        refine = _load_refine(monkeypatch)
        assert refine._REASONING_SHORT is False

    def test_reasoning_medium_flag_is_true_by_default(self, monkeypatch):
        refine = _load_refine(monkeypatch)
        assert refine._REASONING_MEDIUM is True


# ---------------------------------------------------------------------------
# _REASONING_CAPABLE_MODELS
# ---------------------------------------------------------------------------

class TestReasoningCapableModels:
    def test_mistral_small_in_set(self, monkeypatch):
        refine = _load_refine(monkeypatch)
        assert "mistral-small-latest" in refine._REASONING_CAPABLE_MODELS

    def test_mistral_medium_35_in_set(self, monkeypatch):
        refine = _load_refine(monkeypatch)
        assert "mistral-medium-3.5" in refine._REASONING_CAPABLE_MODELS

    def test_magistral_not_in_set(self, monkeypatch):
        # Magistral reasons natively — no reasoning_effort param needed
        refine = _load_refine(monkeypatch)
        assert "magistral-medium-latest" not in refine._REASONING_CAPABLE_MODELS

    def test_is_a_set(self, monkeypatch):
        refine = _load_refine(monkeypatch)
        assert isinstance(refine._REASONING_CAPABLE_MODELS, set)


# ---------------------------------------------------------------------------
# _HISTORY_MAX_BULLETS default
# ---------------------------------------------------------------------------

class TestHistoryMaxBullets:
    def test_default_is_80(self, monkeypatch):
        monkeypatch.delenv("HISTORY_MAX_BULLETS", raising=False)
        refine = _load_refine(monkeypatch)
        assert refine._HISTORY_MAX_BULLETS == 80

    def test_custom_value_from_env(self, monkeypatch):
        refine = _load_refine(monkeypatch, HISTORY_MAX_BULLETS="50")
        assert refine._HISTORY_MAX_BULLETS == 50

    def test_value_is_int(self, monkeypatch):
        refine = _load_refine(monkeypatch)
        assert isinstance(refine._HISTORY_MAX_BULLETS, int)


# ---------------------------------------------------------------------------
# env-driven model spec parsing (end-to-end: env → _MODEL + _REASONING flag)
# ---------------------------------------------------------------------------

class TestEnvDrivenModelSpec:
    def test_short_model_env_with_reasoning_suffix(self, monkeypatch):
        refine = _load_refine(monkeypatch,
                              REFINE_MODEL_SHORT="my-model+reasoning")
        assert refine._MODEL_SHORT == "my-model"
        assert refine._REASONING_SHORT is True
        assert refine._PARAMS_SHORT.get("reasoning_effort") == "high"

    def test_medium_model_env_without_suffix(self, monkeypatch):
        refine = _load_refine(monkeypatch,
                              REFINE_MODEL_MEDIUM="mistral-medium-latest")
        assert refine._MODEL_MEDIUM == "mistral-medium-latest"
        assert refine._REASONING_MEDIUM is False
        assert "reasoning_effort" not in refine._PARAMS_MEDIUM

    def test_long_model_env_with_reasoning_suffix(self, monkeypatch):
        refine = _load_refine(monkeypatch,
                              REFINE_MODEL_LONG="magistral-medium-latest+reasoning")
        assert refine._MODEL_LONG == "magistral-medium-latest"
        assert refine._REASONING_LONG is True

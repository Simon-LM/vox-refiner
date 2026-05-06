"""Unit tests for src/voice_rewrite.py.

Covers (no real API calls):
  _LANG_NAMES              — code→name mapping (9 languages)
  _SYSTEM_PROMPT           — required directives, placeholders, security block
  _REASONING_THRESHOLD     — value and intent
  _MODEL_PARAMS_SHORT/LONG — parameter sets for tiered reasoning
  voice_rewrite()          — missing key, param selection by word count,
                             message format, language resolution,
                             HTTP fallback chain, graceful degradation
"""

import sys
from unittest.mock import patch

import pytest
import requests


# ---------------------------------------------------------------------------
# Module loader — reloads so env changes at import time take effect
# ---------------------------------------------------------------------------

def _load_vr(monkeypatch, *, target_lang="en", model=None, model_fallback=None):
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    monkeypatch.setenv("TRANSLATE_TARGET_LANG", target_lang)
    if model:
        monkeypatch.setenv("VOICE_REWRITE_MODEL", model)
    if model_fallback:
        monkeypatch.setenv("VOICE_REWRITE_MODEL_FALLBACK", model_fallback)
    for mod in list(sys.modules):
        if mod == "src.voice_rewrite":
            del sys.modules[mod]
    import src.voice_rewrite as vr
    return vr


# ---------------------------------------------------------------------------
# _LANG_NAMES (9 languages, smaller than translate._LANG_NAMES)
# ---------------------------------------------------------------------------

class TestVoiceRewriteLangNames:
    EXPECTED = ["en", "fr", "de", "es", "pt", "it", "nl", "hi", "ar"]

    def test_all_expected_codes_present(self, monkeypatch):
        vr = _load_vr(monkeypatch)
        for code in self.EXPECTED:
            assert code in vr._LANG_NAMES, f"Missing: {code}"

    def test_esperanto_present(self, monkeypatch):
        vr = _load_vr(monkeypatch)
        assert "eo" in vr._LANG_NAMES

    def test_all_values_non_empty_strings(self, monkeypatch):
        vr = _load_vr(monkeypatch)
        for code, name in vr._LANG_NAMES.items():
            assert isinstance(name, str) and name.strip(), f"Empty name for {code}"

    def test_english_maps_to_english(self, monkeypatch):
        vr = _load_vr(monkeypatch)
        assert vr._LANG_NAMES["en"] == "English"

    def test_chinese_not_in_voice_rewrite_lang_names(self, monkeypatch):
        # voice_rewrite has 10 languages, not the extended 16 of translate
        vr = _load_vr(monkeypatch)
        assert "zh" not in vr._LANG_NAMES


# ---------------------------------------------------------------------------
# _SYSTEM_PROMPT
# ---------------------------------------------------------------------------

class TestVoiceRewriteSystemPrompt:
    def _formatted(self, monkeypatch, lang="English", context=""):
        vr = _load_vr(monkeypatch)
        return vr._SYSTEM_PROMPT.format(target_language=lang, context=context)

    def test_security_block_injected(self, monkeypatch):
        vr = _load_vr(monkeypatch)
        from src.common import SECURITY_BLOCK
        assert SECURITY_BLOCK in vr._SYSTEM_PROMPT

    def test_target_language_placeholder_present(self, monkeypatch):
        vr = _load_vr(monkeypatch)
        assert "{target_language}" in vr._SYSTEM_PROMPT

    def test_context_placeholder_present(self, monkeypatch):
        vr = _load_vr(monkeypatch)
        assert "{context}" in vr._SYSTEM_PROMPT

    def test_no_placeholder_after_format(self, monkeypatch):
        result = self._formatted(monkeypatch)
        assert "{target_language}" not in result
        assert "{context}" not in result

    def test_three_task_steps_mentioned(self, monkeypatch):
        result = self._formatted(monkeypatch)
        assert "CLEAN" in result
        assert "REWRITE" in result
        assert "TRANSLATE" in result

    def test_output_only_instruction(self, monkeypatch):
        result = self._formatted(monkeypatch)
        assert "Output ONLY" in result

    def test_transcription_treated_as_data(self, monkeypatch):
        result = self._formatted(monkeypatch)
        assert "microphone" in result.lower() or "transcription" in result.lower()

    def test_tts_oriented_phrasing(self, monkeypatch):
        vr = _load_vr(monkeypatch)
        assert "text-to-speech" in vr._SYSTEM_PROMPT.lower() or "ear" in vr._SYSTEM_PROMPT.lower()

    def test_target_language_injected_in_output(self, monkeypatch):
        result = self._formatted(monkeypatch, lang="Spanish")
        assert "Spanish" in result


# ---------------------------------------------------------------------------
# _REASONING_THRESHOLD and model params
# ---------------------------------------------------------------------------

class TestReasoningConfig:
    def test_threshold_is_120(self, monkeypatch):
        vr = _load_vr(monkeypatch)
        assert vr._REASONING_THRESHOLD == 120

    def test_short_params_have_no_reasoning_effort(self, monkeypatch):
        vr = _load_vr(monkeypatch)
        assert "reasoning_effort" not in vr._MODEL_PARAMS_SHORT

    def test_long_params_have_reasoning_effort_high(self, monkeypatch):
        vr = _load_vr(monkeypatch)
        assert vr._MODEL_PARAMS_LONG["reasoning_effort"] == "high"

    def test_short_params_lower_temperature_than_long(self, monkeypatch):
        vr = _load_vr(monkeypatch)
        assert vr._MODEL_PARAMS_SHORT["temperature"] < vr._MODEL_PARAMS_LONG["temperature"]

    def test_short_params_lower_top_p_than_long(self, monkeypatch):
        vr = _load_vr(monkeypatch)
        assert vr._MODEL_PARAMS_SHORT["top_p"] < vr._MODEL_PARAMS_LONG["top_p"]


# ---------------------------------------------------------------------------
# voice_rewrite() — missing API key
# ---------------------------------------------------------------------------

class TestVoiceRewriteMissingApiKey:
    def test_raises_runtime_error(self, monkeypatch):
        vr = _load_vr(monkeypatch)
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="MISTRAL_API_KEY"):
            vr.voice_rewrite("some text")


# ---------------------------------------------------------------------------
# voice_rewrite() — param selection by word count
# ---------------------------------------------------------------------------

class TestVoiceRewriteParamSelection:
    def _capture_params(self, monkeypatch, text):
        vr = _load_vr(monkeypatch)
        captured = {}

        def fake_call_model(model, messages, api_key, model_params=None, **kwargs):
            captured["model_params"] = model_params
            return "ok"

        with patch.object(vr, "call_model", side_effect=fake_call_model):
            vr.voice_rewrite(text)

        return captured.get("model_params")

    def test_short_text_uses_short_params(self, monkeypatch):
        text = " ".join(["word"] * 50)  # 50 words < 120
        params = self._capture_params(monkeypatch, text)
        assert params is not None
        assert "reasoning_effort" not in params

    def test_long_text_uses_long_params(self, monkeypatch):
        text = " ".join(["word"] * 130)  # 130 words ≥ 120
        params = self._capture_params(monkeypatch, text)
        assert params is not None
        assert params.get("reasoning_effort") == "high"

    def test_exactly_at_threshold_uses_long_params(self, monkeypatch):
        text = " ".join(["word"] * 120)  # 120 words == threshold
        params = self._capture_params(monkeypatch, text)
        assert params.get("reasoning_effort") == "high"

    def test_one_below_threshold_uses_short_params(self, monkeypatch):
        text = " ".join(["word"] * 119)  # 119 words < 120
        params = self._capture_params(monkeypatch, text)
        assert "reasoning_effort" not in params

    def test_fallback_model_uses_no_params(self, monkeypatch):
        vr = _load_vr(monkeypatch,
                      model="primary-model",
                      model_fallback="fallback-model")
        calls = []

        def fake_call_model(model, messages, api_key, model_params=None, **kwargs):
            calls.append((model, model_params))
            if model == "primary-model":
                resp = __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock()
                resp.status_code = 429
                raise requests.HTTPError(response=resp)
            return "fallback ok"

        with patch.object(vr, "call_model", side_effect=fake_call_model):
            vr.voice_rewrite("hello world")

        fallback_call = next(c for c in calls if c[0] == "fallback-model")
        assert fallback_call[1] is None


# ---------------------------------------------------------------------------
# voice_rewrite() — message format
# ---------------------------------------------------------------------------

class TestVoiceRewriteMessageFormat:
    def _capture_messages(self, monkeypatch, text="hello world"):
        vr = _load_vr(monkeypatch)
        captured = {}

        def fake_call_model(model, messages, api_key, **kwargs):
            captured["messages"] = messages
            return "ok"

        with patch.object(vr, "call_model", side_effect=fake_call_model):
            vr.voice_rewrite(text)

        return captured["messages"]

    def test_system_message_is_first(self, monkeypatch):
        messages = self._capture_messages(monkeypatch)
        assert messages[0]["role"] == "system"

    def test_user_message_is_second(self, monkeypatch):
        messages = self._capture_messages(monkeypatch)
        assert messages[1]["role"] == "user"

    def test_transcription_wrapped_in_xml_tags(self, monkeypatch):
        messages = self._capture_messages(monkeypatch, "my spoken text")
        content = messages[1]["content"]
        assert "<transcription>" in content
        assert "my spoken text" in content
        assert "</transcription>" in content

    def test_target_language_in_system_prompt(self, monkeypatch):
        vr = _load_vr(monkeypatch, target_lang="fr")
        captured = {}

        def fake_call_model(model, messages, api_key, **kwargs):
            captured["system"] = messages[0]["content"]
            return "ok"

        with patch.object(vr, "call_model", side_effect=fake_call_model):
            vr.voice_rewrite("hello world")

        assert "French" in captured["system"]


# ---------------------------------------------------------------------------
# voice_rewrite() — language resolution at module level
# ---------------------------------------------------------------------------

class TestVoiceRewriteLangResolution:
    def _get_system_prompt(self, monkeypatch, target_lang):
        vr = _load_vr(monkeypatch, target_lang=target_lang)
        captured = {}

        def fake_call_model(model, messages, api_key, **kwargs):
            captured["system"] = messages[0]["content"]
            return "ok"

        with patch.object(vr, "call_model", side_effect=fake_call_model):
            vr.voice_rewrite("hello")

        return captured["system"]

    def test_known_code_resolves_to_full_name(self, monkeypatch):
        assert "Spanish" in self._get_system_prompt(monkeypatch, "es")

    def test_unknown_code_capitalized(self, monkeypatch):
        assert "Xx" in self._get_system_prompt(monkeypatch, "xx")

    def test_english_resolves_to_english(self, monkeypatch):
        assert "English" in self._get_system_prompt(monkeypatch, "en")


# ---------------------------------------------------------------------------
# voice_rewrite() — graceful degradation (returns raw_text, no exception)
# ---------------------------------------------------------------------------

class TestVoiceRewriteGracefulDegradation:
    def _make_http_error(self, status_code):
        resp = __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock()
        resp.status_code = status_code
        return requests.HTTPError(response=resp)

    def test_all_models_fail_returns_raw_text(self, monkeypatch):
        vr = _load_vr(monkeypatch)
        raw = "the original transcription text"

        def fake_call_model(model, messages, api_key, **kwargs):
            raise self._make_http_error(503)

        with patch.object(vr, "call_model", side_effect=fake_call_model):
            result = vr.voice_rewrite(raw)

        assert result == raw

    def test_request_exception_on_both_models_returns_raw(self, monkeypatch):
        vr = _load_vr(monkeypatch)
        raw = "fallback input"

        def fake_call_model(model, messages, api_key, **kwargs):
            raise requests.RequestException("unreachable")

        with patch.object(vr, "call_model", side_effect=fake_call_model):
            result = vr.voice_rewrite(raw)

        assert result == raw

    def test_429_on_primary_falls_back_to_second_model(self, monkeypatch):
        vr = _load_vr(monkeypatch)
        calls = []

        def fake_call_model(model, messages, api_key, **kwargs):
            calls.append(model)
            if len(calls) == 1:
                raise self._make_http_error(429)
            return "fallback result"

        with patch.object(vr, "call_model", side_effect=fake_call_model):
            result = vr.voice_rewrite("hello world")

        assert result == "fallback result"
        assert len(calls) == 2

    def test_non_retryable_status_reraises(self, monkeypatch):
        vr = _load_vr(monkeypatch)

        def fake_call_model(model, messages, api_key, **kwargs):
            raise self._make_http_error(401)

        with patch.object(vr, "call_model", side_effect=fake_call_model):
            with pytest.raises(requests.HTTPError):
                vr.voice_rewrite("text")

"""Unit tests for src/translate.py.

Covers (no real API calls):
  _LANG_NAMES          — code→name mapping completeness
  translate()          — missing API key, language resolution (env chain),
                         system prompt construction, <source> wrapper stripping,
                         message format, HTTP fallback chain
"""

import sys
from unittest.mock import patch

import pytest
import requests


# ---------------------------------------------------------------------------
# Module loader
# ---------------------------------------------------------------------------

def _load_translate(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    if "src.translate" in sys.modules:
        del sys.modules["src.translate"]
    import src.translate as translate
    return translate


# ---------------------------------------------------------------------------
# _LANG_NAMES
# ---------------------------------------------------------------------------

class TestLangNames:
    EXPECTED_CODES = ["en", "fr", "de", "es", "pt", "it", "nl", "hi", "ar",
                      "zh", "ja", "ko", "ru", "pl", "sv", "eo"]

    def test_all_expected_codes_present(self, monkeypatch):
        t = _load_translate(monkeypatch)
        for code in self.EXPECTED_CODES:
            assert code in t._LANG_NAMES, f"Missing code: {code}"

    def test_all_values_are_non_empty_strings(self, monkeypatch):
        t = _load_translate(monkeypatch)
        for code, name in t._LANG_NAMES.items():
            assert isinstance(name, str) and name.strip(), f"Empty name for {code}"

    def test_english_maps_to_english(self, monkeypatch):
        t = _load_translate(monkeypatch)
        assert t._LANG_NAMES["en"] == "English"

    def test_french_maps_to_french(self, monkeypatch):
        t = _load_translate(monkeypatch)
        assert t._LANG_NAMES["fr"] == "French"

    def test_arabic_present(self, monkeypatch):
        t = _load_translate(monkeypatch)
        assert "ar" in t._LANG_NAMES

    def test_unknown_code_not_in_table(self, monkeypatch):
        t = _load_translate(monkeypatch)
        assert "xx" not in t._LANG_NAMES


# ---------------------------------------------------------------------------
# translate() — missing API key
# ---------------------------------------------------------------------------

class TestTranslateMissingApiKey:
    def test_raises_runtime_error_when_no_key(self, monkeypatch):
        t = _load_translate(monkeypatch)
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="MISTRAL_API_KEY"):
            t.translate("some text")


# ---------------------------------------------------------------------------
# translate() — language resolution (env chain)
# ---------------------------------------------------------------------------

class TestTranslateLangResolution:
    def _captured_system_prompt(self, monkeypatch, **env):
        t = _load_translate(monkeypatch)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        for k in ("TRANSLATE_TARGET_LANG", "OUTPUT_DEFAULT_LANG"):
            if k not in env:
                monkeypatch.delenv(k, raising=False)
        captured = {}

        def fake_call_model(model, messages, api_key, **kwargs):
            captured["system"] = messages[0]["content"]
            return "translated"

        with patch.object(t, "call_model", side_effect=fake_call_model):
            t.translate("hello")

        return captured["system"]

    def test_translate_target_lang_takes_priority(self, monkeypatch):
        prompt = self._captured_system_prompt(
            monkeypatch,
            TRANSLATE_TARGET_LANG="fr",
            OUTPUT_DEFAULT_LANG="de",
        )
        assert "French" in prompt
        assert "German" not in prompt

    def test_output_default_lang_used_when_translate_lang_absent(self, monkeypatch):
        prompt = self._captured_system_prompt(
            monkeypatch,
            OUTPUT_DEFAULT_LANG="de",
        )
        assert "German" in prompt

    def test_defaults_to_english_when_both_absent(self, monkeypatch):
        prompt = self._captured_system_prompt(monkeypatch)
        assert "English" in prompt

    def test_unknown_code_capitalized_as_fallback(self, monkeypatch):
        prompt = self._captured_system_prompt(
            monkeypatch,
            TRANSLATE_TARGET_LANG="xx",
        )
        assert "Xx" in prompt

    def test_code_lowercased_before_lookup(self, monkeypatch):
        prompt = self._captured_system_prompt(
            monkeypatch,
            TRANSLATE_TARGET_LANG="FR",
        )
        assert "French" in prompt


# ---------------------------------------------------------------------------
# translate() — system prompt
# ---------------------------------------------------------------------------

class TestTranslateSystemPrompt:
    def _get_system_prompt(self, monkeypatch, lang="en"):
        t = _load_translate(monkeypatch)
        monkeypatch.setenv("TRANSLATE_TARGET_LANG", lang)
        captured = {}

        def fake_call_model(model, messages, api_key, **kwargs):
            captured["system"] = messages[0]["content"]
            return "ok"

        with patch.object(t, "call_model", side_effect=fake_call_model):
            t.translate("test")

        return captured["system"]

    def test_target_language_injected(self, monkeypatch):
        prompt = self._get_system_prompt(monkeypatch, lang="fr")
        assert "French" in prompt

    def test_security_block_present(self, monkeypatch):
        from src.common import SECURITY_BLOCK
        prompt = self._get_system_prompt(monkeypatch)
        assert SECURITY_BLOCK in prompt

    def test_no_summarise_rule(self, monkeypatch):
        prompt = self._get_system_prompt(monkeypatch)
        assert "summarise" in prompt.lower() or "summarize" in prompt.lower()

    def test_output_only_instruction(self, monkeypatch):
        prompt = self._get_system_prompt(monkeypatch)
        assert "ONLY" in prompt

    def test_no_placeholder_left(self, monkeypatch):
        prompt = self._get_system_prompt(monkeypatch)
        assert "{target_language}" not in prompt


# ---------------------------------------------------------------------------
# translate() — message format
# ---------------------------------------------------------------------------

class TestTranslateMessageFormat:
    def _capture_messages(self, monkeypatch, text="hello world"):
        t = _load_translate(monkeypatch)
        monkeypatch.setenv("TRANSLATE_TARGET_LANG", "en")
        captured = {}

        def fake_call_model(model, messages, api_key, **kwargs):
            captured["messages"] = messages
            return "translated"

        with patch.object(t, "call_model", side_effect=fake_call_model):
            t.translate(text)

        return captured["messages"]

    def test_system_message_is_first(self, monkeypatch):
        messages = self._capture_messages(monkeypatch)
        assert messages[0]["role"] == "system"

    def test_user_message_is_second(self, monkeypatch):
        messages = self._capture_messages(monkeypatch)
        assert messages[1]["role"] == "user"

    def test_user_content_wrapped_in_source_tags(self, monkeypatch):
        messages = self._capture_messages(monkeypatch, "my text")
        content = messages[1]["content"]
        assert "<source>" in content
        assert "my text" in content
        assert "</source>" in content


# ---------------------------------------------------------------------------
# translate() — <source> wrapper stripping
# ---------------------------------------------------------------------------

class TestTranslateSourceStripping:
    def _run(self, monkeypatch, model_output):
        t = _load_translate(monkeypatch)
        monkeypatch.setenv("TRANSLATE_TARGET_LANG", "en")
        with patch.object(t, "call_model", return_value=model_output):
            return t.translate("input text")

    def test_clean_output_unchanged(self, monkeypatch):
        assert self._run(monkeypatch, "Translated text.") == "Translated text."

    def test_leading_source_tag_stripped(self, monkeypatch):
        result = self._run(monkeypatch, "<source>Translated text.")
        assert not result.startswith("<source>")
        assert "Translated text." in result

    def test_trailing_source_tag_stripped(self, monkeypatch):
        result = self._run(monkeypatch, "Translated text.</source>")
        assert not result.endswith("</source>")
        assert "Translated text." in result

    def test_both_tags_stripped(self, monkeypatch):
        result = self._run(monkeypatch, "<source>\nTranslated text.\n</source>")
        assert result == "Translated text."

    def test_whitespace_around_tags_stripped(self, monkeypatch):
        result = self._run(monkeypatch, "  <source>  Translated.  </source>  ")
        assert result == "Translated."

    def test_output_stripped_of_surrounding_whitespace(self, monkeypatch):
        result = self._run(monkeypatch, "  Clean output.  ")
        assert result == "Clean output."


# ---------------------------------------------------------------------------
# translate() — HTTP fallback chain
# ---------------------------------------------------------------------------

def _http_error(status_code):
    resp = __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock()
    resp.status_code = status_code
    return requests.HTTPError(response=resp)


class TestTranslateFallback:
    def test_primary_success_no_fallback(self, monkeypatch):
        t = _load_translate(monkeypatch)
        monkeypatch.setenv("TRANSLATE_TARGET_LANG", "en")
        calls = []

        def fake(model, messages, api_key, **kwargs):
            calls.append(model)
            return "result"

        with patch.object(t, "call_model", side_effect=fake):
            result = t.translate("text")

        assert result == "result"
        assert len(calls) == 1
        assert calls[0] == t._MODEL

    def test_429_triggers_fallback(self, monkeypatch):
        t = _load_translate(monkeypatch)
        monkeypatch.setenv("TRANSLATE_TARGET_LANG", "en")
        calls = []

        def fake(model, messages, api_key, **kwargs):
            calls.append(model)
            if model == t._MODEL:
                raise _http_error(429)
            return "fallback"

        with patch.object(t, "call_model", side_effect=fake):
            result = t.translate("text")

        assert result == "fallback"
        assert t._MODEL in calls
        assert t._MODEL_FALLBACK in calls

    def test_502_triggers_fallback(self, monkeypatch):
        t = _load_translate(monkeypatch)
        monkeypatch.setenv("TRANSLATE_TARGET_LANG", "en")

        def fake(model, messages, api_key, **kwargs):
            if model == t._MODEL:
                raise _http_error(502)
            return "ok"

        with patch.object(t, "call_model", side_effect=fake):
            assert t.translate("text") == "ok"

    def test_non_retryable_status_reraises(self, monkeypatch):
        t = _load_translate(monkeypatch)
        monkeypatch.setenv("TRANSLATE_TARGET_LANG", "en")

        def fake(model, messages, api_key, **kwargs):
            raise _http_error(403)

        with patch.object(t, "call_model", side_effect=fake):
            with pytest.raises(requests.HTTPError):
                t.translate("text")

    def test_all_models_fail_raises_runtime_error(self, monkeypatch):
        t = _load_translate(monkeypatch)
        monkeypatch.setenv("TRANSLATE_TARGET_LANG", "en")

        def fake(model, messages, api_key, **kwargs):
            raise _http_error(503)

        with patch.object(t, "call_model", side_effect=fake):
            with pytest.raises(RuntimeError, match="All translation models failed"):
                t.translate("text")

    def test_request_exception_triggers_fallback(self, monkeypatch):
        t = _load_translate(monkeypatch)
        monkeypatch.setenv("TRANSLATE_TARGET_LANG", "en")
        calls = []

        def fake(model, messages, api_key, **kwargs):
            calls.append(model)
            if model == t._MODEL:
                raise requests.RequestException("timeout")
            return "recovered"

        with patch.object(t, "call_model", side_effect=fake):
            result = t.translate("text")

        assert result == "recovered"
        assert len(calls) == 2

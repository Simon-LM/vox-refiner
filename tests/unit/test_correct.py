"""Unit tests for src/correct.py.

Covers (no real API calls):
  _SYSTEM_PROMPT  — presence of safety rules and security block
  correct()       — missing API key, message format, <transcription> wrapper
                    stripping, HTTP fallback chain, all-models-fail error
"""

import sys
from unittest.mock import MagicMock, call, patch

import pytest
import requests


# ---------------------------------------------------------------------------
# Module loader (reloads correct so env changes take effect)
# ---------------------------------------------------------------------------

def _load_correct(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    for mod in list(sys.modules):
        if mod in ("src.correct",):
            del sys.modules[mod]
    import src.correct as correct
    return correct


# ---------------------------------------------------------------------------
# _SYSTEM_PROMPT
# ---------------------------------------------------------------------------

class TestSystemPrompt:
    def test_contains_non_rephrase_rule(self, monkeypatch):
        correct = _load_correct(monkeypatch)
        assert "Do NOT rephrase" in correct._SYSTEM_PROMPT

    def test_contains_output_only_rule(self, monkeypatch):
        correct = _load_correct(monkeypatch)
        assert "Output ONLY" in correct._SYSTEM_PROMPT

    def test_contains_no_remove_rule(self, monkeypatch):
        correct = _load_correct(monkeypatch)
        assert "remove" in correct._SYSTEM_PROMPT.lower()

    def test_security_block_injected(self, monkeypatch):
        correct = _load_correct(monkeypatch)
        from src.common import SECURITY_BLOCK
        assert SECURITY_BLOCK in correct._SYSTEM_PROMPT

    def test_describes_task_as_correction_not_rewrite(self, monkeypatch):
        correct = _load_correct(monkeypatch)
        prompt_lower = correct._SYSTEM_PROMPT.lower()
        assert "correct" in prompt_lower
        assert "transcription" in prompt_lower

    def test_mentions_context_as_guide(self, monkeypatch):
        correct = _load_correct(monkeypatch)
        assert "context" in correct._SYSTEM_PROMPT.lower()


# ---------------------------------------------------------------------------
# correct() — missing API key
# ---------------------------------------------------------------------------

class TestCorrectMissingApiKey:
    def test_raises_runtime_error_when_no_key(self, monkeypatch):
        # Import first (load_dotenv runs), then delete so correct() sees no key at call time
        correct = _load_correct(monkeypatch)
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="MISTRAL_API_KEY"):
            correct.correct("some text", "some context")


# ---------------------------------------------------------------------------
# correct() — message format
# ---------------------------------------------------------------------------

class TestCorrectMessageFormat:
    def test_context_wrapped_in_xml_tags(self, monkeypatch):
        correct = _load_correct(monkeypatch)
        captured = {}

        def fake_call_model(model, messages, api_key, **kwargs):
            captured["messages"] = messages
            return "corrected text"

        with patch.object(correct, "call_model", side_effect=fake_call_model):
            correct.correct("raw transcription", "my context terms")

        user_content = captured["messages"][1]["content"]
        assert "<context>" in user_content
        assert "my context terms" in user_content
        assert "</context>" in user_content

    def test_transcription_wrapped_in_xml_tags(self, monkeypatch):
        correct = _load_correct(monkeypatch)
        captured = {}

        def fake_call_model(model, messages, api_key, **kwargs):
            captured["messages"] = messages
            return "corrected text"

        with patch.object(correct, "call_model", side_effect=fake_call_model):
            correct.correct("raw transcription", "context")

        user_content = captured["messages"][1]["content"]
        assert "<transcription>" in user_content
        assert "raw transcription" in user_content
        assert "</transcription>" in user_content

    def test_system_message_is_first(self, monkeypatch):
        correct = _load_correct(monkeypatch)

        def fake_call_model(model, messages, api_key, **kwargs):
            return "ok"

        with patch.object(correct, "call_model", side_effect=fake_call_model):
            correct.correct("text", "ctx")

    def test_user_message_is_second(self, monkeypatch):
        correct = _load_correct(monkeypatch)
        captured = {}

        def fake_call_model(model, messages, api_key, **kwargs):
            captured["messages"] = messages
            return "ok"

        with patch.object(correct, "call_model", side_effect=fake_call_model):
            correct.correct("text", "ctx")

        assert captured["messages"][0]["role"] == "system"
        assert captured["messages"][1]["role"] == "user"


# ---------------------------------------------------------------------------
# correct() — <transcription> wrapper stripping
# ---------------------------------------------------------------------------

class TestCorrectWrapperStripping:
    def _run(self, monkeypatch, model_output):
        correct = _load_correct(monkeypatch)
        with patch.object(correct, "call_model", return_value=model_output):
            return correct.correct("raw text", "context")

    def test_no_wrapper_returned_as_is(self, monkeypatch):
        assert self._run(monkeypatch, "Clean output.") == "Clean output."

    def test_leading_transcription_tag_stripped(self, monkeypatch):
        result = self._run(monkeypatch, "<transcription>Clean output.")
        assert not result.startswith("<transcription>")
        assert "Clean output." in result

    def test_trailing_transcription_tag_stripped(self, monkeypatch):
        result = self._run(monkeypatch, "Clean output.</transcription>")
        assert not result.endswith("</transcription>")
        assert "Clean output." in result

    def test_both_tags_stripped(self, monkeypatch):
        result = self._run(monkeypatch, "<transcription>\nClean output.\n</transcription>")
        assert result == "Clean output."

    def test_whitespace_trimmed_after_strip(self, monkeypatch):
        result = self._run(monkeypatch, "<transcription>\n  Clean.  \n</transcription>")
        assert result == "Clean."

    def test_content_without_tags_unchanged(self, monkeypatch):
        result = self._run(monkeypatch, "Some transcription text without tags.")
        assert result == "Some transcription text without tags."


# ---------------------------------------------------------------------------
# correct() — HTTP fallback chain
# ---------------------------------------------------------------------------

def _http_error(status_code):
    resp = MagicMock()
    resp.status_code = status_code
    err = requests.HTTPError(response=resp)
    return err


class TestCorrectFallback:
    def test_primary_success_no_fallback(self, monkeypatch):
        correct = _load_correct(monkeypatch)
        calls = []

        def fake_call_model(model, messages, api_key, **kwargs):
            calls.append(model)
            return "result"

        with patch.object(correct, "call_model", side_effect=fake_call_model):
            result = correct.correct("text", "ctx")

        assert result == "result"
        assert len(calls) == 1
        assert calls[0] == correct._MODEL

    def test_429_triggers_fallback(self, monkeypatch):
        correct = _load_correct(monkeypatch)
        calls = []

        def fake_call_model(model, messages, api_key, **kwargs):
            calls.append(model)
            if model == correct._MODEL:
                raise _http_error(429)
            return "fallback result"

        with patch.object(correct, "call_model", side_effect=fake_call_model):
            result = correct.correct("text", "ctx")

        assert result == "fallback result"
        assert correct._MODEL in calls
        assert correct._MODEL_FALLBACK in calls

    def test_500_triggers_fallback(self, monkeypatch):
        correct = _load_correct(monkeypatch)

        def fake_call_model(model, messages, api_key, **kwargs):
            if model == correct._MODEL:
                raise _http_error(500)
            return "ok"

        with patch.object(correct, "call_model", side_effect=fake_call_model):
            result = correct.correct("text", "ctx")

        assert result == "ok"

    def test_non_retryable_status_reraises(self, monkeypatch):
        correct = _load_correct(monkeypatch)

        def fake_call_model(model, messages, api_key, **kwargs):
            raise _http_error(401)

        with patch.object(correct, "call_model", side_effect=fake_call_model):
            with pytest.raises(requests.HTTPError):
                correct.correct("text", "ctx")

    def test_all_models_fail_raises_runtime_error(self, monkeypatch):
        correct = _load_correct(monkeypatch)

        def fake_call_model(model, messages, api_key, **kwargs):
            raise _http_error(503)

        with patch.object(correct, "call_model", side_effect=fake_call_model):
            with pytest.raises(RuntimeError, match="All correction models failed"):
                correct.correct("text", "ctx")

    def test_request_exception_triggers_fallback(self, monkeypatch):
        correct = _load_correct(monkeypatch)
        calls = []

        def fake_call_model(model, messages, api_key, **kwargs):
            calls.append(model)
            if model == correct._MODEL:
                raise requests.RequestException("network error")
            return "recovered"

        with patch.object(correct, "call_model", side_effect=fake_call_model):
            result = correct.correct("text", "ctx")

        assert result == "recovered"
        assert len(calls) == 2

    def test_502_triggers_fallback(self, monkeypatch):
        correct = _load_correct(monkeypatch)

        def fake_call_model(model, messages, api_key, **kwargs):
            if model == correct._MODEL:
                raise _http_error(502)
            return "ok"

        with patch.object(correct, "call_model", side_effect=fake_call_model):
            assert correct.correct("text", "ctx") == "ok"

    def test_503_triggers_fallback(self, monkeypatch):
        correct = _load_correct(monkeypatch)

        def fake_call_model(model, messages, api_key, **kwargs):
            if model == correct._MODEL:
                raise _http_error(503)
            return "ok"

        with patch.object(correct, "call_model", side_effect=fake_call_model):
            assert correct.correct("text", "ctx") == "ok"


# ---------------------------------------------------------------------------
# correct() — model selection and API key forwarding
# ---------------------------------------------------------------------------

class TestCorrectModelSelection:
    def test_refine_model_short_env_overrides_model(self, monkeypatch):
        monkeypatch.setenv("REFINE_MODEL_SHORT", "my-custom-model")
        correct = _load_correct(monkeypatch)
        calls = []

        def fake_call_model(model, messages, api_key, **kwargs):
            calls.append(model)
            return "ok"

        with patch.object(correct, "call_model", side_effect=fake_call_model):
            correct.correct("text", "ctx")

        assert calls[0] == "my-custom-model"

    def test_api_key_forwarded_to_call_model(self, monkeypatch):
        # _load_correct sets MISTRAL_API_KEY="test-key"; override it after reload
        # so correct() (which reads the key at call time) sees our custom value.
        correct = _load_correct(monkeypatch)
        monkeypatch.setenv("MISTRAL_API_KEY", "secret-key-xyz")
        captured = {}

        def fake_call_model(model, messages, api_key, **kwargs):
            captured["api_key"] = api_key
            return "ok"

        with patch.object(correct, "call_model", side_effect=fake_call_model):
            correct.correct("text", "ctx")

        assert captured["api_key"] == "secret-key-xyz"

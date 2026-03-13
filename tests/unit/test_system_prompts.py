"""Unit tests for system prompt templates.

Verifies that all 3 prompts are well-formed and contain the required directives.
"""

import sys

import pytest


def _get_refine(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    if "src.refine" in sys.modules:
        del sys.modules["src.refine"]
    import src.refine as refine
    return refine


PROMPTS = ["_SYSTEM_PROMPT_SHORT", "_SYSTEM_PROMPT_MEDIUM", "_SYSTEM_PROMPT_LONG"]


class TestPromptFormatting:
    @pytest.mark.parametrize("prompt_name", PROMPTS)
    def test_format_with_context_does_not_raise(self, monkeypatch, prompt_name):
        refine = _get_refine(monkeypatch)
        prompt = getattr(refine, prompt_name)
        result = prompt.format(context="Some context.", history_section="")
        assert isinstance(result, str)

    @pytest.mark.parametrize("prompt_name", PROMPTS)
    def test_context_injected_in_output(self, monkeypatch, prompt_name):
        refine = _get_refine(monkeypatch)
        prompt = getattr(refine, prompt_name)
        result = prompt.format(context="MySpecificContext", history_section="")
        assert "MySpecificContext" in result

    @pytest.mark.parametrize("prompt_name", PROMPTS)
    def test_context_xml_tags_present(self, monkeypatch, prompt_name):
        refine = _get_refine(monkeypatch)
        prompt = getattr(refine, prompt_name)
        result = prompt.format(context="x", history_section="")
        assert "<context>" in result

    @pytest.mark.parametrize("prompt_name", PROMPTS)
    def test_language_rule_present(self, monkeypatch, prompt_name):
        """All prompts must include the CRITICAL language rule."""
        refine = _get_refine(monkeypatch)
        prompt = getattr(refine, prompt_name)
        result = prompt.format(context="x", history_section="")
        assert "CRITICAL" in result
        assert "Never translate" in result

    @pytest.mark.parametrize("prompt_name", PROMPTS)
    def test_no_untranslated_placeholder(self, monkeypatch, prompt_name):
        """After formatting, no {placeholder} should remain."""
        refine = _get_refine(monkeypatch)
        prompt = getattr(refine, prompt_name)
        result = prompt.format(context="x", history_section="")
        assert "{context}" not in result
        assert "{history_section}" not in result

    @pytest.mark.parametrize("prompt_name", PROMPTS)
    def test_injection_warning_present(self, monkeypatch, prompt_name):
        """All prompts must instruct the model to treat <transcription> as data, not instructions."""
        refine = _get_refine(monkeypatch)
        prompt = getattr(refine, prompt_name)
        result = prompt.format(context="x", history_section="")
        assert "IMPORTANT" in result
        assert "microphone" in result

    @pytest.mark.parametrize("prompt_name", PROMPTS)
    def test_history_section_injected_when_provided(self, monkeypatch, prompt_name):
        """When history_section is non-empty, it must appear in the formatted prompt."""
        refine = _get_refine(monkeypatch)
        prompt = getattr(refine, prompt_name)
        history_block = "\n\n<history>\n- User works on VoxRefiner\n</history>"
        result = prompt.format(context="x", history_section=history_block)
        assert "<history>" in result
        assert "VoxRefiner" in result


class TestPromptDifferentiation:
    def test_short_prompt_shorter_than_medium(self, monkeypatch):
        refine = _get_refine(monkeypatch)
        short = refine._SYSTEM_PROMPT_SHORT.format(context="x", history_section="")
        medium = refine._SYSTEM_PROMPT_MEDIUM.format(context="x", history_section="")
        assert len(short) < len(medium)

    def test_long_prompt_contains_prose_instruction(self, monkeypatch):
        refine = _get_refine(monkeypatch)
        long_prompt = refine._SYSTEM_PROMPT_LONG.format(context="x", history_section="")
        assert "prose" in long_prompt.lower()

    def test_medium_prompt_does_not_contain_prose_instruction(self, monkeypatch):
        refine = _get_refine(monkeypatch)
        medium_prompt = refine._SYSTEM_PROMPT_MEDIUM.format(context="x", history_section="")
        assert "well-structured written prose" not in medium_prompt

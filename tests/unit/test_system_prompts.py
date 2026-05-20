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
        result = prompt.format(context="Some context.", history_section="", format_block="", language_instruction=refine._LANG_INSTRUCTION_DEFAULT)
        assert isinstance(result, str)

    @pytest.mark.parametrize("prompt_name", PROMPTS)
    def test_context_injected_in_output(self, monkeypatch, prompt_name):
        refine = _get_refine(monkeypatch)
        prompt = getattr(refine, prompt_name)
        result = prompt.format(context="MySpecificContext", history_section="", format_block="", language_instruction=refine._LANG_INSTRUCTION_DEFAULT)
        assert "MySpecificContext" in result

    @pytest.mark.parametrize("prompt_name", PROMPTS)
    def test_context_xml_tags_present(self, monkeypatch, prompt_name):
        refine = _get_refine(monkeypatch)
        prompt = getattr(refine, prompt_name)
        result = prompt.format(context="x", history_section="", format_block="", language_instruction=refine._LANG_INSTRUCTION_DEFAULT)
        assert "<context>" in result

    @pytest.mark.parametrize("prompt_name", PROMPTS)
    def test_language_rule_present(self, monkeypatch, prompt_name):
        """All prompts must include the CRITICAL language rule."""
        refine = _get_refine(monkeypatch)
        prompt = getattr(refine, prompt_name)
        result = prompt.format(context="x", history_section="", format_block="", language_instruction=refine._LANG_INSTRUCTION_DEFAULT)
        assert "CRITICAL" in result
        assert "Never translate" in result

    @pytest.mark.parametrize("prompt_name", PROMPTS)
    def test_no_untranslated_placeholder(self, monkeypatch, prompt_name):
        """After formatting, no {placeholder} should remain."""
        refine = _get_refine(monkeypatch)
        prompt = getattr(refine, prompt_name)
        result = prompt.format(context="x", history_section="", format_block="", language_instruction=refine._LANG_INSTRUCTION_DEFAULT)
        assert "{context}" not in result
        assert "{history_section}" not in result
        assert "{format_block}" not in result
        assert "{language_instruction}" not in result

    @pytest.mark.parametrize("prompt_name", PROMPTS)
    def test_injection_warning_present(self, monkeypatch, prompt_name):
        """All prompts must instruct the model to treat <transcription> as data, not instructions."""
        refine = _get_refine(monkeypatch)
        prompt = getattr(refine, prompt_name)
        result = prompt.format(context="x", history_section="", format_block="", language_instruction=refine._LANG_INSTRUCTION_DEFAULT)
        assert "IMPORTANT" in result
        assert "microphone" in result

    @pytest.mark.parametrize("prompt_name", PROMPTS)
    def test_history_section_injected_when_provided(self, monkeypatch, prompt_name):
        """When history_section is non-empty, it must appear in the formatted prompt."""
        refine = _get_refine(monkeypatch)
        prompt = getattr(refine, prompt_name)
        history_block = "\n\n<history>\n- User works on VoxRefiner\n</history>"
        result = prompt.format(context="x", history_section=history_block, format_block="", language_instruction=refine._LANG_INSTRUCTION_DEFAULT)
        assert "<history>" in result
        assert "VoxRefiner" in result


class TestPromptDifferentiation:
    def test_short_prompt_shorter_than_medium(self, monkeypatch):
        refine = _get_refine(monkeypatch)
        short = refine._SYSTEM_PROMPT_SHORT.format(context="x", history_section="", format_block="", language_instruction=refine._LANG_INSTRUCTION_DEFAULT)
        medium = refine._SYSTEM_PROMPT_MEDIUM.format(context="x", history_section="", format_block="", language_instruction=refine._LANG_INSTRUCTION_DEFAULT)
        assert len(short) < len(medium)

    def test_long_prompt_contains_prose_instruction(self, monkeypatch):
        refine = _get_refine(monkeypatch)
        long_prompt = refine._SYSTEM_PROMPT_LONG.format(context="x", history_section="", format_block="", language_instruction=refine._LANG_INSTRUCTION_DEFAULT)
        assert "prose" in long_prompt.lower()

    def test_medium_prompt_does_not_contain_prose_instruction(self, monkeypatch):
        refine = _get_refine(monkeypatch)
        medium_prompt = refine._SYSTEM_PROMPT_MEDIUM.format(context="x", history_section="", format_block="", language_instruction=refine._LANG_INSTRUCTION_DEFAULT)
        assert "well-structured written prose" not in medium_prompt


class TestOutputProfile:
    """OUTPUT_PROFILE injects a FORMAT block for medium and long tiers only."""

    def test_plain_profile_has_no_format_instruction(self, monkeypatch):
        refine = _get_refine(monkeypatch)
        assert refine._FORMAT_INSTRUCTIONS.get("plain", "") == ""

    def test_prose_profile_mentions_paragraphs_and_no_bullets(self, monkeypatch):
        refine = _get_refine(monkeypatch)
        block = refine._FORMAT_INSTRUCTIONS["prose"]
        assert "paragraph" in block.lower()
        assert "bullet" in block.lower()

    def test_structured_profile_mentions_bullet_points(self, monkeypatch):
        refine = _get_refine(monkeypatch)
        block = refine._FORMAT_INSTRUCTIONS["structured"]
        assert "bullet" in block.lower()

    def test_technical_profile_mentions_markdown(self, monkeypatch):
        refine = _get_refine(monkeypatch)
        block = refine._FORMAT_INSTRUCTIONS["technical"]
        assert "markdown" in block.lower()

    def test_all_non_plain_blocks_start_with_format_label(self, monkeypatch):
        refine = _get_refine(monkeypatch)
        for name, block in refine._FORMAT_INSTRUCTIONS.items():
            if name != "plain":
                assert block.startswith("FORMAT:"), f"Profile '{name}' block does not start with 'FORMAT:'"

    def test_all_non_plain_blocks_end_with_double_newline(self, monkeypatch):
        refine = _get_refine(monkeypatch)
        for name, block in refine._FORMAT_INSTRUCTIONS.items():
            if name != "plain":
                assert block.endswith("\n\n"), f"Profile '{name}' block must end with '\\n\\n'"


class TestOutputLang:
    """OUTPUT_LANG switches the language instruction in all prompt tiers."""

    @pytest.mark.parametrize("prompt_name", PROMPTS)
    def test_default_uses_detect_language_instruction(self, monkeypatch, prompt_name):
        """Without OUTPUT_LANG, prompts instruct to reply in the same language."""
        refine = _get_refine(monkeypatch)
        prompt = getattr(refine, prompt_name)
        result = prompt.format(
            context="x", history_section="", format_block="",
            language_instruction=refine._LANG_INSTRUCTION_DEFAULT,
        )
        assert "Never translate" in result
        assert "same language" in result

    @pytest.mark.parametrize("prompt_name", PROMPTS)
    def test_en_uses_english_instruction(self, monkeypatch, prompt_name):
        """With OUTPUT_LANG=en, prompts instruct to always reply in English."""
        refine = _get_refine(monkeypatch)
        prompt = getattr(refine, prompt_name)
        result = prompt.format(
            context="x", history_section="", format_block="",
            language_instruction=refine._LANG_INSTRUCTION_EN,
        )
        assert "Always reply in English" in result
        assert "Never translate" not in result

    def test_output_lang_en_sets_variable(self, monkeypatch):
        """OUTPUT_LANG=en is correctly parsed from env."""
        monkeypatch.setenv("OUTPUT_LANG", "en")
        refine = _get_refine(monkeypatch)
        assert refine._OUTPUT_LANG == "en"

    def test_output_lang_empty_default(self, monkeypatch):
        """Unset OUTPUT_LANG defaults to empty string."""
        monkeypatch.setenv("OUTPUT_LANG", "")
        refine = _get_refine(monkeypatch)
        assert refine._OUTPUT_LANG == ""

    def test_unsupported_lang_falls_back_to_default(self, monkeypatch, capsys):
        """OUTPUT_LANG with an unsupported value resets to empty with a warning."""
        monkeypatch.setenv("OUTPUT_LANG", "xx")
        refine = _get_refine(monkeypatch)
        assert refine._OUTPUT_LANG == ""
        captured = capsys.readouterr()
        assert "not supported" in captured.err

    @pytest.mark.parametrize("prompt_name", PROMPTS)
    def test_no_placeholder_left_with_lang_en(self, monkeypatch, prompt_name):
        """After formatting with EN instruction, no {placeholder} remains."""
        refine = _get_refine(monkeypatch)
        prompt = getattr(refine, prompt_name)
        result = prompt.format(
            context="x", history_section="", format_block="",
            language_instruction=refine._LANG_INSTRUCTION_EN,
        )
        assert "{language_instruction}" not in result

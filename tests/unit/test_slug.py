"""Unit tests for src/slug.py — pure functions only (no API calls).

Covers:
  _clean_slug   — accent removal, special-char normalisation, hyphen collapsing,
                  60-char limit, empty-input fallback
  _build_prompt — language instruction switching (auto vs en)
"""

import pytest

from src.slug import _build_prompt, _clean_slug


# ---------------------------------------------------------------------------
# _clean_slug
# ---------------------------------------------------------------------------

class TestCleanSlugBasic:
    def test_simple_lowercase_passthrough(self):
        assert _clean_slug("hello-world") == "hello-world"

    def test_uppercased_to_lowercase(self):
        assert _clean_slug("Hello-World") == "hello-world"

    def test_leading_trailing_whitespace_stripped(self):
        assert _clean_slug("  hello-world  ") == "hello-world"

    def test_spaces_replaced_by_hyphens(self):
        assert _clean_slug("hello world") == "hello-world"

    def test_digits_preserved(self):
        assert _clean_slug("step-1-done") == "step-1-done"

    def test_empty_string_returns_fallback(self):
        result = _clean_slug("")
        assert result != ""
        assert isinstance(result, str)

    def test_whitespace_only_returns_fallback(self):
        result = _clean_slug("   ")
        assert result != ""

    def test_hyphens_only_returns_fallback(self):
        result = _clean_slug("---")
        assert result != ""


class TestCleanSlugAccents:
    def test_e_acute(self):
        assert _clean_slug("éléphant") == "elephant"

    def test_e_grave(self):
        assert _clean_slug("père") == "pere"

    def test_e_circumflex(self):
        assert _clean_slug("fête") == "fete"

    def test_e_umlaut(self):
        assert _clean_slug("naïve") == "naive"

    def test_a_grave(self):
        assert _clean_slug("à") == "a"

    def test_a_circumflex(self):
        assert _clean_slug("château") == "chateau"

    def test_a_umlaut(self):
        assert _clean_slug("Mädchen") == "madchen"

    def test_i_circumflex(self):
        assert _clean_slug("île") == "ile"

    def test_i_umlaut(self):
        assert _clean_slug("naïf") == "naif"

    def test_o_circumflex(self):
        assert _clean_slug("côte") == "cote"

    def test_o_umlaut(self):
        assert _clean_slug("Köln") == "koln"

    def test_u_grave(self):
        assert _clean_slug("où") == "ou"

    def test_u_circumflex(self):
        assert _clean_slug("flûte") == "flute"

    def test_u_umlaut(self):
        assert _clean_slug("über") == "uber"

    def test_cedilla(self):
        assert _clean_slug("façade") == "facade"

    def test_n_tilde(self):
        assert _clean_slug("señor") == "senor"

    def test_mixed_accents(self):
        assert _clean_slug("réunion-économique") == "reunion-economique"


class TestCleanSlugSpecialChars:
    def test_underscore_becomes_hyphen(self):
        assert _clean_slug("hello_world") == "hello-world"

    def test_dot_becomes_hyphen(self):
        assert _clean_slug("hello.world") == "hello-world"

    def test_slash_becomes_hyphen(self):
        assert _clean_slug("hello/world") == "hello-world"

    def test_apostrophe_becomes_hyphen(self):
        result = _clean_slug("l'exemple")
        assert "l" in result
        assert "exemple" in result
        assert "'" not in result

    def test_parentheses_removed(self):
        result = _clean_slug("test(value)")
        assert "(" not in result
        assert ")" not in result

    def test_exclamation_removed(self):
        assert "!" not in _clean_slug("hello!")

    def test_question_mark_removed(self):
        assert "?" not in _clean_slug("what?")

    def test_only_alnum_and_hyphens_in_output(self):
        result = _clean_slug("hello, world! (test)")
        assert all(c.isalnum() or c == "-" for c in result)


class TestCleanSlugHyphens:
    def test_multiple_hyphens_collapsed(self):
        assert _clean_slug("hello---world") == "hello-world"

    def test_leading_hyphen_stripped(self):
        result = _clean_slug("-hello")
        assert not result.startswith("-")

    def test_trailing_hyphen_stripped(self):
        result = _clean_slug("hello-")
        assert not result.endswith("-")

    def test_special_chars_creating_adjacent_hyphens_collapsed(self):
        result = _clean_slug("hello!!world")
        assert "--" not in result

    def test_no_leading_or_trailing_hyphen_after_special_chars(self):
        result = _clean_slug("!hello!")
        assert not result.startswith("-")
        assert not result.endswith("-")


class TestCleanSlugLength:
    def test_short_slug_not_truncated(self):
        assert _clean_slug("short") == "short"

    def test_exactly_60_chars_not_truncated(self):
        slug = "a" * 60
        assert _clean_slug(slug) == slug

    def test_61_chars_truncated_to_60(self):
        slug = "a" * 61
        assert len(_clean_slug(slug)) == 60

    def test_long_slug_truncated(self):
        slug = "a" * 200
        assert len(_clean_slug(slug)) == 60

    def test_long_slug_with_hyphens_truncated(self):
        slug = ("word-" * 20).strip("-")
        result = _clean_slug(slug)
        assert len(result) <= 60


# ---------------------------------------------------------------------------
# _build_prompt
# ---------------------------------------------------------------------------

class TestBuildPrompt:
    def test_returns_string(self):
        assert isinstance(_build_prompt("some text", "auto"), str)

    def test_contains_transcription(self):
        prompt = _build_prompt("my transcription text", "auto")
        assert "my transcription text" in prompt

    def test_auto_lang_instruction_same_language(self):
        prompt = _build_prompt("hello world", "auto")
        assert "same language" in prompt.lower()

    def test_en_lang_instruction_english(self):
        prompt = _build_prompt("hello world", "en")
        assert "english" in prompt.lower()

    def test_auto_does_not_mention_english_forced(self):
        prompt = _build_prompt("bonjour", "auto")
        assert "regardless" not in prompt.lower()

    def test_en_does_not_mention_same_language(self):
        prompt = _build_prompt("bonjour", "en")
        assert "same language" not in prompt.lower()

    def test_slug_rules_present(self):
        prompt = _build_prompt("some text", "auto")
        assert "lowercase" in prompt.lower()
        assert "hyphen" in prompt.lower()

    def test_word_count_constraint_mentioned(self):
        prompt = _build_prompt("some text", "auto")
        assert "3" in prompt and "5" in prompt

    def test_long_text_truncated_to_400_chars(self):
        long_text = "word " * 200  # 1000 chars
        prompt = _build_prompt(long_text, "auto")
        # The prompt itself contains at most 400 chars of the transcription
        assert long_text[:400] in prompt
        assert long_text[400:] not in prompt

    def test_output_only_instruction(self):
        prompt = _build_prompt("test", "auto")
        assert "only" in prompt.lower()

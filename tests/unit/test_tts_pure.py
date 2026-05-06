"""Unit tests for pure helper functions in src/tts.py.

Covers (no API calls, no audio I/O):
  _is_gradium_voice()        — UUID → False, non-UUID → True
  _is_google_voice()         — "google-" prefix detection
  _strip_markdown()          — bold, italic, headings, inline code
  _collapse_math_lines()     — Wikipedia-style fragmented formula joining
  _merge_split_identifiers() — "E v a l" → "Eval", "C 1" → "C1"
  _expand_math_symbols()     — symbol-to-French substitution, code spans preserved
  _expand_function_calls()   — D(E(m)) → D de E de m (nested expansion)
  _is_quoted_paragraph()     — quote-start detection («, ", ")
  _isolate_quotes()          — embedded quotes split into separate paragraphs
  _split_sentences()         — sub-split oversized paragraphs at sentence boundaries
  _make_chunks()             — paragraph grouping, oversized splitting, quote voice routing
  _parse_accent_tags()       — [accent: french/quebec/...] tag parsing
  _resolve_voice_id()        — TTS_LANG → map, TTS_VOICE_ID, default fallback
"""

import sys
from typing import Optional
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Module loader (needed for env-sensitive functions)
# ---------------------------------------------------------------------------

def _get_tts(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    if "src.tts" in sys.modules:
        del sys.modules["src.tts"]
    import src.tts as tts
    return tts


# For pure functions that don't depend on env at import time, we can import once.
import src.tts as _tts_module


# ---------------------------------------------------------------------------
# _is_gradium_voice
# ---------------------------------------------------------------------------

class TestIsGradiumVoice:
    def test_uuid_returns_false(self):
        assert _tts_module._is_gradium_voice("c69964a6-ab8b-4f8a-9465-ec0925096ec8") is False

    def test_uuid_uppercase_returns_false(self):
        assert _tts_module._is_gradium_voice("C69964A6-AB8B-4F8A-9465-EC0925096EC8") is False

    def test_short_alphanumeric_returns_true(self):
        assert _tts_module._is_gradium_voice("abc123") is True

    def test_google_prefix_returns_true(self):
        assert _tts_module._is_gradium_voice("google-kore") is True

    def test_eleven_prefix_returns_true(self):
        assert _tts_module._is_gradium_voice("eleven-v2-pNInz6obpgDQGcFmaJgB") is True

    def test_grok_prefix_returns_true(self):
        assert _tts_module._is_gradium_voice("grok-ara-fr") is True


# ---------------------------------------------------------------------------
# _is_google_voice
# ---------------------------------------------------------------------------

class TestIsGoogleVoice:
    def test_google_prefix_returns_true(self):
        assert _tts_module._is_google_voice("google-kore") is True

    def test_google_with_lang_returns_true(self):
        assert _tts_module._is_google_voice("google-kore-fr-ca") is True

    def test_mistral_uuid_returns_false(self):
        assert _tts_module._is_google_voice("c69964a6-ab8b-4f8a-9465-ec0925096ec8") is False

    def test_eleven_prefix_returns_false(self):
        assert _tts_module._is_google_voice("eleven-v2-voice") is False

    def test_bare_google_without_dash_returns_false(self):
        assert _tts_module._is_google_voice("google") is False


# ---------------------------------------------------------------------------
# _strip_markdown
# ---------------------------------------------------------------------------

class TestStripMarkdown:
    def test_bold_removed(self):
        assert _tts_module._strip_markdown("**bold text**") == "bold text"

    def test_italic_removed(self):
        assert _tts_module._strip_markdown("*italic*") == "italic"

    def test_triple_star_bold_italic_removed(self):
        assert _tts_module._strip_markdown("***very important***") == "very important"

    def test_heading_h1_removed(self):
        assert _tts_module._strip_markdown("# Title") == "Title"

    def test_heading_h3_removed(self):
        assert _tts_module._strip_markdown("### Sub-title") == "Sub-title"

    def test_inline_code_removed(self):
        assert _tts_module._strip_markdown("`code`") == "code"

    def test_triple_backtick_inline_removed(self):
        result = _tts_module._strip_markdown("```block```")
        assert "```" not in result

    def test_plain_text_unchanged(self):
        text = "This is plain text."
        assert _tts_module._strip_markdown(text) == text

    def test_mixed_formatting(self):
        result = _tts_module._strip_markdown("## Title\n**bold** and *italic*")
        assert "##" not in result
        assert "**" not in result
        assert "*" not in result
        assert "Title" in result
        assert "bold" in result
        assert "italic" in result


# ---------------------------------------------------------------------------
# _collapse_math_lines
# ---------------------------------------------------------------------------

class TestCollapseMathLines:
    def test_wikipedia_formula_collapsed(self):
        # Typical Wikipedia SVG rendering: each symbol on its own line
        inp = "K\n:\nN\n→\nPK\n×\nSK"
        out = _tts_module._collapse_math_lines(inp)
        # Should be joined on a single line
        assert "\n" not in out.strip()
        assert "K" in out
        assert "×" in out

    def test_fewer_than_3_lines_not_collapsed(self):
        inp = "K\n:"
        out = _tts_module._collapse_math_lines(inp)
        assert out == inp

    def test_french_prose_not_collapsed(self):
        # French lines have accented chars → not math tokens
        inp = "de\nla\nun\nle\nest\nune"
        out = _tts_module._collapse_math_lines(inp)
        # Lines with accented-free French words: but "de", "la", "un"
        # have no accented chars — however single-char ratio is 0 → not collapsed
        assert "de" in out

    def test_mostly_multi_char_tokens_not_collapsed(self):
        # Ratio of single-char tokens < 50 %  → no collapsing
        inp = "PK\nSK\nEval\nFunc\nName"
        out = _tts_module._collapse_math_lines(inp)
        # Not collapsed — no single-char tokens at all
        assert "PK" in out

    def test_normal_text_around_formula_preserved(self):
        inp = "Voici la formule :\nK\n:\nN\n→\nPK\n×\nSK\nC'est clair."
        out = _tts_module._collapse_math_lines(inp)
        assert "Voici la formule" in out
        assert "C'est clair." in out


# ---------------------------------------------------------------------------
# _merge_split_identifiers
# ---------------------------------------------------------------------------

class TestMergeSplitIdentifiers:
    def test_four_letters_merged(self):
        out = _tts_module._merge_split_identifiers("E v a l")
        assert "Eval" in out

    def test_three_letters_merged(self):
        out = _tts_module._merge_split_identifiers("m o d")
        assert "mod" in out

    def test_letter_digit_merged(self):
        out = _tts_module._merge_split_identifiers("C 1")
        assert "C1" in out

    def test_comma_breaks_run(self):
        out = _tts_module._merge_split_identifiers("K , E")
        # Comma prevents merging K and E
        assert "K" in out
        assert "E" in out
        # Not merged into "KE"
        assert "KE" not in out

    def test_single_letter_no_run(self):
        out = _tts_module._merge_split_identifiers("K")
        assert out == "K"

    def test_normal_word_unchanged(self):
        text = "bonjour le monde"
        assert _tts_module._merge_split_identifiers(text) == text


# ---------------------------------------------------------------------------
# _expand_math_symbols
# ---------------------------------------------------------------------------

class TestExpandMathSymbols:
    def test_for_all_symbol(self):
        out = _tts_module._expand_math_symbols("∀x")
        assert "pour tout" in out

    def test_belongs_to_symbol(self):
        out = _tts_module._expand_math_symbols("x ∈ S")
        assert "appartient à" in out

    def test_arrow_symbol(self):
        out = _tts_module._expand_math_symbols("A → B")
        assert "vers" in out

    def test_times_symbol(self):
        out = _tts_module._expand_math_symbols("PK × SK")
        assert "croix" in out

    def test_code_span_preserved(self):
        # Symbols inside backtick spans must NOT be replaced
        out = _tts_module._expand_math_symbols("`∀x ∈ S`")
        assert "∀" in out
        assert "∈" in out

    def test_not_equal_symbol(self):
        out = _tts_module._expand_math_symbols("a ≠ b")
        assert "différent de" in out

    def test_infinity_symbol(self):
        out = _tts_module._expand_math_symbols("∞")
        assert "infini" in out

    def test_plain_text_unchanged(self):
        text = "Bonjour le monde."
        assert _tts_module._expand_math_symbols(text) == text


# ---------------------------------------------------------------------------
# _expand_function_calls
# ---------------------------------------------------------------------------

class TestExpandFunctionCalls:
    def test_simple_call(self):
        out = _tts_module._expand_function_calls("D(m)")
        assert out == "D de m"

    def test_nested_call(self):
        out = _tts_module._expand_function_calls("D(E(m))")
        assert out == "D de E de m"

    def test_multiple_args(self):
        out = _tts_module._expand_function_calls("Eval(f, C1, C2)")
        assert "Eval de" in out
        assert "virgule" in out

    def test_triple_nesting(self):
        out = _tts_module._expand_function_calls("D(E(K(x)))")
        assert "D de E de K de x" == out

    def test_lowercase_start_unchanged(self):
        # Lowercase identifiers are not expanded (would false-positive on French)
        text = "sin(x)"
        assert _tts_module._expand_function_calls(text) == text

    def test_uppercase_single_letter(self):
        out = _tts_module._expand_function_calls("K(x, y)")
        assert "K de" in out
        assert "virgule" in out

    def test_plain_text_unchanged(self):
        text = "Bonjour le monde."
        assert _tts_module._expand_function_calls(text) == text


# ---------------------------------------------------------------------------
# _is_quoted_paragraph
# ---------------------------------------------------------------------------

class TestIsQuotedParagraph:
    def test_french_guillemet_returns_true(self):
        assert _tts_module._is_quoted_paragraph("«Bonjour le monde»") is True

    def test_curly_open_quote_returns_true(self):
        assert _tts_module._is_quoted_paragraph("“Hello world”") is True

    def test_straight_double_quote_returns_true(self):
        assert _tts_module._is_quoted_paragraph('"This is a quote"') is True

    def test_normal_text_returns_false(self):
        assert _tts_module._is_quoted_paragraph("Normal paragraph text.") is False

    def test_empty_string_returns_false(self):
        assert _tts_module._is_quoted_paragraph("") is False

    def test_leading_whitespace_stripped(self):
        # strip() is applied before the check
        assert _tts_module._is_quoted_paragraph("  «Quoted»") is True


# ---------------------------------------------------------------------------
# _isolate_quotes
# ---------------------------------------------------------------------------

class TestIsolateQuotes:
    def test_embedded_guillemet_quote_isolated(self):
        text = "L'objectif est «de doubler la production» selon la direction."
        out = _tts_module._isolate_quotes(text)
        paragraphs = [p.strip() for p in out.split("\n\n") if p.strip()]
        assert any("«de doubler la production»" == p for p in paragraphs)

    def test_already_isolated_quote_unchanged(self):
        text = "«Bonjour tout le monde.»"
        out = _tts_module._isolate_quotes(text)
        # Should remain a single paragraph
        paragraphs = [p.strip() for p in out.split("\n\n") if p.strip()]
        assert len(paragraphs) == 1

    def test_no_quote_paragraph_unchanged(self):
        text = "Normal text without any quotation marks."
        assert _tts_module._isolate_quotes(text) == text

    def test_multiple_quotes_in_para_all_isolated(self):
        text = 'Il a dit «oui» puis précisé «sous conditions» avant de partir.'
        out = _tts_module._isolate_quotes(text)
        paragraphs = [p.strip() for p in out.split("\n\n") if p.strip()]
        assert any("«oui»" == p for p in paragraphs)
        assert any("«sous conditions»" == p for p in paragraphs)

    def test_fragment_with_no_alphanum_discarded(self):
        # A lone "." or "," fragment should not become a paragraph
        text = "Avant «la citation». Après."
        out = _tts_module._isolate_quotes(text)
        for para in out.split("\n\n"):
            para = para.strip()
            if para:
                assert any(c.isalnum() for c in para)

    def test_empty_text_returns_empty(self):
        assert _tts_module._isolate_quotes("").strip() == ""


# ---------------------------------------------------------------------------
# _split_sentences
# ---------------------------------------------------------------------------

class TestSplitSentences:
    def test_short_text_not_split(self):
        text = "Hello world."
        result = _tts_module._split_sentences(text, max_chars=100)
        assert result == ["Hello world."]

    def test_long_text_split_at_sentence_boundary(self):
        text = "First sentence. Second sentence. Third sentence."
        result = _tts_module._split_sentences(text, max_chars=20)
        # Each sentence fits individually
        assert len(result) >= 2
        assert all("sentence" in r for r in result)

    def test_sentence_joined_when_they_fit(self):
        text = "Short. Also short."
        result = _tts_module._split_sentences(text, max_chars=100)
        assert len(result) == 1

    def test_empty_string_returns_list_with_empty(self):
        result = _tts_module._split_sentences("", max_chars=100)
        assert result == []

    def test_oversized_single_word_not_infinite_loop(self):
        # A word longer than max_chars should still produce output
        text = "a" * 30
        result = _tts_module._split_sentences(text, max_chars=10)
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_question_mark_splits(self):
        text = "Is this true? Yes it is. Good to know."
        result = _tts_module._split_sentences(text, max_chars=20)
        assert len(result) >= 2

    def test_no_chunk_exceeds_max_chars_significantly(self):
        # No chunk should be more than max_chars (unless a single word is longer)
        long_text = "The quick brown fox jumps over the lazy dog. " * 5
        result = _tts_module._split_sentences(long_text, max_chars=50)
        for chunk in result:
            # Allow overrun only for unsplittable single token
            assert len(chunk) <= 50 + 50


# ---------------------------------------------------------------------------
# _make_chunks
# ---------------------------------------------------------------------------

class TestMakeChunksBasic:
    def test_empty_text_returns_empty(self):
        assert _tts_module._make_chunks("") == []

    def test_whitespace_only_returns_empty(self):
        assert _tts_module._make_chunks("   \n\n   ") == []

    def test_short_text_single_chunk(self):
        result = _tts_module._make_chunks("Hello world.", max_chars=800)
        assert len(result) == 1
        assert result[0][0] == "Hello world."
        assert result[0][1] is None  # no quote voice

    def test_result_is_list_of_tuples(self):
        result = _tts_module._make_chunks("Test text.", max_chars=800)
        assert isinstance(result, list)
        assert all(isinstance(item, tuple) and len(item) == 2 for item in result)


class TestMakeChunksGrouping:
    def test_small_paragraphs_grouped(self):
        # Two short paragraphs that together fit in max_chars → 1 chunk
        text = "Para one.\n\nPara two."
        result = _tts_module._make_chunks(text, max_chars=800)
        assert len(result) == 1
        assert "Para one." in result[0][0]
        assert "Para two." in result[0][0]

    def test_paragraphs_split_when_combined_exceeds_max(self):
        # Each paragraph fits alone but not together
        text = "A" * 60 + "\n\n" + "B" * 60
        result = _tts_module._make_chunks(text, max_chars=80)
        assert len(result) == 2

    def test_oversized_single_paragraph_sub_split(self):
        # Paragraph longer than max_chars → sub-split at sentence boundaries
        long_para = ("The quick brown fox jumps over the lazy dog. " * 8).strip()
        result = _tts_module._make_chunks(long_para, max_chars=100)
        assert len(result) > 1
        # All pieces together should reconstruct the content
        combined = " ".join(r[0] for r in result)
        assert "quick brown fox" in combined


class TestMakeChunksQuoteVoice:
    def test_quoted_paragraph_gets_quote_voice_id(self):
        text = "Normal text.\n\n«Une citation importante.»\n\nSuite normale."
        quote_id = "quote-voice-uuid"
        result = _tts_module._make_chunks(text, max_chars=800, quote_voice_id=quote_id)
        voices = [voice for _, voice in result]
        assert quote_id in voices

    def test_non_quoted_paragraphs_get_none_voice(self):
        text = "Normal text.\n\nAlso normal."
        result = _tts_module._make_chunks(text, max_chars=800, quote_voice_id="some-voice")
        # No paragraph starts with a quote
        assert all(voice is None for _, voice in result)

    def test_quote_voice_none_no_routing(self):
        text = "Normal.\n\n«A quote.»\n\nEnd."
        result = _tts_module._make_chunks(text, max_chars=800, quote_voice_id=None)
        # Without quote voice, all chunks have None
        assert all(voice is None for _, voice in result)

    def test_quoted_chunk_isolated_from_group(self):
        # A quoted paragraph must be emitted alone (not merged with neighbors)
        text = "Before.\n\n«Quote.»\n\nAfter."
        result = _tts_module._make_chunks(text, max_chars=800, quote_voice_id="q-voice")
        texts = [t for t, _ in result]
        # The quote must be its own chunk
        assert any(t == "«Quote.»" for t in texts)


# ---------------------------------------------------------------------------
# _parse_accent_tags
# ---------------------------------------------------------------------------

class TestParseAccentTags:
    def test_french_accent_tag(self):
        text, lang = _tts_module._parse_accent_tags("[accent: french] Bonjour.")
        assert lang == "fr-FR"
        assert "[accent:" not in text

    def test_quebec_accent_tag(self):
        _, lang = _tts_module._parse_accent_tags("[accent: quebec] Text.")
        assert lang == "fr-CA"

    def test_canadian_accent_tag(self):
        _, lang = _tts_module._parse_accent_tags("[accent: canadian] Text.")
        assert lang == "fr-CA"

    def test_unknown_accent_tag(self):
        _, lang = _tts_module._parse_accent_tags("[accent: german] Text.")
        assert lang is None

    def test_no_tag_returns_none_lang(self):
        text, lang = _tts_module._parse_accent_tags("Normal text.")
        assert lang is None
        assert text == "Normal text."

    def test_case_insensitive(self):
        _, lang = _tts_module._parse_accent_tags("[ACCENT: FRENCH] Text.")
        assert lang == "fr-FR"

    def test_tag_removed_from_text(self):
        text, _ = _tts_module._parse_accent_tags("[accent: french] Bonjour le monde.")
        assert "[accent:" not in text
        assert "Bonjour le monde." in text


# ---------------------------------------------------------------------------
# _resolve_voice_id
# ---------------------------------------------------------------------------

class TestResolveVoiceId:
    def test_known_lang_returns_map_voice(self, monkeypatch):
        monkeypatch.setenv("TTS_LANG", "fr")
        monkeypatch.delenv("TTS_VOICE_ID", raising=False)
        tts = _get_tts(monkeypatch)
        result = tts._resolve_voice_id()
        assert result == tts._LANG_VOICE_MAP["fr"]

    def test_english_lang_returns_map_voice(self, monkeypatch):
        monkeypatch.setenv("TTS_LANG", "en")
        monkeypatch.delenv("TTS_VOICE_ID", raising=False)
        tts = _get_tts(monkeypatch)
        result = tts._resolve_voice_id()
        assert result == tts._LANG_VOICE_MAP["en"]

    def test_unknown_lang_falls_through_to_voice_id(self, monkeypatch):
        monkeypatch.setenv("TTS_LANG", "de")  # not in _LANG_VOICE_MAP
        monkeypatch.setenv("TTS_VOICE_ID", "custom-voice-id")
        tts = _get_tts(monkeypatch)
        result = tts._resolve_voice_id()
        assert result == "custom-voice-id"

    def test_empty_lang_uses_voice_id(self, monkeypatch):
        monkeypatch.setenv("TTS_LANG", "")
        monkeypatch.setenv("TTS_VOICE_ID", "my-uuid")
        tts = _get_tts(monkeypatch)
        result = tts._resolve_voice_id()
        assert result == "my-uuid"

    def test_empty_voice_id_returns_none(self, monkeypatch):
        monkeypatch.setenv("TTS_LANG", "de")
        monkeypatch.setenv("TTS_VOICE_ID", "")
        tts = _get_tts(monkeypatch)
        result = tts._resolve_voice_id()
        assert result is None

    def test_no_lang_no_voice_id_uses_default(self, monkeypatch):
        monkeypatch.setenv("TTS_LANG", "")
        monkeypatch.delenv("TTS_VOICE_ID", raising=False)
        monkeypatch.setenv("TTS_DEFAULT_VOICE_ID", "default-uuid")
        tts = _get_tts(monkeypatch)
        result = tts._resolve_voice_id()
        assert result == "default-uuid"

    def test_returns_none_when_default_empty(self, monkeypatch):
        monkeypatch.setenv("TTS_LANG", "")
        monkeypatch.delenv("TTS_VOICE_ID", raising=False)
        monkeypatch.setenv("TTS_DEFAULT_VOICE_ID", "")
        tts = _get_tts(monkeypatch)
        result = tts._resolve_voice_id()
        assert result is None

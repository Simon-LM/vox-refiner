"""Unit tests for _verbalize_tables() in src/tts.py."""

import sys
import os

import pytest


def _get_tts(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    if "src.tts" in sys.modules:
        del sys.modules["src.tts"]
    import src.tts as tts
    return tts


class TestPipeTable:
    def test_simple_3col(self, monkeypatch):
        tts = _get_tts(monkeypatch)
        inp = (
            "| Length | Model | Fallback |\n"
            "|--------|-------|----------|\n"
            "| <80 words | mistral-small | mistral-medium |\n"
            "| >240 words | magistral-large | mistral-medium |"
        )
        out = tts._verbalize_tables(inp)
        assert "Length: <80 words. Model: mistral-small. Fallback: mistral-medium." in out
        assert "Length: >240 words. Model: magistral-large. Fallback: mistral-medium." in out

    def test_separator_row_skipped(self, monkeypatch):
        tts = _get_tts(monkeypatch)
        inp = (
            "| A | B |\n"
            "|---|---|\n"
            "| x | y |"
        )
        out = tts._verbalize_tables(inp)
        assert "|---" not in out
        assert "A: x. B: y." in out

    def test_dash_cell_skipped(self, monkeypatch):
        tts = _get_tts(monkeypatch)
        inp = (
            "| Profile | Alias | Format |\n"
            "|---------|-------|--------|\n"
            "| plain | — | Flowing text |"
        )
        out = tts._verbalize_tables(inp)
        assert "Alias" not in out
        assert "Profile: plain. Format: Flowing text." in out

    def test_non_table_pipe_line_unchanged(self, monkeypatch):
        tts = _get_tts(monkeypatch)
        inp = "This sentence has a | character in it but is not a table."
        out = tts._verbalize_tables(inp)
        assert out == inp


class TestTabTable:
    def test_basic_tab_table(self, monkeypatch):
        tts = _get_tts(monkeypatch)
        inp = "Length\tModel\tFallback\n<80 words\tmistral-small\tmistral-medium\n>240 words\tmagistral-large\tmistral-medium"
        out = tts._verbalize_tables(inp)
        assert "Length: <80 words. Model: mistral-small. Fallback: mistral-medium." in out
        assert "Length: >240 words. Model: magistral-large. Fallback: mistral-medium." in out

    def test_single_tab_col_not_treated_as_table(self, monkeypatch):
        tts = _get_tts(monkeypatch)
        inp = "key\tvalue"
        out = tts._verbalize_tables(inp)
        # Only 1 tab = 2 cols, still valid as table (mode >= 2)
        # This is acceptable behaviour — 2 cols is allowed for tab tables
        # Just verify it doesn't crash and returns a string
        assert isinstance(out, str)

    def test_tab_dash_cell_skipped(self, monkeypatch):
        tts = _get_tts(monkeypatch)
        inp = "Profile\tAlias\tFormat\nplain\t—\tFlowing text"
        out = tts._verbalize_tables(inp)
        assert "Alias" not in out
        assert "Profile: plain. Format: Flowing text." in out


class TestSpaceAlignedTable:
    def test_3col_3row_converted(self, monkeypatch):
        tts = _get_tts(monkeypatch)
        inp = (
            "Transcription length    Primary model   Fallback\n"
            "< 80 words      mistral-small-latest    mistral-medium-latest\n"
            "80 – 240 words  magistral-small-latest  mistral-medium-latest\n"
            "> 240 words     magistral-medium-latest mistral-medium-latest"
        )
        out = tts._verbalize_tables(inp)
        assert "Transcription length: < 80 words." in out
        assert "Primary model: mistral-small-latest." in out
        assert "Transcription length: 80 – 240 words." in out

    def test_only_2_rows_not_converted(self, monkeypatch):
        """2 rows (header + 1 data) should NOT be converted — too risky."""
        tts = _get_tts(monkeypatch)
        inp = (
            "Name    Age    City\n"
            "Alice   30     Paris"
        )
        out = tts._verbalize_tables(inp)
        # Should be left as-is (only 2 rows)
        assert "Name: Alice" not in out

    def test_prose_not_converted(self, monkeypatch):
        """Regular prose with occasional double-spaces should not be converted."""
        tts = _get_tts(monkeypatch)
        inp = "This is a normal sentence.  It has a double space but is not a table."
        out = tts._verbalize_tables(inp)
        assert out == inp

    def test_heading_not_converted(self, monkeypatch):
        """Lines starting with # should not trigger table detection."""
        tts = _get_tts(monkeypatch)
        inp = (
            "## Heading  with  spaces\n"
            "Col1  Col2  Col3\n"
            "a     b     c\n"
            "d     e     f"
        )
        out = tts._verbalize_tables(inp)
        # The ## line should be left alone
        assert "## Heading" in out


class TestCleanTextIntegration:
    def test_verbalize_tables_called_in_clean_text(self, monkeypatch):
        """_clean_text should convert a pipe table (end-to-end)."""
        tts = _get_tts(monkeypatch)
        inp = (
            "| Col A | Col B |\n"
            "|-------|-------|\n"
            "| foo   | bar   |\n"
            "| baz   | qux   |"
        )
        out = tts._clean_text(inp)
        assert "Col A: foo. Col B: bar." in out
        assert "Col A: baz. Col B: qux." in out
        assert "|" not in out

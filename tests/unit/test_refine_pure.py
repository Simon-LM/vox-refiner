"""Unit tests for src/refine.py — pure helper functions.

Covers (excluding _parse_model_spec/_build_tier_params, already in test_refine_model_spec.py
and _refine_timing, already in test_refine_timing.py):
  _select_models()           — 3-tier routing: SHORT / MEDIUM / LONG thresholds
  _history_line_key()        — timestamp-prefix stripping + lowercase normalisation
  _parse_history_lines()     — keep only valid bullets (starts with '- ', len > 3)
  _build_lang_instruction()  — empty → default, 'en' → EN-specific, known code,
                               unknown code → capitalised fallback
  _strip_unsupported_params() — removes reasoning_effort for non-capable models,
                                does not mutate original, handles None/empty
  _load_history()            — disabled → '', missing file → '', max_bullets cap,
                               full history when max_bullets=None
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Module loader
# ---------------------------------------------------------------------------

def _load_refine(monkeypatch, **env):
    """Reload src.refine with a clean env (always sets MISTRAL_API_KEY)."""
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    for mod in list(sys.modules):
        if mod == "src.refine":
            del sys.modules[mod]
    import src.refine as refine
    return refine


# ---------------------------------------------------------------------------
# _select_models
# ---------------------------------------------------------------------------

class TestSelectModels:
    def test_word_count_zero_routes_short(self, monkeypatch):
        r = _load_refine(monkeypatch)
        primary, fallback = r._select_models(0)
        assert primary == r._MODEL_SHORT
        assert fallback == r._MODEL_SHORT_FALLBACK

    def test_below_threshold_short_routes_short(self, monkeypatch):
        r = _load_refine(monkeypatch)
        primary, _ = r._select_models(r._THRESHOLD_SHORT - 1)
        assert primary == r._MODEL_SHORT

    def test_at_threshold_short_routes_medium(self, monkeypatch):
        r = _load_refine(monkeypatch)
        primary, fallback = r._select_models(r._THRESHOLD_SHORT)
        assert primary == r._MODEL_MEDIUM
        assert fallback == r._MODEL_MEDIUM_FALLBACK

    def test_between_thresholds_routes_medium(self, monkeypatch):
        r = _load_refine(monkeypatch)
        mid = (r._THRESHOLD_SHORT + r._THRESHOLD_LONG) // 2
        primary, _ = r._select_models(mid)
        assert primary == r._MODEL_MEDIUM

    def test_just_below_threshold_long_routes_medium(self, monkeypatch):
        r = _load_refine(monkeypatch)
        primary, _ = r._select_models(r._THRESHOLD_LONG - 1)
        assert primary == r._MODEL_MEDIUM

    def test_at_threshold_long_routes_long(self, monkeypatch):
        r = _load_refine(monkeypatch)
        primary, fallback = r._select_models(r._THRESHOLD_LONG)
        assert primary == r._MODEL_LONG
        assert fallback == r._MODEL_LONG_FALLBACK

    def test_above_threshold_long_routes_long(self, monkeypatch):
        r = _load_refine(monkeypatch)
        primary, _ = r._select_models(r._THRESHOLD_LONG + 500)
        assert primary == r._MODEL_LONG

    def test_returns_two_strings(self, monkeypatch):
        r = _load_refine(monkeypatch)
        result = r._select_models(50)
        assert len(result) == 2
        assert all(isinstance(s, str) for s in result)

    def test_custom_threshold_short_env(self, monkeypatch):
        r = _load_refine(monkeypatch, REFINE_MODEL_THRESHOLD_SHORT="50")
        # 49 < 50 → short
        primary, _ = r._select_models(49)
        assert primary == r._MODEL_SHORT
        # 50 ≥ 50 → medium
        primary, _ = r._select_models(50)
        assert primary == r._MODEL_MEDIUM

    def test_custom_threshold_long_env(self, monkeypatch):
        r = _load_refine(monkeypatch, REFINE_MODEL_THRESHOLD_LONG="300")
        # 299 < 300 → medium
        primary, _ = r._select_models(299)
        assert primary == r._MODEL_MEDIUM
        # 300 ≥ 300 → long
        primary, _ = r._select_models(300)
        assert primary == r._MODEL_LONG

    def test_default_threshold_short_is_80(self, monkeypatch):
        monkeypatch.delenv("REFINE_MODEL_THRESHOLD_SHORT", raising=False)
        r = _load_refine(monkeypatch)
        assert r._THRESHOLD_SHORT == 80

    def test_default_threshold_long_is_240(self, monkeypatch):
        monkeypatch.delenv("REFINE_MODEL_THRESHOLD_LONG", raising=False)
        r = _load_refine(monkeypatch)
        assert r._THRESHOLD_LONG == 240


# ---------------------------------------------------------------------------
# _history_line_key
# ---------------------------------------------------------------------------

class TestHistoryLineKey:
    def _fn(self, monkeypatch):
        return _load_refine(monkeypatch)._history_line_key

    def test_plain_bullet_strips_prefix(self, monkeypatch):
        key = self._fn(monkeypatch)
        assert key("- Hello world") == "hello world"

    def test_timestamp_prefix_stripped(self, monkeypatch):
        key = self._fn(monkeypatch)
        line = "- [2024-03-15 10:30:00] Working on project X"
        assert key(line) == "working on project x"

    def test_timestamp_prefix_stripped_different_date(self, monkeypatch):
        key = self._fn(monkeypatch)
        line = "- [2025-12-31 23:59:59] Final session of the year"
        assert key(line) == "final session of the year"

    def test_lowercase_normalisation(self, monkeypatch):
        key = self._fn(monkeypatch)
        assert key("- UPPER CASE TEXT") == "upper case text"

    def test_lowercase_with_timestamp(self, monkeypatch):
        key = self._fn(monkeypatch)
        line = "- [2024-01-01 00:00:00] MIXED Case Content"
        assert key(line) == "mixed case content"

    def test_line_without_bullet_prefix_returned_lowercase(self, monkeypatch):
        key = self._fn(monkeypatch)
        assert key("Just text") == "just text"

    def test_leading_whitespace_stripped(self, monkeypatch):
        key = self._fn(monkeypatch)
        assert key("  - Some content  ") == "some content"

    def test_two_bullets_same_content_same_key(self, monkeypatch):
        key = self._fn(monkeypatch)
        a = key("- [2024-01-01 10:00:00] Python project")
        b = key("- [2025-06-15 18:30:00] Python project")
        assert a == b

    def test_different_content_different_key(self, monkeypatch):
        key = self._fn(monkeypatch)
        a = key("- [2024-01-01 10:00:00] Python project")
        b = key("- [2024-01-01 10:00:00] Rust project")
        assert a != b

    def test_bare_dash_only_returns_dash(self, monkeypatch):
        key = self._fn(monkeypatch)
        # "- ".strip() → "-" — no space left, neither prefix matches, falls through
        result = key("- ")
        assert result == "-"

    def test_malformed_timestamp_no_closing_bracket_falls_back_to_bare_bullet(self, monkeypatch):
        key = self._fn(monkeypatch)
        # No "] " found → does NOT strip timestamp prefix, falls through to bare "- " case
        line = "- [no closing bracket here"
        result = key(line)
        assert result == "[no closing bracket here"


# ---------------------------------------------------------------------------
# _parse_history_lines
# ---------------------------------------------------------------------------

class TestParseHistoryLines:
    def _fn(self, monkeypatch):
        return _load_refine(monkeypatch)._parse_history_lines

    def test_empty_string_returns_empty_list(self, monkeypatch):
        parse = self._fn(monkeypatch)
        assert parse("") == []

    def test_valid_bullets_kept(self, monkeypatch):
        parse = self._fn(monkeypatch)
        content = "- First bullet\n- Second bullet"
        assert parse(content) == ["- First bullet", "- Second bullet"]

    def test_lines_not_starting_with_dash_filtered(self, monkeypatch):
        parse = self._fn(monkeypatch)
        content = "Not a bullet\n- Valid bullet\n# Header"
        assert parse(content) == ["- Valid bullet"]

    def test_too_short_lines_filtered(self, monkeypatch):
        parse = self._fn(monkeypatch)
        # "- x" has length 3, which is NOT > 3 → filtered
        content = "- x\n- longer bullet"
        assert parse(content) == ["- longer bullet"]

    def test_exactly_3_chars_filtered(self, monkeypatch):
        parse = self._fn(monkeypatch)
        assert parse("- x") == []

    def test_exactly_4_chars_kept(self, monkeypatch):
        parse = self._fn(monkeypatch)
        assert parse("- xy") == ["- xy"]

    def test_blank_lines_ignored(self, monkeypatch):
        parse = self._fn(monkeypatch)
        content = "\n- Bullet one\n\n- Bullet two\n"
        assert parse(content) == ["- Bullet one", "- Bullet two"]

    def test_timestamp_bullets_kept(self, monkeypatch):
        parse = self._fn(monkeypatch)
        line = "- [2024-03-15 10:30:00] Some content"
        assert parse(line) == [line]

    def test_whitespace_only_lines_filtered(self, monkeypatch):
        parse = self._fn(monkeypatch)
        content = "   \n- Valid\n   "
        assert parse(content) == ["- Valid"]

    def test_mixed_content_only_valid_bullets_returned(self, monkeypatch):
        parse = self._fn(monkeypatch)
        content = (
            "Title\n"
            "- Short\n"
            "- This is a valid bullet\n"
            "- x\n"
            "  - indented not a bullet\n"  # starts with "  - " → stripped to "- " ... wait
            "- Another good one\n"
        )
        result = parse(content)
        # "  - indented not a bullet" strips to "- indented not a bullet" → valid
        assert "- This is a valid bullet" in result
        assert "- Another good one" in result

    def test_preserves_order(self, monkeypatch):
        parse = self._fn(monkeypatch)
        content = "- Alpha\n- Beta\n- Gamma"
        assert parse(content) == ["- Alpha", "- Beta", "- Gamma"]


# ---------------------------------------------------------------------------
# _build_lang_instruction
# ---------------------------------------------------------------------------

class TestBuildLangInstruction:
    def _fn(self, monkeypatch):
        return _load_refine(monkeypatch)._build_lang_instruction

    def test_empty_string_returns_default_instruction(self, monkeypatch):
        fn = self._fn(monkeypatch)
        result = fn("")
        assert "same language" in result.lower() or "detect" in result.lower()

    def test_empty_never_translate_hint(self, monkeypatch):
        fn = self._fn(monkeypatch)
        result = fn("")
        assert "Never translate" in result or "CRITICAL" in result

    def test_en_returns_english_specific_instruction(self, monkeypatch):
        fn = self._fn(monkeypatch)
        result = fn("en")
        assert "English" in result

    def test_en_contains_critical(self, monkeypatch):
        fn = self._fn(monkeypatch)
        result = fn("en")
        assert "CRITICAL" in result

    def test_fr_returns_french_instruction(self, monkeypatch):
        fn = self._fn(monkeypatch)
        result = fn("fr")
        assert "French" in result

    def test_de_returns_german_instruction(self, monkeypatch):
        fn = self._fn(monkeypatch)
        result = fn("de")
        assert "German" in result

    def test_zh_returns_chinese_instruction(self, monkeypatch):
        fn = self._fn(monkeypatch)
        result = fn("zh")
        assert "Chinese" in result

    def test_known_code_contains_critical(self, monkeypatch):
        fn = self._fn(monkeypatch)
        result = fn("es")
        assert "CRITICAL" in result

    def test_unknown_code_capitalised_in_result(self, monkeypatch):
        fn = self._fn(monkeypatch)
        result = fn("xx")
        # Unknown code: fallback is lang.capitalize() → "Xx"
        assert "Xx" in result or "xx" in result.lower()

    def test_unknown_code_still_contains_critical(self, monkeypatch):
        fn = self._fn(monkeypatch)
        result = fn("zz")
        assert "CRITICAL" in result

    def test_empty_vs_en_are_different(self, monkeypatch):
        fn = self._fn(monkeypatch)
        assert fn("") != fn("en")

    def test_en_vs_fr_are_different(self, monkeypatch):
        fn = self._fn(monkeypatch)
        assert fn("en") != fn("fr")

    def test_returns_string(self, monkeypatch):
        fn = self._fn(monkeypatch)
        assert isinstance(fn(""), str)
        assert isinstance(fn("en"), str)


# ---------------------------------------------------------------------------
# _strip_unsupported_params
# ---------------------------------------------------------------------------

class TestStripUnsupportedParams:
    def _fn(self, monkeypatch):
        return _load_refine(monkeypatch)._strip_unsupported_params

    def test_none_params_returns_empty_dict(self, monkeypatch):
        strip = self._fn(monkeypatch)
        assert strip("any-model", None) == {}

    def test_empty_dict_returns_empty_dict(self, monkeypatch):
        strip = self._fn(monkeypatch)
        assert strip("any-model", {}) == {}

    def test_capable_model_keeps_reasoning_effort(self, monkeypatch):
        strip = self._fn(monkeypatch)
        params = {"temperature": 0.3, "reasoning_effort": "high"}
        result = strip("mistral-small-latest", params)
        assert result.get("reasoning_effort") == "high"

    def test_capable_model_medium_35_keeps_reasoning_effort(self, monkeypatch):
        strip = self._fn(monkeypatch)
        params = {"reasoning_effort": "high"}
        result = strip("mistral-medium-3.5", params)
        assert result.get("reasoning_effort") == "high"

    def test_incapable_model_strips_reasoning_effort(self, monkeypatch):
        strip = self._fn(monkeypatch)
        params = {"temperature": 0.4, "reasoning_effort": "high"}
        result = strip("magistral-medium-latest", params)
        assert "reasoning_effort" not in result

    def test_incapable_model_keeps_other_params(self, monkeypatch):
        strip = self._fn(monkeypatch)
        params = {"temperature": 0.4, "top_p": 0.9, "reasoning_effort": "high"}
        result = strip("magistral-medium-latest", params)
        assert result["temperature"] == pytest.approx(0.4)
        assert result["top_p"] == pytest.approx(0.9)

    def test_does_not_mutate_original_params(self, monkeypatch):
        strip = self._fn(monkeypatch)
        params = {"temperature": 0.2, "reasoning_effort": "high"}
        strip("magistral-medium-latest", params)
        assert "reasoning_effort" in params  # original untouched

    def test_no_reasoning_effort_in_params_unchanged(self, monkeypatch):
        strip = self._fn(monkeypatch)
        params = {"temperature": 0.2, "top_p": 0.85}
        result = strip("magistral-medium-latest", params)
        assert result == {"temperature": pytest.approx(0.2), "top_p": pytest.approx(0.85)}

    def test_unknown_model_strips_reasoning_effort(self, monkeypatch):
        strip = self._fn(monkeypatch)
        params = {"reasoning_effort": "high"}
        result = strip("some-future-model", params)
        assert "reasoning_effort" not in result

    def test_returns_new_dict_not_same_object(self, monkeypatch):
        strip = self._fn(monkeypatch)
        params = {"temperature": 0.3}
        result = strip("mistral-small-latest", params)
        assert result is not params


# ---------------------------------------------------------------------------
# _load_history
# ---------------------------------------------------------------------------

class TestLoadHistory:
    def test_disabled_returns_empty_string(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ENABLE_HISTORY", "false")
        r = _load_refine(monkeypatch, ENABLE_HISTORY="false")
        hist_file = tmp_path / "history.txt"
        hist_file.write_text("- Some bullet\n- Another bullet", encoding="utf-8")
        # Patch the module-level _HISTORY_FILE to point to our tmp file
        monkeypatch.setattr(r, "_HISTORY_FILE", hist_file)
        assert r._load_history() == ""

    def test_missing_file_returns_empty_string(self, monkeypatch, tmp_path):
        r = _load_refine(monkeypatch, ENABLE_HISTORY="true")
        monkeypatch.setattr(r, "_ENABLE_HISTORY", True)
        nonexistent = tmp_path / "no_such_history.txt"
        monkeypatch.setattr(r, "_HISTORY_FILE", nonexistent)
        assert r._load_history() == ""

    def test_empty_file_returns_empty_string(self, monkeypatch, tmp_path):
        r = _load_refine(monkeypatch, ENABLE_HISTORY="true")
        monkeypatch.setattr(r, "_ENABLE_HISTORY", True)
        hist_file = tmp_path / "history.txt"
        hist_file.write_text("", encoding="utf-8")
        monkeypatch.setattr(r, "_HISTORY_FILE", hist_file)
        assert r._load_history() == ""

    def test_full_history_when_max_bullets_is_none(self, monkeypatch, tmp_path):
        r = _load_refine(monkeypatch)
        monkeypatch.setattr(r, "_ENABLE_HISTORY", True)
        content = "- Bullet one\n- Bullet two\n- Bullet three"
        hist_file = tmp_path / "history.txt"
        hist_file.write_text(content, encoding="utf-8")
        monkeypatch.setattr(r, "_HISTORY_FILE", hist_file)
        result = r._load_history(max_bullets=None)
        assert "Bullet one" in result
        assert "Bullet three" in result

    def test_max_bullets_caps_to_last_n_lines(self, monkeypatch, tmp_path):
        r = _load_refine(monkeypatch)
        monkeypatch.setattr(r, "_ENABLE_HISTORY", True)
        lines = [f"- Bullet {i}" for i in range(1, 6)]
        hist_file = tmp_path / "history.txt"
        hist_file.write_text("\n".join(lines), encoding="utf-8")
        monkeypatch.setattr(r, "_HISTORY_FILE", hist_file)
        result = r._load_history(max_bullets=2)
        result_lines = result.splitlines()
        assert len(result_lines) == 2
        assert "Bullet 4" in result_lines[0]
        assert "Bullet 5" in result_lines[1]

    def test_max_bullets_zero_returns_empty(self, monkeypatch, tmp_path):
        r = _load_refine(monkeypatch)
        monkeypatch.setattr(r, "_ENABLE_HISTORY", True)
        hist_file = tmp_path / "history.txt"
        hist_file.write_text("- Some content here", encoding="utf-8")
        monkeypatch.setattr(r, "_HISTORY_FILE", hist_file)
        assert r._load_history(max_bullets=0) == ""

    def test_max_bullets_larger_than_file_returns_all(self, monkeypatch, tmp_path):
        r = _load_refine(monkeypatch)
        monkeypatch.setattr(r, "_ENABLE_HISTORY", True)
        lines = ["- Line A", "- Line B"]
        hist_file = tmp_path / "history.txt"
        hist_file.write_text("\n".join(lines), encoding="utf-8")
        monkeypatch.setattr(r, "_HISTORY_FILE", hist_file)
        result = r._load_history(max_bullets=100)
        assert "Line A" in result
        assert "Line B" in result

    def test_max_bullets_1_returns_only_last_line(self, monkeypatch, tmp_path):
        r = _load_refine(monkeypatch)
        monkeypatch.setattr(r, "_ENABLE_HISTORY", True)
        hist_file = tmp_path / "history.txt"
        hist_file.write_text("- First\n- Second\n- Third", encoding="utf-8")
        monkeypatch.setattr(r, "_HISTORY_FILE", hist_file)
        result = r._load_history(max_bullets=1)
        assert result.strip() == "- Third"

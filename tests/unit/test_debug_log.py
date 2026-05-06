"""Unit tests for src/debug_log.py — pure functions, no real side-effects.

Covers:
  is_enabled()      — env-var based toggle
  log_path()        — path resolution (default, custom absolute, custom relative)
  _read()           — missing file, corrupt JSON, valid JSON
  _write()          — atomic write via .tmp, parent dirs created
  set_section()     — noop when disabled, overwrites when enabled
  append_to()       — noop when disabled, creates list, accumulates items
  merge_into()      — noop when disabled, merges dict, replaces non-dict section
  perf_seconds_since() — positive float, monotonically increasing
"""

import json
import time
from pathlib import Path

import pytest

from src.debug_log import (
    _read,
    _write,
    append_to,
    is_enabled,
    log_path,
    merge_into,
    perf_seconds_since,
    set_section,
)


# ---------------------------------------------------------------------------
# is_enabled
# ---------------------------------------------------------------------------

class TestIsEnabled:
    def test_unset_returns_false(self, monkeypatch):
        monkeypatch.delenv("VOX_DEBUG_LOG", raising=False)
        assert is_enabled() is False

    def test_empty_string_returns_false(self, monkeypatch):
        monkeypatch.setenv("VOX_DEBUG_LOG", "")
        assert is_enabled() is False

    def test_zero_string_returns_false(self, monkeypatch):
        monkeypatch.setenv("VOX_DEBUG_LOG", "0")
        assert is_enabled() is False

    def test_zero_with_whitespace_returns_false(self, monkeypatch):
        monkeypatch.setenv("VOX_DEBUG_LOG", "  0  ")
        assert is_enabled() is False

    def test_one_returns_true(self, monkeypatch):
        monkeypatch.setenv("VOX_DEBUG_LOG", "1")
        assert is_enabled() is True

    def test_custom_path_returns_true(self, monkeypatch):
        monkeypatch.setenv("VOX_DEBUG_LOG", "/tmp/vox_debug.json")
        assert is_enabled() is True

    def test_whitespace_only_returns_false(self, monkeypatch):
        monkeypatch.setenv("VOX_DEBUG_LOG", "   ")
        assert is_enabled() is False


# ---------------------------------------------------------------------------
# log_path
# ---------------------------------------------------------------------------

class TestLogPath:
    def test_unset_returns_none(self, monkeypatch):
        monkeypatch.delenv("VOX_DEBUG_LOG", raising=False)
        assert log_path() is None

    def test_zero_returns_none(self, monkeypatch):
        monkeypatch.setenv("VOX_DEBUG_LOG", "0")
        assert log_path() is None

    def test_one_returns_path_object(self, monkeypatch):
        monkeypatch.setenv("VOX_DEBUG_LOG", "1")
        result = log_path()
        assert isinstance(result, Path)

    def test_one_ends_with_default_filename(self, monkeypatch):
        monkeypatch.setenv("VOX_DEBUG_LOG", "1")
        result = log_path()
        assert result.name == "last-session.json"

    def test_one_path_is_absolute(self, monkeypatch):
        monkeypatch.setenv("VOX_DEBUG_LOG", "1")
        assert log_path().is_absolute()

    def test_custom_absolute_path_returned_as_is(self, monkeypatch, tmp_path):
        custom = tmp_path / "my_debug.json"
        monkeypatch.setenv("VOX_DEBUG_LOG", str(custom))
        assert log_path() == custom

    def test_custom_relative_path_resolved_to_absolute(self, monkeypatch):
        monkeypatch.setenv("VOX_DEBUG_LOG", "relative/debug.json")
        result = log_path()
        assert result.is_absolute()
        assert result.name == "debug.json"

    def test_tilde_expanded(self, monkeypatch):
        monkeypatch.setenv("VOX_DEBUG_LOG", "~/vox_debug.json")
        result = log_path()
        assert "~" not in str(result)
        assert result.is_absolute()


# ---------------------------------------------------------------------------
# _read / _write
# ---------------------------------------------------------------------------

class TestRead:
    def test_missing_file_returns_empty_dict(self, tmp_path):
        result = _read(tmp_path / "nonexistent.json")
        assert result == {}

    def test_valid_json_file_parsed(self, tmp_path):
        f = tmp_path / "log.json"
        f.write_text('{"key": "value"}', encoding="utf-8")
        assert _read(f) == {"key": "value"}

    def test_corrupt_json_returns_empty_dict(self, tmp_path):
        f = tmp_path / "log.json"
        f.write_text("{not valid json", encoding="utf-8")
        assert _read(f) == {}

    def test_empty_file_returns_empty_dict(self, tmp_path):
        f = tmp_path / "log.json"
        f.write_text("", encoding="utf-8")
        assert _read(f) == {}


class TestWrite:
    def test_file_created_with_content(self, tmp_path):
        f = tmp_path / "log.json"
        _write(f, {"a": 1})
        assert f.exists()
        assert json.loads(f.read_text()) == {"a": 1}

    def test_parent_dirs_created(self, tmp_path):
        f = tmp_path / "deep" / "nested" / "log.json"
        _write(f, {"x": 2})
        assert f.exists()

    def test_no_tmp_file_left_behind(self, tmp_path):
        f = tmp_path / "log.json"
        _write(f, {"k": "v"})
        assert not (tmp_path / "log.json.tmp").exists()

    def test_overwrites_existing_content(self, tmp_path):
        f = tmp_path / "log.json"
        _write(f, {"old": True})
        _write(f, {"new": True})
        assert json.loads(f.read_text()) == {"new": True}

    def test_roundtrip_read_write(self, tmp_path):
        f = tmp_path / "log.json"
        data = {"section": {"key": [1, 2, 3]}}
        _write(f, data)
        assert _read(f) == data


# ---------------------------------------------------------------------------
# set_section
# ---------------------------------------------------------------------------

class TestSetSection:
    def test_noop_when_disabled(self, monkeypatch, tmp_path):
        monkeypatch.setenv("VOX_DEBUG_LOG", "0")
        f = tmp_path / "log.json"
        set_section("my_section", {"x": 1})
        assert not f.exists()

    def test_writes_section_when_enabled(self, monkeypatch, tmp_path):
        log = tmp_path / "log.json"
        monkeypatch.setenv("VOX_DEBUG_LOG", str(log))
        _write(log, {})
        set_section("step", {"status": "ok"})
        doc = _read(log)
        assert doc["step"] == {"status": "ok"}

    def test_overwrites_existing_section(self, monkeypatch, tmp_path):
        log = tmp_path / "log.json"
        monkeypatch.setenv("VOX_DEBUG_LOG", str(log))
        _write(log, {"step": {"old": True}})
        set_section("step", {"new": True})
        assert _read(log)["step"] == {"new": True}

    def test_preserves_other_sections(self, monkeypatch, tmp_path):
        log = tmp_path / "log.json"
        monkeypatch.setenv("VOX_DEBUG_LOG", str(log))
        _write(log, {"other": "keep", "step": "old"})
        set_section("step", "new")
        doc = _read(log)
        assert doc["other"] == "keep"
        assert doc["step"] == "new"


# ---------------------------------------------------------------------------
# append_to
# ---------------------------------------------------------------------------

class TestAppendTo:
    def test_noop_when_disabled(self, monkeypatch, tmp_path):
        monkeypatch.setenv("VOX_DEBUG_LOG", "0")
        append_to("events", {"e": 1})
        # No file created

    def test_creates_list_when_section_missing(self, monkeypatch, tmp_path):
        log = tmp_path / "log.json"
        monkeypatch.setenv("VOX_DEBUG_LOG", str(log))
        _write(log, {})
        append_to("events", "first")
        assert _read(log)["events"] == ["first"]

    def test_accumulates_items(self, monkeypatch, tmp_path):
        log = tmp_path / "log.json"
        monkeypatch.setenv("VOX_DEBUG_LOG", str(log))
        _write(log, {})
        append_to("events", "a")
        append_to("events", "b")
        append_to("events", "c")
        assert _read(log)["events"] == ["a", "b", "c"]

    def test_replaces_non_list_section(self, monkeypatch, tmp_path):
        log = tmp_path / "log.json"
        monkeypatch.setenv("VOX_DEBUG_LOG", str(log))
        _write(log, {"events": "not_a_list"})
        append_to("events", "item")
        assert _read(log)["events"] == ["item"]

    def test_accepts_dict_items(self, monkeypatch, tmp_path):
        log = tmp_path / "log.json"
        monkeypatch.setenv("VOX_DEBUG_LOG", str(log))
        _write(log, {})
        append_to("steps", {"name": "step1", "status": "ok"})
        assert _read(log)["steps"][0]["name"] == "step1"


# ---------------------------------------------------------------------------
# merge_into
# ---------------------------------------------------------------------------

class TestMergeInto:
    def test_noop_when_disabled(self, monkeypatch, tmp_path):
        monkeypatch.setenv("VOX_DEBUG_LOG", "0")
        merge_into("section", {"k": "v"})

    def test_noop_when_data_not_dict(self, monkeypatch, tmp_path):
        log = tmp_path / "log.json"
        monkeypatch.setenv("VOX_DEBUG_LOG", str(log))
        _write(log, {"s": {"a": 1}})
        merge_into("s", "not_a_dict")
        assert _read(log)["s"] == {"a": 1}  # unchanged

    def test_merges_new_keys(self, monkeypatch, tmp_path):
        log = tmp_path / "log.json"
        monkeypatch.setenv("VOX_DEBUG_LOG", str(log))
        _write(log, {"s": {"a": 1}})
        merge_into("s", {"b": 2})
        doc = _read(log)["s"]
        assert doc["a"] == 1
        assert doc["b"] == 2

    def test_overwrites_existing_key(self, monkeypatch, tmp_path):
        log = tmp_path / "log.json"
        monkeypatch.setenv("VOX_DEBUG_LOG", str(log))
        _write(log, {"s": {"status": "starting"}})
        merge_into("s", {"status": "ok"})
        assert _read(log)["s"]["status"] == "ok"

    def test_creates_section_when_missing(self, monkeypatch, tmp_path):
        log = tmp_path / "log.json"
        monkeypatch.setenv("VOX_DEBUG_LOG", str(log))
        _write(log, {})
        merge_into("new_section", {"key": "val"})
        assert _read(log)["new_section"] == {"key": "val"}

    def test_replaces_non_dict_section_with_data(self, monkeypatch, tmp_path):
        log = tmp_path / "log.json"
        monkeypatch.setenv("VOX_DEBUG_LOG", str(log))
        _write(log, {"s": "not_a_dict"})
        merge_into("s", {"key": "val"})
        assert _read(log)["s"] == {"key": "val"}


# ---------------------------------------------------------------------------
# perf_seconds_since
# ---------------------------------------------------------------------------

class TestPerfSecondsSince:
    def test_returns_positive_float(self):
        t0 = time.perf_counter()
        time.sleep(0.001)
        result = perf_seconds_since(t0)
        assert isinstance(result, float)
        assert result > 0

    def test_increases_over_time(self):
        t0 = time.perf_counter()
        r1 = perf_seconds_since(t0)
        time.sleep(0.002)
        r2 = perf_seconds_since(t0)
        assert r2 > r1

    def test_result_is_rounded_to_3_decimals(self):
        t0 = time.perf_counter()
        result = perf_seconds_since(t0)
        # round(x, 3) has at most 3 decimal places
        assert result == round(result, 3)

    def test_recent_call_is_small(self):
        t0 = time.perf_counter()
        result = perf_seconds_since(t0)
        assert result < 1.0  # should complete in under 1 second

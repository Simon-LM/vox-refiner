"""Unit tests for src/subtitles.py — pure functions only (no API calls).

Covers:
  _seconds_to_srt      — timecode formatting
  _split_long_segment  — segment splitting logic
  _prepare_segments    — batch splitting
  format_srt           — SRT block generation
  get_unique_speakers  — speaker deduplication
  format_dialogue_preview — readable transcript without timecodes
"""

import pytest

from src.subtitles import (
    _prepare_segments,
    _seconds_to_srt,
    _split_long_segment,
    format_dialogue_preview,
    format_srt,
    get_unique_speakers,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seg(text, start, end, speaker_id=None):
    return {"text": text, "start": start, "end": end, "speaker_id": speaker_id}


# ---------------------------------------------------------------------------
# _seconds_to_srt
# ---------------------------------------------------------------------------

class TestSecondsToSrt:
    def test_zero(self):
        assert _seconds_to_srt(0.0) == "00:00:00,000"

    def test_one_second(self):
        assert _seconds_to_srt(1.0) == "00:00:01,000"

    def test_one_minute(self):
        assert _seconds_to_srt(60.0) == "00:01:00,000"

    def test_one_hour(self):
        assert _seconds_to_srt(3600.0) == "01:00:00,000"

    def test_mixed_hms(self):
        # 1h 2m 3s = 3723.0
        assert _seconds_to_srt(3723.0) == "01:02:03,000"

    def test_milliseconds(self):
        assert _seconds_to_srt(1.5) == "00:00:01,500"

    def test_milliseconds_precision(self):
        assert _seconds_to_srt(0.123) == "00:00:00,123"

    def test_milliseconds_rounding(self):
        # 0.9999 → rounds to 1000 ms → capped at 999
        result = _seconds_to_srt(0.9999)
        assert result == "00:00:00,999"

    def test_negative_clamped_to_zero(self):
        assert _seconds_to_srt(-1.0) == "00:00:00,000"

    def test_negative_large_clamped(self):
        assert _seconds_to_srt(-999.0) == "00:00:00,000"

    def test_large_value(self):
        # 10h = 36000s
        assert _seconds_to_srt(36000.0) == "10:00:00,000"

    def test_output_format_structure(self):
        result = _seconds_to_srt(5.25)
        parts = result.split(",")
        assert len(parts) == 2
        hms = parts[0].split(":")
        assert len(hms) == 3
        assert len(parts[1]) == 3  # milliseconds always 3 digits

    def test_zero_padding_hours(self):
        assert _seconds_to_srt(3661.0).startswith("01:")

    def test_zero_padding_minutes(self):
        assert _seconds_to_srt(61.0) == "00:01:01,000"


# ---------------------------------------------------------------------------
# _split_long_segment
# ---------------------------------------------------------------------------

class TestSplitLongSegment:
    def test_short_segment_returned_as_is(self):
        seg = _seg("hello world", 0.0, 5.0)
        result = _split_long_segment(seg, max_dur=7.0)
        assert result == [seg]

    def test_segment_exactly_at_max_dur_not_split(self):
        seg = _seg("hello world", 0.0, 7.0)
        result = _split_long_segment(seg, max_dur=7.0)
        assert result == [seg]

    def test_long_segment_produces_multiple_chunks(self):
        seg = _seg("a b c d e f g h i j", 0.0, 20.0)
        result = _split_long_segment(seg, max_dur=7.0)
        assert len(result) > 1

    def test_single_word_never_split(self):
        seg = _seg("hello", 0.0, 30.0)
        result = _split_long_segment(seg, max_dur=7.0)
        assert result == [seg]

    def test_chunks_cover_full_duration(self):
        seg = _seg("a b c d e f g h i j k l", 10.0, 34.0)
        result = _split_long_segment(seg, max_dur=7.0)
        assert result[0]["start"] == pytest.approx(10.0)
        assert result[-1]["end"] == pytest.approx(34.0)

    def test_chunks_are_consecutive(self):
        seg = _seg("one two three four five six seven eight", 0.0, 24.0)
        result = _split_long_segment(seg, max_dur=7.0)
        for i in range(len(result) - 1):
            assert result[i]["end"] == pytest.approx(result[i + 1]["start"])

    def test_speaker_id_preserved_in_all_chunks(self):
        seg = _seg("a b c d e f g h i j", 0.0, 20.0, speaker_id="speaker_0")
        result = _split_long_segment(seg, max_dur=7.0)
        for chunk in result:
            assert chunk["speaker_id"] == "speaker_0"

    def test_no_speaker_id_preserved_as_none(self):
        seg = _seg("a b c d e f g h i j", 0.0, 20.0)
        result = _split_long_segment(seg, max_dur=7.0)
        for chunk in result:
            assert chunk["speaker_id"] is None

    def test_all_words_preserved_across_chunks(self):
        words = "one two three four five six seven eight nine ten"
        seg = _seg(words, 0.0, 30.0)
        result = _split_long_segment(seg, max_dur=7.0)
        reconstructed = " ".join(chunk["text"] for chunk in result)
        assert reconstructed == words

    def test_custom_max_dur(self):
        seg = _seg("a b c d e", 0.0, 5.0)
        assert _split_long_segment(seg, max_dur=10.0) == [seg]
        assert len(_split_long_segment(seg, max_dur=2.0)) > 1


# ---------------------------------------------------------------------------
# _prepare_segments
# ---------------------------------------------------------------------------

class TestPrepareSegments:
    def test_empty_list(self):
        assert _prepare_segments([]) == []

    def test_all_short_segments_unchanged(self):
        segs = [_seg("hello", 0.0, 3.0), _seg("world", 3.0, 6.0)]
        result = _prepare_segments(segs)
        assert len(result) == 2

    def test_long_segment_is_expanded(self):
        segs = [_seg("a b c d e f g h i j k l", 0.0, 24.0)]
        result = _prepare_segments(segs)
        assert len(result) > 1

    def test_mix_short_and_long(self):
        segs = [
            _seg("short", 0.0, 3.0),
            _seg("a b c d e f g h i j k l", 5.0, 29.0),
            _seg("also short", 30.0, 33.0),
        ]
        result = _prepare_segments(segs)
        # short segments survive; long segment is split
        assert len(result) > 3

    def test_output_is_flat_list(self):
        segs = [_seg("a b c d e f g h i j k l", 0.0, 24.0)]
        result = _prepare_segments(segs)
        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, dict)


# ---------------------------------------------------------------------------
# format_srt
# ---------------------------------------------------------------------------

class TestFormatSrt:
    def test_empty_segments_returns_empty_string(self):
        assert format_srt([]) == ""

    def test_single_segment_block_structure(self):
        segs = [_seg("Hello world.", 0.0, 2.5)]
        output = format_srt(segs)
        lines = output.strip().split("\n")
        assert lines[0] == "1"
        assert "-->" in lines[1]
        assert lines[2] == "Hello world."

    def test_timecodes_in_output(self):
        segs = [_seg("Test.", 1.0, 3.5)]
        output = format_srt(segs)
        assert "00:00:01,000 --> 00:00:03,500" in output

    def test_multiple_segments_numbered_consecutively(self):
        segs = [_seg("First.", 0.0, 1.0), _seg("Second.", 1.0, 2.0), _seg("Third.", 2.0, 3.0)]
        output = format_srt(segs)
        assert "\n1\n" in "\n" + output
        assert "\n2\n" in output
        assert "\n3\n" in output

    def test_empty_text_segment_skipped(self):
        segs = [_seg("Hello.", 0.0, 1.0), _seg("", 1.0, 2.0), _seg("World.", 2.0, 3.0)]
        output = format_srt(segs)
        assert "Hello." in output
        assert "World." in output
        # Blank text must not produce a timecode line for an empty subtitle
        lines = [l for l in output.split("\n") if l.strip() == ""]
        # Two non-empty blocks separated by blank lines
        blocks = [b for b in output.split("\n\n") if b.strip()]
        assert len(blocks) == 2

    def test_whitespace_only_text_skipped(self):
        segs = [_seg("   ", 0.0, 1.0), _seg("Real text.", 1.0, 2.0)]
        output = format_srt(segs)
        assert "Real text." in output
        # No block for whitespace-only segment
        assert "00:00:00,000" not in output

    def test_no_speaker_names_no_labels(self):
        segs = [_seg("Hello.", 0.0, 1.0, speaker_id="speaker_0")]
        output = format_srt(segs)
        assert "[" not in output

    def test_speaker_name_added_on_first_occurrence(self):
        speaker_names = {"speaker_0": "Alice"}
        segs = [_seg("Hello.", 0.0, 1.0, speaker_id="speaker_0")]
        output = format_srt(segs, speaker_names=speaker_names)
        assert "[Alice]:" in output

    def test_speaker_label_not_repeated_for_consecutive_same_speaker(self):
        speaker_names = {"speaker_0": "Alice"}
        segs = [
            _seg("First.", 0.0, 1.0, speaker_id="speaker_0"),
            _seg("Second.", 1.0, 2.0, speaker_id="speaker_0"),
        ]
        output = format_srt(segs, speaker_names=speaker_names)
        assert output.count("[Alice]:") == 1

    def test_speaker_label_reset_when_speaker_changes(self):
        speaker_names = {"speaker_0": "Alice", "speaker_1": "Bob"}
        segs = [
            _seg("Hello.", 0.0, 1.0, speaker_id="speaker_0"),
            _seg("Hi.", 1.0, 2.0, speaker_id="speaker_1"),
            _seg("Back.", 2.0, 3.0, speaker_id="speaker_0"),
        ]
        output = format_srt(segs, speaker_names=speaker_names)
        assert output.count("[Alice]:") == 2
        assert output.count("[Bob]:") == 1

    def test_unknown_speaker_id_falls_back_to_raw_id(self):
        speaker_names = {"speaker_0": "Alice"}
        segs = [_seg("Hello.", 0.0, 1.0, speaker_id="speaker_99")]
        output = format_srt(segs, speaker_names=speaker_names)
        assert "[speaker_99]:" in output

    def test_blocks_joined_with_newline(self):
        segs = [_seg("A.", 0.0, 1.0), _seg("B.", 1.0, 2.0)]
        output = format_srt(segs)
        assert "\n" in output


# ---------------------------------------------------------------------------
# get_unique_speakers
# ---------------------------------------------------------------------------

class TestGetUniqueSpeakers:
    def test_empty_segments(self):
        assert get_unique_speakers([]) == []

    def test_no_speaker_ids(self):
        segs = [_seg("text", 0.0, 1.0), _seg("more", 1.0, 2.0)]
        assert get_unique_speakers(segs) == []

    def test_null_speaker_id_excluded(self):
        segs = [_seg("text", 0.0, 1.0, speaker_id=None)]
        assert get_unique_speakers(segs) == []

    def test_single_speaker(self):
        segs = [_seg("hello", 0.0, 1.0, speaker_id="speaker_0")]
        assert get_unique_speakers(segs) == ["speaker_0"]

    def test_duplicates_removed(self):
        segs = [
            _seg("a", 0.0, 1.0, speaker_id="speaker_0"),
            _seg("b", 1.0, 2.0, speaker_id="speaker_0"),
        ]
        assert get_unique_speakers(segs) == ["speaker_0"]

    def test_order_preserved(self):
        segs = [
            _seg("a", 0.0, 1.0, speaker_id="speaker_1"),
            _seg("b", 1.0, 2.0, speaker_id="speaker_0"),
        ]
        assert get_unique_speakers(segs) == ["speaker_1", "speaker_0"]

    def test_multiple_speakers_deduplicated(self):
        segs = [
            _seg("a", 0.0, 1.0, speaker_id="speaker_0"),
            _seg("b", 1.0, 2.0, speaker_id="speaker_1"),
            _seg("c", 2.0, 3.0, speaker_id="speaker_0"),
            _seg("d", 3.0, 4.0, speaker_id="speaker_2"),
        ]
        result = get_unique_speakers(segs)
        assert result == ["speaker_0", "speaker_1", "speaker_2"]

    def test_mixed_none_and_real(self):
        segs = [
            _seg("a", 0.0, 1.0, speaker_id=None),
            _seg("b", 1.0, 2.0, speaker_id="speaker_0"),
            _seg("c", 2.0, 3.0, speaker_id=None),
        ]
        assert get_unique_speakers(segs) == ["speaker_0"]


# ---------------------------------------------------------------------------
# format_dialogue_preview
# ---------------------------------------------------------------------------

class TestFormatDialoguePreview:
    def test_empty_segments_returns_empty_string(self):
        assert format_dialogue_preview([]) == ""

    def test_single_segment_no_speaker(self):
        segs = [_seg("Hello world.", 0.0, 1.0)]
        result = format_dialogue_preview(segs)
        assert "Hello world." in result
        assert ":" not in result

    def test_single_speaker_header_and_indent(self):
        segs = [_seg("Hello.", 0.0, 1.0, speaker_id="speaker_0")]
        result = format_dialogue_preview(segs)
        assert "speaker_0:" in result
        assert "  Hello." in result

    def test_same_speaker_not_repeated(self):
        segs = [
            _seg("First.", 0.0, 1.0, speaker_id="speaker_0"),
            _seg("Second.", 1.0, 2.0, speaker_id="speaker_0"),
        ]
        result = format_dialogue_preview(segs)
        assert result.count("speaker_0:") == 1

    def test_speaker_change_inserts_blank_line_and_new_header(self):
        segs = [
            _seg("Hello.", 0.0, 1.0, speaker_id="speaker_0"),
            _seg("Hi.", 1.0, 2.0, speaker_id="speaker_1"),
        ]
        result = format_dialogue_preview(segs)
        assert "speaker_0:" in result
        assert "speaker_1:" in result
        # blank line between speakers
        assert "\n\n" in result

    def test_speaker_returns_adds_blank_line(self):
        segs = [
            _seg("A.", 0.0, 1.0, speaker_id="speaker_0"),
            _seg("B.", 1.0, 2.0, speaker_id="speaker_1"),
            _seg("C.", 2.0, 3.0, speaker_id="speaker_0"),
        ]
        result = format_dialogue_preview(segs)
        assert result.count("speaker_0:") == 2

    def test_empty_text_segments_skipped(self):
        segs = [
            _seg("Hello.", 0.0, 1.0, speaker_id="speaker_0"),
            _seg("", 1.0, 2.0, speaker_id="speaker_0"),
            _seg("World.", 2.0, 3.0, speaker_id="speaker_0"),
        ]
        result = format_dialogue_preview(segs)
        assert "Hello." in result
        assert "World." in result

    def test_no_trailing_whitespace(self):
        segs = [_seg("Text.", 0.0, 1.0, speaker_id="speaker_0")]
        result = format_dialogue_preview(segs)
        assert result == result.strip()

    def test_text_indented_under_speaker(self):
        segs = [_seg("Content.", 0.0, 1.0, speaker_id="speaker_0")]
        lines = format_dialogue_preview(segs).split("\n")
        speaker_line = next(l for l in lines if "speaker_0:" in l)
        text_line = next(l for l in lines if "Content." in l)
        assert text_line.startswith("  ")
        assert not speaker_line.startswith(" ")

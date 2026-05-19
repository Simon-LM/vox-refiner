"""Unit tests for src/transcribe.py — pure functions.

_get_timeout():  covers the bug where files < 300 KB had a 2s timeout (too
                 tight), which caused ReadTimeoutError on real 177 KB files.
                 The fix raised it to 3s.

_format_diarized(): groups consecutive same-speaker segments into labelled
                    blocks; transforms speaker IDs to title-case labels.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest


def _load_transcribe(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    if "src.transcribe" in sys.modules:
        del sys.modules["src.transcribe"]
    import src.transcribe as tm
    return tm


class TestGetTimeout:
    def test_tiny_file_returns_3s(self, monkeypatch):
        """< 300 KB must return 3s — was 2s before the ReadTimeout bug fix.

        The real-world failure was a 177 KB file that timed out at 2s.
        """
        tm = _load_transcribe(monkeypatch)
        assert tm._get_timeout(177_000) == 3  # exact size of the bug-triggering file

    def test_sub_300kb_boundary_returns_3s(self, monkeypatch):
        """Confirm the boundary: 299 999 bytes is still in the < 300 KB tier."""
        tm = _load_transcribe(monkeypatch)
        assert tm._get_timeout(299_999) == 3

    def test_mid_range_file_returns_12s(self, monkeypatch):
        """A ~5 min file (2 MB) should fall in the 4 MB tier → 12s."""
        tm = _load_transcribe(monkeypatch)
        assert tm._get_timeout(2_000_000) == 12

    def test_near_max_single_file_returns_55s(self, monkeypatch):
        """A 15 MB file (closest to the 19.5 MB split threshold) → 55s."""
        tm = _load_transcribe(monkeypatch)
        assert tm._get_timeout(15_000_000) == 55

    def test_800kb_tier_returns_3s(self, monkeypatch):
        tm = _load_transcribe(monkeypatch)
        assert tm._get_timeout(500_000) == 3

    def test_1_5mb_tier_returns_5s(self, monkeypatch):
        tm = _load_transcribe(monkeypatch)
        assert tm._get_timeout(1_000_000) == 5

    def test_8mb_tier_returns_20s(self, monkeypatch):
        tm = _load_transcribe(monkeypatch)
        assert tm._get_timeout(6_000_000) == 20

    def test_12mb_tier_returns_30s(self, monkeypatch):
        tm = _load_transcribe(monkeypatch)
        assert tm._get_timeout(10_000_000) == 30

    def test_14_5mb_tier_returns_42s(self, monkeypatch):
        tm = _load_transcribe(monkeypatch)
        assert tm._get_timeout(13_000_000) == 42


# ---------------------------------------------------------------------------
# _format_diarized
# ---------------------------------------------------------------------------

class TestFormatDiarized:
    def _fmt(self, monkeypatch, segments):
        tm = _load_transcribe(monkeypatch)
        return tm._format_diarized(segments)

    def test_empty_list_returns_empty_string(self, monkeypatch):
        assert self._fmt(monkeypatch, []) == ""

    def test_single_segment_produces_one_block(self, monkeypatch):
        segs = [{"speaker_id": "speaker_1", "text": "Hello world."}]
        result = self._fmt(monkeypatch, segs)
        assert "[Speaker 1]" in result
        assert "Hello world." in result

    def test_speaker_id_converted_to_title_case_label(self, monkeypatch):
        segs = [{"speaker_id": "speaker_2", "text": "Hi."}]
        result = self._fmt(monkeypatch, segs)
        assert "[Speaker 2]" in result

    def test_consecutive_same_speaker_merged(self, monkeypatch):
        segs = [
            {"speaker_id": "speaker_1", "text": "First."},
            {"speaker_id": "speaker_1", "text": "Second."},
        ]
        result = self._fmt(monkeypatch, segs)
        assert result.count("[Speaker 1]") == 1
        assert "First." in result
        assert "Second." in result

    def test_alternating_speakers_produce_two_blocks(self, monkeypatch):
        segs = [
            {"speaker_id": "speaker_1", "text": "Hello."},
            {"speaker_id": "speaker_2", "text": "Hi there."},
        ]
        result = self._fmt(monkeypatch, segs)
        assert "[Speaker 1]" in result
        assert "[Speaker 2]" in result
        assert result.count("[Speaker") == 2

    def test_blocks_separated_by_double_newline(self, monkeypatch):
        segs = [
            {"speaker_id": "speaker_1", "text": "A."},
            {"speaker_id": "speaker_2", "text": "B."},
        ]
        result = self._fmt(monkeypatch, segs)
        assert "\n\n" in result

    def test_label_on_its_own_line_above_text(self, monkeypatch):
        segs = [{"speaker_id": "speaker_1", "text": "Hello."}]
        result = self._fmt(monkeypatch, segs)
        lines = result.splitlines()
        assert lines[0] == "[Speaker 1]"
        assert "Hello." in lines[1]

    def test_empty_text_segments_skipped(self, monkeypatch):
        segs = [
            {"speaker_id": "speaker_1", "text": ""},
            {"speaker_id": "speaker_1", "text": "Real text."},
        ]
        result = self._fmt(monkeypatch, segs)
        assert result.count("[Speaker 1]") == 1
        assert "Real text." in result

    def test_missing_speaker_id_defaults_to_speaker_0(self, monkeypatch):
        segs = [{"text": "No speaker field."}]
        result = self._fmt(monkeypatch, segs)
        assert "[Speaker 0]" in result

    def test_three_speakers_three_blocks(self, monkeypatch):
        segs = [
            {"speaker_id": "speaker_1", "text": "One."},
            {"speaker_id": "speaker_2", "text": "Two."},
            {"speaker_id": "speaker_3", "text": "Three."},
        ]
        result = self._fmt(monkeypatch, segs)
        assert result.count("[Speaker") == 3

    def test_speaker_returns_after_gap(self, monkeypatch):
        segs = [
            {"speaker_id": "speaker_1", "text": "Intro."},
            {"speaker_id": "speaker_2", "text": "Response."},
            {"speaker_id": "speaker_1", "text": "Conclusion."},
        ]
        result = self._fmt(monkeypatch, segs)
        assert result.count("[Speaker 1]") == 2

    def test_whitespace_only_text_skipped(self, monkeypatch):
        segs = [
            {"speaker_id": "speaker_1", "text": "   "},
            {"speaker_id": "speaker_1", "text": "Actual."},
        ]
        result = self._fmt(monkeypatch, segs)
        assert "Actual." in result


# ---------------------------------------------------------------------------
# _VOXTRAL_TIMEOUT_ENABLED flag
# ---------------------------------------------------------------------------

class TestVoxtralTimeoutFlag:
    def _success_resp(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"text": "hello"}
        return resp

    def _load(self, monkeypatch):
        if "src.transcribe" in sys.modules:
            del sys.modules["src.transcribe"]
        import src.transcribe as tm
        return tm

    def test_disabled_by_default_passes_none_timeout(self, monkeypatch, tmp_path):
        """VOXTRAL_TIMEOUT_ENABLED absent → requests.post receives timeout=None."""
        monkeypatch.setenv("MISTRAL_API_KEY", "key")
        monkeypatch.delenv("VOXTRAL_TIMEOUT_ENABLED", raising=False)
        tm = self._load(monkeypatch)

        audio = tmp_path / "test.mp3"
        audio.write_bytes(b"x" * 310_797)  # 310 KB → 3s if enabled

        captured: dict = {}
        def fake_post(url, **kwargs):
            captured["timeout"] = kwargs.get("timeout")
            return self._success_resp()

        with patch("src.transcribe.requests.post", side_effect=fake_post):
            tm._transcribe_single(str(audio), "key")

        assert captured["timeout"] is None

    def test_explicitly_false_passes_none_timeout(self, monkeypatch, tmp_path):
        """VOXTRAL_TIMEOUT_ENABLED=false → timeout=None."""
        monkeypatch.setenv("MISTRAL_API_KEY", "key")
        monkeypatch.setenv("VOXTRAL_TIMEOUT_ENABLED", "false")
        tm = self._load(monkeypatch)

        audio = tmp_path / "test.mp3"
        audio.write_bytes(b"x" * 310_797)

        captured: dict = {}
        def fake_post(url, **kwargs):
            captured["timeout"] = kwargs.get("timeout")
            return self._success_resp()

        with patch("src.transcribe.requests.post", side_effect=fake_post):
            tm._transcribe_single(str(audio), "key")

        assert captured["timeout"] is None

    def test_enabled_passes_size_based_timeout(self, monkeypatch, tmp_path):
        """VOXTRAL_TIMEOUT_ENABLED=true → timeout from _get_timeout(file_size)."""
        monkeypatch.setenv("MISTRAL_API_KEY", "key")
        monkeypatch.setenv("VOXTRAL_TIMEOUT_ENABLED", "true")
        tm = self._load(monkeypatch)

        audio = tmp_path / "test.mp3"
        audio.write_bytes(b"x" * 310_797)  # 310 KB → 3s

        captured: dict = {}
        def fake_post(url, **kwargs):
            captured["timeout"] = kwargs.get("timeout")
            return self._success_resp()

        with patch("src.transcribe.requests.post", side_effect=fake_post):
            tm._transcribe_single(str(audio), "key")

        assert captured["timeout"] == 3

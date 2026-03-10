"""Unit tests for _get_timeout() — timeout tier logic.

These tests cover the bug where files < 300 KB had a 2s timeout (too tight),
which caused ReadTimeoutError on real 177 KB files. The fix raised it to 3s.
"""

import sys

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

"""Integration tests for transcribe() — HTTP behaviour.

All HTTP calls are mocked — no real network requests are made.
"""

import sys
from unittest.mock import MagicMock

import pytest
import requests


def _get_transcribe(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    monkeypatch.setenv("TRANSCRIBE_REQUEST_RETRIES", "0")
    if "src.transcribe" in sys.modules:
        del sys.modules["src.transcribe"]
    import src.transcribe as transcribe
    return transcribe


def _ok_response(text: str) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"text": text}
    return resp


def _error_response(status_code: int) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = f"Error {status_code}"
    http_error = requests.HTTPError(response=resp)
    resp.raise_for_status = MagicMock(side_effect=http_error)
    return resp


class TestTranscribeHappyPath:
    def test_returns_transcription_text(self, monkeypatch, tmp_path):
        transcribe = _get_transcribe(monkeypatch)
        audio_file = tmp_path / "audio.mp3"
        audio_file.write_bytes(b"fake audio data")

        monkeypatch.setattr(
            requests, "post", MagicMock(return_value=_ok_response("Hello world."))
        )
        result = transcribe.transcribe(str(audio_file))
        assert result == "Hello world."

    def test_sends_file_to_correct_endpoint(self, monkeypatch, tmp_path):
        transcribe = _get_transcribe(monkeypatch)
        audio_file = tmp_path / "audio.mp3"
        audio_file.write_bytes(b"fake audio data")

        mock_post = MagicMock(return_value=_ok_response("ok"))
        monkeypatch.setattr(requests, "post", mock_post)
        transcribe.transcribe(str(audio_file))

        call_args = mock_post.call_args
        assert "api.mistral.ai" in call_args[0][0]

    def test_sends_authorization_header(self, monkeypatch, tmp_path):
        transcribe = _get_transcribe(monkeypatch)
        audio_file = tmp_path / "audio.mp3"
        audio_file.write_bytes(b"fake audio data")

        mock_post = MagicMock(return_value=_ok_response("ok"))
        monkeypatch.setattr(requests, "post", mock_post)
        transcribe.transcribe(str(audio_file))

        headers = mock_post.call_args[1]["headers"]
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer test-key"


class TestTranscribeErrors:
    def test_no_api_key_raises_runtime_error(self, monkeypatch, tmp_path):
        transcribe = _get_transcribe(monkeypatch)
        monkeypatch.setenv("MISTRAL_API_KEY", "")  # empty string is falsy
        audio_file = tmp_path / "audio.mp3"
        audio_file.write_bytes(b"fake audio")
        with pytest.raises(RuntimeError, match="MISTRAL_API_KEY"):
            transcribe.transcribe(str(audio_file))

    def test_401_raises_http_error(self, monkeypatch, tmp_path):
        transcribe = _get_transcribe(monkeypatch)
        audio_file = tmp_path / "audio.mp3"
        audio_file.write_bytes(b"fake audio")

        monkeypatch.setattr(
            requests, "post", MagicMock(return_value=_error_response(401))
        )
        with pytest.raises(requests.HTTPError):
            transcribe.transcribe(str(audio_file))

    def test_429_raises_http_error(self, monkeypatch, tmp_path):
        """transcribe() has no fallback — 429 should propagate to the caller."""
        transcribe = _get_transcribe(monkeypatch)
        audio_file = tmp_path / "audio.mp3"
        audio_file.write_bytes(b"fake audio")

        monkeypatch.setattr(
            requests, "post", MagicMock(return_value=_error_response(429))
        )
        with pytest.raises(requests.HTTPError):
            transcribe.transcribe(str(audio_file))

    def test_timeout_raises_request_exception(self, monkeypatch, tmp_path):
        """With retries=0 a Timeout propagates immediately (baseline check)."""
        transcribe = _get_transcribe(monkeypatch)
        audio_file = tmp_path / "audio.mp3"
        audio_file.write_bytes(b"fake audio")

        monkeypatch.setattr(
            requests, "post", MagicMock(side_effect=requests.Timeout("timed out"))
        )
        with pytest.raises(requests.Timeout):
            transcribe.transcribe(str(audio_file))


class TestTranscribeRetry:
    """Verify that transient errors (Timeout, 429, 5xx) are actually retried.

    These tests use retries=1 with zero delay to exercise the retry path
    without sleeping.  The core bug was that requests.Timeout was NOT caught
    in the retry loop, causing the exception to escape immediately.
    """

    def _get_with_one_retry(self, monkeypatch):
        """Return a transcribe module loaded with 1 retry and 0s delay."""
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        monkeypatch.setenv("TRANSCRIBE_REQUEST_RETRIES", "0")  # base load
        if "src.transcribe" in sys.modules:
            del sys.modules["src.transcribe"]
        import src.transcribe as tm
        monkeypatch.setattr(tm, "_TRANSCRIBE_RETRIES", 1)
        monkeypatch.setattr(tm, "_TRANSCRIBE_RETRY_DELAY", 0.0)
        return tm

    def test_timeout_retried_succeeds_on_second_attempt(self, monkeypatch, tmp_path):
        """A Timeout on the first attempt must be caught and retried.

        Before the fix, requests.Timeout was not caught in the retry loop, so
        it escaped immediately instead of being retried.
        """
        tm = self._get_with_one_retry(monkeypatch)
        audio_file = tmp_path / "audio.mp3"
        audio_file.write_bytes(b"x" * 10_000)

        mock_post = MagicMock(
            side_effect=[requests.Timeout("timed out"), _ok_response("Retry worked.")]
        )
        monkeypatch.setattr(requests, "post", mock_post)

        result = tm.transcribe(str(audio_file))
        assert result == "Retry worked."
        assert mock_post.call_count == 2

    def test_timeout_exhausted_raises_requests_timeout(self, monkeypatch, tmp_path):
        """After exhausting all retries on Timeout, requests.Timeout is re-raised."""
        tm = self._get_with_one_retry(monkeypatch)
        audio_file = tmp_path / "audio.mp3"
        audio_file.write_bytes(b"x" * 10_000)

        monkeypatch.setattr(
            requests, "post", MagicMock(side_effect=requests.Timeout("timed out"))
        )
        with pytest.raises(requests.Timeout):
            tm.transcribe(str(audio_file))

    def test_429_retried_succeeds_on_second_attempt(self, monkeypatch, tmp_path):
        """A 429 rate-limit response must be retried, not raised immediately."""
        tm = self._get_with_one_retry(monkeypatch)
        audio_file = tmp_path / "audio.mp3"
        audio_file.write_bytes(b"x" * 10_000)

        mock_post = MagicMock(
            side_effect=[_error_response(429), _ok_response("After 429.")]
        )
        monkeypatch.setattr(requests, "post", mock_post)

        result = tm.transcribe(str(audio_file))
        assert result == "After 429."
        assert mock_post.call_count == 2

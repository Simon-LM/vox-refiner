"""Integration tests for refine() — fallback and error handling.

All HTTP calls are mocked — no real network requests are made.
"""

import re
import sys
from unittest.mock import MagicMock

import pytest
import requests


def _get_refine(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    monkeypatch.setenv("REFINE_REQUEST_RETRIES", "0")
    if "src.refine" in sys.modules:
        del sys.modules["src.refine"]
    import src.refine as refine
    return refine


def _ok_response(text: str) -> MagicMock:
    """Build a mock HTTP response that returns a successful refinement."""
    resp = MagicMock()
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {
        "choices": [{"message": {"role": "assistant", "content": text}}]
    }
    return resp


def _error_response(status_code: int, body: str = "") -> MagicMock:
    """Build a mock HTTP response that raises HTTPError with the given status."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = body
    http_error = requests.HTTPError(response=resp)
    resp.raise_for_status = MagicMock(side_effect=http_error)
    return resp


class TestRefineHappyPath:
    def test_returns_refined_text_on_success(self, monkeypatch):
        refine = _get_refine(monkeypatch)
        monkeypatch.setattr(requests, "post", MagicMock(return_value=_ok_response("Clean text.")))
        result = refine.refine("uh so this is a test")
        assert result == "Clean text."

    def test_no_api_key_raises_runtime_error(self, monkeypatch):
        refine = _get_refine(monkeypatch)
        monkeypatch.setenv("MISTRAL_API_KEY", "")  # empty string is falsy
        with pytest.raises(RuntimeError, match="MISTRAL_API_KEY"):
            refine.refine("some text")


class TestRefineFallbackOn429:
    def test_primary_429_triggers_fallback(self, monkeypatch):
        refine = _get_refine(monkeypatch)
        mock_post = MagicMock(side_effect=[
            _error_response(429, '{"message":"Too Many Requests"}'),
            _ok_response("Fallback result."),
        ])
        monkeypatch.setattr(requests, "post", mock_post)
        result = refine.refine("uh so this is a test")
        assert result == "Fallback result."
        assert mock_post.call_count == 2

    def test_primary_500_triggers_fallback(self, monkeypatch):
        refine = _get_refine(monkeypatch)
        mock_post = MagicMock(side_effect=[
            _error_response(500, "Internal Server Error"),
            _ok_response("Fallback result."),
        ])
        monkeypatch.setattr(requests, "post", mock_post)
        result = refine.refine("uh so this is a test")
        assert result == "Fallback result."

    def test_primary_503_triggers_fallback(self, monkeypatch):
        refine = _get_refine(monkeypatch)
        mock_post = MagicMock(side_effect=[
            _error_response(503, "Service Unavailable"),
            _ok_response("Fallback result."),
        ])
        monkeypatch.setattr(requests, "post", mock_post)
        result = refine.refine("uh so this is a test")
        assert result == "Fallback result."


class TestRefineAllModelsFail:
    def test_returns_raw_text_when_all_models_fail_429(self, monkeypatch):
        refine = _get_refine(monkeypatch)
        raw = "uh so this is the raw text"
        mock_post = MagicMock(side_effect=[
            _error_response(429),
            _error_response(429),
        ])
        monkeypatch.setattr(requests, "post", mock_post)
        result = refine.refine(raw)
        assert result == raw

    def test_returns_raw_text_when_all_models_timeout(self, monkeypatch):
        refine = _get_refine(monkeypatch)
        raw = "uh so this is the raw text"
        monkeypatch.setattr(
            requests, "post",
            MagicMock(side_effect=requests.Timeout("timed out")),
        )
        result = refine.refine(raw)
        assert result == raw

    def test_returns_raw_text_when_all_models_connection_error(self, monkeypatch):
        refine = _get_refine(monkeypatch)
        raw = "network failure test"
        monkeypatch.setattr(
            requests, "post",
            MagicMock(side_effect=requests.ConnectionError("no route")),
        )
        result = refine.refine(raw)
        assert result == raw


class TestHistoryExtraction:
    """Tests for _extract_and_update_history — invoked directly, never via refine()."""

    @staticmethod
    def _load(monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        monkeypatch.setenv("REFINE_REQUEST_RETRIES", "0")
        if "src.refine" in sys.modules:
            del sys.modules["src.refine"]
        import src.refine as refine
        return refine

    def test_new_bullets_get_timestamp(self, monkeypatch, tmp_path):
        """Bullets without a date prefix receive today's date from Python code."""
        refine = self._load(monkeypatch)
        monkeypatch.setattr(refine, "_HISTORY_FILE", tmp_path / "history.txt")
        monkeypatch.setattr(requests, "post", MagicMock(return_value=_ok_response("- User works on FastAPI")))
        refine._extract_and_update_history("Some text.", "test-key")
        content = (tmp_path / "history.txt").read_text()
        assert re.search(r"- \[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] User works on FastAPI", content)

    def test_history_content_written_to_file(self, monkeypatch, tmp_path):
        """History extraction writes multiple bullet points to file."""
        refine = self._load(monkeypatch)
        monkeypatch.setattr(refine, "_HISTORY_FILE", tmp_path / "history.txt")
        monkeypatch.setattr(requests, "post", MagicMock(return_value=_ok_response("- Project A\n- Project B")))
        refine._extract_and_update_history("Some text.", "test-key")
        content = (tmp_path / "history.txt").read_text()
        assert re.search(r"- \[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] Project A", content)
        assert re.search(r"- \[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] Project B", content)

    def test_existing_history_passed_to_model(self, monkeypatch, tmp_path):
        """Existing history.txt content is sent to the model for consolidation."""
        refine = self._load(monkeypatch)
        history_file = tmp_path / "history.txt"
        history_file.write_text("- [2026-01-01] Existing fact\n", encoding="utf-8")
        monkeypatch.setattr(refine, "_HISTORY_FILE", history_file)
        mock_post = MagicMock(return_value=_ok_response("- [2026-01-01] Existing fact\n- New fact"))
        monkeypatch.setattr(requests, "post", mock_post)
        refine._extract_and_update_history("New text.", "test-key")
        user_content = mock_post.call_args.kwargs["json"]["messages"][1]["content"]
        assert "Existing fact" in user_content
        assert "New text." in user_content

    def test_history_grows_across_calls(self, monkeypatch, tmp_path):
        """Second extraction sees existing history and returns consolidated result."""
        refine = self._load(monkeypatch)
        monkeypatch.setattr(refine, "_HISTORY_FILE", tmp_path / "history.txt")
        mock_post = MagicMock(side_effect=[
            _ok_response("- First bullet"),
            _ok_response("- [2026-03-08] First bullet\n- Second bullet"),
        ])
        monkeypatch.setattr(requests, "post", mock_post)
        refine._extract_and_update_history("First text.", "test-key")
        refine._extract_and_update_history("Second text.", "test-key")
        content = (tmp_path / "history.txt").read_text()
        assert "First bullet" in content
        assert re.search(r"- \[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] Second bullet", content)

    def test_existing_timestamps_not_doubled(self, monkeypatch, tmp_path):
        """Bullets already carrying [YYYY-MM-DD HH:MM:SS] are preserved without double-stamping."""
        refine = self._load(monkeypatch)
        history_file = tmp_path / "history.txt"
        history_file.write_text("- [2026-01-01] Old fact\n", encoding="utf-8")
        monkeypatch.setattr(refine, "_HISTORY_FILE", history_file)
        monkeypatch.setattr(requests, "post", MagicMock(return_value=_ok_response("- [2026-01-01] Old fact\n- New fact")))
        refine._extract_and_update_history("New text.", "test-key")
        content = (tmp_path / "history.txt").read_text()
        assert "- [2026-01-01] Old fact" in content
        assert not re.search(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\].*\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]", content)
        assert re.search(r"- \[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] New fact", content)

    def test_extraction_falls_back_when_primary_fails(self, monkeypatch, tmp_path):
        """If primary model fails with 429, fallback model is used."""
        refine = self._load(monkeypatch)
        monkeypatch.setattr(refine, "_HISTORY_FILE", tmp_path / "history.txt")
        mock_post = MagicMock(side_effect=[
            _error_response(429),
            _ok_response("- Fallback bullet"),
        ])
        monkeypatch.setattr(requests, "post", mock_post)
        refine._extract_and_update_history("Some text.", "test-key")
        assert mock_post.call_count == 2
        assert (tmp_path / "history.txt").exists()

    def test_extraction_raises_when_all_models_fail(self, monkeypatch, tmp_path):
        """_extract_and_update_history raises RuntimeError when both models fail."""
        refine = self._load(monkeypatch)
        monkeypatch.setattr(refine, "_HISTORY_FILE", tmp_path / "history.txt")
        monkeypatch.setattr(requests, "post", MagicMock(return_value=_error_response(429)))
        with pytest.raises(RuntimeError, match="All history extraction models unavailable"):
            refine._extract_and_update_history("Some text.", "test-key")
        assert not (tmp_path / "history.txt").exists()

    def test_refine_does_not_trigger_extraction(self, monkeypatch, tmp_path):
        """refine() is pure: it never calls history extraction (clipboard not delayed)."""
        monkeypatch.setenv("ENABLE_HISTORY", "true")
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        if "src.refine" in sys.modules:
            del sys.modules["src.refine"]
        import src.refine as refine
        monkeypatch.setattr(refine, "_HISTORY_FILE", tmp_path / "history.txt")
        mock_post = MagicMock(return_value=_ok_response("Clean text."))
        monkeypatch.setattr(requests, "post", mock_post)
        refine.refine(" ".join(["word"] * 50))
        assert mock_post.call_count == 1
        assert not (tmp_path / "history.txt").exists()


class TestRefineNonRetryableError:
    def test_401_propagates_immediately(self, monkeypatch):
        """A 401 Unauthorized should not trigger fallback — it re-raises."""
        refine = _get_refine(monkeypatch)
        mock_post = MagicMock(return_value=_error_response(401, "Unauthorized"))
        monkeypatch.setattr(requests, "post", mock_post)
        with pytest.raises(requests.HTTPError):
            refine.refine("some text")
        # Only 1 call — no fallback attempted for auth failures
        assert mock_post.call_count == 1

    def test_403_propagates_immediately(self, monkeypatch):
        refine = _get_refine(monkeypatch)
        mock_post = MagicMock(return_value=_error_response(403, "Forbidden"))
        monkeypatch.setattr(requests, "post", mock_post)
        with pytest.raises(requests.HTTPError):
            refine.refine("some text")
        assert mock_post.call_count == 1


class TestRefineUserMessageFormat:
    def test_user_message_wraps_text_in_xml_tags(self, monkeypatch):
        refine = _get_refine(monkeypatch)
        captured = {}

        def fake_post(url, headers, json, timeout):
            captured["messages"] = json["messages"]
            return _ok_response("ok")

        monkeypatch.setattr(requests, "post", fake_post)
        refine.refine("hello world")
        user_msg = captured["messages"][1]["content"]
        assert user_msg.startswith("<transcription>")
        assert user_msg.endswith("</transcription>")
        assert "hello world" in user_msg

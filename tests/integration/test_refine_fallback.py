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
    monkeypatch.setenv("REFINE_COMPARE_MODELS", "false")
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
        monkeypatch.setenv("REFINE_COMPARE_MODELS", "false")
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

    def test_history_extraction_uses_doubled_timeout(self, monkeypatch, tmp_path):
        """_extract_and_update_history uses history-only timeout multiplier.

        The exact value depends on the configured history model, but must be
        strictly greater than the foreground base timeout (proof that background
        doubling was applied), and must equal base_bg × model_factor ×
        HISTORY_TIMEOUT_MULTIPLIER.
        """
        refine = self._load(monkeypatch)
        monkeypatch.setattr(refine, "_HISTORY_FILE", tmp_path / "history.txt")
        monkeypatch.setattr(refine, "_HISTORY_TIMEOUT_MULTIPLIER", 1.5)
        mock_post = MagicMock(return_value=_ok_response("- A bullet"))
        monkeypatch.setattr(requests, "post", mock_post)

        text = " ".join(["word"] * 124)
        refine._extract_and_update_history(text, "test-key")

        actual_timeout = mock_post.call_args.kwargs["timeout"]
        fg_timeout, _ = refine._refine_timing(124, background=False)
        bg_base, _ = refine._refine_timing(124, background=True)
        history_model = refine._HISTORY_EXTRACTION_MODEL
        effective = refine._effective_timeout(bg_base, history_model)
        expected_timeout = max(effective, round(effective * refine._HISTORY_TIMEOUT_MULTIPLIER))
        assert actual_timeout == expected_timeout, (
            f"Expected {expected_timeout}s for model={history_model}, got {actual_timeout}s"
        )
        # At minimum the background doubling must be visible
        assert actual_timeout >= fg_timeout * 2

    def test_reasoning_model_timeout_multiplied(self, monkeypatch, tmp_path):
        """refine() passes the model-speed-adjusted timeout to requests.post.

        magistral-medium-latest has factor 3.0: base 14s × 3.0 = 42s.
        This covers the real-world failure where 202 words got only 12s.
        """
        refine = self._load(monkeypatch)
        monkeypatch.setattr(refine, "_HISTORY_FILE", tmp_path / "history.txt")
        # Force LONG model to magistral-medium-latest for a 202-word input
        monkeypatch.setattr(refine, "_MODEL_LONG", "magistral-medium-latest")
        monkeypatch.setattr(refine, "_MODEL_LONG_FALLBACK", "mistral-large-latest")
        monkeypatch.setattr(refine, "_THRESHOLD_LONG", 100)  # 202 words > 100 → LONG tier
        monkeypatch.setattr(refine, "_COMPARE_MODELS", False)  # disable compare: call_args must be primary

        mock_post = MagicMock(return_value=_ok_response("Refined."))
        monkeypatch.setattr(requests, "post", mock_post)

        text = " ".join(["word"] * 202)
        refine.refine(text)

        actual_timeout = mock_post.call_args.kwargs["timeout"]
        base_timeout, _ = refine._refine_timing(202)
        expected = refine._effective_timeout(base_timeout, "magistral-medium-latest")
        assert actual_timeout == expected, (
            f"Expected magistral-medium timeout {expected}s, got {actual_timeout}s"
        )

    def test_history_timeout_uses_fallback_model(self, monkeypatch, tmp_path):
        """History extraction should fallback on network timeout, not only HTTP errors."""
        refine = self._load(monkeypatch)
        monkeypatch.setattr(refine, "_HISTORY_FILE", tmp_path / "history.txt")

        mock_post = MagicMock(side_effect=[
            requests.Timeout("primary timed out"),
            _ok_response("- Fallback after timeout"),
        ])
        monkeypatch.setattr(requests, "post", mock_post)

        refine._extract_and_update_history("Some text.", "test-key")

        assert mock_post.call_count == 2
        assert (tmp_path / "history.txt").exists()

    def test_history_submission_keeps_20_percent_free(self, monkeypatch, tmp_path):
        """Only the most recent 80% of history is sent to the model."""
        refine = self._load(monkeypatch)
        monkeypatch.setattr(refine, "_HISTORY_FILE", tmp_path / "history.txt")
        monkeypatch.setattr(refine, "_HISTORY_MAX_BULLETS", 50)

        existing = "\n".join([f"- [2026-03-01 00:00:{i:02d}] Fact {i}" for i in range(50)]) + "\n"
        (tmp_path / "history.txt").write_text(existing, encoding="utf-8")

        mock_post = MagicMock(return_value=_ok_response("- New fact"))
        monkeypatch.setattr(requests, "post", mock_post)

        refine._extract_and_update_history("Some text.", "test-key")

        user_content = mock_post.call_args.kwargs["json"]["messages"][1]["content"]
        history_block = user_content.split("<history>\n", 1)[1].split("\n</history>", 1)[0]
        sent_lines = [line for line in history_block.splitlines() if line.startswith("- ")]
        assert len(sent_lines) == 40
        assert "Fact 49" in history_block
        assert "Fact 0" not in history_block

    def test_existing_history_is_preserved_if_model_returns_only_new(self, monkeypatch, tmp_path):
        """Model omissions must not wipe existing history bullets."""
        refine = self._load(monkeypatch)
        history_file = tmp_path / "history.txt"
        history_file.write_text(
            "- [2026-03-01 10:00:00] Existing one\n- [2026-03-01 10:01:00] Existing two\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(refine, "_HISTORY_FILE", history_file)
        monkeypatch.setattr(requests, "post", MagicMock(return_value=_ok_response("- Brand new")))

        refine._extract_and_update_history("New text.", "test-key")

        content = history_file.read_text(encoding="utf-8")
        assert "Existing one" in content
        assert "Existing two" in content
        assert "Brand new" in content

    def test_history_rotation_drops_oldest_entries(self, monkeypatch, tmp_path):
        """When over capacity, keep the most recent bullets (tail-rotation)."""
        refine = self._load(monkeypatch)
        history_file = tmp_path / "history.txt"
        history_file.write_text(
            "- [2026-03-01 10:00:00] Old A\n"
            "- [2026-03-01 10:01:00] Old B\n"
            "- [2026-03-01 10:02:00] Old C\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(refine, "_HISTORY_FILE", history_file)
        monkeypatch.setattr(refine, "_HISTORY_MAX_BULLETS", 3)
        monkeypatch.setattr(
            requests,
            "post",
            MagicMock(return_value=_ok_response("- [2026-03-01 10:02:00] Old C\n- New D\n- New E")),
        )

        refine._extract_and_update_history("Text.", "test-key")

        lines = [line.strip() for line in history_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(lines) == 3
        assert any("Old C" in line for line in lines)
        assert any("New D" in line for line in lines)
        assert any("New E" in line for line in lines)
        assert not any("Old A" in line for line in lines)
        assert not any("Old B" in line for line in lines)

    def test_refine_does_not_trigger_extraction(self, monkeypatch, tmp_path):
        """refine() is pure: it never calls history extraction (clipboard not delayed)."""
        monkeypatch.setenv("ENABLE_HISTORY", "true")
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        monkeypatch.setenv("REFINE_COMPARE_MODELS", "false")
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


class TestCompareModels:
    """REFINE_COMPARE_MODELS=true runs the fallback in parallel with the primary.

    Primary and fallback are launched simultaneously; the primary result is
    returned and copied to clipboard; the fallback result is only shown for
    comparison.  Model-aware mocks are used so tests are deterministic regardless
    of thread scheduling.
    """

    def _load(self, monkeypatch, retries: int = 0):
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        monkeypatch.setenv("REFINE_REQUEST_RETRIES", str(retries))
        monkeypatch.setenv("REFINE_COMPARE_MODELS", "true")
        if "src.refine" in sys.modules:
            del sys.modules["src.refine"]
        import src.refine as refine
        return refine

    def _model_mock(self, refine, responses: dict):
        """Build a requests.post mock that dispatches by model name.

        ``responses`` maps model name → callable or response object.
        This makes multi-threaded compare tests deterministic.
        """
        def fake_post(url, **kwargs):  # noqa: ARG001
            model = kwargs["json"]["model"]
            val = responses.get(model, _ok_response("Default."))
            # MagicMock objects are callable but must be returned as-is;
            # plain functions are factory callables that raise or build a response.
            if isinstance(val, MagicMock):
                return val
            return val()
        return fake_post

    def test_compare_mode_calls_both_models(self, monkeypatch):
        """When primary succeeds and REFINE_COMPARE_MODELS=true, fallback also runs."""
        refine = self._load(monkeypatch)
        called = []
        def fake_post(url, headers, json, timeout):
            called.append(json["model"])
            return _ok_response("Result.")
        monkeypatch.setattr(requests, "post", fake_post)
        result = refine.refine("uh so this is a test")
        assert result == "Result."
        assert len(called) == 2

    def test_compare_mode_returns_primary_not_fallback(self, monkeypatch):
        """The return value is always the primary result, not the fallback."""
        refine = self._load(monkeypatch)
        fake_post = self._model_mock(refine, {
            refine._MODEL_SHORT:          _ok_response("Primary only."),
            refine._MODEL_SHORT_FALLBACK: _ok_response("Fallback ignored."),
        })
        monkeypatch.setattr(requests, "post", fake_post)
        assert refine.refine("test input") == "Primary only."

    def test_compare_mode_off_by_default(self, monkeypatch):
        """Without REFINE_COMPARE_MODELS=true, only the primary is called."""
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        monkeypatch.setenv("REFINE_REQUEST_RETRIES", "0")
        monkeypatch.setenv("REFINE_COMPARE_MODELS", "false")
        if "src.refine" in sys.modules:
            del sys.modules["src.refine"]
        import src.refine as refine
        mock_post = MagicMock(return_value=_ok_response("Result."))
        monkeypatch.setattr(requests, "post", mock_post)
        refine.refine("test input")
        assert mock_post.call_count == 1

    def test_compare_mode_fallback_failure_does_not_affect_result(self, monkeypatch):
        """If fallback compare fails, the primary result is still returned cleanly."""
        refine = self._load(monkeypatch)

        def _raise_timeout():
            raise requests.Timeout("compare timed out")

        fake_post = self._model_mock(refine, {
            refine._MODEL_SHORT:          _ok_response("Primary result."),
            refine._MODEL_SHORT_FALLBACK: _raise_timeout,
        })
        monkeypatch.setattr(requests, "post", fake_post)
        result = refine.refine("test input")
        assert result == "Primary result."

    def test_compare_primary_fails_fallback_used_as_actual(self, monkeypatch):
        """When primary fails, fallback takes over as actual result; compare result discarded."""
        # With parallel compare, the compare thread (fallback) starts before primary.
        # When primary fails, the actual fallback also runs.  Both use the same model
        # and get the same mock response.  The returned value is the actual fallback result.
        refine = self._load(monkeypatch)
        fake_post = self._model_mock(refine, {
            refine._MODEL_SHORT:          _error_response(429),
            refine._MODEL_SHORT_FALLBACK: _ok_response("Fallback result."),
        })
        monkeypatch.setattr(requests, "post", fake_post)
        result = refine.refine("test input")
        assert result == "Fallback result."


class TestOutputProfile:
    """OUTPUT_PROFILE injects a FORMAT block into medium/long tier system prompts."""

    def _load(self, monkeypatch, profile: str = "plain"):
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        monkeypatch.setenv("REFINE_REQUEST_RETRIES", "0")
        monkeypatch.setenv("REFINE_COMPARE_MODELS", "false")
        monkeypatch.setenv("OUTPUT_PROFILE", profile)
        if "src.refine" in sys.modules:
            del sys.modules["src.refine"]
        import src.refine as refine
        return refine

    def _capture_system_prompt(self, monkeypatch, refine, text: str) -> str:
        captured = {}

        def fake_post(url, **kwargs):  # noqa: ARG001
            captured["system"] = kwargs["json"]["messages"][0]["content"]
            return _ok_response("ok")

        monkeypatch.setattr(requests, "post", fake_post)
        refine.refine(text)
        return captured["system"]

    def test_structured_profile_injects_format_block_for_medium(self, monkeypatch):
        refine = self._load(monkeypatch, "structured")
        system = self._capture_system_prompt(monkeypatch, refine, " ".join(["word"] * 100))
        assert "FORMAT:" in system
        assert "bullet" in system.lower()

    def test_prose_profile_injects_format_block_for_long(self, monkeypatch):
        refine = self._load(monkeypatch, "prose")
        system = self._capture_system_prompt(monkeypatch, refine, " ".join(["word"] * 300))
        assert "FORMAT:" in system
        assert "paragraph" in system.lower()

    def test_plain_profile_no_format_block_for_medium(self, monkeypatch):
        refine = self._load(monkeypatch, "plain")
        system = self._capture_system_prompt(monkeypatch, refine, " ".join(["word"] * 100))
        assert "FORMAT:" not in system

    def test_format_block_not_applied_to_short_tier(self, monkeypatch):
        """Even with a non-plain profile, short texts never receive FORMAT."""
        refine = self._load(monkeypatch, "structured")
        system = self._capture_system_prompt(monkeypatch, refine, "hello world")
        assert "FORMAT:" not in system

    def test_unknown_profile_defaults_to_plain(self, monkeypatch):
        """An unrecognised profile value falls back to no formatting."""
        refine = self._load(monkeypatch, "nonexistent_profile")
        system = self._capture_system_prompt(monkeypatch, refine, " ".join(["word"] * 100))
        assert "FORMAT:" not in system

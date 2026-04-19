"""Integration tests for refine() — fallback and error handling.

Since the provider layer (src.providers) was introduced, refine() no longer
touches requests.post directly: it calls providers.call() which handles all
HTTP details, 429 retries, Eden fallback, and cascade. Tests therefore mock
``src.refine.call`` (the imported symbol) and inspect the opts / messages
passed to it.
"""

import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from src.providers import PROVIDERS, CallResult, ProviderError


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_call_result(
    text: str,
    provider_name: str = "mistral_direct",
    effective_model: str = "mistral-small-latest",
    requested_model: str = "mistral-small-latest",
    substituted: bool = False,
    attempts: int = 1,
) -> CallResult:
    """Build a real CallResult for use as a mocked return value."""
    return CallResult(
        text=text,
        provider=PROVIDERS[provider_name],
        effective_model=effective_model,
        requested_model=requested_model,
        substituted=substituted,
        attempts=attempts,
    )


def _clear_refine_env(monkeypatch):
    """Unset all provider env keys so is_available('refine') returns False."""
    for var in ("MISTRAL_API_KEY", "EDENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)


def _get_refine(monkeypatch):
    monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
    monkeypatch.setenv("REFINE_COMPARE_MODELS", "false")
    if "src.refine" in sys.modules:
        del sys.modules["src.refine"]
    import src.refine as refine
    return refine


def _route_by_model(responses, default_text="ok"):
    """Return a side_effect that dispatches the provider.call() by model kwarg.

    ``responses`` maps requested model -> CallResult | Exception | callable.
    Unknown models receive a generic success with the requested model echoed.
    """
    def _side_effect(capability, messages, **kwargs):  # noqa: ARG001
        model = kwargs.get("model", "")
        val = responses.get(model)
        if val is None:
            return _make_call_result(
                text=default_text,
                effective_model=model or "mistral-small-latest",
                requested_model=model or "mistral-small-latest",
            )
        if isinstance(val, BaseException):
            raise val
        if callable(val) and not isinstance(val, CallResult):
            return val(capability, messages, **kwargs)
        return val
    return _side_effect


# ── Happy path & availability guard ──────────────────────────────────────────

class TestRefineHappyPath:
    def test_returns_refined_text_on_success(self, monkeypatch):
        refine = _get_refine(monkeypatch)
        with patch("src.refine.call") as mock_call:
            mock_call.return_value = _make_call_result("Clean text.")
            result = refine.refine("uh so this is a test")
        assert result == "Clean text."

    def test_no_api_key_raises_runtime_error(self, monkeypatch):
        # Import refine first (load_dotenv may repopulate from host .env),
        # then clear provider keys so is_available('refine') returns False
        # when refine() is actually called.
        monkeypatch.setenv("MISTRAL_API_KEY", "placeholder")
        monkeypatch.setenv("REFINE_COMPARE_MODELS", "false")
        if "src.refine" in sys.modules:
            del sys.modules["src.refine"]
        import src.refine as refine
        _clear_refine_env(monkeypatch)
        with pytest.raises(RuntimeError, match="MISTRAL_API_KEY"):
            refine.refine("some text")


# ── Tier fallback on ProviderError ───────────────────────────────────────────

class TestRefineFallbackOnProviderError:
    """When providers.call() gives up on the primary model, refine() switches
    to the tier fallback model.  The provider layer itself handles 429 retries
    and Eden redundancy internally — refine() only sees the final ProviderError.
    """

    def test_primary_failure_triggers_tier_fallback(self, monkeypatch):
        refine = _get_refine(monkeypatch)
        with patch("src.refine.call") as mock_call:
            mock_call.side_effect = _route_by_model({
                refine._MODEL_SHORT:          ProviderError("429 exhausted"),
                refine._MODEL_SHORT_FALLBACK: _make_call_result("Fallback result."),
            })
            result = refine.refine("uh so this is a test")
        assert result == "Fallback result."
        assert mock_call.call_count == 2

    def test_auth_failure_falls_back_gracefully(self, monkeypatch):
        """A 401 surfaces as ProviderError from the provider layer.  refine()
        no longer propagates it — it tries the tier fallback, then returns
        raw text if both fail. This is an intentional improvement over the
        old behavior which raised HTTPError and aborted the paste."""
        refine = _get_refine(monkeypatch)
        with patch("src.refine.call") as mock_call:
            mock_call.side_effect = _route_by_model({
                refine._MODEL_SHORT:          ProviderError("key rejected (401)"),
                refine._MODEL_SHORT_FALLBACK: _make_call_result("Recovered."),
            })
            result = refine.refine("some text")
        assert result == "Recovered."
        assert mock_call.call_count == 2


class TestRefineAllModelsFail:
    def test_returns_raw_text_when_all_models_fail(self, monkeypatch):
        refine = _get_refine(monkeypatch)
        raw = "uh so this is the raw text"
        with patch("src.refine.call", side_effect=ProviderError("all failed")):
            result = refine.refine(raw)
        assert result == raw


# ── History extraction ───────────────────────────────────────────────────────

class TestHistoryExtraction:
    """Tests for _extract_and_update_history — invoked directly, never via refine()."""

    @staticmethod
    def _load(monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        monkeypatch.setenv("REFINE_COMPARE_MODELS", "false")
        if "src.refine" in sys.modules:
            del sys.modules["src.refine"]
        import src.refine as refine
        return refine

    def test_new_bullets_get_timestamp(self, monkeypatch, tmp_path):
        refine = self._load(monkeypatch)
        monkeypatch.setattr(refine, "_HISTORY_FILE", tmp_path / "history.txt")
        with patch("src.refine.call") as mock_call:
            mock_call.return_value = _make_call_result("- User works on FastAPI")
            refine._extract_and_update_history("Some text.")
        content = (tmp_path / "history.txt").read_text()
        assert re.search(r"- \[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] User works on FastAPI", content)

    def test_history_content_written_to_file(self, monkeypatch, tmp_path):
        refine = self._load(monkeypatch)
        monkeypatch.setattr(refine, "_HISTORY_FILE", tmp_path / "history.txt")
        with patch("src.refine.call") as mock_call:
            mock_call.return_value = _make_call_result("- Project A\n- Project B")
            refine._extract_and_update_history("Some text.")
        content = (tmp_path / "history.txt").read_text()
        assert re.search(r"- \[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] Project A", content)
        assert re.search(r"- \[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] Project B", content)

    def test_existing_history_passed_to_model(self, monkeypatch, tmp_path):
        refine = self._load(monkeypatch)
        history_file = tmp_path / "history.txt"
        history_file.write_text("- [2026-01-01] Existing fact\n", encoding="utf-8")
        monkeypatch.setattr(refine, "_HISTORY_FILE", history_file)
        with patch("src.refine.call") as mock_call:
            mock_call.return_value = _make_call_result("- [2026-01-01] Existing fact\n- New fact")
            refine._extract_and_update_history("New text.")
            messages = mock_call.call_args.args[1]
        user_content = messages[1]["content"]
        assert "Existing fact" in user_content
        assert "New text." in user_content

    def test_history_grows_across_calls(self, monkeypatch, tmp_path):
        refine = self._load(monkeypatch)
        monkeypatch.setattr(refine, "_HISTORY_FILE", tmp_path / "history.txt")
        with patch("src.refine.call") as mock_call:
            mock_call.side_effect = [
                _make_call_result("- First bullet"),
                _make_call_result("- [2026-03-08] First bullet\n- Second bullet"),
            ]
            refine._extract_and_update_history("First text.")
            refine._extract_and_update_history("Second text.")
        content = (tmp_path / "history.txt").read_text()
        assert "First bullet" in content
        assert re.search(r"- \[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] Second bullet", content)

    def test_existing_timestamps_not_doubled(self, monkeypatch, tmp_path):
        refine = self._load(monkeypatch)
        history_file = tmp_path / "history.txt"
        history_file.write_text("- [2026-01-01] Old fact\n", encoding="utf-8")
        monkeypatch.setattr(refine, "_HISTORY_FILE", history_file)
        with patch("src.refine.call") as mock_call:
            mock_call.return_value = _make_call_result("- [2026-01-01] Old fact\n- New fact")
            refine._extract_and_update_history("New text.")
        content = (tmp_path / "history.txt").read_text()
        assert "- [2026-01-01] Old fact" in content
        assert not re.search(
            r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\].*\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]",
            content,
        )
        assert re.search(r"- \[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] New fact", content)

    def test_extraction_falls_back_when_primary_fails(self, monkeypatch, tmp_path):
        refine = self._load(monkeypatch)
        monkeypatch.setattr(refine, "_HISTORY_FILE", tmp_path / "history.txt")
        with patch("src.refine.call") as mock_call:
            mock_call.side_effect = _route_by_model({
                refine._HISTORY_EXTRACTION_MODEL:          ProviderError("rate limited"),
                refine._HISTORY_EXTRACTION_FALLBACK_MODEL: _make_call_result("- Fallback bullet"),
            })
            refine._extract_and_update_history("Some text.")
            assert mock_call.call_count == 2
        assert (tmp_path / "history.txt").exists()

    def test_extraction_raises_when_all_models_fail(self, monkeypatch, tmp_path):
        refine = self._load(monkeypatch)
        monkeypatch.setattr(refine, "_HISTORY_FILE", tmp_path / "history.txt")
        with patch("src.refine.call", side_effect=ProviderError("all failed")):
            with pytest.raises(RuntimeError, match="All history extraction models unavailable"):
                refine._extract_and_update_history("Some text.")
        assert not (tmp_path / "history.txt").exists()

    def test_history_extraction_uses_doubled_timeout(self, monkeypatch, tmp_path):
        """_extract_and_update_history uses background timeout × HISTORY_TIMEOUT_MULTIPLIER."""
        refine = self._load(monkeypatch)
        monkeypatch.setattr(refine, "_HISTORY_FILE", tmp_path / "history.txt")
        monkeypatch.setattr(refine, "_HISTORY_TIMEOUT_MULTIPLIER", 1.5)
        with patch("src.refine.call") as mock_call:
            mock_call.return_value = _make_call_result("- A bullet")
            text = " ".join(["word"] * 124)
            refine._extract_and_update_history(text)
            actual_timeout = mock_call.call_args.kwargs["timeout"]

        fg_timeout, _ = refine._refine_timing(124, background=False)
        bg_base, _ = refine._refine_timing(124, background=True)
        history_model = refine._HISTORY_EXTRACTION_MODEL
        effective = refine._effective_timeout(bg_base, history_model, refine._PARAMS_HISTORY)
        expected_timeout = max(effective, round(effective * refine._HISTORY_TIMEOUT_MULTIPLIER))
        assert actual_timeout == expected_timeout, (
            f"Expected {expected_timeout}s for model={history_model}, got {actual_timeout}s"
        )
        assert actual_timeout >= fg_timeout * 2

    def test_reasoning_model_timeout_multiplied(self, monkeypatch, tmp_path):
        """refine() passes the model-speed-adjusted timeout to call().

        magistral-medium-latest has factor 4.5: base 8s × 4.5 = 36s.
        """
        refine = self._load(monkeypatch)
        monkeypatch.setattr(refine, "_HISTORY_FILE", tmp_path / "history.txt")
        monkeypatch.setattr(refine, "_MODEL_LONG", "magistral-medium-latest")
        monkeypatch.setattr(refine, "_MODEL_LONG_FALLBACK", "mistral-large-latest")
        monkeypatch.setattr(refine, "_THRESHOLD_LONG", 100)
        monkeypatch.setattr(refine, "_COMPARE_MODELS", False)

        with patch("src.refine.call") as mock_call:
            mock_call.return_value = _make_call_result(
                "Refined.",
                effective_model="magistral-medium-latest",
                requested_model="magistral-medium-latest",
            )
            text = " ".join(["word"] * 202)
            refine.refine(text)
            actual_timeout = mock_call.call_args.kwargs["timeout"]

        base_timeout, _ = refine._refine_timing(202)
        expected = refine._effective_timeout(base_timeout, "magistral-medium-latest", refine._PARAMS_LONG)
        assert actual_timeout == expected, (
            f"Expected magistral-medium timeout {expected}s, got {actual_timeout}s"
        )

    def test_history_timeout_uses_fallback_model(self, monkeypatch, tmp_path):
        """History extraction falls back on ProviderError (covers timeout + HTTP)."""
        refine = self._load(monkeypatch)
        monkeypatch.setattr(refine, "_HISTORY_FILE", tmp_path / "history.txt")
        with patch("src.refine.call") as mock_call:
            mock_call.side_effect = _route_by_model({
                refine._HISTORY_EXTRACTION_MODEL:          ProviderError("timed out"),
                refine._HISTORY_EXTRACTION_FALLBACK_MODEL: _make_call_result("- Fallback after timeout"),
            })
            refine._extract_and_update_history("Some text.")
            assert mock_call.call_count == 2
        assert (tmp_path / "history.txt").exists()

    def test_history_submission_keeps_20_percent_free(self, monkeypatch, tmp_path):
        refine = self._load(monkeypatch)
        monkeypatch.setattr(refine, "_HISTORY_FILE", tmp_path / "history.txt")
        monkeypatch.setattr(refine, "_HISTORY_MAX_BULLETS", 50)
        existing = "\n".join([f"- [2026-03-01 00:00:{i:02d}] Fact {i}" for i in range(50)]) + "\n"
        (tmp_path / "history.txt").write_text(existing, encoding="utf-8")

        with patch("src.refine.call") as mock_call:
            mock_call.return_value = _make_call_result("- New fact")
            refine._extract_and_update_history("Some text.")
            messages = mock_call.call_args.args[1]

        user_content = messages[1]["content"]
        history_block = user_content.split("<history>\n", 1)[1].split("\n</history>", 1)[0]
        sent_lines = [line for line in history_block.splitlines() if line.startswith("- ")]
        assert len(sent_lines) == 40
        assert "Fact 49" in history_block
        assert "Fact 0" not in history_block

    def test_existing_history_is_preserved_if_model_returns_only_new(self, monkeypatch, tmp_path):
        refine = self._load(monkeypatch)
        history_file = tmp_path / "history.txt"
        history_file.write_text(
            "- [2026-03-01 10:00:00] Existing one\n- [2026-03-01 10:01:00] Existing two\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(refine, "_HISTORY_FILE", history_file)
        with patch("src.refine.call") as mock_call:
            mock_call.return_value = _make_call_result("- Brand new")
            refine._extract_and_update_history("New text.")

        content = history_file.read_text(encoding="utf-8")
        assert "Existing one" in content
        assert "Existing two" in content
        assert "Brand new" in content

    def test_history_rotation_drops_oldest_entries(self, monkeypatch, tmp_path):
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
        with patch("src.refine.call") as mock_call:
            mock_call.return_value = _make_call_result(
                "- [2026-03-01 10:02:00] Old C\n- New D\n- New E"
            )
            refine._extract_and_update_history("Text.")

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
        with patch("src.refine.call") as mock_call:
            mock_call.return_value = _make_call_result("Clean text.")
            refine.refine(" ".join(["word"] * 50))
            assert mock_call.call_count == 1
        assert not (tmp_path / "history.txt").exists()


# ── User message format ─────────────────────────────────────────────────────

class TestRefineUserMessageFormat:
    def test_user_message_wraps_text_in_xml_tags(self, monkeypatch):
        refine = _get_refine(monkeypatch)
        with patch("src.refine.call") as mock_call:
            mock_call.return_value = _make_call_result("ok")
            refine.refine("hello world")
            messages = mock_call.call_args.args[1]
        user_msg = messages[1]["content"]
        assert user_msg.startswith("<transcription>")
        assert user_msg.endswith("</transcription>")
        assert "hello world" in user_msg


# ── Compare mode ─────────────────────────────────────────────────────────────

class TestCompareModels:
    """REFINE_COMPARE_MODELS=true runs the fallback in parallel with the primary.

    Primary and fallback are launched simultaneously; the primary result is
    returned and copied to clipboard; the fallback result is only shown for
    comparison.  Model-aware mocks are used so tests are deterministic
    regardless of thread scheduling.
    """

    def _load(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        monkeypatch.setenv("REFINE_COMPARE_MODELS", "true")
        if "src.refine" in sys.modules:
            del sys.modules["src.refine"]
        import src.refine as refine
        return refine

    def test_compare_mode_calls_both_models(self, monkeypatch):
        refine = self._load(monkeypatch)
        called = []

        def _record(capability, messages, **kwargs):  # noqa: ARG001
            model = kwargs["model"]
            called.append(model)
            return _make_call_result("Result.", effective_model=model, requested_model=model)

        with patch("src.refine.call", side_effect=_record):
            result = refine.refine("uh so this is a test")
        assert result == "Result."
        assert len(called) == 2

    def test_compare_mode_returns_primary_not_fallback(self, monkeypatch):
        refine = self._load(monkeypatch)
        with patch("src.refine.call", side_effect=_route_by_model({
            refine._MODEL_SHORT:          _make_call_result(
                "Primary only.",
                effective_model=refine._MODEL_SHORT,
                requested_model=refine._MODEL_SHORT,
            ),
            refine._MODEL_SHORT_FALLBACK: _make_call_result(
                "Fallback ignored.",
                effective_model=refine._MODEL_SHORT_FALLBACK,
                requested_model=refine._MODEL_SHORT_FALLBACK,
            ),
        })):
            assert refine.refine("test input") == "Primary only."

    def test_compare_mode_off_by_default(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        monkeypatch.setenv("REFINE_COMPARE_MODELS", "false")
        if "src.refine" in sys.modules:
            del sys.modules["src.refine"]
        import src.refine as refine
        with patch("src.refine.call") as mock_call:
            mock_call.return_value = _make_call_result("Result.")
            refine.refine("test input")
            assert mock_call.call_count == 1

    def test_compare_mode_fallback_failure_does_not_affect_result(self, monkeypatch):
        refine = self._load(monkeypatch)
        with patch("src.refine.call", side_effect=_route_by_model({
            refine._MODEL_SHORT:          _make_call_result(
                "Primary result.",
                effective_model=refine._MODEL_SHORT,
                requested_model=refine._MODEL_SHORT,
            ),
            refine._MODEL_SHORT_FALLBACK: ProviderError("compare timed out"),
        })):
            result = refine.refine("test input")
        assert result == "Primary result."

    def test_compare_primary_fails_fallback_used_as_actual(self, monkeypatch):
        """When primary fails, the tier fallback becomes the actual result."""
        refine = self._load(monkeypatch)
        with patch("src.refine.call", side_effect=_route_by_model({
            refine._MODEL_SHORT:          ProviderError("rate limited"),
            refine._MODEL_SHORT_FALLBACK: _make_call_result(
                "Fallback result.",
                effective_model=refine._MODEL_SHORT_FALLBACK,
                requested_model=refine._MODEL_SHORT_FALLBACK,
            ),
        })):
            result = refine.refine("test input")
        assert result == "Fallback result."


# ── OUTPUT_PROFILE ───────────────────────────────────────────────────────────

class TestOutputProfile:
    """OUTPUT_PROFILE injects a FORMAT block into medium/long tier system prompts."""

    def _load(self, monkeypatch, profile: str = "plain"):
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        monkeypatch.setenv("REFINE_COMPARE_MODELS", "false")
        monkeypatch.setenv("OUTPUT_PROFILE", profile)
        if "src.refine" in sys.modules:
            del sys.modules["src.refine"]
        import src.refine as refine
        return refine

    def _capture_system_prompt(self, refine, text: str) -> str:
        captured = {}

        def _record(capability, messages, **kwargs):  # noqa: ARG001
            captured["system"] = messages[0]["content"]
            return _make_call_result("ok")

        with patch("src.refine.call", side_effect=_record):
            refine.refine(text)
        return captured["system"]

    def test_structured_profile_injects_format_block_for_medium(self, monkeypatch):
        refine = self._load(monkeypatch, "structured")
        system = self._capture_system_prompt(refine, " ".join(["word"] * 100))
        assert "FORMAT:" in system
        assert "bullet" in system.lower()

    def test_prose_profile_injects_format_block_for_long(self, monkeypatch):
        refine = self._load(monkeypatch, "prose")
        system = self._capture_system_prompt(refine, " ".join(["word"] * 300))
        assert "FORMAT:" in system
        assert "paragraph" in system.lower()

    def test_plain_profile_no_format_block_for_medium(self, monkeypatch):
        refine = self._load(monkeypatch, "plain")
        system = self._capture_system_prompt(refine, " ".join(["word"] * 100))
        assert "FORMAT:" not in system

    def test_format_block_not_applied_to_short_tier(self, monkeypatch):
        refine = self._load(monkeypatch, "structured")
        system = self._capture_system_prompt(refine, "hello world")
        assert "FORMAT:" not in system

    def test_unknown_profile_defaults_to_plain(self, monkeypatch):
        refine = self._load(monkeypatch, "nonexistent_profile")
        system = self._capture_system_prompt(refine, " ".join(["word"] * 100))
        assert "FORMAT:" not in system


# ── OUTPUT_LANG ──────────────────────────────────────────────────────────────

class TestOutputLang:
    """OUTPUT_LANG switches the language instruction in the system prompt."""

    def _load(self, monkeypatch, lang: str = ""):
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        monkeypatch.setenv("REFINE_COMPARE_MODELS", "false")
        if lang:
            monkeypatch.setenv("OUTPUT_LANG", lang)
        else:
            monkeypatch.delenv("OUTPUT_LANG", raising=False)
        if "src.refine" in sys.modules:
            del sys.modules["src.refine"]
        import src.refine as refine
        return refine

    def _capture_system_prompt(self, refine, text: str) -> str:
        captured = {}

        def _record(capability, messages, **kwargs):  # noqa: ARG001
            captured["system"] = messages[0]["content"]
            return _make_call_result("ok")

        with patch("src.refine.call", side_effect=_record):
            refine.refine(text)
        return captured["system"]

    def test_default_sends_same_language_instruction_short(self, monkeypatch):
        refine = self._load(monkeypatch, "")
        system = self._capture_system_prompt(refine, "hello world")
        assert "Never translate" in system
        assert "Always reply in English" not in system

    def test_default_sends_same_language_instruction_medium(self, monkeypatch):
        refine = self._load(monkeypatch, "")
        system = self._capture_system_prompt(refine, " ".join(["word"] * 100))
        assert "Never translate" in system

    def test_en_sends_english_instruction_short(self, monkeypatch):
        refine = self._load(monkeypatch, "en")
        system = self._capture_system_prompt(refine, "bonjour le monde")
        assert "Always reply in English" in system
        assert "Never translate" not in system

    def test_en_sends_english_instruction_medium(self, monkeypatch):
        refine = self._load(monkeypatch, "en")
        system = self._capture_system_prompt(refine, " ".join(["mot"] * 100))
        assert "Always reply in English" in system

    def test_en_sends_english_instruction_long(self, monkeypatch):
        refine = self._load(monkeypatch, "en")
        system = self._capture_system_prompt(refine, " ".join(["mot"] * 300))
        assert "Always reply in English" in system


# ── Per-tier model params ────────────────────────────────────────────────────

class TestModelParams:
    """Per-tier API parameters are forwarded to call() for the primary model,
    and stripped for fallback / incompatible models."""

    def _load(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        monkeypatch.setenv("REFINE_COMPARE_MODELS", "false")
        # Force code defaults — load_dotenv() in refine.py may override from .env.
        monkeypatch.setenv("REFINE_MODEL_MEDIUM", "mistral-small-latest")
        monkeypatch.setenv("HISTORY_EXTRACTION_MODEL", "mistral-small-latest")
        if "src.refine" in sys.modules:
            del sys.modules["src.refine"]
        import src.refine as refine
        return refine

    def _capture_opts(self, refine, text: str) -> dict:
        captured = {}

        def _record(capability, messages, **kwargs):  # noqa: ARG001
            captured["opts"] = kwargs
            return _make_call_result(
                "ok",
                effective_model=kwargs.get("model", ""),
                requested_model=kwargs.get("model", ""),
            )

        with patch("src.refine.call", side_effect=_record):
            refine.refine(text)
        return captured["opts"]

    def test_short_tier_sends_temperature_and_top_p(self, monkeypatch):
        refine = self._load(monkeypatch)
        opts = self._capture_opts(refine, "hello world")
        assert opts["temperature"] == 0.2
        assert opts["top_p"] == 0.85
        assert "reasoning_effort" not in opts

    def test_medium_tier_sends_all_params(self, monkeypatch):
        refine = self._load(monkeypatch)
        opts = self._capture_opts(refine, " ".join(["word"] * 100))
        assert opts["reasoning_effort"] == "high"
        assert opts["temperature"] == 0.3
        assert opts["top_p"] == 0.9

    def test_long_tier_sends_temperature_no_reasoning(self, monkeypatch):
        """LONG tier uses magistral-medium which doesn't support reasoning_effort."""
        refine = self._load(monkeypatch)
        opts = self._capture_opts(refine, " ".join(["word"] * 300))
        assert opts["temperature"] == 0.4
        assert opts["top_p"] == 0.9
        assert "reasoning_effort" not in opts

    def test_fallback_has_no_extra_params(self, monkeypatch):
        """When primary fails, fallback call must NOT include tier params."""
        refine = self._load(monkeypatch)
        recorded = []

        def _record(capability, messages, **kwargs):  # noqa: ARG001
            recorded.append(kwargs)
            if len(recorded) == 1:
                raise ProviderError("primary exhausted")
            return _make_call_result(
                "fallback ok",
                effective_model=kwargs["model"],
                requested_model=kwargs["model"],
            )

        with patch("src.refine.call", side_effect=_record):
            refine.refine(" ".join(["word"] * 100))

        assert "reasoning_effort" in recorded[0]
        assert "reasoning_effort" not in recorded[1]
        assert "temperature" not in recorded[1]

    def test_magistral_model_strips_reasoning_effort(self, monkeypatch):
        """If user overrides MEDIUM to magistral, reasoning_effort is filtered out."""
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        monkeypatch.setenv("REFINE_COMPARE_MODELS", "false")
        monkeypatch.setenv("REFINE_MODEL_MEDIUM", "magistral-small-latest")
        if "src.refine" in sys.modules:
            del sys.modules["src.refine"]
        import src.refine as refine
        opts = self._capture_opts(refine, " ".join(["word"] * 100))
        assert "reasoning_effort" not in opts
        assert opts["model"] == "magistral-small-latest"

    def test_history_primary_sends_reasoning_effort(self, monkeypatch, tmp_path):
        """History extraction primary model receives reasoning_effort=high."""
        refine = self._load(monkeypatch)
        monkeypatch.setattr(refine, "_HISTORY_FILE", tmp_path / "history.txt")
        captured = {}

        def _record(capability, messages, **kwargs):  # noqa: ARG001
            captured["opts"] = kwargs
            return _make_call_result("- Some fact")

        with patch("src.refine.call", side_effect=_record):
            refine._extract_and_update_history("Some longer text to extract facts from.")
        assert captured["opts"]["reasoning_effort"] == "high"

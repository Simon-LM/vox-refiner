"""Unit tests for src/display_meta.py and src/display_reconstitute.py.

display_meta:
  _make_system_prompt()  — placeholder replacement
  generate()             — missing key, empty text, code-fence stripping,
                           dynamic chunk target calculation

display_reconstitute:
  reconstruct()          — missing key, empty text, JSON structure validation,
                           graceful-degradation (returns "" on failure),
                           user message format
"""

import json
import sys
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_response(content: str, status: int = 200):
    resp = MagicMock()
    resp.status_code = status
    resp.ok = status < 400
    resp.json.return_value = {
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}]
    }
    if status >= 400:
        from requests import HTTPError
        resp.raise_for_status.side_effect = HTTPError(response=resp)
    else:
        resp.raise_for_status.return_value = None
    return resp


# ===========================================================================
# display_meta
# ===========================================================================

class TestMakeSystemPrompt:
    def test_returns_string(self):
        from src.display_meta import _make_system_prompt
        result = _make_system_prompt(4, 8)
        assert isinstance(result, str)

    def test_target_min_injected(self):
        from src.display_meta import _make_system_prompt
        result = _make_system_prompt(5, 10)
        assert "5" in result

    def test_target_max_injected(self):
        from src.display_meta import _make_system_prompt
        result = _make_system_prompt(5, 10)
        assert "10" in result

    def test_no_leftover_placeholders(self):
        from src.display_meta import _make_system_prompt
        result = _make_system_prompt(3, 7)
        assert "{target_min}" not in result
        assert "{target_max}" not in result

    def test_different_values_produce_different_prompts(self):
        from src.display_meta import _make_system_prompt
        a = _make_system_prompt(4, 8)
        b = _make_system_prompt(10, 20)
        assert a != b

    def test_security_notice_present(self):
        from src.display_meta import _make_system_prompt
        result = _make_system_prompt(4, 8)
        assert "SECURITY" in result or "untrusted" in result.lower()


class TestDisplayMetaGenerate:
    def test_raises_when_no_api_key(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        if "src.display_meta" in sys.modules:
            del sys.modules["src.display_meta"]
        import src.display_meta as dm
        # Delete after import so load_dotenv() in the module doesn't restore it
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="MISTRAL_API_KEY"):
            dm.generate("some text")

    def test_raises_on_empty_text(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        if "src.display_meta" in sys.modules:
            del sys.modules["src.display_meta"]
        import src.display_meta as dm
        with pytest.raises(RuntimeError, match="[Ee]mpty"):
            dm.generate("   ")

    def test_code_fence_json_stripped(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        if "src.display_meta" in sys.modules:
            del sys.modules["src.display_meta"]
        import src.display_meta as dm
        payload = {"language": "en", "display_chunks": []}
        fenced = f"```json\n{json.dumps(payload)}\n```"
        with patch("src.display_meta.requests.post",
                   return_value=_fake_response(fenced)):
            result = dm.generate("Hello world test.")
        assert result == payload

    def test_plain_code_fence_stripped(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        if "src.display_meta" in sys.modules:
            del sys.modules["src.display_meta"]
        import src.display_meta as dm
        payload = {"language": "fr", "display_chunks": []}
        fenced = f"```\n{json.dumps(payload)}\n```"
        with patch("src.display_meta.requests.post",
                   return_value=_fake_response(fenced)):
            result = dm.generate("Bonjour le monde.")
        assert result == payload

    def test_no_fence_plain_json_parsed(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        if "src.display_meta" in sys.modules:
            del sys.modules["src.display_meta"]
        import src.display_meta as dm
        payload = {"language": "en", "display_chunks": [{"anchor": "Hello"}]}
        with patch("src.display_meta.requests.post",
                   return_value=_fake_response(json.dumps(payload))):
            result = dm.generate("Hello world test.")
        assert result == payload

    def test_invalid_json_raises(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        if "src.display_meta" in sys.modules:
            del sys.modules["src.display_meta"]
        import src.display_meta as dm
        with patch("src.display_meta.requests.post",
                   return_value=_fake_response("not valid json {")):
            with pytest.raises(json.JSONDecodeError):
                dm.generate("Some text to process.")

    def test_short_text_target_min_at_least_4(self, monkeypatch):
        """For short texts (< 600 chars), target_min = max(4, n//150) ≥ 4."""
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        if "src.display_meta" in sys.modules:
            del sys.modules["src.display_meta"]
        import src.display_meta as dm
        captured = {}

        def fake_post(url, headers, json=None, timeout=None):
            captured["messages"] = json["messages"]
            payload = {"language": "en", "display_chunks": []}
            return _fake_response(__import__("json").dumps(payload))

        with patch("src.display_meta.requests.post", side_effect=fake_post):
            dm.generate("Short.")  # 6 chars → target_min = max(4, 0) = 4

        sys_content = captured["messages"][0]["content"]
        # The prompt must contain "4" as the min target
        assert "4" in sys_content

    def test_long_text_larger_target(self, monkeypatch):
        """For long text (1500 chars), target_min = max(4, 1500//150) = 10."""
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        if "src.display_meta" in sys.modules:
            del sys.modules["src.display_meta"]
        import src.display_meta as dm
        captured = {}

        def fake_post(url, headers, json=None, timeout=None):
            captured["messages"] = json["messages"]
            payload = {"language": "en", "display_chunks": []}
            return _fake_response(__import__("json").dumps(payload))

        long_text = "word " * 300  # ~1500 chars
        with patch("src.display_meta.requests.post", side_effect=fake_post):
            dm.generate(long_text)

        sys_content = captured["messages"][0]["content"]
        # target_min = max(4, 1500//150) = 10
        assert "10" in sys_content


# ===========================================================================
# display_reconstitute
# ===========================================================================

class TestReconstructMissingKey:
    def test_returns_empty_string_when_no_key(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        if "src.display_reconstitute" in sys.modules:
            del sys.modules["src.display_reconstitute"]
        import src.display_reconstitute as dr
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        result = dr.reconstruct("original", "cleaned")
        assert result == ""


class TestReconstructEmptyInput:
    def test_returns_empty_when_cleaned_text_empty(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        if "src.display_reconstitute" in sys.modules:
            del sys.modules["src.display_reconstitute"]
        import src.display_reconstitute as dr
        assert dr.reconstruct("original", "") == ""

    def test_returns_empty_when_cleaned_text_whitespace(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        if "src.display_reconstitute" in sys.modules:
            del sys.modules["src.display_reconstitute"]
        import src.display_reconstitute as dr
        assert dr.reconstruct("original", "   \n  ") == ""


class TestReconstructJsonValidation:
    def _run(self, monkeypatch, api_content: str) -> str:
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        if "src.display_reconstitute" in sys.modules:
            del sys.modules["src.display_reconstitute"]
        import src.display_reconstitute as dr
        with patch("src.display_reconstitute.requests.post",
                   return_value=_fake_response(api_content)):
            return dr.reconstruct("original text", "cleaned text")

    def test_valid_structure_returns_json_string(self, monkeypatch):
        valid = {"pages": [[{"type": "paragraph", "text": "Hello."}]]}
        result = self._run(monkeypatch, json.dumps(valid))
        assert result != ""
        parsed = json.loads(result)
        assert "pages" in parsed

    def test_missing_pages_key_returns_empty(self, monkeypatch):
        assert self._run(monkeypatch, json.dumps({"data": []})) == ""

    def test_empty_pages_list_returns_empty(self, monkeypatch):
        assert self._run(monkeypatch, json.dumps({"pages": []})) == ""

    def test_invalid_block_type_returns_empty(self, monkeypatch):
        bad = {"pages": [[{"type": "invalid_type", "text": "Hello."}]]}
        assert self._run(monkeypatch, json.dumps(bad)) == ""

    def test_block_missing_text_returns_empty(self, monkeypatch):
        bad = {"pages": [[{"type": "paragraph"}]]}
        assert self._run(monkeypatch, json.dumps(bad)) == ""

    def test_heading_type_accepted(self, monkeypatch):
        valid = {"pages": [[{"type": "heading", "text": "Title"},
                             {"type": "paragraph", "text": "Body."}]]}
        result = self._run(monkeypatch, json.dumps(valid))
        assert result != ""

    def test_subheading_type_accepted(self, monkeypatch):
        valid = {"pages": [[{"type": "subheading", "text": "Sub"},
                             {"type": "paragraph", "text": "Body."}]]}
        result = self._run(monkeypatch, json.dumps(valid))
        assert result != ""

    def test_invalid_json_returns_empty(self, monkeypatch):
        assert self._run(monkeypatch, "not json {") == ""

    def test_empty_api_response_returns_empty(self, monkeypatch):
        assert self._run(monkeypatch, "") == ""

    def test_multi_page_valid_structure(self, monkeypatch):
        valid = {
            "pages": [
                [{"type": "paragraph", "text": "Page 1."}],
                [{"type": "heading",   "text": "H2"},
                 {"type": "paragraph", "text": "Page 2."}],
            ]
        }
        result = self._run(monkeypatch, json.dumps(valid))
        parsed = json.loads(result)
        assert len(parsed["pages"]) == 2


class TestReconstructUserMessageFormat:
    def test_original_and_cleaned_both_in_user_message(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        if "src.display_reconstitute" in sys.modules:
            del sys.modules["src.display_reconstitute"]
        import src.display_reconstitute as dr
        captured = {}
        valid = {"pages": [[{"type": "paragraph", "text": "x"}]]}

        def fake_post(url, headers, json=None, timeout=None):
            captured["messages"] = json["messages"]
            return _fake_response(__import__("json").dumps(valid))

        with patch("src.display_reconstitute.requests.post", side_effect=fake_post):
            dr.reconstruct("the original", "the cleaned")

        user_content = captured["messages"][1]["content"]
        assert "the original" in user_content
        assert "the cleaned" in user_content

    def test_user_message_has_original_label(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "test-key")
        if "src.display_reconstitute" in sys.modules:
            del sys.modules["src.display_reconstitute"]
        import src.display_reconstitute as dr
        captured = {}
        valid = {"pages": [[{"type": "paragraph", "text": "x"}]]}

        def fake_post(url, headers, json=None, timeout=None):
            captured["messages"] = json["messages"]
            return _fake_response(__import__("json").dumps(valid))

        with patch("src.display_reconstitute.requests.post", side_effect=fake_post):
            dr.reconstruct("original text", "cleaned text")

        user_content = captured["messages"][1]["content"]
        assert "ORIGINAL" in user_content
        assert "TTS_CLEANED" in user_content

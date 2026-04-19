"""Unit tests for src/providers.py.

Tests cover:
  - PROVIDERS table: all entries have the required fields
  - CAPABILITIES table: all referenced provider names exist, policy values valid
  - CapabilitySpec: policy field semantics
  - resolve(): correct filtering by API key presence
  - is_available(): True/False based on key presence
  - _key_hash(): consistent, non-empty, no secrets leaked
  - _load_cache() / _save_cache(): round-trip, missing file, corrupt JSON
  - is_key_validated(): cache hit / miss / key-rotation detection
  - mark_invalid(): updates cache entry
  - Model mapping: EDEN_MODEL_MAP, EDEN_SUBSTITUTIONS, EDEN_FALLBACK_CHAINS
  - _prepare_eden_opts(): model translation, substitution, fallback injection
  - call(): happy path, ping-pong 429 retry, sticky retry, immediate fail on non-429
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from src.providers import (
    CAPABILITIES,
    EDEN_FALLBACK_CHAINS,
    EDEN_MODEL_MAP,
    EDEN_SUBSTITUTIONS,
    MISTRAL_FALLBACK_MAP,
    PERPLEXITY_FALLBACK_MAP,
    PROVIDERS,
    XAI_FALLBACK_MAP,
    CallResult,
    CapabilitySpec,
    Provider,
    ProviderError,
    RateLimitError,
    _key_hash,
    _load_cache,
    _prepare_eden_opts,
    _save_cache,
    call,
    is_available,
    is_key_validated,
    mark_invalid,
    resolve,
)


# == Helpers ==================================================================

def _make_resp(status_code: int, body: dict | None = None) -> MagicMock:
    """Build a fake requests.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.json.return_value = body or {}
    resp.text = json.dumps(body or {})
    return resp


def _chat_resp(content: str = "pong") -> MagicMock:
    return _make_resp(200, {"choices": [{"message": {"content": content}}]})


# == PROVIDERS table ==========================================================

class TestProvidersTable:
    def test_all_required_fields_non_empty(self):
        for name, p in PROVIDERS.items():
            assert p.name == name, f"{name}: name field mismatch"
            assert p.display_name, f"{name}: display_name is empty"
            assert p.required_env_key, f"{name}: required_env_key is empty"
            assert p.ping_url, f"{name}: ping_url is empty"
            assert p.ping_method in ("GET", "POST"), f"{name}: unexpected ping_method"
            assert p.adapter_type in ("openai", "xai_sdk", "eden_ocr", "mistral_ocr"), \
                f"{name}: unknown adapter_type {p.adapter_type!r}"

    def test_openai_providers_have_endpoint(self):
        for name, p in PROVIDERS.items():
            if p.adapter_type == "openai":
                assert p.endpoint, f"{name}: openai provider missing endpoint"

    def test_eden_providers_have_is_eden_true(self):
        """All providers requiring EDENAI_API_KEY must have is_eden=True."""
        for name, p in PROVIDERS.items():
            if p.required_env_key == "EDENAI_API_KEY":
                assert p.is_eden is True, f"{name}: Eden provider missing is_eden=True"

    def test_direct_providers_have_is_eden_false(self):
        """Direct providers (Mistral, xAI, Perplexity) must NOT be is_eden."""
        for name, p in PROVIDERS.items():
            if p.required_env_key != "EDENAI_API_KEY":
                assert p.is_eden is False, f"{name}: direct provider has is_eden=True"

    def test_eden_providers_have_ping_model_id(self):
        """Eden providers with POST pings need a ping_model_id."""
        for name, p in PROVIDERS.items():
            if p.is_eden and p.ping_method == "POST":
                assert p.ping_model_id, f"{name}: Eden provider missing ping_model_id"


# == CAPABILITIES table =======================================================

class TestCapabilitiesTable:
    def test_all_provider_names_exist(self):
        for cap, spec in CAPABILITIES.items():
            for name in spec.providers:
                assert name in PROVIDERS, \
                    f"Capability '{cap}' references unknown provider '{name}'"

    def test_all_policies_valid(self):
        for cap, spec in CAPABILITIES.items():
            assert spec.policy in ("pingpong", "sticky"), \
                f"Capability '{cap}' has invalid policy '{spec.policy}'"

    def test_required_capabilities_present(self):
        required = {
            "refine", "insight", "translate", "history",
            "transcribe", "fact_check_x", "fact_check_web", "search", "ocr",
        }
        for cap in required:
            assert cap in CAPABILITIES, f"Missing capability: {cap}"

    def test_transcribe_has_only_mistral_direct(self):
        """Voxtral is Mistral-only -- no Eden fallback allowed."""
        assert CAPABILITIES["transcribe"].providers == ["mistral_direct"]

    def test_transcribe_is_sticky(self):
        assert CAPABILITIES["transcribe"].policy == "sticky"

    def test_fact_check_x_is_sticky(self):
        """Grok direct must not ping-pong to Eden (loses X/Twitter search)."""
        assert CAPABILITIES["fact_check_x"].policy == "sticky"

    def test_fact_check_web_is_pingpong(self):
        """Perplexity direct <-> Eden/Perplexity are functionally equivalent."""
        assert CAPABILITIES["fact_check_web"].policy == "pingpong"

    def test_priority_order_mistral_before_eden(self):
        """For text generation capabilities, Mistral direct is always first."""
        for cap in ("refine", "insight", "translate", "history"):
            names = CAPABILITIES[cap].providers
            assert names[0] == "mistral_direct", \
                f"Capability '{cap}': mistral_direct should be first"

    def test_ocr_is_pingpong(self):
        """OCR 4-tier cascade: mistral_ocr → eden_ocr_mistral → mistral_vision → eden_mistral."""
        assert CAPABILITIES["ocr"].policy == "pingpong"
        assert CAPABILITIES["ocr"].providers == [
            "mistral_ocr", "eden_ocr_mistral", "mistral_vision", "eden_mistral"
        ]


# == Model mapping tables =====================================================

class TestModelMapping:
    def test_eden_model_map_covers_all_mistral_fallbacks(self):
        """Every base model in MISTRAL_FALLBACK_MAP should have an Eden equivalent.

        Compound keys ('model+option') are stripped to their base model name
        before checking — the option part is handled by EDEN_SUBSTITUTIONS.
        """
        for key in MISTRAL_FALLBACK_MAP:
            base_model = key.split("+")[0]
            assert base_model in EDEN_MODEL_MAP, \
                f"Model '{base_model}' (from key '{key}') in MISTRAL_FALLBACK_MAP " \
                f"but missing from EDEN_MODEL_MAP"

    def test_eden_model_map_covers_all_perplexity_fallbacks(self):
        """Every canonical Perplexity model must translate to an Eden identifier.

        Without this, a search call with only EDENAI_API_KEY fails because the
        canonical model (e.g. 'sonar-pro') is sent to Eden verbatim — Eden
        rejects it with HTTP 400 'Model not found'.
        """
        for key in PERPLEXITY_FALLBACK_MAP:
            base_model = key.split("+")[0]
            assert base_model in EDEN_MODEL_MAP, \
                f"Model '{base_model}' (from key '{key}') in PERPLEXITY_FALLBACK_MAP " \
                f"but missing from EDEN_MODEL_MAP"

    def test_eden_model_map_covers_all_xai_fallbacks(self):
        """Every canonical xAI model must translate to an Eden identifier."""
        for key in XAI_FALLBACK_MAP:
            base_model = key.split("+")[0]
            assert base_model in EDEN_MODEL_MAP, \
                f"Model '{base_model}' (from key '{key}') in XAI_FALLBACK_MAP " \
                f"but missing from EDEN_MODEL_MAP"

    def test_eden_model_map_uses_provider_slash_format(self):
        for canonical, eden in EDEN_MODEL_MAP.items():
            assert "/" in eden, \
                f"Eden model '{eden}' for '{canonical}' should use provider/model format"

    def test_eden_fallback_chains_keys_are_eden_format(self):
        for key in EDEN_FALLBACK_CHAINS:
            assert "/" in key, \
                f"Fallback chain key '{key}' should be in Eden provider/model format"

    def test_eden_fallback_chains_values_are_eden_format(self):
        for key, chain in EDEN_FALLBACK_CHAINS.items():
            for fallback in chain:
                assert "/" in fallback, \
                    f"Fallback '{fallback}' for '{key}' should be in Eden format"

    def test_substitution_keys_have_plus_format(self):
        for key in EDEN_SUBSTITUTIONS:
            assert "+" in key, \
                f"Substitution key '{key}' should have format 'model+option'"

    def test_substitution_entries_have_model_and_strip(self):
        for key, sub in EDEN_SUBSTITUTIONS.items():
            assert "model" in sub, f"Substitution '{key}' missing 'model' field"
            assert "strip" in sub, f"Substitution '{key}' missing 'strip' field"
            assert isinstance(sub["strip"], list), \
                f"Substitution '{key}' 'strip' should be a list"

    def test_compound_keys_have_matching_substitution(self):
        """Compound keys in MISTRAL_FALLBACK_MAP (model+option) should have
        a corresponding entry in EDEN_SUBSTITUTIONS for the Eden path."""
        for key in MISTRAL_FALLBACK_MAP:
            if "+" not in key:
                continue
            assert key in EDEN_SUBSTITUTIONS, \
                f"Compound key '{key}' in MISTRAL_FALLBACK_MAP but missing " \
                f"from EDEN_SUBSTITUTIONS"

    def test_xai_fallback_map_chain_is_followable(self):
        """Every non-empty fallback must itself be a key in the map
        (chain terminates with '' or cycles back to a known key).
        Also catches trailing-space typos in keys."""
        for model, fb in XAI_FALLBACK_MAP.items():
            if fb:
                assert fb in XAI_FALLBACK_MAP, \
                    f"xAI fallback '{fb}' (from '{model}') is not a key " \
                    f"in XAI_FALLBACK_MAP — chain would break"

    def test_perplexity_fallback_map_chain_is_followable(self):
        for model, fb in PERPLEXITY_FALLBACK_MAP.items():
            if fb:
                assert fb in PERPLEXITY_FALLBACK_MAP, \
                    f"Perplexity fallback '{fb}' (from '{model}') is not a key " \
                    f"in PERPLEXITY_FALLBACK_MAP — chain would break"

    def test_direct_fallback_maps_use_canonical_format(self):
        """Direct-API fallback maps must NOT use Eden 'provider/model' format."""
        for key in XAI_FALLBACK_MAP:
            assert "/" not in key, \
                f"XAI_FALLBACK_MAP key '{key}' looks like Eden format (has '/')"
        for key in PERPLEXITY_FALLBACK_MAP:
            assert "/" not in key, \
                f"PERPLEXITY_FALLBACK_MAP key '{key}' looks like Eden format (has '/')"

    def test_fallback_map_keys_have_no_whitespace(self):
        """Trailing/leading whitespace in keys silently breaks lookups."""
        for name, table in (
            ("MISTRAL_FALLBACK_MAP",    MISTRAL_FALLBACK_MAP),
            ("XAI_FALLBACK_MAP",        XAI_FALLBACK_MAP),
            ("PERPLEXITY_FALLBACK_MAP", PERPLEXITY_FALLBACK_MAP),
        ):
            for key in table:
                assert key == key.strip(), \
                    f"{name} key {key!r} has leading/trailing whitespace"

    def test_eden_fallback_chains_align_with_mistral(self):
        """Eden fallback chains should mirror MISTRAL_FALLBACK_MAP logic.

        For each base model in MISTRAL_FALLBACK_MAP that has a non-empty
        fallback, the corresponding Eden model should also have a non-empty
        fallback chain in EDEN_FALLBACK_CHAINS.
        """
        for key, fallback in MISTRAL_FALLBACK_MAP.items():
            if not fallback or "+" in key:
                continue  # skip empty fallbacks and compound keys
            eden_model = EDEN_MODEL_MAP.get(key)
            if eden_model is None:
                continue
            chain = EDEN_FALLBACK_CHAINS.get(eden_model, [])
            assert len(chain) > 0, \
                f"Model '{key}' has Mistral fallback '{fallback}' but its " \
                f"Eden equivalent '{eden_model}' has no fallback chain"


# == _prepare_eden_opts() =====================================================

class TestPrepareEdenOpts:
    def test_simple_model_mapping(self):
        opts, sub = _prepare_eden_opts({"model": "mistral-small-latest", "temperature": 0.2})
        assert opts["model"] == "mistral/mistral-small-latest"
        assert opts["temperature"] == 0.2
        assert sub is False  # plain mapping is not a substitution

    def test_reasoning_effort_substitution(self):
        """mistral-small + reasoning_effort -> magistral-small, effort stripped."""
        opts, sub = _prepare_eden_opts({
            "model": "mistral-small-latest",
            "reasoning_effort": "high",
            "temperature": 0.3,
        })
        assert opts["model"] == "mistral/magistral-small-latest"
        assert "reasoning_effort" not in opts
        assert opts["temperature"] == 0.3
        assert sub is True

    def test_fallback_chain_injected(self):
        opts, _ = _prepare_eden_opts({"model": "mistral-small-latest"})
        expected = EDEN_FALLBACK_CHAINS["mistral/mistral-small-latest"]
        assert opts["fallbacks"] == expected
        assert len(expected) > 0  # sanity: chain must be non-empty

    def test_no_fallback_chain_when_absent(self):
        """If the Eden model has no entry in EDEN_FALLBACK_CHAINS, no fallbacks injected."""
        opts, _ = _prepare_eden_opts({"model": "some-model-without-chain"})
        assert "fallbacks" not in opts

    def test_fallback_chain_after_substitution(self):
        """After substituting to magistral-small, its chain should be injected."""
        opts, sub = _prepare_eden_opts({
            "model": "mistral-small-latest",
            "reasoning_effort": "high",
        })
        assert opts["model"] == "mistral/magistral-small-latest"
        expected_chain = EDEN_FALLBACK_CHAINS.get("mistral/magistral-small-latest", [])
        assert opts.get("fallbacks") == expected_chain
        assert sub is True

    def test_unknown_model_passes_through(self):
        """Models not in EDEN_MODEL_MAP are passed through unchanged."""
        opts, sub = _prepare_eden_opts({"model": "some-future-model"})
        assert opts["model"] == "some-future-model"
        assert sub is False

    def test_does_not_mutate_input(self):
        original = {"model": "mistral-small-latest", "temperature": 0.2}
        original_copy = dict(original)
        _prepare_eden_opts(original)
        assert original == original_copy

    def test_grok_model_mapping(self):
        """Non-Mistral models that are already in Eden format pass through."""
        # Pick any grok model that has a fallback chain configured
        eden_key = next(k for k in EDEN_FALLBACK_CHAINS if k.startswith("xai/"))
        opts, sub = _prepare_eden_opts({"model": eden_key})
        # Not in EDEN_MODEL_MAP (already Eden format) -> passes through
        assert opts["model"] == eden_key
        # But fallback chain should still be injected
        assert opts["fallbacks"] == EDEN_FALLBACK_CHAINS[eden_key]
        assert sub is False


# == resolve() ================================================================

class TestResolve:
    def test_no_keys_returns_empty(self, monkeypatch):
        monkeypatch.delenv("MISTRAL_API_KEY",    raising=False)
        monkeypatch.delenv("EDENAI_API_KEY",     raising=False)
        monkeypatch.delenv("XAI_API_KEY",        raising=False)
        monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
        assert resolve("refine") == []

    def test_mistral_only(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "key-abc")
        monkeypatch.delenv("EDENAI_API_KEY", raising=False)
        result = resolve("refine")
        assert len(result) == 1
        assert result[0].name == "mistral_direct"

    def test_mistral_and_eden(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "key-abc")
        monkeypatch.setenv("EDENAI_API_KEY",  "key-eden")
        result = resolve("refine")
        assert len(result) == 2
        assert result[0].name == "mistral_direct"
        assert result[1].name == "eden_mistral"

    def test_eden_only_no_mistral(self, monkeypatch):
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        monkeypatch.setenv("EDENAI_API_KEY",  "key-eden")
        result = resolve("refine")
        assert len(result) == 1
        assert result[0].name == "eden_mistral"

    def test_fact_check_x_with_xai_and_eden(self, monkeypatch):
        monkeypatch.setenv("XAI_API_KEY",    "key-xai")
        monkeypatch.setenv("EDENAI_API_KEY", "key-eden")
        result = resolve("fact_check_x")
        assert result[0].name == "xai_direct"
        assert result[1].name == "eden_xai"

    def test_fact_check_x_eden_only(self, monkeypatch):
        monkeypatch.delenv("XAI_API_KEY", raising=False)
        monkeypatch.setenv("EDENAI_API_KEY", "key-eden")
        result = resolve("fact_check_x")
        assert len(result) == 1
        assert result[0].name == "eden_xai"

    def test_unknown_capability_returns_empty(self, monkeypatch):
        assert resolve("nonexistent_capability") == []

    def test_preserves_order(self, monkeypatch):
        """resolve() must respect the CAPABILITIES table order."""
        monkeypatch.setenv("MISTRAL_API_KEY", "k1")
        monkeypatch.setenv("EDENAI_API_KEY",  "k2")
        result = resolve("refine")
        names = [p.name for p in result]
        assert names == ["mistral_direct", "eden_mistral"]


# == is_available() ===========================================================

class TestIsAvailable:
    def test_available_when_key_set(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "key-abc")
        assert is_available("refine") is True

    def test_not_available_when_no_key(self, monkeypatch):
        monkeypatch.delenv("MISTRAL_API_KEY",    raising=False)
        monkeypatch.delenv("EDENAI_API_KEY",     raising=False)
        assert is_available("refine") is False

    def test_transcribe_requires_mistral(self, monkeypatch):
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        monkeypatch.setenv("EDENAI_API_KEY",  "key-eden")
        assert is_available("transcribe") is False

    def test_ocr_requires_at_least_one(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "key-m")
        monkeypatch.delenv("EDENAI_API_KEY",  raising=False)
        assert is_available("ocr") is True

    def test_ocr_eden_only(self, monkeypatch):
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        monkeypatch.setenv("EDENAI_API_KEY", "key-eden")
        assert is_available("ocr") is True


# == _key_hash() ==============================================================

class TestKeyHash:
    def test_returns_string(self):
        assert isinstance(_key_hash("my-key"), str)

    def test_non_empty(self):
        assert _key_hash("abc") != ""

    def test_same_key_same_hash(self):
        assert _key_hash("sk-secret") == _key_hash("sk-secret")

    def test_different_keys_different_hashes(self):
        assert _key_hash("key-aaa") != _key_hash("key-bbb")

    def test_does_not_contain_key(self):
        key = "supersecret-api-key"
        h = _key_hash(key)
        assert key[:8] not in h


# == Cache helpers ============================================================

class TestCache:
    def test_load_missing_file_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert _load_cache() == {}

    def test_save_and_load_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        data = {"mistral": {"valid": True, "key_hash": "abc123"}}
        _save_cache(data)
        assert _load_cache() == data

    def test_load_corrupt_json_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        cache_file = tmp_path / "vox-refiner" / "keys-cache.json"
        cache_file.parent.mkdir(parents=True)
        cache_file.write_text("NOT VALID JSON{{{", encoding="utf-8")
        assert _load_cache() == {}

    def test_save_creates_parent_dirs(self, tmp_path, monkeypatch):
        nested = tmp_path / "a" / "b" / "c"
        monkeypatch.setenv("XDG_DATA_HOME", str(nested))
        _save_cache({"x": 1})
        assert _load_cache() == {"x": 1}


# == is_key_validated() =======================================================

class TestIsKeyValidated:
    def test_returns_false_when_key_absent(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        assert is_key_validated("mistral_direct") is False

    def test_cache_hit_returns_cached_value(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setenv("MISTRAL_API_KEY", "sk-abc12345")
        key_hash = _key_hash("sk-abc12345")
        _save_cache({"mistral_direct": {"valid": True, "key_hash": key_hash}})
        assert is_key_validated("mistral_direct") is True

    def test_cache_hit_invalid_returns_false(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setenv("MISTRAL_API_KEY", "sk-abc12345")
        key_hash = _key_hash("sk-abc12345")
        _save_cache({"mistral_direct": {"valid": False, "key_hash": key_hash, "reason": "401"}})
        assert is_key_validated("mistral_direct") is False

    def test_key_rotation_triggers_revalidation(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        _save_cache({"mistral_direct": {"valid": True, "key_hash": _key_hash("old-key-x")}})
        monkeypatch.setenv("MISTRAL_API_KEY", "new-key-y")
        with patch("src.providers._ping_provider", return_value=(True, "ok")) as mock_ping:
            result = is_key_validated("mistral_direct")
        mock_ping.assert_called_once()
        assert result is True

    def test_force_always_repings(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setenv("MISTRAL_API_KEY", "sk-abc12345")
        key_hash = _key_hash("sk-abc12345")
        _save_cache({"mistral_direct": {"valid": True, "key_hash": key_hash}})
        with patch("src.providers._ping_provider", return_value=(True, "ok")) as mock_ping:
            is_key_validated("mistral_direct", force=True)
        mock_ping.assert_called_once()

    def test_429_counts_as_valid(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setenv("MISTRAL_API_KEY", "sk-rate-limited")
        with patch("src.providers._ping_provider", return_value=(True, "429_rate_limited")):
            result = is_key_validated("mistral_direct", force=True)
        assert result is True


# == mark_invalid() ===========================================================

class TestMarkInvalid:
    def test_marks_entry_as_invalid(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setenv("MISTRAL_API_KEY", "sk-abc12345")
        mark_invalid("mistral_direct", reason="401")
        cache = _load_cache()
        assert cache["mistral_direct"]["valid"] is False
        assert cache["mistral_direct"]["reason"] == "401"

    def test_unknown_provider_is_noop(self, monkeypatch, tmp_path):
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        mark_invalid("nonexistent_provider")
        assert _load_cache() == {}


# == call() ===================================================================

class TestCall:
    def test_happy_path_returns_call_result(self, monkeypatch):
        monkeypatch.setenv("MISTRAL_API_KEY", "key-m")
        monkeypatch.delenv("EDENAI_API_KEY", raising=False)
        with patch("src.providers._call_openai_adapter", return_value="refined text"):
            result = call("refine", [{"role": "user", "content": "hello"}],
                          model="mistral-small-latest")
        assert isinstance(result, CallResult)
        assert result.text == "refined text"
        assert result.provider.name == "mistral_direct"
        assert result.requested_model == "mistral-small-latest"
        assert result.effective_model == "mistral-small-latest"
        assert result.substituted is False
        assert result.attempts == 1

    def test_raises_when_no_providers(self, monkeypatch):
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        monkeypatch.delenv("EDENAI_API_KEY",  raising=False)
        with pytest.raises(ProviderError, match="No providers available"):
            call("refine", [{"role": "user", "content": "hi"}])

    def test_raises_on_unknown_capability(self, monkeypatch):
        with pytest.raises(ProviderError, match="Unknown capability"):
            call("nonexistent", [{"role": "user", "content": "hi"}])

    def test_pingpong_fallback_on_429(self, monkeypatch):
        """Primary 429 -> secondary succeeds -> returns secondary result."""
        monkeypatch.setenv("MISTRAL_API_KEY", "key-m")
        monkeypatch.setenv("EDENAI_API_KEY",  "key-eden")

        def adapter_side_effect(provider, messages, **opts):
            if provider.name == "mistral_direct":
                raise RateLimitError("429")
            return "eden response"

        with patch("src.providers._call_openai_adapter", side_effect=adapter_side_effect), \
             patch("src.providers.time.sleep"):
            result = call("refine", [{"role": "user", "content": "hi"}],
                          model="mistral-small-latest")

        assert result.text == "eden response"
        assert result.provider.name == "eden_mistral"
        assert result.attempts == 2

    def test_non_429_error_raises_immediately(self, monkeypatch):
        """A ProviderError (e.g. HTTP 500) must not be retried."""
        monkeypatch.setenv("MISTRAL_API_KEY", "key-m")
        monkeypatch.setenv("EDENAI_API_KEY",  "key-eden")

        call_count = {"n": 0}

        def adapter_side_effect(provider, messages, **opts):
            call_count["n"] += 1
            raise ProviderError("HTTP 500 internal error")

        with patch("src.providers._call_openai_adapter", side_effect=adapter_side_effect), \
             patch("src.providers.time.sleep"):
            with pytest.raises(ProviderError, match="HTTP 500"):
                call("refine", [{"role": "user", "content": "hi"}])

        assert call_count["n"] == 1  # not retried

    def test_all_429_exhausts_attempts(self, monkeypatch):
        """6 consecutive 429s -> ProviderError after all attempts."""
        monkeypatch.setenv("MISTRAL_API_KEY", "key-m")
        monkeypatch.setenv("EDENAI_API_KEY",  "key-eden")

        def always_rate_limit(provider, messages, **opts):
            raise RateLimitError("429 forever")

        with patch("src.providers._call_openai_adapter", side_effect=always_rate_limit), \
             patch("src.providers.time.sleep"):
            with pytest.raises(ProviderError, match="All providers exhausted"):
                call("refine", [{"role": "user", "content": "hi"}])

    def test_single_provider_retries_same(self, monkeypatch):
        """With one provider, all retries go to the same provider."""
        monkeypatch.setenv("MISTRAL_API_KEY", "key-m")
        monkeypatch.delenv("EDENAI_API_KEY", raising=False)

        calls = []

        def adapter_side_effect(provider, messages, **opts):
            calls.append(provider.name)
            raise RateLimitError("429")

        with patch("src.providers._call_openai_adapter", side_effect=adapter_side_effect), \
             patch("src.providers.time.sleep"):
            with pytest.raises(ProviderError):
                call("refine", [{"role": "user", "content": "hi"}])

        assert all(c == "mistral_direct" for c in calls)
        assert len(calls) == 6  # _MAX_ATTEMPTS

    def test_backoff_sleep_called_between_retries(self, monkeypatch):
        """Verify sleep is called with the correct backoff values."""
        monkeypatch.setenv("MISTRAL_API_KEY", "key-m")
        monkeypatch.setenv("EDENAI_API_KEY",  "key-eden")

        def always_429(provider, messages, **opts):
            raise RateLimitError("429")

        with patch("src.providers._call_openai_adapter", side_effect=always_429), \
             patch("src.providers.time.sleep") as mock_sleep:
            with pytest.raises(ProviderError):
                call("refine", [{"role": "user", "content": "hi"}])

        expected_waits = [2, 4, 8, 15, 30]
        actual_waits = [c.args[0] for c in mock_sleep.call_args_list]
        assert actual_waits == expected_waits


# == call() — sticky policy ===================================================

class TestCallSticky:
    def test_sticky_stays_on_primary(self, monkeypatch):
        """fact_check_x with both keys: all retries on xai_direct."""
        monkeypatch.setenv("XAI_API_KEY",    "key-xai")
        monkeypatch.setenv("EDENAI_API_KEY", "key-eden")

        calls = []

        def adapter_side_effect(provider, messages, **opts):
            calls.append(provider.name)
            raise RateLimitError("429")

        with patch("src.providers._call_xai_adapter", side_effect=adapter_side_effect), \
             patch("src.providers.time.sleep"):
            with pytest.raises(ProviderError):
                call("fact_check_x", [{"role": "user", "content": "hi"}])

        # All 6 attempts should be on xai_direct, never eden_xai
        assert all(c == "xai_direct" for c in calls)
        assert len(calls) == 6

    def test_sticky_falls_back_when_primary_absent(self, monkeypatch):
        """fact_check_x without XAI_API_KEY: uses eden_xai."""
        monkeypatch.delenv("XAI_API_KEY", raising=False)
        monkeypatch.setenv("EDENAI_API_KEY", "key-eden")

        with patch("src.providers._call_openai_adapter", return_value="grok via eden"):
            result = call("fact_check_x",
                          [{"role": "user", "content": "hi"}],
                          model="xai/grok-4-1-fast")

        assert result.text == "grok via eden"
        assert result.provider.name == "eden_xai"

    def test_sticky_success_on_first_try(self, monkeypatch):
        """Sticky happy path: first attempt succeeds."""
        monkeypatch.setenv("XAI_API_KEY",    "key-xai")
        monkeypatch.setenv("EDENAI_API_KEY", "key-eden")

        with patch("src.providers._call_xai_adapter", return_value="grok result"):
            result = call("fact_check_x",
                          [{"role": "user", "content": "check this"}])

        assert result.text == "grok result"
        assert result.provider.name == "xai_direct"
        assert result.attempts == 1


# == call() — Eden model mapping integration ==================================

class TestCallEdenMapping:
    def test_eden_provider_gets_mapped_model(self, monkeypatch):
        """When Eden provider is called, model is translated to Eden format."""
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        monkeypatch.setenv("EDENAI_API_KEY", "key-eden")

        captured_opts = {}

        def capture_adapter(provider, messages, **opts):
            captured_opts.update(opts)
            return "result"

        with patch("src.providers._call_openai_adapter", side_effect=capture_adapter):
            call("refine", [{"role": "user", "content": "hi"}],
                 model="mistral-small-latest", temperature=0.2)

        assert captured_opts["model"] == "mistral/mistral-small-latest"
        assert captured_opts["fallbacks"] == EDEN_FALLBACK_CHAINS["mistral/mistral-small-latest"]
        assert captured_opts["temperature"] == 0.2

    def test_eden_reasoning_effort_stripped(self, monkeypatch):
        """reasoning_effort on Eden triggers substitution and stripping."""
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        monkeypatch.setenv("EDENAI_API_KEY", "key-eden")

        captured_opts = {}

        def capture_adapter(provider, messages, **opts):
            captured_opts.update(opts)
            return "result"

        with patch("src.providers._call_openai_adapter", side_effect=capture_adapter):
            call("refine", [{"role": "user", "content": "hi"}],
                 model="mistral-small-latest", reasoning_effort="high",
                 temperature=0.3)

        assert captured_opts["model"] == "mistral/magistral-small-latest"
        assert "reasoning_effort" not in captured_opts
        assert captured_opts["temperature"] == 0.3

    def test_direct_provider_passes_opts_unchanged(self, monkeypatch):
        """Mistral direct should receive canonical model name and all opts."""
        monkeypatch.setenv("MISTRAL_API_KEY", "key-m")
        monkeypatch.delenv("EDENAI_API_KEY", raising=False)

        captured_opts = {}

        def capture_adapter(provider, messages, **opts):
            captured_opts.update(opts)
            return "result"

        with patch("src.providers._call_openai_adapter", side_effect=capture_adapter):
            call("refine", [{"role": "user", "content": "hi"}],
                 model="mistral-small-latest", reasoning_effort="high",
                 temperature=0.3)

        assert captured_opts["model"] == "mistral-small-latest"
        assert captured_opts["reasoning_effort"] == "high"
        assert captured_opts["temperature"] == 0.3


# == CallResult — model/provider visibility ===================================

class TestCallResult:
    def test_direct_call_preserves_requested_and_effective(self, monkeypatch):
        """Mistral direct: requested_model == effective_model, no substitution."""
        monkeypatch.setenv("MISTRAL_API_KEY", "key-m")
        monkeypatch.delenv("EDENAI_API_KEY", raising=False)

        with patch("src.providers._call_openai_adapter", return_value="ok"):
            result = call("refine", [{"role": "user", "content": "hi"}],
                          model="magistral-medium-latest")

        assert result.requested_model == "magistral-medium-latest"
        assert result.effective_model == "magistral-medium-latest"
        assert result.substituted is False

    def test_eden_mapping_sets_effective_model_to_eden_format(self, monkeypatch):
        """Eden route: effective_model reflects the Eden identifier."""
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        monkeypatch.setenv("EDENAI_API_KEY", "key-eden")

        with patch("src.providers._call_openai_adapter", return_value="ok"):
            result = call("refine", [{"role": "user", "content": "hi"}],
                          model="mistral-small-latest")

        assert result.requested_model == "mistral-small-latest"
        assert result.effective_model == "mistral/mistral-small-latest"
        assert result.substituted is False  # plain mapping is not a substitution

    def test_eden_substitution_reports_substituted_true(self, monkeypatch):
        """Eden + reasoning_effort substitution must set substituted=True."""
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        monkeypatch.setenv("EDENAI_API_KEY", "key-eden")

        with patch("src.providers._call_openai_adapter", return_value="ok"):
            result = call("refine", [{"role": "user", "content": "hi"}],
                          model="mistral-small-latest",
                          reasoning_effort="high")

        assert result.requested_model == "mistral-small-latest"
        assert result.effective_model == "mistral/magistral-small-latest"
        assert result.substituted is True

    def test_attempts_reflects_retry_count(self, monkeypatch):
        """After one 429 then a success, attempts should be 2."""
        monkeypatch.setenv("MISTRAL_API_KEY", "key-m")
        monkeypatch.setenv("EDENAI_API_KEY", "key-eden")

        def side_effect(provider, messages, **opts):
            if provider.name == "mistral_direct":
                raise RateLimitError("429")
            return "from eden"

        with patch("src.providers._call_openai_adapter", side_effect=side_effect), \
             patch("src.providers.time.sleep"):
            result = call("refine", [{"role": "user", "content": "hi"}],
                          model="mistral-small-latest")

        assert result.attempts == 2
        assert result.provider.name == "eden_mistral"

    def test_requested_model_empty_when_not_passed(self, monkeypatch):
        """If caller doesn't pass a model, requested_model is ''."""
        monkeypatch.setenv("XAI_API_KEY", "key-xai")
        monkeypatch.delenv("EDENAI_API_KEY", raising=False)

        with patch("src.providers._call_xai_adapter", return_value="grok"):
            result = call("fact_check_x", [{"role": "user", "content": "hi"}])

        assert result.requested_model == ""
        assert result.substituted is False


# == call() — Layer-1 cascade on 429 ==========================================

class TestCallCascade:
    """Cascade via *_FALLBACK_MAP on the same direct provider.

    These tests verify that call() consumes MISTRAL/XAI/PERPLEXITY_FALLBACK_MAP
    and not only the Eden native chain.  Cascade state is per-provider.
    """

    def test_mistral_cascade_simple_chain(self, monkeypatch):
        """small -> medium -> large via MISTRAL_FALLBACK_MAP on consecutive 429s."""
        monkeypatch.setenv("MISTRAL_API_KEY", "key-m")
        monkeypatch.delenv("EDENAI_API_KEY", raising=False)

        seen_models = []

        def adapter(provider, messages, **opts):
            seen_models.append(opts.get("model"))
            raise RateLimitError("429")

        with patch("src.providers._call_openai_adapter", side_effect=adapter), \
             patch("src.providers.time.sleep"):
            with pytest.raises(ProviderError):
                call("refine", [{"role": "user", "content": "hi"}],
                     model="mistral-small-latest")

        # Cascade: small -> medium -> large, then "" => provider exhausted.
        assert seen_models == [
            "mistral-small-latest",
            "mistral-medium-latest",
            "mistral-large-latest",
        ]

    def test_mistral_cascade_recovers_on_fallback(self, monkeypatch):
        """First model 429, cascade to next, second model succeeds."""
        monkeypatch.setenv("MISTRAL_API_KEY", "key-m")
        monkeypatch.delenv("EDENAI_API_KEY", raising=False)

        def adapter(provider, messages, **opts):
            if opts.get("model") == "mistral-small-latest":
                raise RateLimitError("429")
            return "medium answered"

        with patch("src.providers._call_openai_adapter", side_effect=adapter), \
             patch("src.providers.time.sleep"):
            result = call("refine", [{"role": "user", "content": "hi"}],
                          model="mistral-small-latest")

        assert result.text == "medium answered"
        assert result.provider.name == "mistral_direct"
        assert result.effective_model == "mistral-medium-latest"
        assert result.requested_model == "mistral-small-latest"
        assert result.attempts == 2

    def test_mistral_cascade_compound_key_strips_reasoning_effort(self, monkeypatch):
        """mistral-small + reasoning_effort -> magistral-small (effort stripped)."""
        monkeypatch.setenv("MISTRAL_API_KEY", "key-m")
        monkeypatch.delenv("EDENAI_API_KEY", raising=False)

        seen = []

        def adapter(provider, messages, **opts):
            seen.append({"model": opts.get("model"),
                         "reasoning_effort": opts.get("reasoning_effort")})
            if len(seen) == 1:
                raise RateLimitError("429")
            return "ok"

        with patch("src.providers._call_openai_adapter", side_effect=adapter), \
             patch("src.providers.time.sleep"):
            result = call("refine", [{"role": "user", "content": "hi"}],
                          model="mistral-small-latest",
                          reasoning_effort="high",
                          temperature=0.3)

        assert seen[0] == {"model": "mistral-small-latest",
                           "reasoning_effort": "high"}
        # After 429, compound key triggers substitution + strip.
        assert seen[1] == {"model": "magistral-small-latest",
                           "reasoning_effort": None}
        assert result.effective_model == "magistral-small-latest"

    def test_mistral_cascade_exhausts_raises_provider_error(self, monkeypatch):
        """Once the chain terminates with '', the provider is exhausted."""
        monkeypatch.setenv("MISTRAL_API_KEY", "key-m")
        monkeypatch.delenv("EDENAI_API_KEY", raising=False)

        call_count = {"n": 0}

        def always_429(provider, messages, **opts):
            call_count["n"] += 1
            raise RateLimitError("429")

        with patch("src.providers._call_openai_adapter", side_effect=always_429), \
             patch("src.providers.time.sleep"):
            with pytest.raises(ProviderError, match="All providers exhausted"):
                call("refine", [{"role": "user", "content": "hi"}],
                     model="mistral-small-latest")

        # small -> medium -> large -> "" : 3 attempts, then exhausted.
        assert call_count["n"] == 3

    def test_xai_cascade_cycles_within_attempt_cap(self, monkeypatch):
        """xAI cyclic chain is safe under _MAX_ATTEMPTS; sticky never switches."""
        monkeypatch.setenv("XAI_API_KEY",    "key-xai")
        monkeypatch.setenv("EDENAI_API_KEY", "key-eden")

        seen_models = []

        def adapter(provider, messages, **opts):
            seen_models.append(opts.get("model"))
            raise RateLimitError("429")

        with patch("src.providers._call_xai_adapter", side_effect=adapter), \
             patch("src.providers.time.sleep"):
            with pytest.raises(ProviderError, match="All providers exhausted"):
                call("fact_check_x", [{"role": "user", "content": "hi"}],
                     model="grok-4-1-fast-non-reasoning")

        # Sticky: all 6 attempts on xai_direct (never eden_xai).
        assert len(seen_models) == 6
        # Chain walks through XAI_FALLBACK_MAP; cycle kicks in before cap.
        # Model should advance on each attempt and never get stuck.
        assert seen_models[0] == "grok-4-1-fast-non-reasoning"
        assert seen_models[1] == "grok-4-1-fast-reasoning"
        # The cycle (multi-agent <-> reasoning) is intentional.
        assert len(set(seen_models)) >= 3  # at least 3 distinct models tried

    def test_perplexity_cascade_cycles_within_cap(self, monkeypatch):
        """Perplexity cyclic chain: sonar-deep -> sonar-reasoning -> sonar-pro -> sonar -> sonar-pro."""
        monkeypatch.setenv("PERPLEXITY_API_KEY", "key-p")
        monkeypatch.delenv("EDENAI_API_KEY", raising=False)

        seen_models = []

        def adapter(provider, messages, **opts):
            seen_models.append(opts.get("model"))
            raise RateLimitError("429")

        with patch("src.providers._call_openai_adapter", side_effect=adapter), \
             patch("src.providers.time.sleep"):
            with pytest.raises(ProviderError):
                call("fact_check_web", [{"role": "user", "content": "hi"}],
                     model="sonar-deep-research")

        assert seen_models[0] == "sonar-deep-research"
        assert seen_models[1] == "sonar-reasoning-pro"
        assert seen_models[2] == "sonar-pro"
        assert seen_models[3] == "sonar"
        # Cycle: sonar -> sonar-pro
        assert seen_models[4] == "sonar-pro"

    def test_eden_does_not_cascade_client_side(self, monkeypatch):
        """Eden provider 429s keep the same effective model (server-side chain)."""
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        monkeypatch.setenv("EDENAI_API_KEY", "key-eden")

        seen_models = []

        def adapter(provider, messages, **opts):
            seen_models.append(opts.get("model"))
            raise RateLimitError("429")

        with patch("src.providers._call_openai_adapter", side_effect=adapter), \
             patch("src.providers.time.sleep"):
            with pytest.raises(ProviderError):
                call("refine", [{"role": "user", "content": "hi"}],
                     model="mistral-small-latest")

        # Eden mapped once by _prepare_eden_opts, then re-mapped each attempt
        # from the original canonical (since cascade is a no-op for Eden).
        assert len(seen_models) == 6
        assert set(seen_models) == {"mistral/mistral-small-latest"}

    def test_pingpong_direct_cascade_suppressed_when_eden_live(self, monkeypatch):
        """With Eden in the live set (pingpong), direct keeps its model.

        Rationale: a 429 on Mistral direct is typically an account-wide
        rate limit — swapping to another Mistral model on the same account
        rarely helps. Eden provides real redundancy via a separate account,
        so direct-model degradation is deferred to the Eden-absent case.
        """
        monkeypatch.setenv("MISTRAL_API_KEY", "key-m")
        monkeypatch.setenv("EDENAI_API_KEY",  "key-eden")

        seen = []

        def adapter(provider, messages, **opts):
            seen.append((provider.name, opts.get("model")))
            raise RateLimitError("429")

        with patch("src.providers._call_openai_adapter", side_effect=adapter), \
             patch("src.providers.time.sleep"):
            with pytest.raises(ProviderError):
                call("refine", [{"role": "user", "content": "hi"}],
                     model="mistral-small-latest")

        # All 6 attempts: mistral_direct stays on mistral-small-latest,
        # eden_mistral stays on mistral/mistral-small-latest.
        assert seen == [
            ("mistral_direct", "mistral-small-latest"),
            ("eden_mistral",   "mistral/mistral-small-latest"),
            ("mistral_direct", "mistral-small-latest"),
            ("eden_mistral",   "mistral/mistral-small-latest"),
            ("mistral_direct", "mistral-small-latest"),
            ("eden_mistral",   "mistral/mistral-small-latest"),
        ]

    def test_sticky_direct_cascade_runs_even_with_eden_key(self, monkeypatch):
        """Sticky never rotates to Eden — so Eden's presence in live must
        NOT suppress the direct cascade (otherwise the provider would be
        stuck on a model it cannot serve with no alternative)."""
        monkeypatch.setenv("XAI_API_KEY",    "key-xai")
        monkeypatch.setenv("EDENAI_API_KEY", "key-eden")

        seen = []

        def adapter(provider, messages, **opts):
            seen.append((provider.name, opts.get("model")))
            raise RateLimitError("429")

        with patch("src.providers._call_xai_adapter", side_effect=adapter), \
             patch("src.providers.time.sleep"):
            with pytest.raises(ProviderError):
                call("fact_check_x", [{"role": "user", "content": "hi"}],
                     model="grok-4-1-fast-non-reasoning")

        # Sticky keeps all 6 attempts on xai_direct.
        assert len(seen) == 6
        assert all(p == "xai_direct" for p, _ in seen)
        # Cascade should still advance through XAI_FALLBACK_MAP.
        models = [m for _, m in seen]
        assert models[0] == "grok-4-1-fast-non-reasoning"
        assert models[1] == "grok-4-1-fast-reasoning"
        assert len(set(models)) >= 3

    def test_pingpong_exhausted_direct_keeps_eden_live(self, monkeypatch):
        """When mistral_direct exhausts its chain, eden can still serve."""
        monkeypatch.setenv("MISTRAL_API_KEY", "key-m")
        monkeypatch.setenv("EDENAI_API_KEY",  "key-eden")

        calls = []

        def adapter(provider, messages, **opts):
            calls.append(provider.name)
            if provider.name == "mistral_direct":
                raise RateLimitError("429")
            return "eden wins"

        with patch("src.providers._call_openai_adapter", side_effect=adapter), \
             patch("src.providers.time.sleep"):
            result = call("refine", [{"role": "user", "content": "hi"}],
                          model="mistral-small-latest")

        # Eden succeeds on the pingpong's first visit (attempt 1).
        assert result.provider.name == "eden_mistral"
        assert result.text == "eden wins"
        assert calls == ["mistral_direct", "eden_mistral"]

    def test_cascade_noop_when_no_model_passed(self, monkeypatch):
        """Without an explicit model, cascade does not advance — retry same."""
        monkeypatch.setenv("MISTRAL_API_KEY", "key-m")
        monkeypatch.delenv("EDENAI_API_KEY", raising=False)

        seen = []

        def adapter(provider, messages, **opts):
            seen.append(opts.get("model"))
            raise RateLimitError("429")

        with patch("src.providers._call_openai_adapter", side_effect=adapter), \
             patch("src.providers.time.sleep"):
            with pytest.raises(ProviderError):
                call("refine", [{"role": "user", "content": "hi"}])

        # All 6 attempts: no model, cascade is a no-op, no exhaustion.
        assert len(seen) == 6
        assert all(m is None for m in seen)

    def test_cascade_unknown_model_does_not_exhaust(self, monkeypatch):
        """A model not listed in MISTRAL_FALLBACK_MAP keeps retrying same."""
        monkeypatch.setenv("MISTRAL_API_KEY", "key-m")
        monkeypatch.delenv("EDENAI_API_KEY", raising=False)

        seen = []

        def adapter(provider, messages, **opts):
            seen.append(opts.get("model"))
            raise RateLimitError("429")

        with patch("src.providers._call_openai_adapter", side_effect=adapter), \
             patch("src.providers.time.sleep"):
            with pytest.raises(ProviderError):
                call("refine", [{"role": "user", "content": "hi"}],
                     model="some-custom-model-not-in-map")

        # Cascade lookup misses => no advance => all 6 attempts on same model.
        assert len(seen) == 6
        assert set(seen) == {"some-custom-model-not-in-map"}

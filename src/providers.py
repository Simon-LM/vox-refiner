#!/usr/bin/env python3
"""VoxRefiner — Provider resolution and routing.

Central registry for all AI providers used by VoxRefiner.
Maps capabilities (refine, search, fact_check_x, ...) to an ordered list of
available providers, based solely on which API keys are present in the
environment.

NOT yet integrated into existing flows (refine.py, insight.py, text_flows.sh).
Migration is progressive — one flow at a time, starting with fact_check.

Public API
----------
    resolve(capability)         -> list[Provider]   (key-filtered, ordered)
    is_available(capability)    -> bool
    call(capability, messages)  -> CallResult        (with retry / fallback)
    mark_invalid(provider_name) -> invalidate cached key on 401

CallResult
----------
    Result of a successful call(). Exposes the provider that answered, the
    actually-used model (effective_model), what was requested (requested_model),
    whether the Eden adapter substituted the model (substituted), and the
    attempt count. Business code uses these fields to display the real
    provider + model to the user, even after a fallback or substitution.

Retry policies
--------------
    pingpong : alternates primary <-> secondary on 429 (e.g. Mistral <-> Eden)
    sticky   : all retries on the same provider (e.g. Grok direct for X search)

    With a single available provider, both policies behave identically:
    retry on the same provider with backoff.

Cascade on 429 (Layer 1)
------------------------
    Direct providers have a Layer-1 cascade consumed by call() through
    _advance_cascade(). On each RateLimitError, the cascade walks the
    provider's *_FALLBACK_MAP and the next retry uses the fallback model.
    Cascade state is per-provider, so each provider tracks its own chain.
    Compound keys ("model+option") also strip options that the fallback
    model does not support. A terminal "" marks the provider exhausted;
    remaining live providers keep retrying.

    Direct cascade is SUPPRESSED when Eden redundancy is active (pingpong
    policy with an Eden route live): a 429 on direct is typically an
    account-wide rate limit, so swapping models on the same account rarely
    helps, while Eden provides real redundancy via a separate account.
    Under sticky policy, Eden is never rotated to, so the cascade runs
    normally even if an Eden key is configured.

    Eden providers do NOT cascade client-side — their "fallbacks" payload
    field handles fallback server-side in a single HTTP call.

Model mapping (Eden AI)
-----------------------
    Eden providers translate canonical Mistral model names to Eden format
    (e.g. "mistral-small-latest" -> "mistral/mistral-small-latest") and inject
    native fallback chains via the "fallbacks" payload field.

    When a model + option combination is unsupported on Eden (e.g.
    reasoning_effort on mistral-small), the adapter substitutes an equivalent
    model and strips the incompatible option.

XDG cache
---------
    ~/.local/share/vox-refiner/keys-cache.json
    Re-validates only when the key changes (hash check) or on 401 in use.
    No periodic TTL (user decision: solution b).

CLI
---
    python -m src.providers --audit         capability status table
    python -m src.providers --validate      force re-validate all keys
    python -m src.providers --available CAP exit 0 if available, 1 if not
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


# == Constants ================================================================

EDEN_CHAT_URL = "https://api.edenai.run/v3/llm/chat/completions"
EDEN_OCR_URL  = "https://api.edenai.run/v3/universal-ai/async"

# Retry backoff: waits (seconds) between the 6 attempts (3 per provider).
# Attempt sequence (pingpong): primary -> eden -> primary -> eden -> primary -> eden -> FAIL
# Attempt sequence (sticky):   primary -> primary -> primary -> primary -> primary -> primary -> FAIL
_BACKOFF_SECONDS: list[int] = [2, 4, 8, 15, 30]  # 5 waits for 6 attempts
_MAX_ATTEMPTS = 6                                  # = 3 per provider (if 2 available)


# == Dataclasses ==============================================================

@dataclass
class CapabilitySpec:
    """Defines how a capability resolves and retries across providers.

    Attributes:
        providers: ordered list of provider names (priority order).
        policy:    "pingpong" — alternate primary <-> secondary on 429.
                   "sticky"   — all retries on primary provider (no fallback
                                to secondary even if available).
    """
    providers: list[str]
    policy:    str = "pingpong"  # "pingpong" | "sticky"


@dataclass
class Provider:
    """Represents one API provider for a specific route.

    Each provider maps to exactly one API key variable and one endpoint.
    Multiple providers can share the same required_env_key (e.g. Eden routes
    all require EDENAI_API_KEY but hit different model IDs).
    """
    name:             str    # internal identifier, e.g. "mistral_direct"
    display_name:     str    # human label, e.g. "Mistral (direct)"
    required_env_key: str    # env var name, e.g. "MISTRAL_API_KEY"
    ping_url:         str    # URL used to validate the key
    ping_method:      str  = "GET"      # GET or POST
    endpoint:         str  = ""         # chat completions URL
    ping_model_id:    str  = ""         # model used for POST-based pings only
    adapter_type:     str  = "openai"   # openai | xai_sdk | eden_ocr
    is_eden:          bool = False      # activates model mapping + fallback chains

    def key(self) -> str:
        """Return the current value of the required API key from env."""
        return os.environ.get(self.required_env_key, "").strip()

    def has_key(self) -> bool:
        return bool(self.key())


@dataclass
class CallResult:
    """Result of a successful call(), including provider/model visibility.

    Attributes:
        text:             generated text returned by the provider.
        provider:         the Provider that produced the text.
        effective_model:  the model identifier actually sent to the API
                          (Eden format like "mistral/magistral-small-latest"
                          after mapping/substitution, or the canonical name
                          for direct providers).
        requested_model:  the canonical model name requested by the caller.
        substituted:      True if the Eden adapter substituted the model
                          because an option (e.g. reasoning_effort) was
                          incompatible with the requested model on Eden.
        attempts:         number of attempts made (1 = succeeded on first try).
    """
    text:             str
    provider:         "Provider"
    effective_model:  str
    requested_model:  str
    substituted:      bool = False
    attempts:         int  = 1


# == Model mapping tables =====================================================
#
# Three layers of resilience:
#   1. *_FALLBACK_MAP         — canonical model -> fallback on the same direct API
#                               (MISTRAL / XAI / PERPLEXITY).  Used when the
#                               primary model degrades and we stay on the same
#                               provider (sticky policy, or Eden key absent).
#   2. EDEN_MODEL_MAP         — canonical Mistral model -> Eden AI identifier
#      EDEN_SUBSTITUTIONS     — model + incompatible option -> substitute model
#   3. EDEN_FALLBACK_CHAINS   — Eden model -> native fallback chain (server-side)
#
# The user adjusts the actual model choices; this code provides the structure.

# Layer 1: Mistral direct fallbacks (canonical -> canonical)
# Consumed by call() via _advance_cascade() — on 429 the cascade walks this
# map, swapping the model and retrying on the same direct provider.
#
# Compound keys ("model+option") distinguish modes that have different
# fallback paths.  On Mistral direct, mistral-small-latest supports
# reasoning_effort=high (Mistral Small 4's internal CoT); fallback models
# do NOT support it, so reasoning_effort is stripped on fallback.
#
# Alignment: these defaults match .env.example (REFINE_MODEL_*_FALLBACK).
MISTRAL_FALLBACK_MAP: dict[str, str] = {
    # SHORT tier: mistral-small (fast, no reasoning) -> mistral-medium
    "mistral-small-latest":                    "mistral-medium-latest",
    "mistral-small-latest+reasoning_effort":   "magistral-small-latest",
    "magistral-medium-latest":                 "mistral-medium-latest",
    "mistral-medium-latest":                   "mistral-large-latest",
    "mistral-large-latest":                    "",  # no further fallback
    "magistral-small-latest":                  "mistral-medium-latest",
}

# Layer 1 (xAI direct): canonical Grok model -> fallback on xAI direct.
# Used when XAI_API_KEY is present and the primary model is 429 / degrades.
# Canonical format = xAI API model name (no "xai/" prefix — that's Eden's format).
# Empty value = end of chain, no further fallback.
XAI_FALLBACK_MAP: dict[str, str] = {
    "grok-4-1-fast-non-reasoning":    "grok-4-1-fast-reasoning",
    "grok-4-1-fast-reasoning":        "grok-4.20-0309-non-reasoning",
    "grok-4.20-0309-non-reasoning":   "grok-4.20-0309-reasoning",
    "grok-4.20-0309-reasoning":       "grok-4.20-multi-agent-0309",
    "grok-4.20-multi-agent-0309":     "grok-4.20-0309-reasoning",
}

# Layer 1 (Perplexity direct): canonical Sonar model -> fallback on Perplexity direct.
# Used when PERPLEXITY_API_KEY is present and the primary model degrades.
# Canonical format = Perplexity API model name (no "perplexityai/" prefix).
# Empty value = end of chain.
PERPLEXITY_FALLBACK_MAP: dict[str, str] = {
    "sonar-deep-research":  "sonar-reasoning-pro",
    "sonar-reasoning-pro":  "sonar-pro",
    "sonar-pro":            "sonar",
    "sonar":                "sonar-pro",
}

# Layer 2a: Canonical model name (Mistral / Perplexity / xAI) -> Eden AI
# model identifier (prefixed by Eden's provider routing namespace).
# The canonical names here must match the keys of the direct-provider
# fallback maps (MISTRAL_FALLBACK_MAP / PERPLEXITY_FALLBACK_MAP /
# XAI_FALLBACK_MAP) so the same model string used against a direct API
# can be translated for Eden without the business code caring.
EDEN_MODEL_MAP: dict[str, str] = {
    # Mistral
    "mistral-small-latest":    "mistral/mistral-small-latest",
    "mistral-medium-latest":   "mistral/mistral-medium-latest",
    "mistral-large-latest":    "mistral/mistral-large-latest",
    "magistral-medium-latest": "mistral/magistral-medium-latest",
    "magistral-small-latest":  "mistral/magistral-small-latest",
    # Perplexity
    "sonar":                   "perplexityai/sonar",
    "sonar-pro":               "perplexityai/sonar-pro",
    "sonar-reasoning-pro":     "perplexityai/sonar-reasoning-pro",
    "sonar-deep-research":     "perplexityai/sonar-deep-research",
    # xAI
    "grok-4-1-fast-non-reasoning":    "xai/grok-4-1-fast-non-reasoning-latest",
    "grok-4-1-fast-reasoning":        "xai/grok-4-1-fast-reasoning-latest",
    "grok-4.20-0309-non-reasoning":   "xai/grok-4.20-beta-0309-non-reasoning",
    "grok-4.20-0309-reasoning":       "xai/grok-4.20-beta-0309-reasoning",
    "grok-4.20-multi-agent-0309":     "xai/grok-4.20-beta-0309-reasoning",
}

# Layer 2b: Substitutions when a model + option is unsupported on Eden.
# Key format: "canonical-model+option_name"
# Eden AI does not support reasoning_effort on mistral-small; substitute
# magistral-small which has native reasoning (no option needed).
EDEN_SUBSTITUTIONS: dict[str, dict] = {
    "mistral-small-latest+reasoning_effort": {
        "model": "mistral/magistral-small-latest",
        "strip": ["reasoning_effort"],
    },
}

# Layer 3: Eden native fallback chains (injected as "fallbacks" in payload).
# Eden tries these server-side before returning an error — zero extra latency.
# Key = Eden model identifier, Value = ordered list of Eden fallback models.
#
# Alignment: mirrors MISTRAL_FALLBACK_MAP but in Eden provider/model format.
# magistral-medium -> mistral-medium (not mistral-large) to match existing code.
EDEN_FALLBACK_CHAINS: dict[str, list[str]] = {
    "mistral/mistral-small-latest":  ["ovhcloud/Mistral-Small-3.2-24B-Instruct-2506"],
    "mistral/mistral-medium-latest": ["ovhcloud/gpt-oss-120b"],
    "mistral/mistral-large-latest":  ["amazon/mistral.mistral-large-3-675b-instruct"],
    "mistral/magistral-medium-latest": ["amazon/qwen.qwen3-next-80b-a3b"],
    "mistral/magistral-small-latest":  ["amazon/mistral.magistral-small-2509"],
    
    "xai/grok-4-1-fast-non-reasoning-latest":     ["xai/grok-4-fast-non-reasoning"],
    "xai/grok-4-1-fast-reasoning-latest":         ["xai/grok-4-fast-reasoning"], 
    "xai/grok-4.20-beta-0309-non-reasoning":      ["xai/grok-4"],
    "xai/grok-4.20-beta-0309-reasoning":          ["xai/grok-4"],

    "perplexityai/sonar":          ["xai/grok-4-1-fast-non-reasoning-latest"],
    "perplexityai/sonar-pro":          ["perplexityai/sonar"],
    "perplexityai/sonar-reasoning-pro": ["perplexityai/sonar-pro"],
    "perplexityai/sonar-deep-research": ["perplexityai/sonar-reasoning-pro"],
}


# == Provider registry ========================================================

PROVIDERS: dict[str, Provider] = {
    # -- Mistral direct ------------------------------------------------------
    "mistral_direct": Provider(
        name             = "mistral_direct",
        display_name     = "Mistral (direct)",
        required_env_key = "MISTRAL_API_KEY",
        ping_url         = "https://api.mistral.ai/v1/models",
        ping_method      = "GET",
        endpoint         = "https://api.mistral.ai/v1/chat/completions",
        adapter_type     = "openai",
    ),

    # -- Mistral via Eden AI (redundancy) ------------------------------------
    "eden_mistral": Provider(
        name             = "eden_mistral",
        display_name     = "Mistral via Eden AI",
        required_env_key = "EDENAI_API_KEY",
        ping_url         = EDEN_CHAT_URL,
        ping_method      = "POST",
        endpoint         = EDEN_CHAT_URL,
        ping_model_id    = "mistral/mistral-small-latest",
        adapter_type     = "openai",
        is_eden          = True,
    ),

    # -- xAI / Grok direct --------------------------------------------------
    "xai_direct": Provider(
        name             = "xai_direct",
        display_name     = "xAI / Grok (direct)",
        required_env_key = "XAI_API_KEY",
        ping_url         = "https://api.x.ai/v1/models",
        ping_method      = "GET",
        endpoint         = "",          # uses xai_sdk, not a bare HTTP call
        adapter_type     = "xai_sdk",
    ),

    # -- Grok via Eden AI ----------------------------------------------------
    "eden_xai": Provider(
        name             = "eden_xai",
        display_name     = "Grok via Eden AI",
        required_env_key = "EDENAI_API_KEY",
        ping_url         = EDEN_CHAT_URL,
        ping_method      = "POST",
        endpoint         = EDEN_CHAT_URL,
        ping_model_id    = "xai/grok-4-1-fast",
        adapter_type     = "openai",
        is_eden          = True,
    ),

    # -- Perplexity direct ---------------------------------------------------
    "perplexity_direct": Provider(
        name             = "perplexity_direct",
        display_name     = "Perplexity (direct)",
        required_env_key = "PERPLEXITY_API_KEY",
        ping_url         = "https://api.perplexity.ai/models",
        ping_method      = "GET",
        endpoint         = "https://api.perplexity.ai/chat/completions",
        adapter_type     = "openai",
    ),

    # -- Perplexity via Eden AI ----------------------------------------------
    "eden_perplexity": Provider(
        name             = "eden_perplexity",
        display_name     = "Perplexity via Eden AI",
        required_env_key = "EDENAI_API_KEY",
        ping_url         = EDEN_CHAT_URL,
        ping_method      = "POST",
        endpoint         = EDEN_CHAT_URL,
        ping_model_id    = "perplexityai/sonar-pro",
        adapter_type     = "openai",
        is_eden          = True,
    ),

    # -- Mistral OCR direct (/v1/ocr, not chat completions) ------------------
    "mistral_ocr": Provider(
        name             = "mistral_ocr",
        display_name     = "Mistral OCR (direct)",
        required_env_key = "MISTRAL_API_KEY",
        ping_url         = "https://api.mistral.ai/v1/models",
        ping_method      = "GET",
        endpoint         = "https://api.mistral.ai/v1/ocr",
        adapter_type     = "mistral_ocr",
    ),

    # -- OCR via Eden AI (async endpoint) ------------------------------------
    "eden_ocr_mistral": Provider(
        name             = "eden_ocr_mistral",
        display_name     = "OCR via Eden AI (Mistral)",
        required_env_key = "EDENAI_API_KEY",
        ping_url         = EDEN_OCR_URL,
        ping_method      = "POST",
        endpoint         = EDEN_OCR_URL,
        ping_model_id    = "ocr/ocr_async/mistral",
        adapter_type     = "eden_ocr",
        is_eden          = True,
    ),

    # -- Mistral Vision direct (pixtral via /v1/chat/completions) ------------
    "mistral_vision": Provider(
        name             = "mistral_vision",
        display_name     = "Mistral Vision (direct)",
        required_env_key = "MISTRAL_API_KEY",
        ping_url         = "https://api.mistral.ai/v1/models",
        ping_method      = "GET",
        endpoint         = "https://api.mistral.ai/v1/chat/completions",
        adapter_type     = "openai",
    ),

    # -- Dormant entries (not yet wired, key never present) ------------------
    # "gemini_direct": Provider(
    #     name             = "gemini_direct",
    #     display_name     = "Gemini (direct)",
    #     required_env_key = "GEMINI_API_KEY",
    #     ping_url         = "https://generativelanguage.googleapis.com/v1beta/models",
    #     ping_method      = "GET",
    #     endpoint         = "",   # Google Search grounding needs a specific adapter
    #     adapter_type     = "gemini",  # to be implemented
    # ),
}


# == Capability table =========================================================

# Ordered by priority: first entry is always tried first.
# resolve() filters the providers list to those whose key is present.
#
# Policies:
#   pingpong — alternate primary <-> secondary on 429
#   sticky   — all retries on primary (secondary only if primary key absent)

CAPABILITIES: dict[str, CapabilitySpec] = {
    # Core flows — Mistral first, Eden/Mistral as fallback on 429
    "refine":    CapabilitySpec(["mistral_direct", "eden_mistral"],       "pingpong"),
    "insight":   CapabilitySpec(["mistral_direct", "eden_mistral"],       "pingpong"),
    "translate": CapabilitySpec(["mistral_direct", "eden_mistral"],       "pingpong"),
    "history":   CapabilitySpec(["mistral_direct", "eden_mistral"],       "pingpong"),

    # Transcription — Voxtral is Mistral-only; no Eden fallback path
    "transcribe": CapabilitySpec(["mistral_direct"],                      "sticky"),

    # Fact-check X/Twitter — xAI has native X search; Eden/xai loses it.
    # Sticky: when XAI_API_KEY is present, all retries stay on Grok direct.
    # If XAI_API_KEY absent, resolve() returns [eden_xai] and retries there.
    "fact_check_x": CapabilitySpec(["xai_direct", "eden_xai"],           "sticky"),

    # Fact-check web / search — Perplexity direct first, then Eden/Perplexity
    # Pingpong: both paths are functionally equivalent (same search engine)
    "fact_check_web": CapabilitySpec(["perplexity_direct", "eden_perplexity"], "pingpong"),
    "search":         CapabilitySpec(["perplexity_direct", "eden_perplexity"], "pingpong"),

    # OCR — 4-tier cascade driven by available keys:
    #   MISTRAL only  → mistral_ocr → mistral_vision
    #   EDEN only     → eden_ocr_mistral → eden_mistral
    #   Both keys     → mistral_ocr → eden_ocr_mistral → mistral_vision → eden_mistral
    # resolve() filters this list to providers whose key is present.
    # ocr.py iterates resolve("ocr") and dispatches by provider.adapter_type / name.
    "ocr": CapabilitySpec(
        ["mistral_ocr", "eden_ocr_mistral", "mistral_vision", "eden_mistral"],
        "pingpong",
    ),
}


# == Errors ===================================================================

class ProviderError(Exception):
    """Raised when no provider is available or all attempts have failed."""


class RateLimitError(Exception):
    """Transient 429 — signals the retry loop to switch provider."""


# == XDG cache ================================================================

def _cache_path() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    return Path(xdg) / "vox-refiner" / "keys-cache.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _key_hash(key: str) -> str:
    """Short SHA-256 hash of the key prefix — detects rotation without storing the key."""
    return hashlib.sha256(key[:8].encode()).hexdigest()[:16]


def _load_cache() -> dict:
    p = _cache_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(data: dict) -> None:
    p = _cache_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


# == Key validation ===========================================================

def _ping_provider(provider: Provider, timeout: float = 10.0) -> tuple[bool, str]:
    """Send a minimal request to validate the provider key.

    Returns (is_valid, reason).
    Reasons: "ok" | "429_rate_limited" | "401" | "http_NNN" | "network:..."
    """
    key = provider.key()
    if not key:
        return False, "key_missing"

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    try:
        if provider.ping_method == "GET":
            resp = requests.get(provider.ping_url, headers=headers, timeout=timeout)
        elif provider.adapter_type == "eden_ocr":
            # Eden OCR async: POST a no-op job creation
            resp = requests.post(
                provider.ping_url,
                headers=headers,
                json={
                    "model": provider.ping_model_id,
                    "input": {},
                    "show_original_response": False,
                },
                timeout=timeout,
            )
        else:
            # Standard chat ping — use ping_model_id or a safe default
            resp = requests.post(
                provider.ping_url,
                headers=headers,
                json={
                    "model": provider.ping_model_id or "mistral-small-latest",
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                    "temperature": 0,
                },
                timeout=timeout,
            )
    except requests.RequestException as exc:
        return False, f"network:{exc}"

    if resp.status_code in (200, 201, 202):
        return True, "ok"
    if resp.status_code == 401:
        return False, "401"
    if resp.status_code == 429:
        # Key exists and is accepted — just rate-limited right now
        return True, "429_rate_limited"
    return False, f"http_{resp.status_code}"


def is_key_validated(provider_name: str, force: bool = False) -> bool:
    """Return whether the provider's current key is known-good.

    Validation policy (solution b):
      - Re-validates when the key changes (hash mismatch).
      - Re-validates when force=True (manual --validate).
      - Does NOT re-validate on a time-based TTL.
      - 401 during live API use -> call mark_invalid() to update cache.

    Returns False if the key is absent, invalid, or unreachable.
    """
    provider = PROVIDERS.get(provider_name)
    if not provider or not provider.has_key():
        return False

    cache = _load_cache()
    entry = cache.get(provider_name, {})
    current_hash = _key_hash(provider.key())

    if not force and entry.get("key_hash") == current_hash:
        return entry.get("valid", False)

    # Key changed or forced — re-validate
    valid, reason = _ping_provider(provider)
    # 429 means the key is real; mark as valid but note the reason
    is_valid = valid or reason == "429_rate_limited"

    cache[provider_name] = {
        "valid":      is_valid,
        "checked_at": _now_iso(),
        "key_hash":   current_hash,
        **({"reason": reason} if not is_valid else {}),
    }
    _save_cache(cache)
    return is_valid


def mark_invalid(provider_name: str, reason: str = "401") -> None:
    """Invalidate a provider key in the cache after a live 401 rejection.

    Call this from any API call site when HTTP 401 is received.
    The next call to is_key_validated() will re-validate (key may have been
    rotated in .env since the last check).
    """
    provider = PROVIDERS.get(provider_name)
    if not provider:
        return
    cache = _load_cache()
    cache[provider_name] = {
        "valid":      False,
        "checked_at": _now_iso(),
        "key_hash":   _key_hash(provider.key()) if provider.has_key() else "",
        "reason":     reason,
    }
    _save_cache(cache)
    print(
        f"[providers] {provider.display_name} key marked invalid ({reason}).",
        file=sys.stderr,
    )


# == Resolution ===============================================================

def resolve(capability: str) -> list[Provider]:
    """Return the ordered list of available providers for *capability*.

    A provider is considered available if its required API key is present
    in the environment (non-empty). Key validity is NOT checked here —
    invalid keys are caught at call time, then mark_invalid() is called.
    """
    spec = CAPABILITIES.get(capability)
    if spec is None:
        return []
    return [
        PROVIDERS[n]
        for n in spec.providers
        if n in PROVIDERS and PROVIDERS[n].has_key()
    ]


def is_available(capability: str) -> bool:
    """Return True if at least one provider is available for *capability*."""
    return len(resolve(capability)) > 0


# == Eden model mapping =======================================================

def _prepare_eden_opts(opts: dict) -> tuple[dict, bool]:
    """Transform call options for an Eden AI provider.

    Applies three transformations in order:
      1. Substitution — if a model + option combo is unsupported on Eden,
         replace the model and strip the incompatible option.
      2. Model mapping — translate canonical Mistral name to Eden format.
      3. Fallback injection — add "fallbacks" field for Eden-native resilience.

    Returns (new_opts, substituted). `substituted` is True only when step 1
    changed the model via EDEN_SUBSTITUTIONS (so the caller can report the
    substitution to the user). Plain model mapping (step 2) does not count
    as a substitution — it is the expected Eden identifier format.
    """
    opts = dict(opts)
    model = opts.get("model", "")
    substituted = False

    # Step 1: check substitutions (model + incompatible option)
    for opt_name in list(opts.keys()):
        sub_key = f"{model}+{opt_name}"
        if sub_key in EDEN_SUBSTITUTIONS:
            sub = EDEN_SUBSTITUTIONS[sub_key]
            opts["model"] = sub["model"]
            for strip_key in sub["strip"]:
                opts.pop(strip_key, None)
            substituted = True
            # Model is already in Eden format after substitution
            model = ""  # skip step 2
            break

    # Step 2: translate canonical model -> Eden format
    if model and model in EDEN_MODEL_MAP:
        opts["model"] = EDEN_MODEL_MAP[model]

    # Step 3: inject Eden native fallback chain
    eden_model = opts.get("model", "")
    chain = EDEN_FALLBACK_CHAINS.get(eden_model, [])
    if chain:
        opts["fallbacks"] = chain

    return opts, substituted


# == Adapters =================================================================

def _call_openai_adapter(
    provider: Provider,
    messages: list[dict],
    timeout: int = 30,
    **extra_payload,
) -> str:
    """Execute via OpenAI-compatible chat completions endpoint.

    The model is expected in extra_payload["model"] — set by the caller
    (business code) or translated by _prepare_eden_opts() for Eden providers.
    """
    payload: dict = {"messages": messages, **extra_payload}

    try:
        resp = requests.post(
            provider.endpoint,
            headers={
                "Authorization": f"Bearer {provider.key()}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise ProviderError(f"{provider.name} network error: {exc}") from exc

    if resp.status_code == 429:
        raise RateLimitError(f"{provider.name} rate limited (429)")
    if resp.status_code == 401:
        mark_invalid(provider.name)
        raise ProviderError(f"{provider.name} key rejected (401)")
    if not resp.ok:
        raise ProviderError(
            f"{provider.name} HTTP {resp.status_code}: {resp.text[:200]}"
        )

    body = resp.json()
    raw = body["choices"][0]["message"]["content"]
    if isinstance(raw, list):
        return "".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in raw
        ).strip()
    return str(raw).strip()


def _call_xai_adapter(
    provider: Provider,
    messages: list[dict],
    **opts,
) -> str:
    """Execute via xai_sdk (web_search + x_search tools)."""
    try:
        from xai_sdk import Client as _XAIClient          # noqa: PLC0415
        from xai_sdk.chat import system as _xai_sys       # noqa: PLC0415
        from xai_sdk.chat import user as _xai_user        # noqa: PLC0415
        from xai_sdk.tools import web_search as _wsearch  # noqa: PLC0415
        from xai_sdk.tools import x_search as _xsearch    # noqa: PLC0415
    except ImportError as exc:
        raise ProviderError(
            "xai-sdk not installed. Run: pip install xai-sdk"
        ) from exc

    model = opts.pop("model", os.environ.get("INSIGHT_GROK_MODEL", "grok-4-1-fast-non-reasoning"))

    try:
        client = _XAIClient(api_key=provider.key())
        chat = client.chat.create(model=model, tools=[_wsearch(), _xsearch()])
        for msg in messages:
            if msg["role"] == "system":
                chat.append(_xai_sys(msg["content"]))
            elif msg["role"] == "user":
                chat.append(_xai_user(msg["content"]))
        result = str(chat.sample().content).strip()
    except Exception as exc:
        err = str(exc)
        if "429" in err:
            raise RateLimitError(f"{provider.name} rate limited: {exc}") from exc
        if "401" in err:
            mark_invalid(provider.name)
            raise ProviderError(f"{provider.name} key rejected: {exc}") from exc
        raise ProviderError(f"{provider.name} error: {exc}") from exc

    return result


def _dispatch_adapter(
    provider: Provider,
    messages: list[dict],
    **opts,
) -> tuple[str, str, bool]:
    """Route a call to the right adapter for *provider.adapter_type*.

    For Eden providers (is_eden=True), opts are transformed first:
    model mapping, option stripping, and native fallback injection.

    Returns (text, effective_model, substituted):
      - text:            response content from the adapter.
      - effective_model: the model identifier actually sent to the API.
      - substituted:     True only if the Eden adapter swapped the model
                         through EDEN_SUBSTITUTIONS (plain mapping is not
                         reported as a substitution).
    """
    substituted = False
    if provider.is_eden:
        opts, substituted = _prepare_eden_opts(opts)

    effective_model = opts.get("model", "")

    if provider.adapter_type == "openai":
        return _call_openai_adapter(provider, messages, **opts), effective_model, substituted
    if provider.adapter_type == "xai_sdk":
        return _call_xai_adapter(provider, messages, **opts), effective_model, substituted
    if provider.adapter_type == "mistral_ocr":
        raise ProviderError(
            "Mistral OCR uses the /v1/ocr endpoint — use ocr._extract_primary() directly."
        )
    if provider.adapter_type == "eden_ocr":
        raise ProviderError(
            "Eden OCR uses an async endpoint — use call_ocr_async() instead of call()."
        )
    raise ProviderError(f"Unknown adapter type: {provider.adapter_type!r}")


# == call() — retry with policy + cascade =====================================

# Direct-API cascade dispatch table: maps provider.name -> its fallback map.
# Eden providers are intentionally absent — they cascade server-side through
# the "fallbacks" payload field injected by _prepare_eden_opts().
_DIRECT_FALLBACK_MAPS: dict[str, dict[str, str]] = {
    "mistral_direct":    MISTRAL_FALLBACK_MAP,
    "xai_direct":        XAI_FALLBACK_MAP,
    "perplexity_direct": PERPLEXITY_FALLBACK_MAP,
}


def _advance_cascade(
    provider:            Provider,
    current_opts:        dict,
    per_provider_model:  dict[str, str],
    per_provider_strips: dict[str, set[str]],
    eden_live:           bool = False,
) -> bool:
    """Advance the per-provider cascade after a 429.

    Mutates *per_provider_model* / *per_provider_strips* in place to record
    the next model to try for this provider, and any options to strip on
    subsequent attempts.

    Resolution order inside the provider's fallback map:
      1. Compound key "<current-model>+<opt_name>" — takes priority when
         any incoming option matches; the option is added to the strip set.
      2. Simple key "<current-model>" — used when no compound key matches.

    Returns:
      True  — cascade advanced (or no-op because no map / no entry / Eden
              redundancy still live). The provider is still live; keep
              retrying it (possibly with the same model).
      False — cascade reached a terminal "" value. The provider is
              exhausted; the caller should mark it and stop choosing it.

    Direct-cascade suppression when Eden is live:
      When an Eden route is still available for this capability, we do NOT
      degrade the direct provider's model — 429s on direct usually mean an
      account-wide rate limit, so swapping to a different model on the same
      account rarely helps, while Eden uses a separate account + server-side
      fallback chain. The direct cascade is reserved for the Eden-absent
      case. Eden providers themselves always return True with no state
      change: their native "fallbacks" chain runs server-side.
    """
    if provider.is_eden:
        return True

    if eden_live:
        # Prefer Eden redundancy over direct-model degradation.
        return True

    fb_map = _DIRECT_FALLBACK_MAPS.get(provider.name)
    if fb_map is None:
        # Unknown direct provider — nothing to cascade, keep retrying same.
        return True

    cur_model = per_provider_model[provider.name]
    strips    = per_provider_strips[provider.name]

    # 1) Compound key takes priority: "<model>+<opt_name>".
    for opt_name in list(current_opts.keys()):
        if opt_name == "model" or opt_name in strips:
            continue
        compound = f"{cur_model}+{opt_name}"
        if compound in fb_map:
            nxt = fb_map[compound]
            if not nxt:
                return False
            per_provider_model[provider.name] = nxt
            strips.add(opt_name)
            return True

    # 2) Simple key.
    if cur_model not in fb_map:
        # Not in the cascade at all — keep retrying with the same model.
        return True

    nxt = fb_map[cur_model]
    if not nxt:
        return False  # terminal entry ("" value) — provider exhausted

    per_provider_model[provider.name] = nxt
    return True


def call(
    capability: str,
    messages:   list[dict],
    **opts,
) -> CallResult:
    """Execute *capability* with retry / fallback / cascade.

    Retry policies:
      pingpong — alternates between primary and secondary provider on 429.
      sticky   — all retries stay on the first available provider.

    Both policies: up to 6 attempts, backoff 2->4->8->15->30s.
    With a single provider, both behave identically (retry same provider).

    Non-429 errors (400, 401, 500, network) raise immediately — no retry.

    Cascade on 429 (Layer 1):
      For direct providers (mistral/xai/perplexity), each 429 advances the
      cascade via the provider's *_FALLBACK_MAP. The next retry uses the
      fallback model; compound keys ("model+option") also strip options
      that the fallback model does not support (e.g. reasoning_effort).
      Cascade state is tracked per-provider, so pingpong keeps independent
      progress on each side. Reaching a terminal "" marks the provider as
      exhausted; it is dropped from the live set.

      Eden providers do NOT cascade client-side — their "fallbacks" payload
      field handles fallback server-side (single HTTP call, zero extra
      latency).

    The caller passes canonical model names and all options (temperature,
    reasoning_effort, etc.). Eden translation is handled transparently by
    _dispatch_adapter().

    Returns a CallResult exposing the provider that answered, the
    effective_model actually sent, whether the Eden adapter substituted
    the model, and the attempt count.
    Raises ProviderError if all attempts fail.
    """
    spec = CAPABILITIES.get(capability)
    if spec is None:
        raise ProviderError(
            f"Unknown capability '{capability}'. "
            f"Known: {', '.join(CAPABILITIES)}"
        )

    providers = resolve(capability)
    if not providers:
        raise ProviderError(
            f"No providers available for capability '{capability}'. "
            f"Check that the required API key(s) are set in .env."
        )

    requested_model = str(opts.get("model", ""))

    # Per-provider cascade state — mistral_direct and eden_mistral can each
    # advance their own chain independently in pingpong mode.
    per_provider_model:  dict[str, str]       = {p.name: requested_model for p in providers}
    per_provider_strips: dict[str, set[str]]  = {p.name: set()           for p in providers}
    exhausted:           set[str]             = set()

    last_exc: Exception = ProviderError("no attempts made")

    for attempt in range(_MAX_ATTEMPTS):
        live = [p for p in providers if p.name not in exhausted]
        if not live:
            break

        # Provider selection depends on policy.
        if spec.policy == "sticky":
            provider = live[0]
        else:
            provider = live[attempt % len(live)]

        # Build opts for this attempt: apply per-provider cascade model +
        # strips on top of the caller's original opts (original opts are
        # never mutated).
        this_opts = dict(opts)
        cur_model = per_provider_model[provider.name]
        if cur_model:
            this_opts["model"] = cur_model
        for strip_key in per_provider_strips[provider.name]:
            this_opts.pop(strip_key, None)

        try:
            text, effective_model, substituted = _dispatch_adapter(
                provider, messages, **this_opts
            )
            if attempt > 0:
                print(
                    f"  \u2713 {provider.display_name} answered after {attempt + 1} attempt(s).",
                    file=sys.stderr,
                )
            return CallResult(
                text            = text,
                provider        = provider,
                effective_model = effective_model,
                requested_model = requested_model,
                substituted     = substituted,
                attempts        = attempt + 1,
            )

        except RateLimitError as exc:
            last_exc = exc
            # Suppress direct cascade when Eden will actually be used as a
            # fallback in a subsequent attempt. That only happens under
            # pingpong: sticky never rotates off live[0], so an Eden route
            # sitting in the live list provides zero real redundancy.
            eden_redundancy_active = (
                spec.policy == "pingpong"
                and any(p.is_eden for p in providers if p.name not in exhausted)
            )
            still_live = _advance_cascade(
                provider, this_opts, per_provider_model, per_provider_strips,
                eden_live=eden_redundancy_active,
            )
            if not still_live:
                exhausted.add(provider.name)

            remaining = [p for p in providers if p.name not in exhausted]
            if attempt >= _MAX_ATTEMPTS - 1 or not remaining:
                continue  # loop will exit naturally on next iteration check

            wait = _BACKOFF_SECONDS[attempt]
            next_provider = (
                remaining[0] if spec.policy == "sticky"
                else remaining[(attempt + 1) % len(remaining)]
            )
            if next_provider is provider:
                next_model = per_provider_model[provider.name]
                model_note = f" (next model: {next_model})" if next_model and next_model != cur_model else ""
                print(
                    f"  \u23f3 {provider.display_name} rate-limited \u2014 "
                    f"retrying in {wait}s...{model_note}",
                    file=sys.stderr,
                )
            else:
                print(
                    f"  \u23f3 {provider.display_name} rate-limited \u2014 "
                    f"trying {next_provider.display_name} in {wait}s...",
                    file=sys.stderr,
                )
            time.sleep(wait)
        # Non-RateLimitError propagates immediately (no catch)

    raise ProviderError(
        f"All providers exhausted for '{capability}' after {_MAX_ATTEMPTS} attempts. "
        f"Last error: {last_exc}"
    )


# == call_ocr_async() — Eden AI async OCR =====================================

_OCR_POLL_URL = EDEN_OCR_URL  # same base: GET <base>/<job_id>
_OCR_JOB_TIMEOUT_DEFAULT = 120    # seconds until we give up polling
_OCR_POLL_INTERVAL_DEFAULT = 3.0  # seconds between poll attempts
_OCR_MODEL_ID = "ocr/ocr_async/mistral"


def call_ocr_async(
    image_b64: str,
    mime: str,
    *,
    timeout: int = _OCR_JOB_TIMEOUT_DEFAULT,
    poll_interval: float = _OCR_POLL_INTERVAL_DEFAULT,
) -> str:
    """Submit an image to Eden AI's async OCR endpoint and poll for the result.

    Flow:
      1. POST job to EDEN_OCR_URL with base64 image → response contains public_id.
      2. Poll GET EDEN_OCR_URL/<public_id> until status == "completed" (or timeout).
      3. Extract text from the completed job response.

    Args:
        image_b64:     Base64-encoded image data.
        mime:          MIME type string (e.g. "image/png", "image/jpeg").
        timeout:       Total seconds to wait before aborting.
        poll_interval: Seconds between poll requests.

    Returns the extracted text (may be empty string if the image contains none).

    Raises ProviderError if:
      - EDENAI_API_KEY is not set.
      - Job creation fails (non-2xx HTTP).
      - Job reports a failure status.
      - Polling times out.
    """
    provider = PROVIDERS.get("eden_ocr_mistral")
    if provider is None or not provider.has_key():
        raise ProviderError(
            "Eden OCR unavailable — set EDENAI_API_KEY to enable the fallback."
        )

    api_key = os.environ.get(provider.required_env_key, "")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # ── Step 1: create job ────────────────────────────────────────────────────
    payload = {
        "model": _OCR_MODEL_ID,
        "input": {
            "document": {
                "type": "image_url",
                "image_url": f"data:{mime};base64,{image_b64}",
            }
        },
        "show_original_response": False,
    }
    try:
        resp = requests.post(
            provider.endpoint,
            headers=headers,
            json=payload,
            timeout=min(timeout, 30),
        )
        resp.raise_for_status()
        job_id: str = resp.json().get("public_id", "")
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else 0
        raise ProviderError(f"Eden OCR job creation failed (HTTP {code})") from exc
    except requests.RequestException as exc:
        raise ProviderError(f"Eden OCR network error during job creation: {exc}") from exc

    if not job_id:
        raise ProviderError("Eden OCR: no public_id returned — cannot poll.")

    print(f"  ⏳  Eden OCR job submitted ({job_id[:16]}…) — polling…", file=sys.stderr)

    # ── Step 2: poll until completed ─────────────────────────────────────────
    poll_url = f"{_OCR_POLL_URL}/{job_id}"
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        time.sleep(poll_interval)
        try:
            poll_resp = requests.get(poll_url, headers=headers, timeout=15)
            poll_resp.raise_for_status()
            data = poll_resp.json()
        except requests.RequestException as exc:
            raise ProviderError(f"Eden OCR poll error: {exc}") from exc

        status = data.get("status", "")

        if status == "completed":
            return _extract_eden_ocr_text(data)

        if status in ("failed", "error"):
            detail = data.get("error", status)
            raise ProviderError(f"Eden OCR job failed: {detail}")

        # "pending" / "processing" — keep polling

    raise ProviderError(
        f"Eden OCR job {job_id[:16]}… timed out after {timeout}s."
    )


def _extract_eden_ocr_text(data: dict) -> str:
    """Parse text from a completed Eden OCR job response.

    Eden AI may return the result in several shapes depending on the model
    version.  We try each in turn and return the first non-empty text found.
    """
    # Shape A: data.output[0].prediction.pages[].markdown  (observed in v3)
    output = data.get("output") or []
    if isinstance(output, list) and output:
        prediction = output[0].get("prediction", {}) if isinstance(output[0], dict) else {}
        pages = prediction.get("pages", [])
        if pages:
            text = "\n\n".join(
                p.get("markdown", "") or p.get("text", "")
                for p in pages
                if isinstance(p, dict)
            ).strip()
            if text:
                return text
        # Shape B: prediction.text
        text = prediction.get("text", "")
        if text:
            return text.strip()

    # Shape C: data.result.pages[].markdown
    result = data.get("result", {})
    if isinstance(result, dict):
        pages = result.get("pages", [])
        if pages:
            text = "\n\n".join(
                p.get("markdown", "") or p.get("text", "")
                for p in pages
                if isinstance(p, dict)
            ).strip()
            if text:
                return text
        text = result.get("text", "")
        if text:
            return text.strip()

    # Shape D: top-level text
    return data.get("text", "").strip()


# == audit() ==================================================================

def audit(validate: bool = False) -> None:
    """Print a human-readable capability / provider status table.

    If *validate* is True, force re-ping all configured providers and update
    the cache before printing.
    """
    print()
    print("VoxRefiner \u2014 Provider audit")
    print()
    print("  API keys")
    print("  \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500")

    # Deduplicate: one line per unique required_env_key
    seen_keys: set[str] = set()
    for p in PROVIDERS.values():
        if p.required_env_key in seen_keys:
            continue
        seen_keys.add(p.required_env_key)

        if not p.has_key():
            print(f"  \u2717  {p.display_name:<28} ({p.required_env_key} not set)")
            continue

        if validate:
            valid = is_key_validated(p.name, force=True)
        else:
            valid = p.has_key()  # key present = provisionally OK, not pinged

        status = "\u2713" if valid else "\u2717"
        suffix = ""
        if not validate:
            suffix = " (not tested \u2014 run --validate to ping)"
        print(f"  {status}  {p.display_name:<28} ({p.required_env_key}){suffix}")

    print()
    print("  Capabilities")
    print("  \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500")

    for cap, spec in CAPABILITIES.items():
        available = resolve(cap)
        policy_tag = f"[{spec.policy}]"
        if available:
            route = " \u2192 ".join(p.display_name for p in available)
            print(f"  \u2713  {cap:<18} {route}  {policy_tag}")
        else:
            # Show what key would unlock it
            first = PROVIDERS.get(spec.providers[0])
            hint = f" (requires {first.required_env_key})" if first else ""
            print(f"  \u2717  {cap:<18}{hint}  {policy_tag}")

    print()


# == CLI ======================================================================

def _cli_main() -> None:
    parser = argparse.ArgumentParser(
        description="VoxRefiner provider audit and key validation utility."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--audit",
        action="store_true",
        help="Print capability status table (keys not pinged).",
    )
    group.add_argument(
        "--validate",
        action="store_true",
        help="Force re-validate all configured keys (pings each provider).",
    )
    group.add_argument(
        "--available",
        metavar="CAPABILITY",
        help="Exit 0 if capability is available, 1 if not.",
    )
    args = parser.parse_args()

    if args.audit:
        audit(validate=False)

    elif args.validate:
        print("Re-validating all configured API keys...", file=sys.stderr)
        audit(validate=True)

    elif args.available:
        sys.exit(0 if is_available(args.available) else 1)


if __name__ == "__main__":
    _cli_main()

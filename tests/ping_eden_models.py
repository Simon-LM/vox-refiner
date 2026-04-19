#!/usr/bin/env python3
"""Ping every Eden AI model we care about and report availability.

Standalone utility — NOT part of the pytest suite. Hits the real Eden AI API
and requires EDENAI_API_KEY in the environment (or in .env).

Two probe types are covered:
  - LLM chat models  : POST /v3/llm/chat/completions with max_tokens=1
  - OCR async        : POST /v3/universal-ai/async (job creation only — does not
                       wait for completion, just confirms the endpoint accepts the key)

Usage:
    .venv/bin/python tests/ping_eden_models.py
    .venv/bin/python tests/ping_eden_models.py --only ovhcloud
    .venv/bin/python tests/ping_eden_models.py --only ocr
    .venv/bin/python tests/ping_eden_models.py --timeout 30

Exit code 0 if every probed model responded, 1 otherwise.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import requests

EDEN_CHAT_URL = "https://api.edenai.run/v3/llm/chat/completions"
EDEN_OCR_URL  = "https://api.edenai.run/v3/universal-ai/async"

# Keep this catalog aligned with docs/eden-ai-models.md and with the
# EDEN_FALLBACK_CHAINS table in src/providers.py — every key AND every
# fallback value must be probeable here so we can detect drift early.
MODELS: list[str] = [
    # xAI — Grok 4.1 (newer endpoints, reached via "-latest" suffix on Eden)
    "xai/grok-4-1-fast",
    "xai/grok-4-1-fast-reasoning",
    "xai/grok-4-1-fast-non-reasoning",
    "xai/grok-4-1-fast-non-reasoning-latest",
    "xai/grok-4-1-fast-reasoning-latest",
    # xAI — Grok 4.20 (newest, Eden uses "beta-" prefix; direct xAI API does not)
    "xai/grok-4.20-beta-0309-non-reasoning",
    "xai/grok-4.20-beta-0309-reasoning",
    # xAI — Grok 4 (legacy / fallback targets; different endpoints from 4.1)
    "xai/grok-4",
    "xai/grok-4-latest",
    "xai/grok-4-fast-non-reasoning",
    "xai/grok-4-fast-reasoning",
    "xai/grok-3-latest",
    # Perplexity
    "perplexityai/sonar",
    "perplexityai/sonar-pro",
    "perplexityai/sonar-reasoning-pro",
    "perplexityai/sonar-deep-research",
    # Google
    "google/gemini-flash-latest",
    "google/gemini-pro-latest",
    # Mistral (via Eden — redundancy only)
    "mistral/mistral-small-latest",
    "mistral/mistral-medium-latest",
    "mistral/mistral-large-latest",
    "mistral/magistral-small-latest",
    "mistral/magistral-medium-latest",
    # Amazon Bedrock (includes fallback targets from EDEN_FALLBACK_CHAINS)
    "amazon/mistral.mistral-large-2402-v1:0",
    "amazon/mistral.mistral-large-3-675b-instruct",
    "amazon/mistral.magistral-small-2509",
    "amazon/qwen.qwen3-next-80b-a3b",
    # OVHcloud (sovereign, may drift — run --only ovhcloud before relying on these)
    "ovhcloud/Mistral-Small-3.2-24B-Instruct-2506",
    "ovhcloud/Mistral-7B-Instruct-v0.3",
    "ovhcloud/Mixtral-8x7B-Instruct-v0.1",
    "ovhcloud/Meta-Llama-3_3-70B-Instruct",
    "ovhcloud/Llama-3.1-8B-Instruct",
    "ovhcloud/Qwen2.5-Coder-32B-Instruct",
    "ovhcloud/DeepSeek-R1-Distill-Llama-70B",
    "ovhcloud/gpt-oss-120b",
    # OCR async (different endpoint — see docs/eden-ai-models.md § OCR endpoint)
    "ocr/ocr_async/mistral",
]


@dataclass
class Result:
    model: str
    ok: bool
    latency_ms: int
    detail: str


def load_env() -> None:
    """Minimal .env loader so the script runs without python-dotenv."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_OCR_MODEL_PREFIX = "ocr/"


def _is_ocr_model(model: str) -> bool:
    return model.startswith(_OCR_MODEL_PREFIX)


def ping(model: str, api_key: str, timeout: float) -> Result:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    start = time.monotonic()

    if _is_ocr_model(model):
        return _ping_ocr(model, headers, timeout, start)
    return _ping_chat(model, headers, timeout, start)


def _ping_chat(model: str, headers: dict, timeout: float, start: float) -> Result:
    """Ping an LLM chat model via /v3/llm/chat/completions."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 4,
        "temperature": 0,
    }
    try:
        r = requests.post(EDEN_CHAT_URL, json=payload, headers=headers, timeout=timeout)
    except requests.RequestException as e:
        return Result(model, False, int((time.monotonic() - start) * 1000), f"NETWORK: {e}")
    latency = int((time.monotonic() - start) * 1000)

    if r.status_code != 200:
        snippet = r.text.strip().replace("\n", " ")[:160]
        return Result(model, False, latency, f"HTTP {r.status_code}: {snippet}")

    try:
        data = r.json()
        content = data["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as e:
        return Result(model, False, latency, f"PARSE: {e}")

    preview = (content or "").strip().replace("\n", " ")[:40]
    return Result(model, True, latency, f'OK: "{preview}"')


def _ping_ocr(model: str, headers: dict, timeout: float, start: float) -> Result:
    """Ping the OCR async endpoint — creates a job and checks for a public_id.

    Does NOT poll for job completion; only verifies that the endpoint accepts
    the key and model identifier (HTTP 200/201/202 + public_id in response).
    """
    payload = {
        "model": model,
        "input": {},
        "show_original_response": False,
    }
    try:
        r = requests.post(EDEN_OCR_URL, json=payload, headers=headers, timeout=timeout)
    except requests.RequestException as e:
        return Result(model, False, int((time.monotonic() - start) * 1000), f"NETWORK: {e}")
    latency = int((time.monotonic() - start) * 1000)

    if r.status_code not in (200, 201, 202):
        snippet = r.text.strip().replace("\n", " ")[:160]
        return Result(model, False, latency, f"HTTP {r.status_code}: {snippet}")

    try:
        data = r.json()
        job_id = data.get("public_id", "")
    except (ValueError, KeyError, TypeError) as e:
        return Result(model, False, latency, f"PARSE: {e}")

    if not job_id:
        return Result(model, False, latency, "No public_id in response")

    return Result(model, True, latency, f'OK: job {job_id[:16]}…')


def filter_models(models: Iterable[str], only: str | None) -> list[str]:
    if not only:
        return list(models)
    # "ocr" is a special shorthand for the OCR async entry
    if only.lower() == "ocr":
        return [m for m in models if _is_ocr_model(m)]
    prefix = only.rstrip("/") + "/"
    return [m for m in models if m.startswith(prefix)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Ping Eden AI models.")
    parser.add_argument("--only", help="Filter by provider prefix (e.g. ovhcloud, xai)")
    parser.add_argument("--timeout", type=float, default=20.0, help="Per-model timeout in seconds")
    args = parser.parse_args()

    load_env()
    api_key = os.environ.get("EDENAI_API_KEY", "").strip()
    if not api_key:
        print("ERROR: EDENAI_API_KEY is not set (check .env or environment).", file=sys.stderr)
        return 2

    targets = filter_models(MODELS, args.only)
    if not targets:
        print(f"No models matched filter: {args.only!r}", file=sys.stderr)
        return 2

    print(f"Pinging {len(targets)} model(s) on Eden AI (timeout={args.timeout}s)\n")
    results: list[Result] = []
    for model in targets:
        res = ping(model, api_key, args.timeout)
        results.append(res)
        flag = "✓" if res.ok else "✗"
        print(f"  {flag} {model:<55} {res.latency_ms:>6} ms   {res.detail}")

    ok = sum(1 for r in results if r.ok)
    ko = len(results) - ok
    print(f"\nSummary: {ok} OK, {ko} FAIL, {len(results)} total")
    return 0 if ko == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

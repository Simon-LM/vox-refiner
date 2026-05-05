#!/usr/bin/env python3
"""Contextual transcription correction via Mistral Small.

Reads a raw transcription from stdin and a user-supplied context string
(technical terms, speaker names, topic keywords) as a CLI argument.
Returns a corrected transcription — fixing only clear recognition errors
without rephrasing or removing any content.

Usage:
    printf '%s' "$raw_text" | .venv/bin/python -m src.correct "$context"

Exit codes:
    0  — corrected text printed to stdout
    1  — empty input, missing API key, or all models failed
"""

import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv
from src.ui_py import error, process, warn

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from src.common import (  # noqa: E402
    SECURITY_BLOCK,
    call_model,
    compute_timing,
    effective_timeout,
)

_MODEL = os.environ.get("REFINE_MODEL_SHORT", "mistral-small-latest")
_MODEL_FALLBACK = "mistral-medium-latest"
_REQUEST_RETRIES = int(os.environ.get("CORRECT_RETRIES", "2"))

_SYSTEM_PROMPT = (
    "You are a transcription corrector.\n"
    "You will receive a raw transcription of an audio or video file and a context note "
    "describing the topic, technical terms, speaker names, or expected vocabulary.\n"
    "\n"
    "Your task: correct ONLY clear transcription errors — misrecognized words, wrong "
    "homophones, technical terms spelled incorrectly — using the context as a guide.\n"
    "\n"
    "Rules:\n"
    "- Do NOT rephrase, reorder, summarize, or remove any content.\n"
    "- Do NOT add punctuation beyond fixing obvious missing sentence-end punctuation.\n"
    "- If a word seems wrong but has no clear correction from the context, leave it as-is.\n"
    "- Output ONLY the corrected transcription, nothing else.\n"
    "\n"
    + SECURITY_BLOCK
)


def correct(raw_text: str, context: str) -> str:
    """Return *raw_text* with transcription errors corrected using *context*."""
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        raise RuntimeError("MISTRAL_API_KEY is not set. Check your .env file.")

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"<context>\n{context}\n</context>\n\n"
                f"<transcription>\n{raw_text}\n</transcription>"
            ),
        },
    ]

    word_count = len(raw_text.split())
    base_timeout, retry_delay = compute_timing(word_count)

    for model in (_MODEL, _MODEL_FALLBACK):
        try:
            timeout = effective_timeout(base_timeout, model)
            if model == _MODEL:
                process(
                    f"Correcting via {model} "
                    f"({word_count} words, timeout {timeout}s)..."
                )
            else:
                warn(f"{_MODEL} unavailable — switching to fallback: {model}")
            result = call_model(
                model, messages, api_key,
                timeout=timeout,
                retry_delay=retry_delay,
                retries=_REQUEST_RETRIES,
            )
            result = result.strip()
            # Strip <transcription> wrapper echoed by the model due to SECURITY_BLOCK
            if result.startswith("<transcription>"):
                result = result[len("<transcription>"):].lstrip("\n")
            if result.endswith("</transcription>"):
                result = result[: -len("</transcription>")].rstrip("\n")
            return result.strip()
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            if status in (429, 500, 502, 503):
                warn(f"{model} error ({status}) — switching model…")
                continue
            raise
        except requests.RequestException:
            warn(f"{model} unreachable, switching…")
            continue

    raise RuntimeError("All correction models failed.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: correct.py <context>", file=sys.stderr)
        sys.exit(1)
    context_arg = sys.argv[1]
    raw = sys.stdin.read().strip()
    if not raw:
        error("No input text received.")
        sys.exit(1)

    try:
        result = correct(raw, context_arg)
        print(result)
    except RuntimeError as exc:
        error(str(exc))
        sys.exit(1)

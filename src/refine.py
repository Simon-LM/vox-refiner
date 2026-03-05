#!/usr/bin/env python3
"""Step 2: Raw transcription → refined text via Mistral chat API.

Model routing:
  - Short text (< REFINE_MODEL_THRESHOLD words) → devstral-small-latest
  - Long text  (>= REFINE_MODEL_THRESHOLD words) → magistral-medium-latest

Each tier has a fallback model. If all models are exhausted, the raw
transcription is returned unchanged (graceful degradation).
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_API_URL = "https://api.mistral.ai/v1/chat/completions"
_CONTEXT_FILE = Path(__file__).resolve().parent.parent / "context.txt"

_THRESHOLD = int(os.environ.get("REFINE_MODEL_THRESHOLD", "80"))
_MODEL_SHORT = os.environ.get("REFINE_MODEL_SHORT", "devstral-small-latest")
_MODEL_SHORT_FALLBACK = os.environ.get("REFINE_MODEL_SHORT_FALLBACK", "mistral-small-latest")
_MODEL_LONG = os.environ.get("REFINE_MODEL_LONG", "magistral-medium-latest")
_MODEL_LONG_FALLBACK = os.environ.get("REFINE_MODEL_LONG_FALLBACK", "mistral-large-latest")

_SYSTEM_PROMPT_TEMPLATE = """\
You are an assistant specialised in correcting voice transcriptions.

The user will provide raw text produced by automatic speech recognition.
This text may contain: hesitations ("uh", "so", "I mean"), repetitions, broken sentence \
structures, and incorrectly transcribed words caused by homophones or unfamiliar technical vocabulary.

User context:
{context}

Your task:
1. Remove hesitations, filler words and unnecessary repetitions.
2. Correct likely transcription errors using the provided context.
3. Rewrite the text clearly and neatly.
4. Preserve EXACTLY the intent, meaning and logical structure of the original message.
5. Do not add information or interpret beyond what was said.
6. Reply ONLY with the corrected text, without any introduction or commentary.

The output language must match the input language.\
"""


def _load_context() -> str:
    if _CONTEXT_FILE.exists():
        return _CONTEXT_FILE.read_text(encoding="utf-8").strip()
    return "No context defined."


def _select_models(word_count: int) -> Tuple[str, str]:
    if word_count < _THRESHOLD:
        return _MODEL_SHORT, _MODEL_SHORT_FALLBACK
    return _MODEL_LONG, _MODEL_LONG_FALLBACK


def _call_model(model: str, messages: List[Dict[str, str]], api_key: str) -> str:
    response = requests.post(
        _API_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={"model": model, "messages": messages},  # type: ignore[arg-type]
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


def refine(raw_text: str) -> str:
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        raise RuntimeError("MISTRAL_API_KEY is not set. Check your .env file.")

    word_count = len(raw_text.split())
    primary, fallback = _select_models(word_count)

    system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(context=_load_context())
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": raw_text},
    ]

    for model in (primary, fallback):
        try:
            print(f"✨ Refining via {model} ({word_count} words)...", file=sys.stderr)
            result = _call_model(model, messages, api_key)
            if model != primary:
                print(f"⚠️  Primary model unavailable — fallback used: {model}", file=sys.stderr)
            return result
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "?"
            if status in (429, 500, 503):
                print(f"⚠️  {model} unavailable ({status}), switching...", file=sys.stderr)
                continue
            raise
        except requests.RequestException:
            print(f"⚠️  {model} unreachable, switching...", file=sys.stderr)
            continue

    print("⚠️  All models unavailable — returning raw transcription.", file=sys.stderr)
    return raw_text


if __name__ == "__main__":
    raw = sys.stdin.read().strip()
    if not raw:
        print("❌ No input text received.", file=sys.stderr)
        sys.exit(1)

    result = refine(raw)
    print(result)  # stdout only — captured by the shell script

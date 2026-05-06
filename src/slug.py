#!/usr/bin/env python3
"""Generate a short filename slug from a raw transcription.

Reads raw text from stdin, returns a 3-5 word hyphenated slug on stdout.
Used by Voice Translate to name saved audio files.

Language:
  - SAVE_SLUG_LANG=auto (default) — slug in the same language as the input text
  - SAVE_SLUG_LANG=en             — always generate slug in English

Model chain:
  1. mistral-small-latest  (no reasoning)
  2. mistral-medium-latest (fallback)
  3. "voice-translate"     (hardcoded fallback if both fail)
"""

import os
import re
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from src.ui_py import process, warn

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from src.common import call_model  # noqa: E402

_MODEL_PRIMARY      = "mistral-small-latest"
_MODEL_FALLBACK     = "mistral-medium-latest"
_DEFAULT_FALLBACK   = "voice-translate"
_TIMEOUT_ENABLED    = os.environ.get("ENABLE_TIMEOUT", "false").lower() in ("true", "1", "yes")
_TIMEOUT: Optional[int] = 5 if _TIMEOUT_ENABLED else None
_RETRY_DELAY    = 1.5


_FALLBACK_SLUG = _DEFAULT_FALLBACK  # may be overridden by CLI --fallback


def _build_prompt(text: str, lang: str) -> str:
    if lang == "en":
        lang_instruction = "The slug must be in English regardless of the input language."
    else:
        lang_instruction = "The slug must be in the same language as the input text."

    return (
        "Generate a filename slug for the following transcription.\n\n"
        "Rules:\n"
        "- 3 to 5 words, all lowercase, hyphen-separated\n"
        "- No punctuation, no accents, no special characters\n"
        "- Capture the main topic or action\n"
        f"- {lang_instruction}\n"
        "- Output ONLY the slug, nothing else — no explanation, no quotes\n\n"
        f"Transcription: {text[:400]}"
    )


def _clean_slug(raw: str) -> str:
    """Normalise the model output to a safe filename slug."""
    slug = raw.strip().lower()
    # Replace accented characters
    replacements = {
        "à": "a", "â": "a", "ä": "a", "é": "e", "è": "e", "ê": "e", "ë": "e",
        "î": "i", "ï": "i", "ô": "o", "ö": "o", "ù": "u", "û": "u", "ü": "u",
        "ç": "c", "ñ": "n",
    }
    for src, dst in replacements.items():
        slug = slug.replace(src, dst)
    # Keep only alphanumeric and hyphens
    slug = re.sub(r"[^a-z0-9\-]", "-", slug)
    # Collapse multiple hyphens
    slug = re.sub(r"-{2,}", "-", slug)
    slug = slug.strip("-")
    # Limit to 60 chars
    return slug[:60] if slug else _FALLBACK_SLUG


def generate_slug(text: str, lang: str = "auto") -> str:
    api_key = os.environ.get("MISTRAL_API_KEY", "")
    if not api_key:
        return _FALLBACK_SLUG

    prompt = _build_prompt(text, lang)
    messages = [{"role": "user", "content": prompt}]
    # No reasoning_effort — this is a simple formatting task
    model_params = {"temperature": 0.2, "max_tokens": 30}

    for model in (_MODEL_PRIMARY, _MODEL_FALLBACK):
        try:
            process(f"Generating slug via {model}...")
            raw = call_model(
                model,
                messages,
                api_key,
                timeout=_TIMEOUT,
                retry_delay=_RETRY_DELAY,
                retries=0,
                model_params=model_params,
            )
            slug = _clean_slug(raw)
            if slug and slug != _FALLBACK_SLUG:
                return slug
        except Exception as exc:  # noqa: BLE001
            warn(f"{model} slug failed: {exc}")

    return _FALLBACK_SLUG


def main() -> None:
    global _FALLBACK_SLUG
    import argparse  # noqa: PLC0415
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--fallback", default=None)
    args, _ = parser.parse_known_args()
    if args.fallback:
        _FALLBACK_SLUG = args.fallback

    text = sys.stdin.read().strip()
    if not text:
        print(_FALLBACK_SLUG)
        return
    lang = os.environ.get("SAVE_SLUG_LANG", "auto")
    print(generate_slug(text, lang))


if __name__ == "__main__":
    main()

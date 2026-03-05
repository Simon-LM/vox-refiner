#!/usr/bin/env python3
"""Step 1: Audio file → raw transcription via Mistral Voxtral API."""

import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_API_URL = "https://api.mistral.ai/v1/audio/transcriptions"
_MODEL = "voxtral-mini-latest"


def transcribe(audio_path: str) -> str:
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        raise RuntimeError("MISTRAL_API_KEY is not set. Check your .env file.")

    with open(audio_path, "rb") as f:
        audio_data = f.read()

    print(f"🎤 Audio read: {len(audio_data)} bytes.", file=sys.stderr)
    print("🔊 Transcribing via Mistral Voxtral...", file=sys.stderr)

    response = requests.post(
        _API_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        files={"file": (Path(audio_path).name, audio_data, "audio/mpeg")},
        data={"model": _MODEL},
        timeout=60,
    )
    response.raise_for_status()

    return response.json()["text"]


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: transcribe.py <audio_file>", file=sys.stderr)
        sys.exit(1)

    audio_file = sys.argv[1]

    if not Path(audio_file).exists():
        print(f"❌ File not found: {audio_file}", file=sys.stderr)
        sys.exit(1)

    result = transcribe(audio_file)
    print(result)  # stdout only — captured by the shell script

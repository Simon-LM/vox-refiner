#!/usr/bin/env python3
"""Voxtral TTS: convert text to speech using the speaker's voice.

Calls the Mistral audio.speech API with an optional voice sample for cloning.
"""

import base64
import os
import sys
import time
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_API_URL = "https://api.mistral.ai/v1/audio/speech"
_MODEL = os.environ.get("TTS_MODEL", "voxtral-mini-tts-2603")
_DEFAULT_VOICE_ID = os.environ.get("TTS_DEFAULT_VOICE_ID", "c69964a6-ab8b-4f8a-9465-ec0925096ec8")  # Paul - Neutral
_REQUEST_RETRIES = int(os.environ.get("TTS_REQUEST_RETRIES", "2"))
_RETRY_DELAY = 2.0

_TRANSIENT_HTTP_CODES = (429, 500, 502, 503)


def _encode_voice_sample(sample_path: str) -> str:
    """Read and base64-encode a voice sample file."""
    data = Path(sample_path).read_bytes()
    return base64.b64encode(data).decode("ascii")


def synthesize(
    text: str,
    output_path: str,
    *,
    voice_sample: Optional[str] = None,
    voice_format: str = "mp3",
    output_format: str = "mp3",
) -> None:
    """Call Voxtral TTS and write the result to output_path.

    Args:
        text: The text to convert to speech.
        output_path: Where to write the output audio file.
        voice_sample: Path to a voice sample for cloning (optional).
        voice_format: Format of the voice sample file.
        output_format: Desired output audio format.
    """
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        raise RuntimeError("MISTRAL_API_KEY is not set. Check your .env file.")

    # API requires voice_id (preset UUID) OR ref_audio (raw base64 for cloning).
    # Response is JSON {"audio_data": "<base64>"} — must decode to get audio bytes.
    base_payload = {
        "model": _MODEL,
        "input": text,
        "response_format": output_format,
    }

    ref_audio_b64: Optional[str] = None
    if voice_sample and Path(voice_sample).exists():
        ref_audio_b64 = _encode_voice_sample(voice_sample)

    # Estimate timeout: ~1s per 100 chars + base overhead
    timeout = max(10, len(text) // 100 + 15)

    # Try with voice cloning first, then fallback to preset voice.
    attempts = []
    if ref_audio_b64:
        attempts.append(("with voice cloning", {**base_payload, "ref_audio": ref_audio_b64}))
    attempts.append(("default voice", {**base_payload, "voice_id": _DEFAULT_VOICE_ID}))

    for label, payload in attempts:
        last_exc: Exception = RuntimeError("unreachable")
        for attempt in range(1 + _REQUEST_RETRIES):
            if attempt > 0:
                print(
                    f"\u23f3  TTS ({label}) — retry {attempt}/{_REQUEST_RETRIES} "
                    f"(waiting {_RETRY_DELAY:.0f}s)\u2026",
                    file=sys.stderr,
                )
                time.sleep(_RETRY_DELAY)
            try:
                response = requests.post(
                    _API_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=timeout,
                )
                response.raise_for_status()
                # Response is JSON: {"audio_data": "<base64-encoded audio>"}
                audio_b64 = response.json()["audio_data"]
                Path(output_path).write_bytes(base64.b64decode(audio_b64))
                return
            except requests.HTTPError as exc:
                code = exc.response.status_code if exc.response is not None else None
                if exc.response is not None:
                    print(
                        f"\u274c TTS API error {code} ({label}): {exc.response.text[:500]}",
                        file=sys.stderr,
                    )
                if code in _TRANSIENT_HTTP_CODES:
                    last_exc = exc
                    continue
                # Non-transient error (422, etc.) — skip to next attempt mode
                last_exc = exc
                break
            except requests.Timeout as exc:
                print(f"\u23f1\ufe0f  TTS timed out ({timeout}s) \u2014 will retry\u2026", file=sys.stderr)
                last_exc = exc
                continue
        else:
            # All retries exhausted for this mode — try next
            if len(attempts) > 1 and label != "default voice":
                print(
                    f"\u26a0\ufe0f  Voice cloning failed \u2014 falling back to default voice.",
                    file=sys.stderr,
                )
                continue
        # Non-transient error broke out of retry loop — try next mode
        if len(attempts) > 1 and label != "default voice":
            print(
                f"\u26a0\ufe0f  Voice cloning failed \u2014 falling back to default voice.",
                file=sys.stderr,
            )
            continue
        raise last_exc
    raise last_exc  # type: ignore[possibly-undefined]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            "Usage: tts.py <output_mp3> [voice_sample]\n"
            "       Text is read from stdin.\n"
            "       voice_sample is optional (enables voice cloning).",
            file=sys.stderr,
        )
        sys.exit(1)

    output_file = sys.argv[1]
    sample_file = sys.argv[2] if len(sys.argv) > 2 else None

    text = sys.stdin.read().strip()
    if not text:
        print("\u274c No input text received.", file=sys.stderr)
        sys.exit(1)

    voice_fmt = "mp3"
    if sample_file and sample_file.endswith(".wav"):
        voice_fmt = "wav"

    print(
        f"\U0001f50a Generating speech via {_MODEL} ({len(text)} chars)...",
        file=sys.stderr,
    )
    synthesize(
        text,
        output_file,
        voice_sample=sample_file,
        voice_format=voice_fmt,
    )
    print(f"\u2705 Audio saved to {output_file}", file=sys.stderr)

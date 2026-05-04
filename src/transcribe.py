#!/usr/bin/env python3
"""Step 1: Audio file → raw transcription via Mistral Voxtral API."""

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import List

import requests
from dotenv import load_dotenv
from src.ui_py import error, info, process, warn, debug

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_API_URL = "https://api.mistral.ai/v1/audio/transcriptions"
_MODEL = "voxtral-mini-latest"

_TRANSCRIBE_RETRIES = int(os.environ.get("TRANSCRIBE_REQUEST_RETRIES", "2"))
_TRANSCRIBE_RETRY_DELAY = 2.0
_VOXTRAL_MAX_FILE_SIZE = 19_500_000  # ~19.5 MB → split into chunks (~60 min at 64 kbps after ×1.5)
_CHUNK_TARGET_SECONDS = 1800  # ~30 min per chunk
_TRANSIENT_HTTP_CODES = (429, 500, 502, 503)


def _get_timeout(file_size: int) -> int:
    """Return HTTP timeout in seconds based on audio file size (MP3 @64kbps, speech ×1.5)."""
    if file_size < 300_000:    # < ~80 words
        return 3
    if file_size < 800_000:    # < ~240 words
        return 3
    if file_size < 1_500_000:  # < ~500 words
        return 5
    if file_size < 4_000_000:  # < ~10 min
        return 12
    if file_size < 8_000_000:  # < ~20 min
        return 20
    if file_size < 12_000_000: # < ~30 min
        return 30
    if file_size < 14_500_000: # < ~45 min
        return 42
    return 55                  # < ~60 min


def _format_diarized(segments: list) -> str:
    """Group consecutive same-speaker segments into labelled blocks.

    speaker_1 → [Speaker 1], speaker_2 → [Speaker 2], etc.
    """
    groups: List[tuple] = []
    current_speaker = None
    current_parts: List[str] = []

    for seg in segments:
        speaker = seg.get("speaker_id") or "speaker_0"
        text = seg.get("text", "").strip()
        if not text:
            continue
        if speaker != current_speaker:
            if current_parts:
                groups.append((current_speaker, " ".join(current_parts)))
            current_speaker = speaker
            current_parts = [text]
        else:
            current_parts.append(text)

    if current_parts:
        groups.append((current_speaker, " ".join(current_parts)))

    blocks = []
    for speaker_id, text in groups:
        label = speaker_id.replace("_", " ").title()  # "speaker_1" → "Speaker 1"
        blocks.append(f"[{label}]\n{text}")

    return "\n\n".join(blocks)


def _transcribe_single(audio_path: str, api_key: str, diarize: bool = False) -> str:
    """Transcribe one audio file via Voxtral, retrying on transient errors."""
    file_size = Path(audio_path).stat().st_size
    timeout = _get_timeout(file_size)

    with open(audio_path, "rb") as f:
        audio_data = f.read()

    last_exc: Exception = RuntimeError("unreachable")
    for attempt in range(1 + _TRANSCRIBE_RETRIES):
        if attempt > 0:
            info(
                f"Voxtral — retry {attempt}/{_TRANSCRIBE_RETRIES} (waiting {_TRANSCRIBE_RETRY_DELAY:.0f}s)…"
            )
            time.sleep(_TRANSCRIBE_RETRY_DELAY)
        try:
            if diarize:
                # Diarization requires timestamp_granularities=segment.
                # Use list-of-tuples to pass repeated multipart fields alongside the file.
                multipart = [
                    ("model", (None, _MODEL)),
                    ("diarize", (None, "true")),
                    ("timestamp_granularities", (None, "segment")),
                    ("file", (Path(audio_path).name, audio_data, "audio/mpeg")),
                ]
                response = requests.post(
                    _API_URL,
                    headers={"Authorization": f"Bearer {api_key}"},
                    files=multipart,
                    timeout=timeout,
                )
            else:
                response = requests.post(
                    _API_URL,
                    headers={"Authorization": f"Bearer {api_key}"},
                    files={"file": (Path(audio_path).name, audio_data, "audio/mpeg")},
                    data={"model": _MODEL},
                    timeout=timeout,
                )
            response.raise_for_status()
            body = response.json()

            if diarize:
                segments = body.get("segments") or []
                if segments:
                    return _format_diarized(segments)
                # Fallback: segments empty (shouldn't happen) — use flat text
                text = body.get("text", "")
                return text

            text = body.get("text")
            if not isinstance(text, str):
                raise RuntimeError(
                    f"Unexpected Voxtral response (missing 'text'): {body}"
                )
            return text
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else None
            if code in _TRANSIENT_HTTP_CODES:
                if code == 429:
                    warn("Voxtral rate limit (429) — will retry…")
                else:
                    warn(f"Voxtral server error ({code}) — will retry…")
                last_exc = exc
                continue
            raise  # 401, 403, 404 — don't retry
        except requests.Timeout as exc:
            warn(f"Voxtral timed out ({timeout}s) — will retry…")
            last_exc = exc
            continue
    raise last_exc


def _get_audio_duration(audio_path: str) -> float:
    """Return audio duration in seconds using ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(
            f"ffprobe failed on {audio_path!r}: {result.stderr.strip()}"
        )
    try:
        return float(result.stdout.strip())
    except ValueError as exc:
        raise RuntimeError(
            f"ffprobe returned invalid duration: {result.stdout.strip()!r}"
        ) from exc


def _detect_silences(audio_path: str) -> List[float]:
    """Return list of silence start timestamps (seconds)."""
    result = subprocess.run(
        ["ffmpeg", "-i", audio_path,
         "-af", "silencedetect=noise=-35dB:d=0.5",
         "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(
            f"  ⚠️  ffmpeg silencedetect failed — will use hard cuts: "
            f"{result.stderr.strip()[-200:]}",
            file=sys.stderr,
        )
        return []
    silences = []
    for line in result.stderr.splitlines():
        if "silence_start:" in line:
            try:
                t = float(line.split("silence_start:")[1].strip())
                silences.append(t)
            except ValueError:
                pass
    return silences


def _split_audio(audio_path: str) -> List[str]:
    """Split audio into ~30 min chunks, cutting near silence boundaries."""
    duration = _get_audio_duration(audio_path)
    if duration <= _CHUNK_TARGET_SECONDS:
        return [audio_path]

    silences = _detect_silences(audio_path)
    split_points = [0.0]
    target = float(_CHUNK_TARGET_SECONDS)
    while target < duration:
        # Find nearest silence within ±2 min of the target boundary
        near = [s for s in silences if abs(s - target) < 120]
        if near:
            split_points.append(min(near, key=lambda s: abs(s - target)))
        else:
            split_points.append(target)  # hard cut if no silence found nearby
        target += _CHUNK_TARGET_SECONDS
    split_points.append(duration)

    base = Path(audio_path).stem
    tmp_dir = Path(audio_path).parent
    chunks = []
    for i in range(len(split_points) - 1):
        start = split_points[i]
        end = split_points[i + 1]
        chunk_path = str(tmp_dir / f"{base}_chunk_{i:03d}.mp3")
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", audio_path,
             "-ss", str(start), "-to", str(end),
             "-c", "copy", chunk_path],
            capture_output=True,
        )
        if proc.returncode != 0:
            warn(
                f"ffmpeg failed creating chunk {i + 1}: "
                f"{proc.stderr.decode(errors='replace').strip()[-200:]}"
            )
        chunks.append(chunk_path)
        info(f"Chunk {i + 1}/{len(split_points) - 1}: {start:.0f}s–{end:.0f}s")

    return chunks


def transcribe(audio_path: str, diarize: bool = False) -> str:
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        raise RuntimeError("MISTRAL_API_KEY is not set. Check your .env file.")

    file_size = Path(audio_path).stat().st_size
    debug(f"Audio read: {file_size} bytes.")

    if file_size >= _VOXTRAL_MAX_FILE_SIZE:
        process("Large file (> ~60 min) — splitting into ~30 min chunks…")
        chunks = _split_audio(audio_path)
        texts = []
        for i, chunk in enumerate(chunks, 1):
            process(f"Transcribing chunk {i}/{len(chunks)} via Voxtral…")
            texts.append(_transcribe_single(chunk, api_key, diarize=diarize))
            if chunk != audio_path:
                try:
                    Path(chunk).unlink()
                except OSError:
                    pass
        sep = "\n\n---\n\n" if diarize else " "
        return sep.join(texts)

    process("Transcribing via Mistral Voxtral...")
    return _transcribe_single(audio_path, api_key, diarize=diarize)


if __name__ == "__main__":
    diarize = "--diarize" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--diarize"]

    if len(args) != 1:
        print("Usage: transcribe.py <audio_file> [--diarize]", file=sys.stderr)
        sys.exit(1)

    audio_file = args[0]

    if not Path(audio_file).exists():
        error(f"File not found: {audio_file}")
        sys.exit(1)

    result = transcribe(audio_file, diarize=diarize)
    print(result)  # stdout only — captured by the shell script

#!/usr/bin/env python3
"""Subtitle generation (SRT) from Voxtral timestamped segments.

Two modes:
  standard      : timestamp_granularities=segment only → clean SRT
  accessibility : + diarize=true → SRT with speaker labels

CLI usage:
  # Standard SRT
  python -m src.subtitles <audio_file>

  # Accessibility step 1 — transcribe + save segments, print speaker_ids
  python -m src.subtitles <audio_file> --diarize --dump-segments <path.json>

  # Accessibility step 2 — generate SRT from cached segments (no API call)
  python -m src.subtitles --from-segments <path.json> --speaker-map "speaker_0=Marie,speaker_1=Jean"
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

import requests
from dotenv import load_dotenv
from src.ui_py import error, process, warn

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_API_URL = "https://api.mistral.ai/v1/audio/transcriptions"
_MODEL = "voxtral-mini-latest"
_MAX_SEGMENT_DURATION = 7.0  # seconds — split longer segments for readability


def _seconds_to_srt(t: float) -> str:
    """Convert float seconds to SRT timecode HH:MM:SS,mmm."""
    t = max(0.0, t)
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int(round((t % 1) * 1000))
    if ms >= 1000:
        ms = 999
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _split_long_segment(seg: dict, max_dur: float = _MAX_SEGMENT_DURATION) -> List[dict]:
    """Split a segment longer than max_dur into shorter ones, distributing timestamps by word count."""
    duration = seg["end"] - seg["start"]
    if duration <= max_dur:
        return [seg]

    words = seg["text"].strip().split()
    if len(words) <= 1:
        return [seg]

    n_chunks = max(2, int(duration / max_dur) + 1)
    chunk_size = max(1, len(words) // n_chunks)

    # Build word chunks
    chunks: List[List[str]] = []
    for i in range(0, len(words), chunk_size):
        chunks.append(words[i : i + chunk_size])

    # Distribute timestamps proportionally
    total_words = len(words)
    result = []
    cur_start = seg["start"]
    for chunk in chunks:
        chunk_dur = duration * len(chunk) / total_words
        result.append({
            "text": " ".join(chunk),
            "start": cur_start,
            "end": cur_start + chunk_dur,
            "speaker_id": seg.get("speaker_id"),
        })
        cur_start += chunk_dur
    return result


def _prepare_segments(segments: List[dict]) -> List[dict]:
    """Split all long segments and return a flat list."""
    out = []
    for seg in segments:
        out.extend(_split_long_segment(seg))
    return out


def format_srt(segments: List[dict], speaker_names: Optional[Dict[str, str]] = None) -> str:
    """Generate SRT file content from a list of segments."""
    blocks = []
    prev_speaker = None
    for i, seg in enumerate(segments, 1):
        text = seg["text"].strip()
        if not text:
            continue
        if speaker_names and seg.get("speaker_id"):
            sid = seg["speaker_id"]
            if sid != prev_speaker:
                name = speaker_names.get(sid, sid)
                text = f"[{name}]: {text}"
            prev_speaker = sid
        tc_start = _seconds_to_srt(seg["start"])
        tc_end = _seconds_to_srt(seg["end"])
        blocks.append(f"{i}\n{tc_start} --> {tc_end}\n{text}\n")
    return "\n".join(blocks)


def get_unique_speakers(segments: List[dict]) -> List[str]:
    """Return ordered list of unique non-null speaker_ids."""
    seen: List[str] = []
    for seg in segments:
        sid = seg.get("speaker_id")
        if sid and sid not in seen:
            seen.append(sid)
    return seen


def format_dialogue_preview(segments: List[dict]) -> str:
    """Return a readable dialogue transcript without timecodes, grouped by speaker."""
    lines = []
    prev_speaker = None
    for seg in segments:
        text = seg["text"].strip()
        if not text:
            continue
        sid = seg.get("speaker_id")
        if sid and sid != prev_speaker:
            if lines:
                lines.append("")
            lines.append(f"{sid}:")
            prev_speaker = sid
        lines.append(f"  {text}")
    return "\n".join(lines).strip()


def suggest_speaker_names(segments: List[dict], api_key: str) -> Dict[str, str]:
    """Ask Mistral to propose a name or role for each detected speaker.
    Returns {speaker_id: proposed_name}."""
    speakers = get_unique_speakers(segments)
    if not speakers:
        return {}

    preview = format_dialogue_preview(segments)[:2000]
    speaker_list_str = "\n".join(f"- {s}" for s in speakers)
    prompt = (
        f"Transcript excerpt:\n\n{preview}\n\n"
        f"Detected speakers:\n{speaker_list_str}\n\n"
        "Based on the content, propose a concise name or role for each speaker "
        "(a first name if identifiable, or a role such as 'Hôte'/'Invité' for French, "
        "'Host'/'Guest' for English, 'Moderador'/'Invitado' for Spanish, etc.).\n"
        "Use the same language as the transcript for any role label.\n"
        "Reply with exactly one line per speaker, format: speaker_id=ProposedName\n"
        "No other text, no explanation."
    )

    model = os.environ.get("REFINE_MODEL_SHORT", "mistral-small-latest")
    process("Analyzing speakers with AI...")
    response = requests.post(
        "https://api.mistral.ai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 200,
        },
        timeout=30,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"].strip()

    result: Dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if "=" in line:
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if k in speakers and v:
                result[k] = v
    return result


def transcribe_segments(audio_path: str, api_key: str, diarize: bool = False) -> List[dict]:
    """Call Voxtral with timestamp_granularities=segment, return raw segments list."""
    label = "with diarization " if diarize else ""
    process(f"Transcribing {label}via Voxtral...")

    audio_data = Path(audio_path).read_bytes()
    multipart = [
        ("model", (None, _MODEL)),
        ("timestamp_granularities", (None, "segment")),
    ]
    if diarize:
        multipart.append(("diarize", (None, "true")))
    multipart.append(("file", (Path(audio_path).name, audio_data, "audio/mpeg")))

    response = requests.post(
        _API_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        files=multipart,
        timeout=120,
    )
    response.raise_for_status()
    body = response.json()
    segments = body.get("segments") or []
    if not segments:
        raise RuntimeError("Voxtral returned no segments.")
    return segments


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("audio_file", nargs="?")
    parser.add_argument("--diarize", action="store_true")
    parser.add_argument("--dump-segments", metavar="PATH")
    parser.add_argument("--from-segments", metavar="PATH")
    parser.add_argument("--speaker-map", metavar="MAP", default="")
    parser.add_argument("--preview", metavar="PATH")
    parser.add_argument("--suggest-names", metavar="PATH")
    args = parser.parse_args()

    # --preview: print dialogue without timecodes, no API call
    if args.preview:
        segs = json.loads(Path(args.preview).read_text())
        print(format_dialogue_preview(segs))
        sys.exit(0)

    # --suggest-names: ask Mistral to propose names for each speaker_id
    if args.suggest_names:
        api_key = os.environ.get("MISTRAL_API_KEY")
        if not api_key:
            error("MISTRAL_API_KEY is not set.")
            sys.exit(1)
        segs = json.loads(Path(args.suggest_names).read_text())
        try:
            names = suggest_speaker_names(segs, api_key)
            for k, v in names.items():
                print(f"{k}={v}")
        except Exception as exc:
            warn(f"Name suggestion failed: {exc}")
        sys.exit(0)

    # Parse speaker map: "speaker_0=Marie,speaker_1=Jean"
    speaker_names: Dict[str, str] = {}
    if args.speaker_map:
        for pair in args.speaker_map.split(","):
            if "=" in pair:
                k, v = pair.split("=", 1)
                speaker_names[k.strip()] = v.strip()

    if args.from_segments:
        # No API call — load cached segments from JSON
        segments = json.loads(Path(args.from_segments).read_text())
    else:
        if not args.audio_file:
            error("Audio file required.")
            sys.exit(1)
        api_key = os.environ.get("MISTRAL_API_KEY")
        if not api_key:
            error("MISTRAL_API_KEY is not set.")
            sys.exit(1)
        try:
            segments = transcribe_segments(args.audio_file, api_key, diarize=args.diarize)
        except Exception as exc:
            error(str(exc))
            sys.exit(1)

    if args.dump_segments:
        # Save segments to JSON and print unique speaker_ids to stdout (one per line)
        Path(args.dump_segments).write_text(json.dumps(segments))
        for sid in get_unique_speakers(segments):
            print(sid)
        sys.exit(0)

    # Generate and print SRT
    segments = _prepare_segments(segments)
    print(format_srt(segments, speaker_names or None))

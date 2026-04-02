#!/usr/bin/env python3
"""Voxtral TTS: convert text to speech using the speaker's voice.

Calls the Mistral audio.speech API with an optional voice sample for cloning.
"""

import base64
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_API_URL = "https://api.mistral.ai/v1/audio/speech"
_MODEL = os.environ.get("TTS_MODEL", "voxtral-mini-tts-2603")

# Default voice when no language mapping or voice sample is available.
# Set TTS_DEFAULT_VOICE_ID="" in .env to use API auto-selection instead.
_DEFAULT_VOICE_ID = os.environ.get("TTS_DEFAULT_VOICE_ID", "c69964a6-ab8b-4f8a-9465-ec0925096ec8")  # Paul - Neutral (EN)

# Preset voice mapping by language code → voice_id (Mistral UUID).
# Only languages with voices currently available in the API are listed.
# French voices (all Marie): neutral, happy, sad, excited, curious, angry.
# English voices: Paul (en_us) + Oliver/Jane (en_gb) with emotion variants.
# Other languages: no Mistral preset voices available yet.
#   fr_marie_neutral 5a271406-039d-46fe-835b-fbbb00eaf08d  ← default fr
#   fr_marie_happy   49d024dd-981b-4462-bb17-74d381eb8fd7
#   fr_marie_sad     4adeb2c6-25a3-44bc-8100-5234dfc1193b
#   fr_marie_excited 2f62b1af-aea3-4079-9d10-7ca665ee7243
#   fr_marie_curious e0580ce5-e63c-4cbe-88c8-a983b80c5f1f
#   fr_marie_angry   a7c07cdc-1c35-4d87-a938-c610a654f600
#   en_paul_neutral  c69964a6-ab8b-4f8a-9465-ec0925096ec8  ← default en
#   gb_oliver_neutral e3596645-b1af-469e-b857-f18ddedc7652
#   gb_jane_neutral   82c99ee6-f932-423f-a4a3-d403c8914b8d
_LANG_VOICE_MAP: dict[str, str] = {
    "fr": "e0580ce5-e63c-4cbe-88c8-a983b80c5f1f",  # fr_marie_curious
    "en": "c69964a6-ab8b-4f8a-9465-ec0925096ec8",  # en_paul_neutral
    # Other languages not yet available — falls back to TTS_DEFAULT_VOICE_ID.
}

_REQUEST_RETRIES = int(os.environ.get("TTS_REQUEST_RETRIES", "2"))
_RETRY_DELAY = 2.0

_TRANSIENT_HTTP_CODES = (429, 500, 502, 503)

_CHUNK_MAX_CHARS = int(os.environ.get("TTS_CHUNK_SIZE", "800"))


_AI_CLEAN_SYSTEM = (
    "Tu es un assistant d'accessibilité pour malvoyants. Tu reçois un texte brut copié-collé depuis "
    "une page web (article de presse, blog, etc.) et tu dois le préparer pour une lecture vocale "
    "complète par un moteur TTS.\n\n"
    "OBJECTIF ABSOLU : que l'utilisateur entende TOUT le contenu éditorial, sans rien sauter.\n\n"
    "CONSERVER ET ADAPTER :\n"
    "- Titre principal (tel quel, en premier)\n"
    "- Sous-titres ou intertitres de sections (garder leur texte intégralement)\n"
    "- Corps de l'article dans son intégralité, tous les paragraphes sans exception\n"
    "- Citations et discours rapportés\n"
    "- Légendes de photos ou d'images : l'utilisateur peut voir les images mais a du mal à lire ; "
    "introduire chaque légende par 'Photo : ' suivi de son texte\n\n"
    "SUPPRIMER UNIQUEMENT (jamais le contenu éditorial) :\n"
    "- Boutons et éléments UI : 'Partager', 'Tweeter', 'Lire plus tard', compteurs de commentaires\n"
    "- Métadonnées techniques : auteur, date de publication, temps de lecture, crédit photo seul (ex: 'AFP')\n"
    "- Navigation : 'Lire aussi', 'Sur le même sujet', 'Newsletter', 'Accueil', fils d'Ariane\n"
    "- Annotations de liens : '(Nouvelle fenêtre)', '(new window)'\n"
    "- URLs brutes et adresses email\n\n"
    "FORMAT de sortie :\n"
    "- Texte brut uniquement, sans markdown (pas de **, *, #, listes à tirets)\n"
    "- Paragraphes séparés par une seule ligne vide\n"
    "- Ne pas ajouter de ponctuation artificielle entre les paragraphes\n"
    "- Pas de commentaire ni d'explication de ta part, uniquement le texte nettoyé"
)

_AI_CLEAN_MODEL = "mistral-small-latest"


def _clean_text(text: str) -> str:
    """Minimal pre-filter: remove only unreadable binary artifacts."""
    text = text.replace("\ufffc", "")  # Unicode object replacement char (icons/images)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def _strip_markdown(text: str) -> str:
    """Remove markdown formatting that would be read aloud by TTS."""
    text = re.sub(r"\*{1,3}([^*\n]+)\*{1,3}", r"\1", text)  # bold/italic
    text = re.sub(r"#{1,6}\s+", "", text)                    # headings
    text = re.sub(r"`+([^`\n]+)`+", r"\1", text)             # inline code
    return text


def _ai_clean_text(text: str) -> str:
    """Use Mistral to extract clean editorial content from web-selected text.

    Falls back to heuristic _clean_text() if the AI call fails.
    """
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        print("\u26a0\ufe0f  No MISTRAL_API_KEY — skipping AI cleaning.", file=sys.stderr)
        return _clean_text(text)

    print("\U0001f9f9 Cleaning text via AI...", file=sys.stderr)
    payload = {
        "model": _AI_CLEAN_MODEL,
        "messages": [
            {"role": "system", "content": _AI_CLEAN_SYSTEM},
            {"role": "user", "content": text},
        ],
        "max_tokens": 4096,
        "temperature": 0.0,
    }
    try:
        resp = requests.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()["choices"][0]["message"]["content"].strip()
        if result:
            print(f"\u2705 AI cleaning done ({len(result)} chars).", file=sys.stderr)
            return result
    except Exception as exc:
        print(f"\u26a0\ufe0f  AI cleaning failed ({exc}), using raw text.", file=sys.stderr)
    return _clean_text(text)


def _make_chunks(text: str, max_chars: int = _CHUNK_MAX_CHARS) -> list[str]:
    """Split text into chunks of at most max_chars, breaking on sentence boundaries."""
    # Normalize line endings: paragraph breaks and single newlines → space.
    text = re.sub(r"\n+", " ", text)
    text = re.sub(r" {2,}", " ", text).strip()

    # Split on sentence boundaries: after .!?… optionally followed by a closing quote
    sentences = re.split(r'(?<=[.!?…])\s+|(?<=[.!?…]["\u00BB\u201D)])\s+', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        return [text] if text else []
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        # Force-split sentences that exceed max_chars on their own
        while len(sentence) > max_chars:
            # Try to split on comma or semicolon
            split_at = -1
            for sep in [", ", "; ", " – ", " — "]:
                pos = sentence.rfind(sep, 0, max_chars)
                if pos > 0:
                    split_at = pos + len(sep)
                    break
            # Fallback: split at last space before max_chars
            if split_at <= 0:
                split_at = sentence.rfind(" ", 0, max_chars)
            if split_at <= 0:
                split_at = max_chars
            if current:
                chunks.append(current)
                current = ""
            chunks.append(sentence[:split_at].rstrip())
            sentence = sentence[split_at:].lstrip()
        if not current:
            current = sentence
        elif len(current) + 1 + len(sentence) <= max_chars:
            current += " " + sentence
        else:
            chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return chunks


def _resolve_voice_id() -> Optional[str]:
    """Resolve voice ID from environment (TTS_LANG → map, TTS_VOICE_ID, or default)."""
    tts_lang = os.environ.get("TTS_LANG", "")
    tts_voice_id_env = os.environ.get("TTS_VOICE_ID", None)
    if tts_lang and tts_lang in _LANG_VOICE_MAP:
        resolved: Optional[str] = _LANG_VOICE_MAP[tts_lang]
        print(f"\U0001f508 Voice: {tts_lang} preset ({resolved})", file=sys.stderr)
    elif tts_voice_id_env is not None:
        resolved = tts_voice_id_env or None
        label = resolved or _DEFAULT_VOICE_ID or "none"
        print(f"\U0001f508 Voice: {label}", file=sys.stderr)
    else:
        resolved = _DEFAULT_VOICE_ID or None
        print(f"\U0001f508 Voice: {resolved or 'none (will fail)'}", file=sys.stderr)
    return resolved


def _encode_voice_sample(sample_path: str) -> str:
    """Read and base64-encode a voice sample file."""
    data = Path(sample_path).read_bytes()
    return base64.b64encode(data).decode("ascii")


def synthesize(
    text: str,
    output_path: str,
    *,
    voice_sample: Optional[str] = None,
    voice_id: Optional[str] = _DEFAULT_VOICE_ID,
    voice_format: str = "mp3",
    output_format: str = "mp3",
) -> None:
    """Call Voxtral TTS and write the result to output_path.

    Args:
        text: The text to convert to speech.
        output_path: Where to write the output audio file.
        voice_sample: Path to a voice sample for cloning (optional).
        voice_id: Preset voice UUID. See GET /v1/audio/voices for available IDs.
        voice_format: Format of the voice sample file.
        output_format: Desired output audio format.
    """
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        raise RuntimeError("MISTRAL_API_KEY is not set. Check your .env file.")

    # API requires voice_id (preset) OR ref_audio (base64 for cloning).
    # Include language when known for correct pronunciation.
    # Response is JSON {"audio_data": "<base64>"} — must decode to get audio bytes.
    base_payload: dict = {
        "model": _MODEL,
        "input": text,
        "response_format": output_format,
    }

    ref_audio_b64: Optional[str] = None
    if voice_sample and Path(voice_sample).exists():
        ref_audio_b64 = _encode_voice_sample(voice_sample)

    # Estimate timeout: ~1s per 100 chars + base overhead
    timeout = max(10, len(text) // 100 + 15)

    # Try with voice cloning first, then fallback to preset/auto voice.
    attempts = []
    if ref_audio_b64:
        attempts.append(("with voice cloning", {**base_payload, "ref_audio": ref_audio_b64}))
    # The API requires either ref_audio or voice_id — auto mode is not supported.
    resolved_preset = voice_id or _DEFAULT_VOICE_ID
    if resolved_preset:
        attempts.append(("preset voice", {**base_payload, "voice_id": resolved_preset}))
    else:
        # No voice configured at all: this will fail — surface a clear error.
        attempts.append(("no voice", base_payload))

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
    # ── Chunked mode: --chunked <output_dir> ──────────────────────────────────
    # Splits text into sentence-boundary chunks, generates them with up to 2
    # parallel workers, and prints each output file path to stdout as soon as
    # it is ready — allowing the caller to start playback immediately.
    if len(sys.argv) >= 3 and sys.argv[1] == "--chunked":
        chunks_dir = sys.argv[2]
        Path(chunks_dir).mkdir(parents=True, exist_ok=True)

        text = sys.stdin.read().strip()
        if not text:
            print("\u274c No input text received.", file=sys.stderr)
            sys.exit(1)

        text = _strip_markdown(_ai_clean_text(text))
        if not text:
            print("\u274c Text is empty after cleaning.", file=sys.stderr)
            sys.exit(1)

        # Display cleaned text in terminal with blue background
        _BG = "\033[44m\033[97m"
        _RST = "\033[0m"
        print(f"{_BG}{'─' * 64}{_RST}", file=sys.stderr)
        print(f"{_BG}  Texte nettoyé — prêt pour la lecture vocale :{_RST}", file=sys.stderr)
        print(f"{_BG}{'─' * 64}{_RST}", file=sys.stderr)
        for _line in text.splitlines():
            print(f"{_BG}{_line}{_RST}", file=sys.stderr)
        print(f"{_BG}{'─' * 64}{_RST}", file=sys.stderr)

        resolved_voice_id = _resolve_voice_id()
        chunks = _make_chunks(text)
        total = len(chunks)
        print(
            f"\U0001f50a Generating {total} chunk(s) via {_MODEL} ({len(text)} chars)...",
            file=sys.stderr,
        )

        _CHUNK_MAX_ATTEMPTS = 5
        _CHUNK_RETRY_DELAYS = [2, 4, 8, 15]  # escalating delays between retries
        _MIN_AUDIO_BYTES = 1024  # valid mp3 should be > 1 KB

        def _gen_chunk(idx_chunk: tuple[int, str]) -> str:
            idx, chunk_text = idx_chunk
            out = str(Path(chunks_dir) / f"chunk_{idx:03d}.mp3")
            Path(chunks_dir, f"chunk_{idx:03d}.txt").write_text(chunk_text, encoding="utf-8")
            last_exc: Exception = RuntimeError("unknown")
            for attempt in range(_CHUNK_MAX_ATTEMPTS):
                try:
                    synthesize(chunk_text, out, voice_id=resolved_voice_id)
                    out_size = Path(out).stat().st_size if Path(out).exists() else 0
                    if out_size < _MIN_AUDIO_BYTES:
                        raise RuntimeError(f"audio trop petit ({out_size} octets)")
                    print(f"  \u2705 Passage {idx + 1}/{total} OK ({out_size:,} octets)", file=sys.stderr)
                    return out
                except Exception as exc:
                    last_exc = exc
                    delay = _CHUNK_RETRY_DELAYS[min(attempt, len(_CHUNK_RETRY_DELAYS) - 1)]
                    print(
                        f"  \u26a0\ufe0f  Passage {idx + 1}/{total} tentative {attempt + 1}/{_CHUNK_MAX_ATTEMPTS}"
                        f" \u00e9chou\u00e9e: {exc}",
                        file=sys.stderr,
                    )
                    if attempt < _CHUNK_MAX_ATTEMPTS - 1:
                        print(f"     Nouvelle tentative dans {delay}s\u2026", file=sys.stderr)
                        time.sleep(delay)
            raise last_exc

        with ThreadPoolExecutor(max_workers=3) as executor:
            # Submit with a slight stagger (0.5s between submissions) to avoid
            # hitting Mistral rate limits while keeping 2-3 chunks pre-generating.
            futures = []
            for i, chunk in enumerate(chunks):
                futures.append(executor.submit(_gen_chunk, (i, chunk)))
                if i < len(chunks) - 1:
                    time.sleep(0.5)
            for i, fut in enumerate(futures):
                try:
                    print(fut.result(), flush=True)
                except Exception as exc:
                    # Signal bash that this position failed — bash will offer retry
                    print(f"CHUNK_FAILED:{i}", flush=True)
                    print(f"\u274c Chunk {i + 1}/{total} definitively failed: {exc}", file=sys.stderr)

        sys.exit(0)

    # ── Single-file mode (default) ────────────────────────────────────────────
    if len(sys.argv) < 2:
        print(
            "Usage: tts.py <output_mp3> [voice_sample]\n"
            "       tts.py --chunked <output_dir>  (reads stdin, prints chunk paths)\n"
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

    resolved_voice_id = _resolve_voice_id()

    print(
        f"\U0001f50a Generating speech via {_MODEL} ({len(text)} chars)...",
        file=sys.stderr,
    )
    synthesize(
        text,
        output_file,
        voice_sample=sample_file,
        voice_format=voice_fmt,
        voice_id=resolved_voice_id,
    )
    print(f"\u2705 Audio saved to {output_file}", file=sys.stderr)

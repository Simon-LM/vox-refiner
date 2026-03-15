#!/bin/bash

cd "$(dirname "$0")"
SCRIPT_NAME="$(basename "$0")"
VENV_PYTHON="$(pwd)/.venv/bin/python"

if [ ! -x "$VENV_PYTHON" ]; then
    echo "❌ Missing .venv Python interpreter: $VENV_PYTHON"
    echo "Run ./install.sh first."
    exit 1
fi

# ─── Cleanup trap — remove temp files on exit (normal or error) ───────────────
_TMPFILES=()
_cleanup() {
    for f in "${_TMPFILES[@]:-}"; do
        rm -f "$f"
    done
}
trap _cleanup EXIT

# Save stderr so Python progress messages reach the terminal even when stdout
# is captured by $() substitution. Falls back gracefully in non-TTY contexts.
exec 3>&2

# ─── Mode ────────────────────────────────────────────────────────────────────────────────
RETRY_MODE=false
if [[ "${1:-}" == "--retry" || "${1:-}" == "-r" ]]; then
    RETRY_MODE=true
fi
# ─── Configuration ───────────────────────────────────────────────────────────

# Load .env if present (for AUDIO_TEMPO and other variables)
if [ -f .env ]; then
    # shellcheck disable=SC1091
    set -a; source .env; set +a
fi

# Speed multiplier applied to the recorded audio before transcription.
# Lower values reduce transcription errors (1.0 = no change, 1.5 = default).
AUDIO_TEMPO="${AUDIO_TEMPO:-1.5}"

# Validate AUDIO_TEMPO is a number in [0.5, 2.0]
if ! awk -v v="$AUDIO_TEMPO" 'BEGIN{exit !(v+0 >= 0.5 && v+0 <= 2.0)}'; then
    echo "❌ AUDIO_TEMPO must be between 0.5 and 2.0 (got: $AUDIO_TEMPO). Check your .env."
    exit 1
fi

# ─── Recording / Audio processing ───────────────────────────────────────────

if [ "$RETRY_MODE" = "false" ]; then
    # Always start from clean audio artifacts to avoid reusing corrupted files
    # after an interrupted/incorrect shutdown.
    rm -f local_audio.wav local_audio.mp3

    # Record into a temporary WAV and only promote it when sane.
    TMP_WAV=$(mktemp /tmp/local_audio_XXXXXX.wav)
    _TMPFILES+=("$TMP_WAV")

    echo "=== Audio recording ==="
    echo "Press Ctrl+C to stop..."

    setsid rec -c 1 -r 16000 "$TMP_WAV" &
    REC_PID=$!

    stop_recording() {
        echo ""
        echo "⏹️ Stopping recording..."
        kill -INT "$REC_PID" 2>/dev/null
        wait "$REC_PID" 2>/dev/null
        echo "✅ Recording stopped."
    }

    trap stop_recording SIGINT
    wait "$REC_PID"

    if [ ! -f "$TMP_WAV" ]; then
        echo "❌ No audio file recorded."
        rm -f "$TMP_WAV"
        exit 1
    fi

    # Defensive guard: corrupted WAVs can report absurd sizes and break ffmpeg.
    MAX_WAV_BYTES="${MAX_WAV_BYTES:-100000000}"  # 100 MB
    wav_size=$(stat -c%s "$TMP_WAV" 2>/dev/null || echo 0)
    if [ "$wav_size" -gt "$MAX_WAV_BYTES" ]; then
        echo "❌ Audio file is abnormally large (${wav_size} bytes)."
        rm -f "$TMP_WAV"
        exit 1
    fi

    mv "$TMP_WAV" local_audio.wav

    echo "⚡ Processing audio (silence removal + ×${AUDIO_TEMPO} speed + MP3)..."
    ffmpeg -y -i local_audio.wav \
        -af "silenceremove=detection=peak:start_periods=1:start_threshold=-35dB:stop_periods=-1:stop_duration=1.2:stop_threshold=-35dB,atempo=${AUDIO_TEMPO}" \
        -codec:a libmp3lame -b:a 64k local_audio.mp3 2>/dev/null

    if [ ! -f "local_audio.mp3" ]; then
        echo "❌ Audio conversion failed."
        exit 1
    fi
else
    echo "🔁 Retry mode — reusing existing local_audio.mp3..."
    if [ ! -f "local_audio.mp3" ]; then
        echo "❌ No local_audio.mp3 found. Run without --retry to record first."
        exit 1
    fi
fi

# ─── Step 1: Speech-to-text (Voxtral) ───────────────────────────────────────

raw_transcription=$("$VENV_PYTHON" src/transcribe.py local_audio.mp3 2>&3)

if [ -z "$raw_transcription" ]; then
    echo "❌ Empty transcription."
    exit 1
fi

# ─── Step 2: Text refinement (Mistral chat) ──────────────────────────────────

if [ "${ENABLE_REFINE:-true}" = "true" ]; then
    # In compare mode, use a temp file so the fallback result is shown AFTER
    # the primary, not during Python execution.
    if [ "${REFINE_COMPARE_MODELS:-false}" = "true" ]; then
        VOXTRAL_COMPARE_FILE=$(mktemp)
        _TMPFILES+=("$VOXTRAL_COMPARE_FILE")
        export VOXTRAL_COMPARE_FILE
        VOXTRAL_MODELS_FILE=$(mktemp)
        _TMPFILES+=("$VOXTRAL_MODELS_FILE")
        export VOXTRAL_MODELS_FILE
    fi
    refined_text=$(printf '%s' "$raw_transcription" | "$VENV_PYTHON" src/refine.py 2>&3)
    # Graceful degradation: if refinement fails, fall back to raw transcription
    final_text="${refined_text:-$raw_transcription}"
else
    final_text="$raw_transcription"
fi

# ─── Clipboard copy ──────────────────────────────────────────────────────────

if [ -n "$final_text" ]; then
    if printf '%s' "$final_text" | xclip -selection clipboard && \
       printf '%s' "$final_text" | xclip -selection primary; then
        echo ""
        echo "✅ Text copied to BOTH clipboards!"
        echo "   - Ctrl+V        → standard clipboard"
        echo "   - Middle-click  → primary selection"
        echo ""
    else
        echo ""
        echo "⚠️  Clipboard copy failed (is xclip installed and running under X11?)."
        echo ""
    fi
    if [ "${REFINE_COMPARE_MODELS:-false}" = "true" ] && [ "${ENABLE_REFINE:-true}" = "true" ]; then
        _primary_label="Primary"
        _fallback_label="Fallback"
        if [ -n "${VOXTRAL_MODELS_FILE:-}" ] && [ -s "$VOXTRAL_MODELS_FILE" ]; then
            _primary_label="Primary ($(sed -n '1p' "$VOXTRAL_MODELS_FILE"))"
            _fallback_label="Fallback ($(sed -n '2p' "$VOXTRAL_MODELS_FILE"))"
            rm -f "$VOXTRAL_MODELS_FILE"
        fi
        echo "📝 [1] Raw Voxtral:"
        echo "────────────────────────────────────────────────────────────────────"
        echo "$raw_transcription"
        echo "────────────────────────────────────────────────────────────────────"
        echo ""
        echo "📝 [2] ${_primary_label} — copied to clipboard:"
    else
        echo "📝 Result:"
    fi
    echo "────────────────────────────────────────────────────────────────────"
    echo "$final_text"
    echo "────────────────────────────────────────────────────────────────────"
    if [ -n "${VOXTRAL_COMPARE_FILE:-}" ] && [ -s "$VOXTRAL_COMPARE_FILE" ]; then
        echo ""
        echo "📝 [3] ${_fallback_label}:"
        echo "────────────────────────────────────────────────────────────────────"
        cat "$VOXTRAL_COMPARE_FILE"
        echo "────────────────────────────────────────────────────────────────────"
        rm -f "$VOXTRAL_COMPARE_FILE"
    fi
else
    echo "⚠️  Could not copy to clipboard."
fi

# ─── History context update (background, after clipboard) ─────────────────────
if [ "${ENABLE_HISTORY:-false}" = "true" ] && [ -n "$final_text" ]; then
    # Use raw_transcription word count (recording length) as the trigger,
    # not the refined output — the AI often compresses text significantly.
    word_count=$(printf '%s' "$raw_transcription" | wc -w)
    threshold="${REFINE_MODEL_THRESHOLD_SHORT:-90}"
    if [ "$word_count" -ge "$threshold" ]; then
        printf '%s' "$final_text" | "$VENV_PYTHON" src/refine.py --update-history 2>&3 &
        echo "🔄 History context update running in background..."
    fi
fi

# ─── Quick commands ───────────────────────────────────────────────────────────
echo ""
echo "💡 Retry:"
echo "   ./$SCRIPT_NAME --retry   → re-run on existing audio (skip recording)"
echo ""
echo "💡 Useful files:"
echo "   ${EDITOR:-nano} context.txt   → edit personal context"
echo "   ${EDITOR:-nano} .env          → edit settings"
if [ "${ENABLE_HISTORY:-false}" = "true" ]; then
    echo "   cat history.txt    → view history"
    echo "   ${EDITOR:-nano} history.txt   → edit history"
fi
echo ""
echo "💡 Updates:"
echo "   ./vox-refiner-update.sh --check   → check for updates"
echo "   ./vox-refiner-update.sh --apply   → apply updates"


#!/bin/bash

cd "$(dirname "$0")"

# ─── Configuration ───────────────────────────────────────────────────────────

# Load .env if present (for AUDIO_TEMPO and other variables)
if [ -f .env ]; then
    # shellcheck disable=SC1091
    set -a; source .env; set +a
fi

# Speed multiplier applied to the recorded audio before transcription.
# Lower values reduce transcription errors (1.0 = no change, 1.5 = default).
AUDIO_TEMPO="${AUDIO_TEMPO:-1.5}"

# ─── Recording ───────────────────────────────────────────────────────────────

echo "=== Audio recording ==="
echo "Press Ctrl+C to stop..."

setsid rec -c 1 -r 16000 local_audio.wav &
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

# ─── Audio processing ────────────────────────────────────────────────────────

if [ ! -f "local_audio.wav" ]; then
    echo "❌ No audio file recorded."
    exit 1
fi

echo "⚡ Adjusting audio speed (tempo ×${AUDIO_TEMPO})..."
sox local_audio.wav local_audio_fast.wav tempo "$AUDIO_TEMPO"

echo "✂️ Removing long silences..."
ffmpeg -y -i local_audio_fast.wav \
    -af silenceremove=stop_periods=-1:stop_duration=1.2:stop_threshold=-35dB \
    local_audio_trim.wav 2>/dev/null

echo "🎵 Converting to MP3..."
lame -b 64 local_audio_trim.wav local_audio.mp3 2>/dev/null

if [ ! -f "local_audio.mp3" ]; then
    echo "❌ Audio conversion failed."
    exit 1
fi

# ─── Step 1: Speech-to-text (Voxtral) ───────────────────────────────────────

raw_transcription=$(python3 src/transcribe.py local_audio.mp3 2>/dev/tty)

if [ -z "$raw_transcription" ]; then
    echo "❌ Empty transcription."
    exit 1
fi

# ─── Step 2: Text refinement (Mistral chat) ──────────────────────────────────

refined_text=$(printf '%s' "$raw_transcription" | python3 src/refine.py 2>/dev/tty)

# Graceful degradation: if refinement fails, fall back to raw transcription
final_text="${refined_text:-$raw_transcription}"

# ─── Clipboard copy ──────────────────────────────────────────────────────────

if [ -n "$final_text" ]; then
    printf '%s' "$final_text" | xclip -selection clipboard
    printf '%s' "$final_text" | xclip -selection primary
    echo ""
    echo "✅ Text copied to BOTH clipboards!"
    echo "   - Ctrl+V        → standard clipboard"
    echo "   - Middle-click  → primary selection"
    echo ""
    echo "📝 Result:"
    echo "────────────────────────────────────────────────────────────────────"
    echo "$final_text"
    echo "────────────────────────────────────────────────────────────────────"
else
    echo "⚠️  Could not copy to clipboard."
fi

# ─── History context update (background, after clipboard) ─────────────────────
if [ "${ENABLE_HISTORY:-false}" = "true" ] && [ -n "$final_text" ]; then
    word_count=$(printf '%s' "$final_text" | wc -w)
    threshold="${REFINE_MODEL_THRESHOLD_SHORT:-90}"
    if [ "$word_count" -ge "$threshold" ]; then
        printf '%s' "$final_text" | python3 src/refine.py --update-history 2>/dev/tty &
        echo "🔄 History context update running in background..."
    fi
fi

# ─── Quick commands ───────────────────────────────────────────────────────────
echo ""
echo "💡 Useful files:"
echo "   ${EDITOR:-nano} context.txt   → edit personal context"
echo "   ${EDITOR:-nano} .env          → edit settings"
if [ "${ENABLE_HISTORY:-false}" = "true" ]; then
    echo "   cat history.txt    → view history"
    echo "   ${EDITOR:-nano} history.txt   → edit history"
fi

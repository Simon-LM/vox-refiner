#!/bin/bash

cd "$(dirname "$0")"
SCRIPT_DIR="$(pwd)"
SCRIPT_NAME="$(basename "$0")"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"

# ─── Shared UI (colors + helpers) ────────────────────────────────────────────
# shellcheck disable=SC1091
source "$SCRIPT_DIR/src/ui.sh"

if [ ! -x "$VENV_PYTHON" ]; then
    echo "❌ Missing .venv Python interpreter: $VENV_PYTHON"
    echo "Run ./install.sh first."
    exit 1
fi

# All audio files go into recordings/stt/ — overwritten each run.
REC_DIR="$SCRIPT_DIR/recordings/stt"
mkdir -p "$REC_DIR"

# Save stderr so Python progress messages reach the terminal even when stdout
# is captured by $() substitution. Falls back gracefully in non-TTY contexts.
exec 3>&2

# ─── Mode ────────────────────────────────────────────────────────────────────────────────
RETRY_MODE=false
if [[ "${1:-}" == "--retry" || "${1:-}" == "-r" ]]; then
    RETRY_MODE=true
fi
# ─── Configuration ───────────────────────────────────────────────────────────

# Save caller-provided overrides before sourcing .env (menu passes these inline).
_PRE_OUTPUT_PROFILE="${OUTPUT_PROFILE:-}"
_PRE_OUTPUT_LANG="${OUTPUT_LANG:-}"
_PRE_COMPARE="${REFINE_COMPARE_MODELS:-}"

# Load .env if present (for AUDIO_TEMPO and other variables)
if [ -f .env ]; then
    # shellcheck disable=SC1091
    set -a; source .env; set +a
fi

# Restore caller-provided values so they take precedence over .env defaults.
[ -n "$_PRE_OUTPUT_PROFILE" ]  && { OUTPUT_PROFILE="$_PRE_OUTPUT_PROFILE";       export OUTPUT_PROFILE; }
[ -n "$_PRE_OUTPUT_LANG" ]     && { OUTPUT_LANG="$_PRE_OUTPUT_LANG";             export OUTPUT_LANG; }
[ -n "$_PRE_COMPARE" ]         && { REFINE_COMPARE_MODELS="$_PRE_COMPARE";       export REFINE_COMPARE_MODELS; }

# Speed multiplier applied to the recorded audio before transcription.
# Lower values reduce transcription errors (1.0 = no change, 1.5 = default).
AUDIO_TEMPO="${AUDIO_TEMPO:-1.5}"

# Validate AUDIO_TEMPO is a number in [1.0, 2.0]
if ! awk -v v="$AUDIO_TEMPO" 'BEGIN{exit !(v+0 >= 1.0 && v+0 <= 2.0)}'; then
    echo "❌ AUDIO_TEMPO must be between 1.0 and 2.0 (got: $AUDIO_TEMPO). Check your .env."
    exit 1
fi

# ─── Recording / Audio processing ───────────────────────────────────────────

if [ "$RETRY_MODE" = "false" ]; then
    # Always start from clean audio artifacts to avoid reusing corrupted files
    # after an interrupted/incorrect shutdown.
    rm -f "$REC_DIR/source.wav" "$REC_DIR/source.mp3"

    # ── B. Kill orphan VoxRefiner rec processes from previous interrupted runs ──
    # Pattern is specific enough to never match visio/webcam/other apps.
    pkill -f "rec.*source.wav" 2>/dev/null || true

    echo ""
    printf "  ${C_BGREEN}🎙  RECORDING${C_RESET}\n"
    echo ""
    printf "  ${C_BBLUE}Press Ctrl+C to stop.${C_RESET}\n"
    echo ""

    # ── C. No setsid — keep rec in the same session so PulseAudio/PipeWire
    #    grants microphone access when launched from a keyboard shortcut. ────────
    rec -c 1 -r 16000 "$REC_DIR/source.wav" &
    REC_PID=$!

    # ── A. Post-launch mic health check ──────────────────────────────────────────
    # Wait briefly then verify rec is still alive. When the mic is inaccessible,
    # rec dies immediately — no need to check file size (SoX buffers audio data
    # and the file stays header-only for ~2s even when recording normally).
    sleep 0.3
    if ! kill -0 "$REC_PID" 2>/dev/null; then
        _warn "Microphone inaccessible, attempting audio reset..."
        systemctl --user restart pipewire pipewire-pulse 2>/dev/null || true
        sleep 1
        rm -f "$REC_DIR/source.wav"
        rec -c 1 -r 16000 "$REC_DIR/source.wav" &
        REC_PID=$!
        sleep 0.3
        if ! kill -0 "$REC_PID" 2>/dev/null; then
            _error "Microphone still inaccessible after reset. Check your audio settings."
            exit 1
        fi
        _success "Microphone recovered."
    fi

    stop_recording() {
        echo ""
        printf "  ${C_DIM}⏹  Stopping recording...${C_RESET}\n"
        kill -INT "$REC_PID" 2>/dev/null
        wait "$REC_PID" 2>/dev/null
        echo "" 
        _success "Recording stopped."
    }

    trap stop_recording SIGINT
    wait "$REC_PID"

    if [ ! -f "$REC_DIR/source.wav" ]; then
        echo "❌ No audio file recorded."
        exit 1
    fi

    # Defensive guard: corrupted WAVs can report absurd sizes and break ffmpeg.
    MAX_WAV_BYTES="${MAX_WAV_BYTES:-100000000}"  # 100 MB
    wav_size=$(stat -c%s "$REC_DIR/source.wav" 2>/dev/null || echo 0)
    if [ "$wav_size" -gt "$MAX_WAV_BYTES" ]; then
        echo "❌ Audio file is abnormally large (${wav_size} bytes)."
        rm -f "$REC_DIR/source.wav"
        exit 1
    fi

    _process "Processing audio..."
    ffmpeg -y -i "$REC_DIR/source.wav" \
        -af "silenceremove=detection=peak:start_periods=1:start_threshold=-35dB:stop_periods=-1:stop_duration=1.2:stop_threshold=-35dB,atempo=${AUDIO_TEMPO}" \
        -codec:a libmp3lame -b:a 64k "$REC_DIR/source.mp3" 2>/dev/null

    if [ ! -f "$REC_DIR/source.mp3" ]; then
        echo "❌ Audio conversion failed."
        exit 1
    fi
else
    echo "🔁 Retry mode — reusing existing recordings/stt/source.mp3..."
    if [ ! -f "$REC_DIR/source.mp3" ]; then
        echo "❌ No source.mp3 found. Run without --retry to record first."
        exit 1
    fi
fi

# ─── Step 1: Speech-to-text (Voxtral) ───────────────────────────────────────

raw_transcription=$("$VENV_PYTHON" src/transcribe.py "$REC_DIR/source.mp3" 2>&3)

if [ -z "$raw_transcription" ]; then
    echo "❌ Empty transcription."
    exit 1
fi

# ─── Step 2: Text refinement (Mistral chat) ──────────────────────────────────

if [ "${ENABLE_REFINE:-true}" = "true" ]; then
    # In compare mode, use a temp file so the fallback result is shown AFTER
    # the primary, not during Python execution.
    VOXTRAL_MODELS_FILE="$REC_DIR/.models_info"
    export VOXTRAL_MODELS_FILE
    if [ "${REFINE_COMPARE_MODELS:-false}" = "true" ]; then
        VOXTRAL_COMPARE_FILE="$REC_DIR/.compare_result"
        export VOXTRAL_COMPARE_FILE
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
        _success "Text copied to BOTH clipboards:"
        echo "   Ctrl+V        → standard clipboard"
        echo "   Middle-click  → primary selection"
        echo ""
    else
        echo ""
        _warn "Clipboard copy failed (is xclip installed and running under X11?)."
        echo ""
    fi
    # Read which model actually produced the clipboard text
    _used_model=""
    _fallback_model=""
    if [ -n "${VOXTRAL_MODELS_FILE:-}" ] && [ -s "$VOXTRAL_MODELS_FILE" ]; then
        _used_model="$(sed -n '1p' "$VOXTRAL_MODELS_FILE")"
        _fallback_model="$(sed -n '2p' "$VOXTRAL_MODELS_FILE")"
    fi
    # Build result label with model name
    if [ -n "$_used_model" ]; then
        _result_label="REFINED TEXT — $_used_model"
    elif [ "${ENABLE_REFINE:-true}" = "true" ]; then
        _result_label="RAW TRANSCRIPTION — refinement failed"
    else
        _result_label="RAW TRANSCRIPTION"
    fi
    _transcribe_label="RAW TRANSCRIPTION — Voxtral"
    if [ "${REFINE_COMPARE_MODELS:-false}" = "true" ] && [ "${ENABLE_REFINE:-true}" = "true" ]; then
        # Full 3-way view: Raw Voxtral + Primary + Fallback
        _fallback_label="FALLBACK MODEL"
        if [ -n "$_fallback_model" ]; then
            _fallback_label="FALLBACK MODEL — $_fallback_model"
        fi
        _header "$_transcribe_label" "📝"
        echo ""
        printf "${C_BG_CYAN} %s ${C_RESET}\n" "$raw_transcription"
        echo ""
        _header "$_result_label" "📝"
        _success "Copied to clipboard"
        echo ""
        printf "${C_BG_BLUE} %s ${C_RESET}\n" "$final_text"
    elif [ "${SHOW_RAW_VOXTRAL:-true}" = "true" ] && [ "${ENABLE_REFINE:-true}" = "true" ]; then
        # 2-way view: Raw Voxtral + Result (on by default)
        _header "$_transcribe_label" "📝"
        echo ""
        printf "${C_BG_CYAN} %s ${C_RESET}\n" "$raw_transcription"
        echo ""
        _header "$_result_label" "📝"
        _success "Copied to clipboard"
        echo ""
        printf "${C_BG_BLUE} %s ${C_RESET}\n" "$final_text"
    else
        _header "$_result_label" "📝"
        printf "${C_BG_BLUE} %s ${C_RESET}\n" "$final_text"
    fi
    if [ -n "${VOXTRAL_COMPARE_FILE:-}" ] && [ -s "$VOXTRAL_COMPARE_FILE" ]; then
        echo ""
        _header "$_fallback_label" "📝"
        echo ""
        printf "${C_BG_PURPLE} %s ${C_RESET}\n" "$(cat "$VOXTRAL_COMPARE_FILE")"
        echo ""
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
        echo ""
        echo "🔄 History context update running in background..."
    fi
fi

# ─── Interactive prompt (only in direct/terminal mode, not from the menu) ────
if [ "${VOXREFINER_MENU:-}" != "1" ]; then
    while true; do
        echo ""
        printf "${C_DIM}──────────────────────────────────────────────────────────────────${C_RESET}\n"
        printf "  ${C_BOLD}[r]${C_RESET} Retry  ${C_BOLD}[n]${C_RESET} New recording  ${C_BOLD}[m]${C_RESET} Open menu  ${C_DIM}[Enter] Quit${C_RESET}: "
        read -r _action
        case "$_action" in
            r|R) exec "$0" --retry ;;
            n|N) exec "$0" ;;
            m|M) exec "$SCRIPT_DIR/vox-refiner-menu.sh" ;;
            *)   break ;;
        esac
    done
fi


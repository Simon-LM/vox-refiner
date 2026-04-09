#!/bin/bash
# VoxRefiner — Voice Translate pipeline
# Record → Voxtral STT → Mistral rewrite+translate → Voxtral TTS → play
# Can be launched standalone (keyboard shortcut) or called from the menu.

cd "$(dirname "$0")"
SCRIPT_DIR="$(pwd)"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"

# ─── Shared UI + helpers ─────────────────────────────────────────────────────
# shellcheck disable=SC1091
source "$SCRIPT_DIR/src/ui.sh"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/src/save_audio.sh"

if [ ! -x "$VENV_PYTHON" ]; then
    echo "❌ Missing .venv Python interpreter: $VENV_PYTHON"
    echo "Run ./install.sh first."
    exit 1
fi

# Load .env
if [ -f .env ]; then
    # shellcheck disable=SC1091
    set -a; source .env; set +a
fi

# Save stderr so Python progress messages reach the terminal even when stdout
# is captured by $() substitution.
exec 3>&2

# ─── Language selection ───────────────────────────────────────────────────────

_lang_marker() {
    # Print colored ► next to the default language
    if [ "$1" = "$2" ]; then printf "${C_BGREEN}▸${C_RESET}"; else printf " "; fi
}

choose_language() {
    local dl="${TRANSLATE_TARGET_LANG:-en}"
    _header "TARGET LANGUAGE" "🌍"
    echo ""
    printf "  $(_lang_marker en "$dl") ${C_BOLD}[1]${C_RESET}  English\n"
    printf "  $(_lang_marker fr "$dl") ${C_BOLD}[2]${C_RESET}  French\n"
    printf "  $(_lang_marker de "$dl") ${C_BOLD}[3]${C_RESET}  German\n"
    printf "  $(_lang_marker es "$dl") ${C_BOLD}[4]${C_RESET}  Spanish\n"
    printf "  $(_lang_marker pt "$dl") ${C_BOLD}[5]${C_RESET}  Portuguese\n"
    printf "  $(_lang_marker it "$dl") ${C_BOLD}[6]${C_RESET}  Italian\n"
    printf "  $(_lang_marker nl "$dl") ${C_BOLD}[7]${C_RESET}  Dutch\n"
    printf "  $(_lang_marker hi "$dl") ${C_BOLD}[8]${C_RESET}  Hindi\n"
    printf "  $(_lang_marker ar "$dl") ${C_BOLD}[9]${C_RESET}  Arabic\n"
    echo ""
    printf "  ${C_DIM}Enter = keep default (▸)${C_RESET}  /  Choice: "
    read -r _lang_choice

    case "$_lang_choice" in
        1) TRANSLATE_TARGET_LANG="en" ;;
        2) TRANSLATE_TARGET_LANG="fr" ;;
        3) TRANSLATE_TARGET_LANG="de" ;;
        4) TRANSLATE_TARGET_LANG="es" ;;
        5) TRANSLATE_TARGET_LANG="pt" ;;
        6) TRANSLATE_TARGET_LANG="it" ;;
        7) TRANSLATE_TARGET_LANG="nl" ;;
        8) TRANSLATE_TARGET_LANG="hi" ;;
        9) TRANSLATE_TARGET_LANG="ar" ;;
        "") TRANSLATE_TARGET_LANG="$dl" ;;
        *)
            echo "  ❌ Invalid choice — using default ($dl)."
            TRANSLATE_TARGET_LANG="$dl"
            sleep 0.5
            ;;
    esac
    export TRANSLATE_TARGET_LANG
}

# ─── Voice profile ───────────────────────────────────────────────────────────

VOICE_PROFILE_FILE="$SCRIPT_DIR/recordings/voice-profile/sample.mp3"

_VOICE_PROFILE_TEXT="Bonjour. Je lis ce texte pour enregistrer ma voix.
Les phrases sont courtes, claires et naturelles.
Voici quelques sons variés : le ciel est bleu,
les oiseaux chantent, le jardin fleurit au printemps.
J'articule bien chaque mot, sans précipitation.
Ma voix est posée, à volume normal.
Merci pour votre écoute."

_record_voice_profile() {
    local profile_dir="$SCRIPT_DIR/recordings/voice-profile"
    local tmp_wav="$profile_dir/source.wav"
    local final_mp3="$profile_dir/sample.mp3"

    mkdir -p "$profile_dir"
    rm -f "$tmp_wav"
    pkill -f "rec.*source.wav" 2>/dev/null || true

    _header "VOICE PROFILE RECORDING" "🎙"
    echo ""
    _info "Read the following text aloud at a natural pace:"
    echo ""
    printf "${C_DIM}──────────────────────────────────────────────────────────────────${C_RESET}\n"
    while IFS= read -r _line; do
        printf "  ${C_BOLD}%s${C_RESET}\n" "$_line"
    done <<< "$_VOICE_PROFILE_TEXT"
    printf "${C_DIM}──────────────────────────────────────────────────────────────────${C_RESET}\n"
    echo ""
    _info "Recording: 30 seconds total — first and last 5s are trimmed automatically."
    _info "Press Ctrl+C to stop early if needed."
    echo ""
    printf "  ${C_DIM}Press Enter when ready...${C_RESET}"
    read -r
    echo ""
    printf "  ${C_BGREEN}🎙  RECORDING (30s)${C_RESET}\n"
    echo ""

    # Record at high quality (48kHz) for better voice cloning
    rec -c 1 -r 48000 "$tmp_wav" &
    REC_PID=$!

    # Post-launch mic health check
    sleep 0.3
    if ! kill -0 "$REC_PID" 2>/dev/null; then
        _warn "Microphone inaccessible, attempting audio reset..."
        systemctl --user restart pipewire pipewire-pulse 2>/dev/null || true
        sleep 1
        rm -f "$tmp_wav"
        rec -c 1 -r 48000 "$tmp_wav" &
        REC_PID=$!
        sleep 0.3
        if ! kill -0 "$REC_PID" 2>/dev/null; then
            _error "Microphone still inaccessible after reset."
            return 1
        fi
        _success "Microphone recovered."
    fi

    # Auto-stop after 30 seconds
    _PROFILE_TIMER_PID=""
    (
        sleep 28
        if kill -0 "$REC_PID" 2>/dev/null; then
            echo ""
            _crucial "  ⏱  2 seconds remaining..."
        fi
        sleep 2
        if kill -0 "$REC_PID" 2>/dev/null; then
            echo ""
            kill -INT "$REC_PID" 2>/dev/null
        fi
    ) &
    _PROFILE_TIMER_PID=$!

    stop_profile_recording() {
        echo ""
        printf "  ${C_DIM}⏹  Stopping recording...${C_RESET}\n"
        kill -INT "$REC_PID" 2>/dev/null
        wait "$REC_PID" 2>/dev/null
    }

    trap stop_profile_recording SIGINT
    wait "$REC_PID" 2>/dev/null
    trap - SIGINT

    kill "$_PROFILE_TIMER_PID" 2>/dev/null
    wait "$_PROFILE_TIMER_PID" 2>/dev/null

    if [ ! -f "$tmp_wav" ]; then
        _error "No audio recorded."
        return 1
    fi

    echo ""
    _process "Processing voice profile..."

    # Extract 5s–25s → 20s at 128kbps (skip hesitation at start and end)
    ffmpeg -y -i "$tmp_wav" -ss 5 -t 20 \
        -codec:a libmp3lame -b:a 128k "$final_mp3" 2>/dev/null

    rm -f "$tmp_wav"

    if [ -f "$final_mp3" ]; then
        _success "Voice profile saved (20s sample, 128 kbps)."
        _info "It will be used automatically for voice cloning."
    else
        _error "Failed to process voice profile."
        return 1
    fi
}

# ─── Save audio to Downloads/VoxRefiner/ ────────────────────────────────────

_save_audio() {
    # Wrapper: delegates to the shared _save_audio_to_downloads helper.
    # Requires: REC_TTS_OUTPUT, raw_transcription — set by voice_translate()
    _save_audio_to_downloads "$REC_TTS_OUTPUT" "$raw_transcription" "voice-translate"
}

# ─── Translate + TTS + Play (reusable for retry) ────────────────────────────

_translate_and_speak() {
    # Requires: raw_transcription, TARGET_LANG, REC_SOURCE_WAV, REC_VOICE_SAMPLE,
    #           REC_TTS_OUTPUT, REC_DIR — all set by voice_translate()

    # ── Voice rewrite (clean + adapt for speech + translate) ──────────
    rewritten_text=$(printf '%s' "$raw_transcription" | "$VENV_PYTHON" -m src.voice_rewrite 2>&3)

    if [ -z "$rewritten_text" ] || [ "$rewritten_text" = "$raw_transcription" ]; then
        rewritten_text="$raw_transcription"
        _header "TRANSLATION FAILED" "⚠"
        echo ""
        printf "${C_BG_BLUE} $rewritten_text ${C_RESET}"
        echo ""
    else
        _header "TRANSLATION ($TARGET_LANG)" "🌍"
        echo ""
        printf "${C_BG_BLUE} $rewritten_text ${C_RESET}"
        echo ""
    fi

    # Copy to clipboard — both selections, same as STT
    if printf '%s' "$rewritten_text" | xclip -selection clipboard && \
       printf '%s' "$rewritten_text" | xclip -selection primary; then
       echo ""
        _success "Copied to clipboard"
    else
        echo ""
        _warn "Clipboard copy failed (is xclip installed and running under X11?)"
    fi

    # ── Voice sample for cloning ──────────────────────────────────────
    # Prefer pre-recorded voice profile; fall back to extracting from WAV.

    VOICE_SAMPLE=""
    echo ""

    if [ "${TTS_USE_VOICE_PROFILE:-true}" = "true" ] && [ -f "$VOICE_PROFILE_FILE" ]; then
        VOICE_SAMPLE="$VOICE_PROFILE_FILE"
        _info "🎤 Voice cloning — using pre-recorded voice profile"
        echo ""
    else
        # Extract from the ORIGINAL WAV (before silence removal + speed-up) to
        # preserve natural voice pitch and timbre for cloning.
        VOICE_SKIP="${TTS_VOICE_SKIP_SECONDS:-3}"
        VOICE_DURATION="${TTS_VOICE_SAMPLE_DURATION:-15}"
        VOICE_MIN_SECONDS=10  # Voxtral TTS recommends 10-20s for voice cloning

        # Get original WAV duration
        wav_duration=$(ffprobe -v error -show_entries format=duration \
            -of default=noprint_wrappers=1:nokey=1 "$REC_SOURCE_WAV" 2>/dev/null || echo "0")

        # Calculate usable duration after skipping the start
        usable_duration=$(awk -v d="$wav_duration" -v s="$VOICE_SKIP" 'BEGIN{print d - s}')

        if awk -v u="$usable_duration" -v m="$VOICE_MIN_SECONDS" 'BEGIN{exit !(u >= m)}'; then
            # Enough audio for voice cloning — extract from WAV and convert to MP3
            ffmpeg -y -i "$REC_SOURCE_WAV" -ss "$VOICE_SKIP" -t "$VOICE_DURATION" \
                -codec:a libmp3lame -b:a 128k "$REC_VOICE_SAMPLE" 2>/dev/null
            VOICE_SAMPLE="$REC_VOICE_SAMPLE"
            _info "🎤 Voice cloning — using YOUR voice (${VOICE_DURATION}s sample)"
            echo ""
        else
            _warn "Default voice — recording too short (${wav_duration%.*}s, need ≥15s)"
            _info "   Record a voice profile [p] for better cloning."
            echo ""
        fi
    fi

    # ── TTS (Voxtral TTS + voice clone) ──────────────────────────────

    TTS_ARGS="$REC_TTS_OUTPUT"
    if [ -n "$VOICE_SAMPLE" ]; then
        TTS_ARGS="$REC_TTS_OUTPUT $VOICE_SAMPLE"
    fi

    # Pass target language so tts.py can pick a matching preset voice when no
    # voice sample is used (TTS_LANG → _LANG_VOICE_MAP lookup in tts.py).
    if printf '%s' "$rewritten_text" | TTS_LANG="$TARGET_LANG" "$VENV_PYTHON" -m src.tts $TTS_ARGS 2>&3; then

        # Loudness normalization + volume boost
        TTS_LOUDNESS="${TTS_LOUDNESS:--16}"
        TTS_VOLUME="${TTS_VOLUME:-2.0}"
        TTS_NORM_TMP="$REC_DIR/.norm_tmp.mp3"
        if ffmpeg -y -i "$REC_TTS_OUTPUT" \
                -af "loudnorm=I=${TTS_LOUDNESS}:TP=-1.5:LRA=11,volume=${TTS_VOLUME}" \
                -codec:a libmp3lame -b:a 128k "$TTS_NORM_TMP" 2>/dev/null; then
            mv "$TTS_NORM_TMP" "$REC_TTS_OUTPUT"
        fi
        rm -f "$TTS_NORM_TMP"

        # Play audio
        TTS_PLAYER="${TTS_PLAYER:-mpv --no-video}"
        echo ""
        if command -v mpv >/dev/null 2>&1; then
            printf "  ${C_BGREEN}🔊 Playing...${C_RESET}\n"
            $TTS_PLAYER "$REC_TTS_OUTPUT" 2>/dev/null
            echo ""
            _success "Playback complete."
        else
            _warn "mpv is not installed — cannot auto-play."
            _info "Install it: sudo apt install mpv"
            _info "Audio saved at: $REC_TTS_OUTPUT"
        fi
    else
        echo ""
        _warn "TTS failed — translated text is still in your clipboard."
    fi
}

# ─── Voice Translate pipeline ─────────────────────────────────────────────────

voice_translate() {
    TARGET_LANG="${TRANSLATE_TARGET_LANG:-en}"
    _header "VOICE TRANSLATE → $TARGET_LANG" "🌍"

    # ── Step 1: Record ────────────────────────────────────────────────────

    AUDIO_TEMPO="${AUDIO_TEMPO:-1.5}"

    # Validate AUDIO_TEMPO
    if ! awk -v v="$AUDIO_TEMPO" 'BEGIN{exit !(v+0 >= 1.0 && v+0 <= 2.0)}'; then
        _error "AUDIO_TEMPO must be between 1.0 and 2.0 (got: $AUDIO_TEMPO)."
        return 1
    fi

    # All audio files go into recordings/voice-translate/ — overwritten each run.
    REC_DIR="$SCRIPT_DIR/recordings/voice-translate"
    mkdir -p "$REC_DIR"
    REC_SOURCE_WAV="$REC_DIR/source.wav"
    REC_SOURCE_MP3="$REC_DIR/source.mp3"
    REC_VOICE_SAMPLE="$REC_DIR/voice_sample.mp3"
    REC_TTS_OUTPUT="$REC_DIR/voice_translate.mp3"

    # Clean previous run
    rm -f "$REC_SOURCE_WAV" "$REC_SOURCE_MP3" "$REC_VOICE_SAMPLE" "$REC_TTS_OUTPUT"

    # Kill orphan rec processes
    pkill -f "rec.*source.wav" 2>/dev/null || true

    REC_MAX_SECONDS=120   # 2 minutes max for short Voice Translate
    REC_WARN_SECONDS=105  # warning 15s before the limit

    echo ""
    printf "  ${C_BGREEN}🎙  RECORDING${C_RESET}\n"
    echo ""
    _info "Speak for ≥15s to clone your voice (shorter → default voice)"
    _info "Max duration: 2 min."
    echo ""
    _stop "Press Ctrl+C to stop."
    echo ""

    rec -c 1 -r 16000 "$REC_SOURCE_WAV" &
    REC_PID=$!

    # Post-launch mic health check
    sleep 0.3
    if ! kill -0 "$REC_PID" 2>/dev/null; then
        _warn "Microphone inaccessible, attempting audio reset..."
        systemctl --user restart pipewire pipewire-pulse 2>/dev/null || true
        sleep 1
        rm -f "$REC_SOURCE_WAV"
        rec -c 1 -r 16000 "$REC_SOURCE_WAV" &
        REC_PID=$!
        sleep 0.3
        if ! kill -0 "$REC_PID" 2>/dev/null; then
            _error "Microphone still inaccessible after reset."
            return 1
        fi
        _success "Microphone recovered."
    fi

    stop_recording() {
        echo ""
        printf "  ${C_DIM}⏹  Stopping recording...${C_RESET}\n"
        kill -INT "$REC_PID" 2>/dev/null
        wait "$REC_PID" 2>/dev/null
        _success "Recording stopped."
    }

    # Background timer: warn at 1:45, auto-stop at 2:00
    _TIMER_PID=""
    (
        sleep "$REC_WARN_SECONDS"
        if kill -0 "$REC_PID" 2>/dev/null; then
            echo ""
            _crucial "  ⏱  15 seconds remaining...\n"
        fi
        sleep $(( REC_MAX_SECONDS - REC_WARN_SECONDS ))
        if kill -0 "$REC_PID" 2>/dev/null; then
            echo ""
            _crucial "  ⏱  Maximum duration reached (2 min) — stopping.${C_RESET}\n"
            kill -INT "$REC_PID" 2>/dev/null
        fi
    ) &
    _TIMER_PID=$!

    trap stop_recording SIGINT
    wait "$REC_PID" 2>/dev/null
    trap - SIGINT

    # Clean up timer if recording was stopped early
    kill "$_TIMER_PID" 2>/dev/null
    wait "$_TIMER_PID" 2>/dev/null

    if [ ! -f "$REC_SOURCE_WAV" ]; then
        _error "No audio file recorded."
        return 1
    fi

    # Size guard
    wav_size=$(stat -c%s "$REC_SOURCE_WAV" 2>/dev/null || echo 0)
    if [ "$wav_size" -gt 100000000 ]; then
        _error "Audio file is abnormally large (${wav_size} bytes)."
        return 1
    fi

    # Audio processing (silence removal + speed + MP3)
    echo ""
    _process "Processing audio..."
    ffmpeg -y -i "$REC_SOURCE_WAV" \
        -af "silenceremove=detection=peak:start_periods=1:start_threshold=-35dB:stop_periods=-1:stop_duration=1.2:stop_threshold=-35dB,atempo=${AUDIO_TEMPO}" \
        -codec:a libmp3lame -b:a 64k "$REC_SOURCE_MP3" 2>/dev/null

    if [ ! -f "$REC_SOURCE_MP3" ]; then
        _error "Audio conversion failed."
        return 1
    fi

    # ── Step 2: Transcription (Voxtral STT) ──────────────────────────────

    raw_transcription=$("$VENV_PYTHON" src/transcribe.py "$REC_SOURCE_MP3" 2>&3)

    if [ -z "$raw_transcription" ]; then
        _error "Empty transcription."
        return 1
    fi

    # ── Results ──────────────────────────────────────────────────────────

    _header "RAW TRANSCRIPTION" "📝"
    echo ""
    printf "${C_BG_CYAN} $raw_transcription ${C_RESET}"
    echo ""
    echo ""
    echo ""

    # ── Steps 3-6: Rewrite + TTS + Play ─────────────────────────────────
    _translate_and_speak

    # ── Post-translate actions ────────────────────────────────────────────
    while true; do
        echo ""
        _sep
        printf "  ${C_BOLD}[l]${C_RESET} Listen  ${C_BOLD}[r]${C_RESET} Retry  ${C_BOLD}[d]${C_RESET} Save  ${C_BOLD}[n]${C_RESET} New (%s)  ${C_BOLD}[m]${C_RESET} Menu VoxRefiner: " "$TARGET_LANG"
        read -r _action
        case "$_action" in
            d|D)
                _save_audio
                ;;
            l|L)
                if [ -f "$REC_TTS_OUTPUT" ] && command -v mpv >/dev/null 2>&1; then
                    echo ""
                    echo ""
                    printf "  ${C_BGREEN}🔊 Replaying...${C_RESET}\n"
                    TTS_PLAYER="${TTS_PLAYER:-mpv --no-video}"
                    $TTS_PLAYER "$REC_TTS_OUTPUT" 2>/dev/null
                    echo ""
                    _success "Playback complete."
                else
                    _warn "No audio to replay."
                fi
                ;;
            r|R)
                echo ""
                printf "  ${C_GREEN}🔄 Retrying translation...${C_RESET}\n"
                _translate_and_speak
                ;;
            n|N)
                # Start a new Voice Translate session with the same language
                voice_translate
                return
                ;;
            m|M) break ;;
            *)   ;;
        esac
    done
}

# ─── Entry point ─────────────────────────────────────────────────────────────

if [ "${1:-}" = "--record-profile" ]; then
    _record_voice_profile
    exit $?
fi

choose_language
voice_translate

#!/bin/bash
# VoxRefiner — Interactive menu
# Launched from the Ubuntu app menu (.desktop file).
# The keyboard shortcut bypasses this and calls record_and_transcribe_local.sh directly.

cd "$(dirname "$0")"
SCRIPT_DIR="$(pwd)"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"
export VOXREFINER_MENU=1  # suppress hints in record_and_transcribe_local.sh

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

# ─── ANSI colors ─────────────────────────────────────────────────────────────

C_RESET='\033[0m'
C_BOLD='\033[1m'
C_DIM='\033[2m'
C_ITALIC="\033[3m"
C_UNDERLINE="\033[4m"
C_BLINK="\033[5m"
C_REVERSE="\033[7m"

C_CYAN='\033[36m'
C_GREEN='\033[32m'
C_YELLOW='\033[33m'
C_RED='\033[31m'
C_WHITE='\033[97m'
C_BCYAN='\033[1;36m'    # bold cyan
C_BGREEN='\033[1;32m'   # bold green
C_BYELLOW='\033[1;33m'  # bold yellow
C_BLUE='\033[34m'
C_BBLUE='\033[1;34m'
C_BG_BLUE="\033[44m"
C_BG_CYAN="\033[46m"

# ─── UI helpers i──────────────────────────────────────────────────────────────

_header() {
    # Print a section header: _header "TITLE" [emoji]
    local title="$1" emoji="${2:-}"
    local prefix=""
    [ -n "$emoji" ] && prefix="$emoji  "
    echo ""
    printf "${C_DIM}%s${C_RESET}\n" "──────────────────────────────────────────────────────────────────"
    printf "  ${C_BGREEN}%s%s${C_RESET}\n" "$prefix" "$title"
    printf "${C_DIM}%s${C_RESET}\n" "──────────────────────────────────────────────────────────────────"
}

_success() { printf "  ${C_BGREEN}✓${C_RESET} %s\n" "$1"; }
_warn()    { printf "  ${C_BYELLOW}⚠${C_RESET}  %s\n" "$1"; }
_error()   { printf "  ${C_RED}✗${C_RESET} %s\n" "$1"; }
_info()    { printf "  ${C_CYAN}%b${C_RESET}\n" "$1"; }
_crucial() { printf "  ${C_BCYAN}%b${C_RESET}\n" "$1"; }
_stop() { printf "  ${C_BBLUE}%b${C_RESET}\n" "$1"; }
_sep()     { printf "${C_DIM}%s${C_RESET}\n" "──────────────────────────────────────────────────────────────────"; }

# ─── API key helpers ─────────────────────────────────────────────────────────

_set_env_var() {
    # Write or update a variable in .env: _set_env_var KEY VALUE
    local key="$1" value="$2"
    if [ ! -f .env ]; then touch .env; fi
    if grep -q "^${key}=" .env; then
        sed -i "s|^${key}=.*|${key}=${value}|" .env
    else
        printf '\n%s=%s\n' "$key" "$value" >> .env
    fi
}

_mask_key() {
    # Show only last 4 chars: sk-...xxxx
    local key="$1"
    if [ -z "$key" ]; then echo "(not set)"; return; fi
    local len="${#key}"
    if [ "$len" -le 4 ]; then echo "****"; return; fi
    printf '...%s' "${key: -4}"
}

_test_mistral_key() {
    local key="$1"
    if [ -z "$key" ]; then
        _error "No API key to test."
        return 1
    fi
    printf "  ${C_CYAN}⚡ Testing Mistral API key...${C_RESET}\n"
    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "Authorization: Bearer $key" \
        "https://api.mistral.ai/v1/models" 2>/dev/null)
    case "$http_code" in
        200) _success "API key is valid." ; return 0 ;;
        401) _error  "Invalid API key (401 Unauthorized)." ; return 1 ;;
        429) _warn   "Rate limited (429) — key exists but quota exceeded." ; return 1 ;;
        000) _error  "No network response — check your internet connection." ; return 1 ;;
        *)   _error  "Unexpected response: HTTP $http_code" ; return 1 ;;
    esac
}

_submenu_api_keys() {
    while true; do
        _header "API KEYS" "🔑"
        echo ""
        printf "  Mistral API key: ${C_CYAN}%s${C_RESET}\n" "$(_mask_key "${MISTRAL_API_KEY:-}")"
        echo ""
        printf "  ${C_BOLD}[t]${C_RESET}  Test key\n"
        printf "  ${C_BOLD}[e]${C_RESET}  Edit key\n"
        echo ""
        printf "  ${C_DIM}Press Enter to return...${C_RESET} "
        read -r _key_action
        case "$_key_action" in
            t|T)
                echo ""
                _test_mistral_key "${MISTRAL_API_KEY:-}"
                echo ""
                printf "  ${C_DIM}Press Enter to continue...${C_RESET}"
                read -r
                ;;
            e|E)
                echo ""
                printf "  Enter new Mistral API key: "
                read -rs _new_key
                echo ""
                if [ -z "$_new_key" ]; then
                    _warn "No key entered — unchanged."
                else
                    _set_env_var "MISTRAL_API_KEY" "$_new_key"
                    export MISTRAL_API_KEY="$_new_key"
                    # Reload .env
                    set -a; source .env; set +a
                    _success "Key saved."
                    echo ""
                    _test_mistral_key "$_new_key"
                fi
                echo ""
                printf "  ${C_DIM}Press Enter to continue...${C_RESET}"
                read -r
                ;;
            *) break ;;
        esac
    done
}

_check_api_key_at_startup() {
    if [ -z "${MISTRAL_API_KEY:-}" ]; then
        clear
        echo ""
        printf "${C_BYELLOW}╔══════════════════════════════════════════════════════════════════╗${C_RESET}\n"
        printf "${C_BYELLOW}║${C_RESET}  ${C_BOLD}⚠  API key required${C_RESET}                                              ${C_BYELLOW}║${C_RESET}\n"
        printf "${C_BYELLOW}║${C_RESET}  No MISTRAL_API_KEY found in .env.                               ${C_BYELLOW}║${C_RESET}\n"
        printf "${C_BYELLOW}║${C_RESET}  VoxRefiner cannot function without it.                          ${C_BYELLOW}║${C_RESET}\n"
        printf "${C_BYELLOW}╚══════════════════════════════════════════════════════════════════╝${C_RESET}\n"
        echo ""
        printf "  Configure it now? ${C_BOLD}[Y/n]${C_RESET} "
        read -r _api_prompt
        case "$_api_prompt" in
            n|N) ;;
            *) _submenu_api_keys ;;
        esac
    else
        # Key is present — test it silently in background, warn if invalid
        local http_code
        http_code=$(curl -s -o /dev/null -w "%{http_code}" \
            -H "Authorization: Bearer ${MISTRAL_API_KEY}" \
            "https://api.mistral.ai/v1/models" \
            --max-time 5 2>/dev/null)
        if [ "$http_code" = "401" ]; then
            clear
            echo ""
            printf "${C_RED}╔══════════════════════════════════════════════════════════════════╗${C_RESET}\n"
            printf "${C_RED}║${C_RESET}  ${C_BOLD}✗  Invalid Mistral API key${C_RESET}                                       ${C_RED}║${C_RESET}\n"
            printf "${C_RED}║${C_RESET}  The key in .env was rejected (401 Unauthorized).                ${C_RED}║${C_RESET}\n"
            printf "${C_RED}║${C_RESET}  VoxRefiner will not work until a valid key is set.             ${C_RED}║${C_RESET}\n"
            printf "${C_RED}╚══════════════════════════════════════════════════════════════════╝${C_RESET}\n"
            echo ""
            printf "  Update it now? ${C_BOLD}[Y/n]${C_RESET} "
            read -r _api_prompt
            case "$_api_prompt" in
                n|N) ;;
                *) _submenu_api_keys ;;
            esac
        fi
    fi
}

# ─── Menu ─────────────────────────────────────────────────────────────────────

show_menu() {
    clear
    echo ""
    echo "╔══════════════════════════════════════════════════════════════════╗"
    printf "║                          ${C_BGREEN} VoxRefiner ${C_RESET}                            ║\n"
    echo "╠══════════════════════════════════════════════════════════════════╣"
    echo "║                                                                  ║"
    printf "║  ${C_BOLD}[1]${C_RESET}  Speech-to-Text      ${C_DIM}speak → clipboard${C_RESET}                      ║\n"
    printf "║  ${C_BOLD}[2]${C_RESET}  Voice Translate     ${C_DIM}speak → audio${C_RESET}                          ║\n"
    echo "║                                                                  ║"
    echo "╠══════════════════════════════════════════════════════════════════╣"
    echo "║                                                                  ║"
    printf "║  ${C_DIM}[s]${C_RESET}  Settings            ${C_DIM}edit .env${C_RESET}                                   ║\n"

    printf "║  ${C_DIM}[c]${C_RESET}  Context             ${C_DIM}edit context.txt${C_RESET}                            ║\n"
    printf "║  ${C_DIM}[h]${C_RESET}  History             ${C_DIM}edit history.txt${C_RESET}                            ║\n"
    printf "║  ${C_DIM}[u]${C_RESET}  Update                                                     ║\n"
    printf "║  ${C_DIM}[?]${C_RESET}  Help                                                       ║\n"
    printf "║  ${C_DIM}[q]${C_RESET}  Quit                                                       ║\n"
    echo "║                                                                  ║"
    echo "╚══════════════════════════════════════════════════════════════════╝"
    echo ""
}

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

# ─── Save audio to Downloads/VoxRefiner/ ────────────────────────────────────

_save_audio() {
    # Requires: REC_TTS_OUTPUT, raw_transcription — set by voice_translate()
    if [ ! -f "$REC_TTS_OUTPUT" ]; then
        _warn "No audio file to save."
        return 1
    fi

    # Resolve Downloads folder (handles Téléchargements, Downloads, etc.)
    DOWNLOADS_DIR="$(xdg-user-dir DOWNLOAD 2>/dev/null || echo "$HOME/Downloads")"
    SAVE_DIR="$DOWNLOADS_DIR/VoxRefiner"
    mkdir -p "$SAVE_DIR"

    # Generate timestamp prefix: 2026-03-31_14h32
    TIMESTAMP="$(date '+%Y-%m-%d_%Hh%M')"

    # Generate slug via Mistral (from raw transcription, not translation)
    echo ""
    _info "🏷️  Generating filename..."
    suggested_slug=$(printf '%s' "$raw_transcription" | "$VENV_PYTHON" -m src.slug 2>&3)
    suggested_slug="${suggested_slug:-voice-translate}"

    # Ask user to confirm or override
    echo ""
    printf "  ${C_BOLD}Suggested name:${C_RESET} ${C_CYAN}%s${C_RESET}\n" "$suggested_slug"
    printf "  Press Enter to confirm, or type a new name: "
    read -r _custom_name

    if [ -n "$_custom_name" ]; then
        # Sanitise manual input: lowercase, spaces → hyphens, strip unsafe chars
        final_slug=$(printf '%s' "$_custom_name" | tr '[:upper:]' '[:lower:]' | tr ' ' '-' | tr -cd 'a-z0-9-')
        final_slug="${final_slug:-voice-translate}"
    else
        final_slug="$suggested_slug"
    fi

    DEST="$SAVE_DIR/${TIMESTAMP}_${final_slug}.mp3"
    if cp "$REC_TTS_OUTPUT" "$DEST"; then
        echo ""
        _success "Saved: $DEST"
    else
        _warn "Could not save file to $DEST"
    fi
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
        _success "Copied to clipboard"
    else
        _warn "Clipboard copy failed (is xclip installed and running under X11?)"
    fi

    # ── Extract voice sample from original WAV ────────────────────────
    # Use the ORIGINAL WAV (before silence removal + speed-up) to preserve
    # natural voice pitch and timbre for cloning.

    VOICE_SKIP="${TTS_VOICE_SKIP_SECONDS:-3}"
    VOICE_DURATION="${TTS_VOICE_SAMPLE_DURATION:-15}"
    VOICE_MIN_SECONDS=10  # Voxtral TTS recommends 10-20s for voice cloning
    VOICE_SAMPLE=""

    # Get original WAV duration
    wav_duration=$(ffprobe -v error -show_entries format=duration \
        -of default=noprint_wrappers=1:nokey=1 "$REC_SOURCE_WAV" 2>/dev/null || echo "0")

    # Calculate usable duration after skipping the start
    usable_duration=$(awk -v d="$wav_duration" -v s="$VOICE_SKIP" 'BEGIN{print d - s}')

    echo ""
    if awk -v u="$usable_duration" -v m="$VOICE_MIN_SECONDS" 'BEGIN{exit !(u >= m)}'; then
        # Enough audio for voice cloning — extract from WAV and convert to MP3
        ffmpeg -y -i "$REC_SOURCE_WAV" -ss "$VOICE_SKIP" -t "$VOICE_DURATION" \
            -codec:a libmp3lame -b:a 128k "$REC_VOICE_SAMPLE" 2>/dev/null
        VOICE_SAMPLE="$REC_VOICE_SAMPLE"
        _info "🎤 Voice cloning — using YOUR voice (${VOICE_DURATION}s sample)"
    else
        _warn "Default voice — recording too short (${wav_duration%.*}s, need ≥15s)"
        _info "Speak longer next time to clone your own voice."
    fi

    # ── TTS (Voxtral TTS + voice clone) ──────────────────────────────

    TTS_ARGS="$REC_TTS_OUTPUT"
    if [ -n "$VOICE_SAMPLE" ]; then
        TTS_ARGS="$REC_TTS_OUTPUT $VOICE_SAMPLE"
    fi

    if printf '%s' "$rewritten_text" | "$VENV_PYTHON" -m src.tts $TTS_ARGS 2>&3; then

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

    # ── Step 1: Record (reuse the existing recording pipeline) ────────────

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
    _info "Speak for ≥15s to clone your voice (shorter → default voice)"
    _info "Max duration: 2 min."
    _stop "Press Ctrl+C to stop."
    echo ""

    rec -c 1 -r 16000 "$REC_SOURCE_WAV" &
    REC_PID=$!

    #rec -c 1 -r 16000 "$REC_SOURCE_WAV" 2> >(grep -v "can't encode 0-bit" >&2) &
    #REC_PID=$!

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

    # Clean up timer if recording was stopped early (Ctrl+C or short recording)
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
    printf "  ⚡ Processing audio...\n"
    ffmpeg -y -i "$REC_SOURCE_WAV" \
        -af "silenceremove=detection=peak:start_periods=1:start_threshold=-35dB:stop_periods=-1:stop_duration=1.2:stop_threshold=-35dB,atempo=${AUDIO_TEMPO}" \
        -codec:a libmp3lame -b:a 64k "$REC_SOURCE_MP3" 2>/dev/null

    if [ ! -f "$REC_SOURCE_MP3" ]; then
        _error "Audio conversion failed."
        return 1
    fi

    # ── Step 2: Transcription (Voxtral STT — existing) ───────────────────

    exec 3>&2
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

    # ── Steps 3-6: Rewrite + TTS + Play ─────────────────────────────────
    _translate_and_speak

    # ── Post-translate actions ──────────────────────────────────────────
    while true; do
        echo ""
        _sep
        printf "  ${C_BOLD}[l]${C_RESET} Listen  ${C_BOLD}[r]${C_RESET} Retry  ${C_BOLD}[d]${C_RESET} Save  ${C_BOLD}[n]${C_RESET} New (%s)  ${C_DIM}[Enter] Menu${C_RESET}: " "$TARGET_LANG"
        read -r _action
        case "$_action" in
            d|D)
                _save_audio
                ;;
            l|L)
                if [ -f "$REC_TTS_OUTPUT" ] && command -v mpv >/dev/null 2>&1; then
                    printf "  ${C_BGREEN}🔊 Replaying...${C_RESET}\n"
                    TTS_PLAYER="${TTS_PLAYER:-mpv --no-video}"
                    $TTS_PLAYER "$REC_TTS_OUTPUT" 2>/dev/null
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
                # Loop back into voice_translate with the same language
                voice_translate
                return
                ;;
            *)  break ;;
        esac
    done
}

# ─── Main loop ────────────────────────────────────────────────────────────────

_check_api_key_at_startup

while true; do
    show_menu
    printf "  ${C_BGREEN}▸${C_RESET} "
    read -r choice

    case "$choice" in
        1)
            while true; do
                ./record_and_transcribe_local.sh
                echo ""
                _sep
                printf "  ${C_BOLD}[r]${C_RESET} Retry  ${C_BOLD}[n]${C_RESET} New recording  ${C_DIM}[Enter] Menu${C_RESET}: "
                read -r _stt_action
                case "$_stt_action" in
                    r|R) ./record_and_transcribe_local.sh --retry ; continue ;;
                    n|N) continue ;;
                    *)   break ;;
                esac
            done
            ;;
        2)
            choose_language
            voice_translate
            ;;
        s|S)
            while true; do
                _header "SETTINGS" "⚙"
                echo ""
                printf "  ${C_BOLD}[k]${C_RESET}  API Keys\n"
                printf "  ${C_BOLD}[e]${C_RESET}  Edit .env\n"
                echo ""
                printf "  ${C_DIM}Press Enter to return...${C_RESET} "
                read -r _set_action
                case "$_set_action" in
                    k|K)
                        _submenu_api_keys
                        ;;
                    e|E)
                        ${EDITOR:-nano} .env
                        if [ -f .env ]; then
                            set -a; source .env; set +a
                        fi
                        ;;
                    *) break ;;
                esac
            done
            ;;
        c|C)
            if [ ! -f context.txt ]; then
                echo ""
                _info "context.txt does not exist yet."
                printf "  Create it from the template? ${C_BOLD}[Y/n]${C_RESET} "
                read -r _ctx_create
                case "$_ctx_create" in
                    n|N) ;;
                    *)   cp context.example.txt context.txt 2>/dev/null \
                             && _success "Created from context.example.txt" \
                             || _warn "Template not found — creating empty file."
                         [ ! -f context.txt ] && touch context.txt
                         ;;
                esac
            fi
            [ -f context.txt ] && ${EDITOR:-nano} context.txt
            ;;
        u|U)
            while true; do
                _header "UPDATE" "🔄"
                echo ""
                printf "  ${C_BOLD}[c]${C_RESET}  Check for updates\n"
                printf "  ${C_BOLD}[a]${C_RESET}  Apply update\n"
                printf "  ${C_BOLD}[?]${C_RESET}  Troubleshooting\n"
                echo ""
                printf "  ${C_DIM}Press Enter to return...${C_RESET} "
                read -r _upd_action
                case "$_upd_action" in
                    c|C)
                        echo ""
                        ./vox-refiner-update.sh --check
                        echo ""
                        printf "  ${C_DIM}Press Enter to return...${C_RESET}"
                        read -r
                        ;;
                    a|A)
                        echo ""
                        if ./vox-refiner-update.sh --apply; then
                            echo ""
                            _success "Restart VoxRefiner to use the new version."
                        fi
                        printf "  ${C_DIM}Press Enter to return...${C_RESET}"
                        read -r
                        ;;
                    '?')
                        echo ""
                        if [ -f docs/troubleshooting-update.md ]; then
                            cat docs/troubleshooting-update.md
                        else
                            _warn "docs/troubleshooting-update.md not found."
                        fi
                        echo ""
                        printf "  ${C_DIM}Press Enter to return...${C_RESET}"
                        read -r
                        ;;
                    *)  break ;;
                esac
            done
            ;;
        h|H)
            if [ -f history.txt ]; then
                _header "HISTORY ($(wc -l < history.txt) lines)" "📜"
                echo ""
                cat history.txt
                echo ""
                _sep
                printf "  ${C_BOLD}[e]${C_RESET} Edit  ${C_DIM}[Enter] Menu${C_RESET}: "
                read -r _hist_action
                case "$_hist_action" in
                    e|E) ${EDITOR:-nano} history.txt ;;
                esac
            else
                echo ""
                _warn "history.txt does not exist yet."
                _info "Set ENABLE_HISTORY=true in .env to start building it."
                sleep 1.5
            fi
            ;;
        '?')
            echo ""
            if [ -f docs/troubleshooting.md ]; then
                cat docs/troubleshooting.md
            else
                _warn "docs/troubleshooting.md not found."
            fi
            echo ""
            printf "  ${C_DIM}Press Enter to return...${C_RESET}"
            read -r
            ;;
        q|Q)
            printf "\n  ${C_DIM}Bye!${C_RESET}\n\n"
            exit 0
            ;;
        *)
            _error "Invalid choice."
            sleep 0.5
            ;;
    esac
done

#!/bin/bash
# VoxRefiner — Media Transcribe (V2)
# Import an audio/video file, transcribe with Voxtral, optionally correct with context.
# Can be launched standalone (keyboard shortcut) or called from the menu.

cd "$(dirname "$0")"
SCRIPT_DIR="$(pwd)"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"

# ─── Shared UI + flow helpers ────────────────────────────────────────────────
# shellcheck disable=SC1091
source "$SCRIPT_DIR/src/ui.sh"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/src/text_flows.sh"

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

# Working directory for converted audio
MEDIA_DIR="$SCRIPT_DIR/recordings/media"
mkdir -p "$MEDIA_DIR"
MP3_FILE="$MEDIA_DIR/source.mp3"

# ─── Dependency check ────────────────────────────────────────────────────────

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
    echo ""
    _error "ffmpeg / ffprobe not found."
    echo ""
    echo "  Install with:"
    echo "    sudo apt install ffmpeg"
    echo ""
    if [ "${VOXREFINER_MENU:-}" != "1" ]; then
        printf "  ${C_DIM}Press Enter to exit...${C_RESET}"
        read -r
    fi
    exit 1
fi

# ─── File input ──────────────────────────────────────────────────────────────

clear
echo ""
_header "MEDIA TRANSCRIBE" "🎞→📋"
echo ""
printf "  ${C_DIM}Accepted: mp3, wav, m4a, ogg, flac, mp4, mkv, mov, avi, webm, …${C_RESET}\n"
echo ""
printf "  Path to audio/video file: "
read -r _media_file

# Trim leading/trailing whitespace + expand ~
_media_file="$(printf '%s' "$_media_file" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
_media_file="${_media_file/#\~/$HOME}"

if [ -z "$_media_file" ]; then
    exit 0
fi

if [ ! -f "$_media_file" ]; then
    echo ""
    _error "File not found: $_media_file"
    echo ""
    if [ "${VOXREFINER_MENU:-}" != "1" ]; then
        printf "  ${C_DIM}Press Enter to exit...${C_RESET}"
        read -r
    fi
    exit 1
fi

# ─── Validate audio stream ───────────────────────────────────────────────────

if ! ffprobe -v error -select_streams a:0 \
        -show_entries stream=codec_type \
        -of default=noprint_wrappers=1 \
        "$_media_file" 2>/dev/null | grep -q "audio"; then
    echo ""
    _error "No audio stream found in this file."
    echo ""
    if [ "${VOXREFINER_MENU:-}" != "1" ]; then
        printf "  ${C_DIM}Press Enter to exit...${C_RESET}"
        read -r
    fi
    exit 1
fi

# ─── Convert to MP3 ──────────────────────────────────────────────────────────

echo ""
_process "Converting audio to MP3..."
echo ""

if ! ffmpeg -y -i "$_media_file" -vn -ar 16000 -ac 1 \
        -c:a libmp3lame -b:a 64k "$MP3_FILE" 2>/dev/null; then
    _error "Audio conversion failed."
    echo ""
    if [ "${VOXREFINER_MENU:-}" != "1" ]; then
        printf "  ${C_DIM}Press Enter to exit...${C_RESET}"
        read -r
    fi
    exit 1
fi

# ─── Transcription helper ────────────────────────────────────────────────────

_run_transcription() {
    clear
    echo ""
    _header "MEDIA TRANSCRIBE" "🎞→📋"
    echo ""
    _process "Transcribing with Voxtral..."
    echo ""

    raw_text=$("$VENV_PYTHON" -m src.transcribe "$MP3_FILE" --diarize 2>&3)

    if [ -z "$raw_text" ]; then
        echo ""
        _warn "Transcription returned empty."
        return 1
    fi

    printf '%s' "$raw_text" | xclip -selection clipboard
    printf '%s' "$raw_text" | xclip -selection primary

    echo ""
    _header "TRANSCRIPTION — Voxtral" "🎞"
    _success "Copied to clipboard"
    echo ""
    printf "${C_BG_CYAN} %s ${C_RESET}\n" "$raw_text"
    echo ""
    return 0
}

# ─── First transcription run ─────────────────────────────────────────────────

_run_transcription

# ─── Session state ────────────────────────────────────────────────────────────

_correct_done=0
corrected_text=""
_translate_done=0
translated_text=""

_SETTING_TRANSLATE_LANG="${TRANSLATE_TARGET_LANG:-${OUTPUT_DEFAULT_LANG:-en}}"

# ─── Post-action menu ────────────────────────────────────────────────────────

while true; do
    clear
    echo ""
    _header "MEDIA TRANSCRIBE" "🎞→📋"
    echo ""
    printf "${C_BG_CYAN} %s ${C_RESET}\n" "$raw_text"
    if [ "$_correct_done" -eq 1 ]; then
        echo ""
        _header "CORRECTED — Mistral" "✏"
        echo ""
        printf "${C_BG_BLUE} %s ${C_RESET}\n" "$corrected_text"
    fi
    if [ "$_translate_done" -eq 1 ]; then
        echo ""
        _header "TRANSLATION → $(_lang_name "$_SETTING_TRANSLATE_LANG")" "🌐"
        echo ""
        printf "${C_BG_BLUE} %s ${C_RESET}\n" "$translated_text"
    fi
    echo ""
    _sep
    _menu_line="  ${C_BOLD}[r]${C_RESET} Retry  ${C_BOLD}[n]${C_RESET} New file  ${C_BOLD}[c]${C_RESET} Correct  ${C_BOLD}[t]${C_RESET} Translate  ${C_BOLD}[l]${C_RESET} Read aloud  ${C_BOLD}[z]${C_RESET} Summarise  ${C_BOLD}[p]${C_RESET} Search  ${C_BOLD}[f]${C_RESET} Fact-check"
    _menu_line="$_menu_line  ${C_BOLD}[s]${C_RESET} Settings  ${C_BOLD}[m]${C_RESET} Menu VoxRefiner"
    printf "  %b: " "$_menu_line"
    read -r _action
    case "$_action" in
        r|R)
            _correct_done=0
            corrected_text=""
            _translate_done=0
            translated_text=""
            _run_transcription
            ;;
        n|N)
            exec "$0"
            ;;
        c|C)
            echo ""
            _sep
            printf "  How to provide context?\n"
            printf "  ${C_BOLD}[k]${C_RESET} Type/paste  ${C_BOLD}[f]${C_RESET} Load file  ${C_BOLD}[v]${C_RESET} Record voice  ${C_BOLD}[m]${C_RESET} Cancel: "
            read -r _ctx_mode
            _context=""
            case "$_ctx_mode" in
                k|K)
                    echo ""
                    printf "  Context (technical terms, names, topic…): "
                    read -r _context
                    ;;
                f|F)
                    echo ""
                    printf "  Path to context file (.md, .txt): "
                    read -r _ctx_file
                    _ctx_file="$(printf '%s' "$_ctx_file" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
                    _ctx_file="${_ctx_file/#\~/$HOME}"
                    if [ ! -f "$_ctx_file" ]; then
                        _error "File not found."
                        continue
                    fi
                    _context=$(cat "$_ctx_file")
                    ;;
                v|V)
                    echo ""
                    _info "Recording context — speak the technical terms and names..."
                    echo ""
                    ENABLE_REFINE=true OUTPUT_PROFILE=markdown \
                        "$SCRIPT_DIR/record_and_transcribe_local.sh"
                    _context=$(xclip -o -selection clipboard 2>/dev/null)
                    ;;
                m|M|*)
                    continue
                    ;;
            esac
            if [ -z "$_context" ]; then
                _warn "No context provided."
                continue
            fi
            echo ""
            _process "Correcting transcription with context..."
            echo ""
            _new_corrected=$(printf '%s' "$raw_text" | \
                "$VENV_PYTHON" -m src.correct "$_context" 2>&3)
            if [ -n "$_new_corrected" ]; then
                corrected_text="$_new_corrected"
                printf '%s' "$corrected_text" | xclip -selection clipboard
                printf '%s' "$corrected_text" | xclip -selection primary
                _correct_done=1
                echo ""
                _success "Corrected text copied to clipboard"
            else
                _warn "Correction returned empty."
            fi
            ;;
        t|T)
            _translate_flow "${corrected_text:-$raw_text}"
            ;;
        l|L)
            _read_text="${corrected_text:-$raw_text}"
            printf '%s' "$_read_text" | xclip -selection primary
            VOXREFINER_MENU=1 "$SCRIPT_DIR/selection_to_voice.sh"
            ;;
        z|Z)
            printf '%s' "${corrected_text:-$raw_text}" | xclip -selection primary
            VOXREFINER_MENU=1 "$SCRIPT_DIR/selection_to_insight.sh"
            ;;
        p|P)
            printf '%s' "${corrected_text:-$raw_text}" | xclip -selection primary
            VOXREFINER_MENU=1 "$SCRIPT_DIR/selection_to_search.sh"
            ;;
        f|F)
            printf '%s' "${corrected_text:-$raw_text}" | xclip -selection primary
            VOXREFINER_MENU=1 "$SCRIPT_DIR/selection_to_factcheck.sh"
            ;;
        s|S)
            _settings_flow
            ;;
        m|M)
            if [ -n "${VOXREFINER_MENU:-}" ]; then exit 0; fi
            exec "$SCRIPT_DIR/vox-refiner-menu.sh"
            ;;
        *)
            break
            ;;
    esac
done

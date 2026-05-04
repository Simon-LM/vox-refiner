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

# Session timestamp — shared by MP3 and TXT filenames
_TIMESTAMP=$(date '+%Y-%m-%d_%Hh%M')
MP3_FILE="$MEDIA_DIR/${_TIMESTAMP}.mp3"
_BASE_NAME=""  # set after slug generation (post-transcription)

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

# ─── File picker ─────────────────────────────────────────────────────────────

_pick_media_file() {
    if command -v zenity >/dev/null 2>&1; then
        zenity --file-selection \
            --title="Media Transcribe — Select audio/video file" \
            --file-filter="Audio/Video|*.mp3 *.wav *.m4a *.ogg *.flac *.aac *.opus *.mp4 *.mkv *.mov *.avi *.webm *.ts *.flv" \
            --file-filter="All files|*" \
            2>/dev/null
        return
    fi
    # Fallback: manual input via /dev/tty (survives $() subshell)
    printf '\n  %b\n' "${C_DIM}zenity not found — type the file path manually.${C_RESET}" >/dev/tty
    printf '  Install: sudo apt install zenity\n\n' >/dev/tty
    printf '  Path to audio/video file: ' >/dev/tty
    read -r _manual_path </dev/tty
    _manual_path="$(printf '%s' "$_manual_path" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    _manual_path="${_manual_path/#\~/$HOME}"
    printf '%s' "$_manual_path"
}

# ─── Storage info ─────────────────────────────────────────────────────────────

_show_storage_info() {
    local _count _size
    _count=$(find "$MEDIA_DIR" -maxdepth 1 -type f | wc -l)
    _size=$(du -sh "$MEDIA_DIR" 2>/dev/null | cut -f1)
    if [ "$_count" -gt 0 ]; then
        printf "  ${C_DIM}📁 recordings/media — %s file(s) · %s${C_RESET}\n" \
            "$_count" "${_size:-?}"
        echo ""
    fi
}

# ─── Landing menu ────────────────────────────────────────────────────────────

_landing_delete() {
    echo ""
    _sep
    _del_files=()
    while IFS= read -r -d '' _f; do
        _del_files+=("$_f")
    done < <(find "$MEDIA_DIR" -maxdepth 1 -type f -print0 | sort -z)

    if [ "${#_del_files[@]}" -eq 0 ]; then
        _warn "No files in recordings/media."
        printf "  ${C_DIM}Press Enter to continue...${C_RESET}"
        read -r
        return
    fi

    for _i in "${!_del_files[@]}"; do
        _sz=$(du -h "${_del_files[$_i]}" 2>/dev/null | cut -f1)
        printf "  ${C_BOLD}[%d]${C_RESET} %s  ${C_DIM}(%s)${C_RESET}\n" \
            "$((_i + 1))" "$(basename "${_del_files[$_i]}")" "$_sz"
    done
    echo ""
    printf "  Number to delete  ${C_BOLD}[a]${C_RESET} Delete all  ${C_BOLD}[q]${C_RESET} Cancel: "
    read -r _del_choice
    case "$_del_choice" in
        q|Q) ;;
        a|A)
            rm -f "${_del_files[@]}"
            _success "All files deleted."
            printf "  ${C_DIM}Press Enter to continue...${C_RESET}"
            read -r
            ;;
        *)
            if [[ "$_del_choice" =~ ^[0-9]+$ ]] \
                && [ "$_del_choice" -ge 1 ] \
                && [ "$_del_choice" -le "${#_del_files[@]}" ]; then
                _del_target="${_del_files[$((_del_choice - 1))]}"
                rm -f "$_del_target"
                _success "Deleted: $(basename "$_del_target")"
            else
                _warn "Invalid selection."
            fi
            printf "  ${C_DIM}Press Enter to continue...${C_RESET}"
            read -r
            ;;
    esac
}

while true; do
    clear
    echo ""
    _header "MEDIA TRANSCRIBE" "🎞→📋"
    echo ""
    _show_storage_info
    printf "  ${C_DIM}Accepted: mp3, wav, m4a, ogg, flac, mp4, mkv, mov, avi, webm, …${C_RESET}\n"
    echo ""
    _sep
    printf "  ${C_BOLD}[n]${C_RESET} New transcription  ${C_BOLD}[o]${C_RESET} Open folder  ${C_BOLD}[d]${C_RESET} Delete files  ${C_BOLD}[m]${C_RESET} Menu VoxRefiner  ${C_BOLD}[q]${C_RESET} Quit: "
    read -r _landing
    case "$_landing" in
        n|N) break ;;
        o|O)
            xdg-open "$MEDIA_DIR" 2>/dev/null &
            echo ""
            _info "Opening folder: $MEDIA_DIR"
            echo ""
            printf "  ${C_DIM}Press Enter to continue...${C_RESET}"
            read -r
            ;;
        d|D) _landing_delete ;;
        m|M)
            if [ -n "${VOXREFINER_MENU:-}" ]; then exit 0; fi
            exec "$SCRIPT_DIR/vox-refiner-menu.sh"
            ;;
        q|Q|*) exit 0 ;;
    esac
done

# ─── File input ──────────────────────────────────────────────────────────────

# Refresh timestamp now that we know a transcription is starting
_TIMESTAMP=$(date '+%Y-%m-%d_%Hh%M')
MP3_FILE="$MEDIA_DIR/${_TIMESTAMP}.mp3"

while true; do
    _media_file=$(_pick_media_file)

    # Trim leading/trailing whitespace + expand ~ (needed for fallback path)
    _media_file="$(printf '%s' "$_media_file" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    _media_file="${_media_file/#\~/$HOME}"

    if [ -z "$_media_file" ]; then
        exit 0
    fi

    # Show file name + size and ask for confirmation
    _file_size=$(du -h "$_media_file" 2>/dev/null | cut -f1)
    echo ""
    printf "  ${C_BOLD}%s${C_RESET}  ${C_DIM}(%s)${C_RESET}\n" \
        "$(basename "$_media_file")" "${_file_size:-?}"
    echo ""
    printf "  ${C_BOLD}[Entrée]${C_RESET} Confirmer  ${C_BOLD}[n]${C_RESET} Choisir un autre fichier  ${C_BOLD}[q]${C_RESET} Annuler : "
    read -r _confirm
    case "$_confirm" in
        n|N) continue ;;
        q|Q) exit 0 ;;
        *) break ;;
    esac
done

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

# ─── Post-transcription save ─────────────────────────────────────────────────
# First call: generates slug, renames MP3, saves TXT.
# Subsequent calls (retry): overwrites TXT only, keeps existing slug/name.

_finalize_session() {
    if [ -z "$_BASE_NAME" ]; then
        _process "Generating filename..."
        local _slug
        _slug=$(printf '%s' "$raw_text" | "$VENV_PYTHON" -m src.slug 2>&3)
        _slug="${_slug:-transcription}"
        _BASE_NAME="${_TIMESTAMP}_${_slug}"

        local _new_mp3="$MEDIA_DIR/${_BASE_NAME}.mp3"
        if [ -f "$MP3_FILE" ] && [ "$MP3_FILE" != "$_new_mp3" ]; then
            mv "$MP3_FILE" "$_new_mp3"
            MP3_FILE="$_new_mp3"
        fi
    fi

    printf '%s' "$raw_text" > "$MEDIA_DIR/${_BASE_NAME}.txt"
    _success "Saved: ${_BASE_NAME}.txt"
}

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

if _run_transcription; then
    _finalize_session
fi

# ─── Session state ────────────────────────────────────────────────────────────

_correct_done=0
corrected_text=""
_translate_done=0
translated_text=""

_SETTING_TRANSLATE_LANG="${MEDIA_TRANSLATE_LANG:-${OUTPUT_DEFAULT_LANG:-en}}"

# ─── Post-action menu ────────────────────────────────────────────────────────

while true; do
    clear
    echo ""
    _header "MEDIA TRANSCRIBE" "🎞→📋"
    echo ""
    _show_storage_info
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
    _menu_line="  ${C_BOLD}[n]${C_RESET} New file  ${C_BOLD}[c]${C_RESET} Correct  ${C_BOLD}[t]${C_RESET} Translate  ${C_BOLD}[l]${C_RESET} Read aloud"
    _menu_line="$_menu_line  ${C_BOLD}[z]${C_RESET} Summarise  ${C_BOLD}[p]${C_RESET} Search  ${C_BOLD}[f]${C_RESET} Fact-check"
    _menu_line="$_menu_line  ${C_BOLD}[x]${C_RESET} Export  ${C_BOLD}[o]${C_RESET} Open folder  ${C_BOLD}[d]${C_RESET} Delete files"
    _menu_line="$_menu_line  ${C_BOLD}[s]${C_RESET} Settings  ${C_BOLD}[m]${C_RESET} Menu VoxRefiner"
    printf "  %b: " "$_menu_line"
    read -r _action
    case "$_action" in
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
            _prev_translate_done="$_translate_done"
            _translate_flow "${corrected_text:-$raw_text}" "MEDIA_TRANSLATE_LANG"
            if [ "$_translate_done" -eq 1 ] && [ "$_prev_translate_done" -eq 0 ] \
                && [ -n "$_BASE_NAME" ] && [ -n "$translated_text" ]; then
                _lang_suffix="${_SETTING_TRANSLATE_LANG:-en}"
                _trans_file="$MEDIA_DIR/${_BASE_NAME}_${_lang_suffix}.txt"
                printf '%s' "$translated_text" > "$_trans_file"
                _success "Saved: $(basename "$_trans_file")"
            fi
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
        x|X)
            _export_text="${corrected_text:-$raw_text}"
            _export_base="${_BASE_NAME:-transcription}"
            if command -v zenity >/dev/null 2>&1; then
                _dest=$(zenity --file-selection --save \
                    --title="Export transcription" \
                    --filename="$HOME/Downloads/${_export_base}.txt" \
                    2>/dev/null)
            else
                echo ""
                printf "  Export path [default: %s]: " \
                    "$HOME/Downloads/${_export_base}.txt"
                read -r _dest
                _dest="${_dest:-$HOME/Downloads/${_export_base}.txt}"
                _dest="$(printf '%s' "$_dest" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
                _dest="${_dest/#\~/$HOME}"
            fi
            if [ -n "$_dest" ]; then
                printf '%s' "$_export_text" > "$_dest"
                echo ""
                _success "Exported: $_dest"
            fi
            echo ""
            printf "  ${C_DIM}Press Enter to continue...${C_RESET}"
            read -r
            ;;
        o|O)
            xdg-open "$MEDIA_DIR" 2>/dev/null &
            echo ""
            _info "Opening folder: $MEDIA_DIR"
            echo ""
            printf "  ${C_DIM}Press Enter to continue...${C_RESET}"
            read -r
            ;;
        d|D)
            _landing_delete
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

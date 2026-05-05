#!/bin/bash
# VoxRefiner — Media Transcribe (V2)
# Import an audio/video file → text transcription or SRT subtitles.
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

# Session timestamp and state — set when user chooses [n]/[s]/[a]
_TIMESTAMP=""
MP3_FILE=""
_BASE_NAME=""

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

# ─── Rename helper — renames all files sharing the same base name ─────────────

_do_rename() {
    local _old_base="$1" _new_base="$2"
    [ -z "$_old_base" ] || [ -z "$_new_base" ] && return 1
    local _f _suffix
    for _f in "$MEDIA_DIR"/"${_old_base}"*; do
        [ -f "$_f" ] || continue
        _suffix="${_f#$MEDIA_DIR/$_old_base}"
        mv -- "$_f" "$MEDIA_DIR/${_new_base}${_suffix}"
    done
}

# ─── Context collection sub-menu (shared by [c] handlers) ─────────────────────
# Sets global $_context. Returns 1 to signal cancellation.

_collect_context() {
    _context=""
    printf "  How to provide context?\n"
    printf "  ${C_BOLD}[k]${C_RESET} Type/paste  ${C_BOLD}[f]${C_RESET} Load file  ${C_BOLD}[v]${C_RESET} Record voice  ${C_BOLD}[m]${C_RESET} Cancel: "
    read -r _ctx_mode
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
                return 1
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
        m|M|*) return 1 ;;
    esac
    return 0
}

# ─── Delete helper (shared by landing + post-action) ─────────────────────────

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

# ─── Landing menu ─────────────────────────────────────────────────────────────

_MODE=""

while true; do
    clear
    echo ""
    _header "MEDIA TRANSCRIBE" "🎞→📋"
    echo ""
    _show_storage_info
    printf "  ${C_DIM}Accepted: mp3, wav, m4a, ogg, flac, mp4, mkv, mov, avi, webm, …${C_RESET}\n"
    echo ""
    _sep
    printf "  ${C_BOLD}[n]${C_RESET} New transcription\n"
    echo ""
    printf "  Subtitles:\n"
    printf "  ${C_BOLD}[s]${C_RESET} Standard SRT\n"
    printf "  ${C_BOLD}[a]${C_RESET} Standard SRT + Accessibility (named speakers)\n"
    echo ""
    printf "  ${C_BOLD}[o]${C_RESET} Open folder  ${C_BOLD}[d]${C_RESET} Delete files  ${C_BOLD}[m]${C_RESET} Menu VoxRefiner  ${C_BOLD}[q]${C_RESET} Quit: "
    read -r _landing
    case "$_landing" in
        n|N) _MODE="text";  break ;;
        s|S) _MODE="srt";   break ;;
        a|A) _MODE="srt_a"; break ;;
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

# ─── Session timestamp (set once user has chosen a mode) ─────────────────────

_TIMESTAMP=$(date '+%Y-%m-%d_%Hh%M')
MP3_FILE="$MEDIA_DIR/${_TIMESTAMP}.mp3"

# ─── File input ──────────────────────────────────────────────────────────────

while true; do
    _media_file=$(_pick_media_file)

    _media_file="$(printf '%s' "$_media_file" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    _media_file="${_media_file/#\~/$HOME}"

    if [ -z "$_media_file" ]; then
        exec "$0"
    fi

    _file_size=$(du -h "$_media_file" 2>/dev/null | cut -f1)
    echo ""
    printf "  ${C_BOLD}%s${C_RESET}  ${C_DIM}(%s)${C_RESET}\n" \
        "$(basename "$_media_file")" "${_file_size:-?}"
    echo ""
    printf "  ${C_BOLD}[Entrée]${C_RESET} Confirmer  ${C_BOLD}[n]${C_RESET} Choisir un autre fichier  ${C_BOLD}[q]${C_RESET} Annuler : "
    read -r _confirm
    case "$_confirm" in
        n|N) continue ;;
        q|Q) exec "$0" ;;
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

# ═════════════════════════════════════════════════════════════════════════════
# MODE: TEXT TRANSCRIPTION
# ═════════════════════════════════════════════════════════════════════════════

if [ "$_MODE" = "text" ]; then

# ─── Post-transcription save (slug + rename) ─────────────────────────────────

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

# ─── Transcription helper ─────────────────────────────────────────────────────

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

# ─── Text post-action menu ────────────────────────────────────────────────────

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
    _menu_line="  ${C_BOLD}[n]${C_RESET} New file  ${C_BOLD}[c]${C_RESET} Fix errors (AI context)  ${C_BOLD}[e]${C_RESET} Rename files  ${C_BOLD}[t]${C_RESET} Translate  ${C_BOLD}[l]${C_RESET} Read aloud"
    _menu_line="$_menu_line  ${C_BOLD}[z]${C_RESET} Summarise  ${C_BOLD}[p]${C_RESET} Search  ${C_BOLD}[f]${C_RESET} Fact-check"
    _menu_line="$_menu_line  ${C_BOLD}[x]${C_RESET} Export  ${C_BOLD}[o]${C_RESET} Open folder  ${C_BOLD}[d]${C_RESET} Delete files"
    _menu_line="$_menu_line  ${C_BOLD}[s]${C_RESET} Settings  ${C_BOLD}[m]${C_RESET} Menu VoxRefiner"
    printf "  %b: " "$_menu_line"
    read -r _action
    case "$_action" in
        n|N) exec "$0" ;;
        c|C)
            echo ""
            _sep
            if ! _collect_context; then continue; fi
            if [ -z "$_context" ]; then _warn "No context provided."; continue; fi
            echo ""
            _process "Fixing transcription errors with AI context..."
            echo ""
            _new_corrected=$(printf '%s' "$raw_text" | \
                "$VENV_PYTHON" -m src.correct "$_context" 2>&3)
            if [ -n "$_new_corrected" ]; then
                corrected_text="$_new_corrected"
                printf '%s' "$corrected_text" | xclip -selection clipboard
                printf '%s' "$corrected_text" | xclip -selection primary
                _correct_done=1
                echo ""
                _success "Fixed text copied to clipboard"
            else
                _warn "Fix returned empty."
            fi
            ;;
        e|E)
            if [ -z "$_BASE_NAME" ]; then _warn "No file saved yet."; continue; fi
            _current_slug="${_BASE_NAME#${_TIMESTAMP}_}"
            echo ""
            printf "  Current: %s\n" "$_BASE_NAME"
            printf "  New name [%s]: " "$_current_slug"
            read -r _new_slug
            _new_slug="$(printf '%s' "$_new_slug" | tr -cd '[:print:]' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
            _new_slug="${_new_slug:-$_current_slug}"
            if [ "$_new_slug" = "$_current_slug" ]; then continue; fi
            _new_base="${_TIMESTAMP}_${_new_slug}"
            _do_rename "$_BASE_NAME" "$_new_base"
            MP3_FILE="$MEDIA_DIR/${_new_base}.mp3"
            _BASE_NAME="$_new_base"
            echo ""
            _success "Renamed to: $_new_base"
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
            printf '%s' "${corrected_text:-$raw_text}" | xclip -selection primary
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
            _export_base="${_BASE_NAME:-transcription}"
            _txt_file="$MEDIA_DIR/${_export_base}.txt"
            if command -v zenity >/dev/null 2>&1; then
                _dest=$(zenity --file-selection --save \
                    --title="Export transcription" \
                    --filename="$_txt_file" \
                    2>/dev/null)
            else
                echo ""
                printf "  Export path [default: %s]: " "$HOME/Downloads/${_export_base}.txt"
                read -r _dest
                _dest="${_dest:-$HOME/Downloads/${_export_base}.txt}"
                _dest="$(printf '%s' "$_dest" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
                _dest="${_dest/#\~/$HOME}"
            fi
            if [ -n "$_dest" ] && [ "$_dest" != "$_txt_file" ]; then
                printf '%s' "${corrected_text:-$raw_text}" > "$_dest"
                echo ""
                _success "Exported: $_dest"
            fi
            ;;
        o|O)
            xdg-open "$MEDIA_DIR" 2>/dev/null &
            echo ""
            _info "Opening folder: $MEDIA_DIR"
            echo ""
            printf "  ${C_DIM}Press Enter to continue...${C_RESET}"
            read -r
            ;;
        d|D) _landing_delete ;;
        s|S) _settings_flow ;;
        m|M)
            if [ -n "${VOXREFINER_MENU:-}" ]; then exit 0; fi
            exec "$SCRIPT_DIR/vox-refiner-menu.sh"
            ;;
        *) break ;;
    esac
done

fi  # end text mode

# ═════════════════════════════════════════════════════════════════════════════
# MODE: STANDARD SRT
# ═════════════════════════════════════════════════════════════════════════════

if [ "$_MODE" = "srt" ]; then

clear
echo ""
_header "MEDIA TRANSCRIBE — Standard SRT" "🎞→💬"
echo ""
_process "Generating subtitles via Voxtral..."
echo ""

_srt_content=$("$VENV_PYTHON" -m src.subtitles "$MP3_FILE" 2>&3)

if [ -z "$_srt_content" ]; then
    echo ""
    _error "Subtitle generation returned empty."
    echo ""
    printf "  ${C_DIM}Press Enter to exit...${C_RESET}"
    read -r
    exec "$0"
fi

# Save with slug-based name
_process "Generating filename..."
_srt_text=$(printf '%s' "$_srt_content" | grep -Ev '^[0-9]+$|-->|^[[:space:]]*$')
_slug=$(printf '%s' "$_srt_text" | "$VENV_PYTHON" -m src.slug 2>&3)
_slug="${_slug:-subtitles}"
_BASE_NAME="${_TIMESTAMP}_${_slug}"

# Rename MP3
_new_mp3="$MEDIA_DIR/${_BASE_NAME}.mp3"
if [ -f "$MP3_FILE" ] && [ "$MP3_FILE" != "$_new_mp3" ]; then
    mv "$MP3_FILE" "$_new_mp3"
    MP3_FILE="$_new_mp3"
fi

_SRT_FILE="$MEDIA_DIR/${_BASE_NAME}.srt"
printf '%s' "$_srt_content" > "$_SRT_FILE"

echo ""
_header "SUBTITLES — Standard SRT" "💬"
_success "Saved: ${_BASE_NAME}.srt"
echo ""
printf "${C_BG_CYAN} %s ${C_RESET}\n" "$_srt_content"
echo ""

# ─── SRT post-action menu ─────────────────────────────────────────────────────

_SETTING_TRANSLATE_LANG="${MEDIA_TRANSLATE_LANG:-${OUTPUT_DEFAULT_LANG:-en}}"
# Plain dialogue text (no timecodes) for tools that expect plain text
_srt_plain="$_srt_text"
_translate_done=0
translated_text=""
_SRT_CORRECTED_FILE=""

while true; do
    echo ""
    _sep
    printf "  ${C_BOLD}[c]${C_RESET} Fix errors (AI context)  ${C_BOLD}[e]${C_RESET} Rename files  ${C_BOLD}[x]${C_RESET} Export SRT"
    printf "  ${C_BOLD}[t]${C_RESET} Translate  ${C_BOLD}[l]${C_RESET} Read aloud"
    printf "  ${C_BOLD}[z]${C_RESET} Summarise  ${C_BOLD}[p]${C_RESET} Search  ${C_BOLD}[f]${C_RESET} Fact-check"
    printf "  ${C_BOLD}[o]${C_RESET} Open folder  ${C_BOLD}[d]${C_RESET} Delete"
    printf "  ${C_BOLD}[s]${C_RESET} Settings  ${C_BOLD}[n]${C_RESET} New  ${C_BOLD}[m]${C_RESET} Menu VoxRefiner: "
    read -r _action
    case "$_action" in
        c|C)
            echo ""
            _sep
            if ! _collect_context; then continue; fi
            if [ -z "$_context" ]; then _warn "No context provided."; continue; fi
            _srt_ctx="$(printf '[SRT format — preserve all timecodes, block numbers, and blank lines between blocks]\n%s' "$_context")"
            echo ""
            _process "Fixing subtitle errors with AI context..."
            echo ""
            _fixed=$(printf '%s' "$_srt_content" | \
                "$VENV_PYTHON" -m src.correct "$_srt_ctx" 2>&3)
            if [ -n "$_fixed" ]; then
                # First correction: create _corrected file; subsequent: update it
                [ -z "$_SRT_CORRECTED_FILE" ] && \
                    _SRT_CORRECTED_FILE="$MEDIA_DIR/${_BASE_NAME}_corrected.srt"
                printf '%s' "$_fixed" > "$_SRT_CORRECTED_FILE"
                _srt_content="$_fixed"
                _srt_plain=$(printf '%s' "$_srt_content" | grep -Ev '^[0-9]+$|-->|^[[:space:]]*$')
                printf '%s' "$_fixed" | xclip -selection clipboard
                printf '%s' "$_fixed" | xclip -selection primary
                echo ""
                _success "Saved: $(basename "$_SRT_CORRECTED_FILE")  ${C_DIM}(original preserved)${C_RESET}"
                echo ""
                printf "${C_BG_CYAN} %s ${C_RESET}\n" "$_fixed"
                echo ""
            else
                _warn "Fix returned empty."
            fi
            ;;
        e|E)
            _current_slug="${_BASE_NAME#${_TIMESTAMP}_}"
            echo ""
            printf "  Current: %s\n" "$_BASE_NAME"
            printf "  New name [%s]: " "$_current_slug"
            read -r _new_slug
            _new_slug="$(printf '%s' "$_new_slug" | tr -cd '[:print:]' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
            _new_slug="${_new_slug:-$_current_slug}"
            if [ "$_new_slug" = "$_current_slug" ]; then continue; fi
            _new_base="${_TIMESTAMP}_${_new_slug}"
            _do_rename "$_BASE_NAME" "$_new_base"
            MP3_FILE="$MEDIA_DIR/${_new_base}.mp3"
            _SRT_FILE="$MEDIA_DIR/${_new_base}.srt"
            [ -n "$_SRT_CORRECTED_FILE" ] && \
                _SRT_CORRECTED_FILE="$MEDIA_DIR/${_new_base}_corrected.srt"
            _BASE_NAME="$_new_base"
            echo ""
            _success "Renamed to: $_new_base"
            ;;
        x|X)
            _export_src="${_SRT_CORRECTED_FILE:-$_SRT_FILE}"
            if [ -n "$_SRT_CORRECTED_FILE" ] && [ ! -f "$_SRT_CORRECTED_FILE" ]; then
                _warn "Corrected file not found, exporting original: $(basename "$_SRT_FILE")"
                _export_src="$_SRT_FILE"
            fi
            echo ""
            _info "Exporting: $(basename "$_export_src")"
            if command -v zenity >/dev/null 2>&1; then
                _dest=$(zenity --file-selection --save \
                    --title="Export SRT" \
                    --filename="$_export_src" \
                    2>/dev/null)
            else
                echo ""
                printf "  Export path [default: %s]: " "$HOME/Downloads/${_BASE_NAME}.srt"
                read -r _dest
                _dest="${_dest:-$HOME/Downloads/${_BASE_NAME}.srt}"
                _dest="$(printf '%s' "$_dest" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
                _dest="${_dest/#\~/$HOME}"
            fi
            if [ -n "$_dest" ] && [ "$_dest" != "$_export_src" ]; then
                cp "$_export_src" "$_dest"
                echo ""
                _success "Exported: $_dest"
            fi
            ;;
        t|T)
            _prev_translate_done="$_translate_done"
            _translate_flow "$_srt_plain" "MEDIA_TRANSLATE_LANG"
            if [ "$_translate_done" -eq 1 ] && [ "$_prev_translate_done" -eq 0 ] \
                && [ -n "$_BASE_NAME" ] && [ -n "$translated_text" ]; then
                _lang_suffix="${_SETTING_TRANSLATE_LANG:-en}"
                _trans_file="$MEDIA_DIR/${_BASE_NAME}_${_lang_suffix}.txt"
                printf '%s' "$translated_text" > "$_trans_file"
                _success "Saved: $(basename "$_trans_file")"
            fi
            ;;
        l|L)
            printf '%s' "$_srt_plain" | xclip -selection primary
            VOXREFINER_MENU=1 "$SCRIPT_DIR/selection_to_voice.sh"
            ;;
        z|Z)
            printf '%s' "$_srt_plain" | xclip -selection primary
            VOXREFINER_MENU=1 "$SCRIPT_DIR/selection_to_insight.sh"
            ;;
        p|P)
            printf '%s' "$_srt_plain" | xclip -selection primary
            VOXREFINER_MENU=1 "$SCRIPT_DIR/selection_to_search.sh"
            ;;
        f|F)
            printf '%s' "$_srt_plain" | xclip -selection primary
            VOXREFINER_MENU=1 "$SCRIPT_DIR/selection_to_factcheck.sh"
            ;;
        o|O)
            xdg-open "$MEDIA_DIR" 2>/dev/null &
            echo ""
            _info "Opening folder: $MEDIA_DIR"
            echo ""
            printf "  ${C_DIM}Press Enter to continue...${C_RESET}"
            read -r
            ;;
        d|D) _landing_delete ;;
        s|S) _settings_flow ;;
        n|N) exec "$0" ;;
        m|M)
            if [ -n "${VOXREFINER_MENU:-}" ]; then exit 0; fi
            exec "$SCRIPT_DIR/vox-refiner-menu.sh"
            ;;
        *) break ;;
    esac
done

fi  # end srt mode

# ═════════════════════════════════════════════════════════════════════════════
# MODE: ACCESSIBILITY SRT
# ═════════════════════════════════════════════════════════════════════════════

if [ "$_MODE" = "srt_a" ]; then

clear
echo ""
_header "MEDIA TRANSCRIBE — Accessibility SRT" "🎞→💬"
echo ""
_process "Transcribing with diarization via Voxtral..."
echo ""

_SEGMENTS_FILE="$MEDIA_DIR/${_TIMESTAMP}_segments.json"

# Step 1: transcribe + dump segments, print speaker_ids to stdout
_speaker_list=$("$VENV_PYTHON" -m src.subtitles "$MP3_FILE" \
    --diarize \
    --dump-segments "$_SEGMENTS_FILE" 2>&3)

if [ -z "$_speaker_list" ] || [ ! -f "$_SEGMENTS_FILE" ]; then
    echo ""
    _error "Transcription returned no speakers."
    echo ""
    rm -f "$_SEGMENTS_FILE"
    printf "  ${C_DIM}Press Enter to exit...${C_RESET}"
    read -r
    exec "$0"
fi

# Keep segments file alive until script exits (needed for [r] Rename)
# shellcheck disable=SC2064
trap "rm -f '$_SEGMENTS_FILE'" EXIT

# Step 2: show dialogue preview so user knows who says what before naming
echo ""
_header "DIALOGUE PREVIEW" "👁"
echo ""
_preview_text=$("$VENV_PYTHON" -m src.subtitles --preview "$_SEGMENTS_FILE" 2>&3)
printf '%s\n' "$_preview_text"
echo ""
_sep

# Step 3: AI name suggestions (used as defaults in naming prompts)
echo ""
_ai_suggestions=$("$VENV_PYTHON" -m src.subtitles \
    --suggest-names "$_SEGMENTS_FILE" 2>&3) || true

declare -A _suggestions
declare -A _cur_names
if [ -n "$_ai_suggestions" ]; then
    while IFS='=' read -r _k _v; do
        [ -n "$_k" ] && _suggestions["$_k"]="${_v}"
    done <<< "$_ai_suggestions"
fi

# Step 4: name each speaker interactively (AI suggestion shown as default)
echo ""
_header "NAME THE SPEAKERS" "🎙"
echo ""
printf "  ${C_DIM}Press Enter to accept the suggestion, or type a custom name.${C_RESET}\n"
echo ""

_speaker_map=""
_idx=1
while IFS= read -r _sid <&4; do
    _default="${_suggestions[$_sid]:-$_sid}"
    printf "  ${C_BOLD}[%d]${C_RESET} %s → name [${C_DIM}%s${C_RESET}]: " "$_idx" "$_sid" "$_default"
    read -r _name
    _name="${_name:-$_default}"
    _cur_names["$_sid"]="$_name"
    if [ -n "$_speaker_map" ]; then
        _speaker_map="${_speaker_map},${_sid}=${_name}"
    else
        _speaker_map="${_sid}=${_name}"
    fi
    _idx=$((_idx + 1))
done 4<<< "$_speaker_list"

# Step 5: generate SRT from cached segments (no second API call)
echo ""
_process "Generating accessibility SRT..."
echo ""

_srt_content=$("$VENV_PYTHON" -m src.subtitles \
    --from-segments "$_SEGMENTS_FILE" \
    --speaker-map "$_speaker_map" 2>&3)

if [ -z "$_srt_content" ]; then
    echo ""
    _error "SRT generation returned empty."
    echo ""
    printf "  ${C_DIM}Press Enter to exit...${C_RESET}"
    read -r
    exec "$0"
fi

# Save with slug-based name
_process "Generating filename..."
_srt_text=$(printf '%s' "$_srt_content" | grep -Ev '^[0-9]+$|-->|^[[:space:]]*$')
_slug=$(printf '%s' "$_srt_text" | "$VENV_PYTHON" -m src.slug 2>&3)
_slug="${_slug:-subtitles-accessibility}"
_BASE_NAME="${_TIMESTAMP}_${_slug}"

# Rename MP3
_new_mp3="$MEDIA_DIR/${_BASE_NAME}.mp3"
if [ -f "$MP3_FILE" ] && [ "$MP3_FILE" != "$_new_mp3" ]; then
    mv "$MP3_FILE" "$_new_mp3"
    MP3_FILE="$_new_mp3"
fi

_SRT_FILE="$MEDIA_DIR/${_BASE_NAME}_accessibility.srt"
printf '%s' "$_srt_content" > "$_SRT_FILE"

echo ""
_header "SUBTITLES — Accessibility SRT" "💬"
_success "Saved: ${_BASE_NAME}_accessibility.srt"
echo ""
printf "${C_BG_CYAN} %s ${C_RESET}\n" "$_srt_content"
echo ""

# ─── Accessibility SRT post-action menu ──────────────────────────────────────

_SETTING_TRANSLATE_LANG="${MEDIA_TRANSLATE_LANG:-${OUTPUT_DEFAULT_LANG:-en}}"
_translate_done=0
translated_text=""
_SRT_CORRECTED_FILE=""

while true; do
    echo ""
    _sep
    printf "  ${C_BOLD}[r]${C_RESET} Rename speakers  ${C_BOLD}[c]${C_RESET} Fix errors (AI context)  ${C_BOLD}[e]${C_RESET} Rename files  ${C_BOLD}[x]${C_RESET} Export SRT"
    printf "  ${C_BOLD}[t]${C_RESET} Translate  ${C_BOLD}[l]${C_RESET} Read aloud"
    printf "  ${C_BOLD}[z]${C_RESET} Summarise  ${C_BOLD}[p]${C_RESET} Search  ${C_BOLD}[f]${C_RESET} Fact-check"
    printf "  ${C_BOLD}[o]${C_RESET} Open folder  ${C_BOLD}[d]${C_RESET} Delete"
    printf "  ${C_BOLD}[s]${C_RESET} Settings  ${C_BOLD}[n]${C_RESET} New  ${C_BOLD}[m]${C_RESET} Menu VoxRefiner: "
    read -r _action
    case "$_action" in
        r|R)
            echo ""
            _header "DIALOGUE PREVIEW" "👁"
            echo ""
            printf '%s\n' "$_preview_text"
            echo ""
            _sep
            echo ""
            _header "RENAME SPEAKERS" "✏"
            echo ""
            printf "  ${C_DIM}Press Enter to keep the current name.${C_RESET}\n"
            echo ""
            _speaker_map=""
            _idx=1
            while IFS= read -r _sid <&4; do
                _cur_name="${_cur_names[$_sid]:-$_sid}"
                printf "  ${C_BOLD}[%d]${C_RESET} %s → name [${C_DIM}%s${C_RESET}]: " "$_idx" "$_sid" "$_cur_name"
                read -r _name
                _name="${_name:-$_cur_name}"
                _cur_names["$_sid"]="$_name"
                if [ -n "$_speaker_map" ]; then
                    _speaker_map="${_speaker_map},${_sid}=${_name}"
                else
                    _speaker_map="${_sid}=${_name}"
                fi
                _idx=$((_idx + 1))
            done 4<<< "$_speaker_list"

            echo ""
            _process "Regenerating SRT..."
            echo ""
            _srt_content=$("$VENV_PYTHON" -m src.subtitles \
                --from-segments "$_SEGMENTS_FILE" \
                --speaker-map "$_speaker_map" 2>&3)

            if [ -n "$_srt_content" ]; then
                printf '%s' "$_srt_content" > "$_SRT_FILE"
                echo ""
                _header "SUBTITLES — Accessibility SRT (updated)" "💬"
                _success "Saved: ${_BASE_NAME}_accessibility.srt"
                echo ""
                printf "${C_BG_CYAN} %s ${C_RESET}\n" "$_srt_content"
                echo ""
            else
                _warn "SRT regeneration failed."
            fi
            ;;
        x|X)
            _export_src="${_SRT_CORRECTED_FILE:-$_SRT_FILE}"
            if [ -n "$_SRT_CORRECTED_FILE" ] && [ ! -f "$_SRT_CORRECTED_FILE" ]; then
                _warn "Corrected file not found, exporting original: $(basename "$_SRT_FILE")"
                _export_src="$_SRT_FILE"
            fi
            echo ""
            _info "Exporting: $(basename "$_export_src")"
            if command -v zenity >/dev/null 2>&1; then
                _dest=$(zenity --file-selection --save \
                    --title="Export accessibility SRT" \
                    --filename="$_export_src" \
                    2>/dev/null)
            else
                echo ""
                printf "  Export path [default: %s]: " \
                    "$HOME/Downloads/${_BASE_NAME}_accessibility.srt"
                read -r _dest
                _dest="${_dest:-$HOME/Downloads/${_BASE_NAME}_accessibility.srt}"
                _dest="$(printf '%s' "$_dest" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
                _dest="${_dest/#\~/$HOME}"
            fi
            if [ -n "$_dest" ] && [ "$_dest" != "$_export_src" ]; then
                cp "$_export_src" "$_dest"
                echo ""
                _success "Exported: $_dest"
            fi
            ;;
        c|C)
            echo ""
            _sep
            if ! _collect_context; then continue; fi
            if [ -z "$_context" ]; then _warn "No context provided."; continue; fi
            _srt_ctx="$(printf '[SRT format — preserve all timecodes, block numbers, and blank lines between blocks]\n%s' "$_context")"
            echo ""
            _process "Fixing subtitle errors with AI context..."
            echo ""
            _fixed=$(printf '%s' "$_srt_content" | \
                "$VENV_PYTHON" -m src.correct "$_srt_ctx" 2>&3)
            if [ -n "$_fixed" ]; then
                # First correction: create _corrected file; subsequent: update it
                [ -z "$_SRT_CORRECTED_FILE" ] && \
                    _SRT_CORRECTED_FILE="$MEDIA_DIR/${_BASE_NAME}_accessibility_corrected.srt"
                printf '%s' "$_fixed" > "$_SRT_CORRECTED_FILE"
                _srt_content="$_fixed"
                printf '%s' "$_fixed" | xclip -selection clipboard
                printf '%s' "$_fixed" | xclip -selection primary
                echo ""
                _success "Saved: $(basename "$_SRT_CORRECTED_FILE")  ${C_DIM}(original preserved)${C_RESET}"
                echo ""
                printf "${C_BG_CYAN} %s ${C_RESET}\n" "$_fixed"
                echo ""
            else
                _warn "Fix returned empty."
            fi
            ;;
        e|E)
            _current_slug="${_BASE_NAME#${_TIMESTAMP}_}"
            echo ""
            printf "  Current: %s\n" "$_BASE_NAME"
            printf "  New name [%s]: " "$_current_slug"
            read -r _new_slug
            _new_slug="$(printf '%s' "$_new_slug" | tr -cd '[:print:]' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
            _new_slug="${_new_slug:-$_current_slug}"
            if [ "$_new_slug" = "$_current_slug" ]; then continue; fi
            _new_base="${_TIMESTAMP}_${_new_slug}"
            _do_rename "$_BASE_NAME" "$_new_base"
            MP3_FILE="$MEDIA_DIR/${_new_base}.mp3"
            _SRT_FILE="$MEDIA_DIR/${_new_base}_accessibility.srt"
            [ -n "$_SRT_CORRECTED_FILE" ] && \
                _SRT_CORRECTED_FILE="$MEDIA_DIR/${_new_base}_accessibility_corrected.srt"
            _BASE_NAME="$_new_base"
            echo ""
            _success "Renamed to: $_new_base"
            ;;
        t|T)
            _prev_translate_done="$_translate_done"
            _translate_flow "$_preview_text" "MEDIA_TRANSLATE_LANG"
            if [ "$_translate_done" -eq 1 ] && [ "$_prev_translate_done" -eq 0 ] \
                && [ -n "$_BASE_NAME" ] && [ -n "$translated_text" ]; then
                _lang_suffix="${_SETTING_TRANSLATE_LANG:-en}"
                _trans_file="$MEDIA_DIR/${_BASE_NAME}_${_lang_suffix}.txt"
                printf '%s' "$translated_text" > "$_trans_file"
                _success "Saved: $(basename "$_trans_file")"
            fi
            ;;
        l|L)
            printf '%s' "$_preview_text" | xclip -selection primary
            VOXREFINER_MENU=1 "$SCRIPT_DIR/selection_to_voice.sh"
            ;;
        z|Z)
            printf '%s' "$_preview_text" | xclip -selection primary
            VOXREFINER_MENU=1 "$SCRIPT_DIR/selection_to_insight.sh"
            ;;
        p|P)
            printf '%s' "$_preview_text" | xclip -selection primary
            VOXREFINER_MENU=1 "$SCRIPT_DIR/selection_to_search.sh"
            ;;
        f|F)
            printf '%s' "$_preview_text" | xclip -selection primary
            VOXREFINER_MENU=1 "$SCRIPT_DIR/selection_to_factcheck.sh"
            ;;
        o|O)
            xdg-open "$MEDIA_DIR" 2>/dev/null &
            echo ""
            _info "Opening folder: $MEDIA_DIR"
            echo ""
            printf "  ${C_DIM}Press Enter to continue...${C_RESET}"
            read -r
            ;;
        d|D) _landing_delete ;;
        s|S) _settings_flow ;;
        n|N) exec "$0" ;;
        m|M)
            if [ -n "${VOXREFINER_MENU:-}" ]; then exit 0; fi
            exec "$SCRIPT_DIR/vox-refiner-menu.sh"
            ;;
        *) break ;;
    esac
done

fi  # end srt_a mode

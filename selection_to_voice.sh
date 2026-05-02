#!/bin/bash
# VoxRefiner — Selection to Voice
# Read selected (or clipboard) text aloud using the default TTS voice.
# Can be launched standalone (keyboard shortcut) or called from the menu.

cd "$(dirname "$0")"
SCRIPT_DIR="$(pwd)"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"

# ─── Shared UI + helpers ─────────────────────────────────────────────────────
# shellcheck disable=SC1091
source "$SCRIPT_DIR/src/ui.sh"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/src/save_audio.sh"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/src/web_display.sh"

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

# ─── Helpers ─────────────────────────────────────────────────────────────────

_lang_name() {
    case "$1" in
        en) echo "English" ;;  fr) echo "French" ;;   de) echo "German" ;;
        es) echo "Spanish" ;;  pt) echo "Portuguese" ;; it) echo "Italian" ;;
        nl) echo "Dutch" ;;    hi) echo "Hindi" ;;    ar) echo "Arabic" ;;
        zh) echo "Chinese" ;;  ja) echo "Japanese" ;; ko) echo "Korean" ;;
        ru) echo "Russian" ;;  pl) echo "Polish" ;;   sv) echo "Swedish" ;;
        *) echo "$1" ;;
    esac
}

# ─── Session state ────────────────────────────────────────────────────────────

_SETTING_VOICE_AUTO_TRANSLATE="${TTS_AUTO_TRANSLATE:-0}"
_SETTING_VOICE_LANG="${TRANSLATE_TARGET_LANG:-${OUTPUT_DEFAULT_LANG:-en}}"

# ─── Voice settings mini-menu ────────────────────────────────────────────────

_voice_settings_flow() {
    while true; do
        echo ""
        _header "VOICE SETTINGS" "⚙"
        echo ""
        local _at_label="off"
        [ "$_SETTING_VOICE_AUTO_TRANSLATE" = "1" ] && _at_label="on"
        printf "  ${C_BOLD}[1]${C_RESET} Auto-translate before reading : ${C_BOLD}%s${C_RESET}  ${C_DIM}(on · off)${C_RESET}\n" "$_at_label"
        printf "  ${C_BOLD}[2]${C_RESET} Translation target language   : ${C_BOLD}%s (%s)${C_RESET}  ${C_DIM}(type a code to change)${C_RESET}\n" \
            "$(_lang_name "$_SETTING_VOICE_LANG")" "$_SETTING_VOICE_LANG"
        echo ""
        printf "  ${C_BOLD}[m]${C_RESET} Back\n"
        printf "  ${C_BGREEN}▸${C_RESET} "
        read -r _vs_choice
        case "$_vs_choice" in
            1)
                if [ "$_SETTING_VOICE_AUTO_TRANSLATE" = "1" ]; then
                    _SETTING_VOICE_AUTO_TRANSLATE="0"
                else
                    _SETTING_VOICE_AUTO_TRANSLATE="1"
                fi
                local _env_file="$SCRIPT_DIR/.env"
                if [ -f "$_env_file" ]; then
                    if grep -q "^TTS_AUTO_TRANSLATE=" "$_env_file"; then
                        sed -i "s/^TTS_AUTO_TRANSLATE=.*/TTS_AUTO_TRANSLATE=$_SETTING_VOICE_AUTO_TRANSLATE/" "$_env_file"
                    else
                        printf '\nTTS_AUTO_TRANSLATE=%s\n' "$_SETTING_VOICE_AUTO_TRANSLATE" >> "$_env_file"
                    fi
                fi
                local _new_label="off"
                [ "$_SETTING_VOICE_AUTO_TRANSLATE" = "1" ] && _new_label="on"
                _success "Auto-translate → $_new_label  (saved to .env)"
                ;;
            2)
                printf "  Language code ${C_DIM}(en, fr, de, es, it, pt, nl, ru, zh, ja…)${C_RESET}: "
                read -r _new_lang
                if [ -n "$_new_lang" ]; then
                    _SETTING_VOICE_LANG="$_new_lang"
                    local _env_file="$SCRIPT_DIR/.env"
                    if [ -f "$_env_file" ]; then
                        if grep -q "^TRANSLATE_TARGET_LANG=" "$_env_file"; then
                            sed -i "s/^TRANSLATE_TARGET_LANG=.*/TRANSLATE_TARGET_LANG=$_new_lang/" "$_env_file"
                        else
                            printf '\nTRANSLATE_TARGET_LANG=%s\n' "$_new_lang" >> "$_env_file"
                        fi
                    fi
                    _success "Target language → $(_lang_name "$_new_lang") ($_new_lang)  (saved to .env)"
                fi
                ;;
            m|M) return ;;
            *) ;;
        esac
    done
}

# ─── Get selected text ───────────────────────────────────────────────────────

# Try primary selection first (mouse highlight), then clipboard.
selected_text="$(xclip -o -selection primary 2>/dev/null || true)"
_source="primary selection"

if [ -z "$(printf '%s' "$selected_text" | tr -d '[:space:]')" ]; then
    selected_text="$(xclip -o -selection clipboard 2>/dev/null || true)"
    _source="clipboard"
fi

if [ -z "$(printf '%s' "$selected_text" | tr -d '[:space:]')" ]; then
    _header "SELECTION TO VOICE" "⌨→🔊"
    echo ""
    _error "No text found in primary selection or clipboard."
    _info "Select some text with your mouse, then run again."
    echo ""
    exit 1
fi

# Debug log session bootstrap (no-op when VOX_DEBUG_LOG is unset).
"$VENV_PYTHON" -m src.debug_log reset --meta "$(VOX_DBG_MODE="voice" VOX_DBG_DM="${VOX_WEB_DISPLAY_MODE:-summary}" "$VENV_PYTHON" -c "
import json, os
print(json.dumps({
    'mode':         os.environ['VOX_DBG_MODE'],
    'display_mode': os.environ['VOX_DBG_DM'],
}))
")" 2>/dev/null
"$VENV_PYTHON" -m src.debug_log set input "$(VOX_TXT="$selected_text" VOX_SRC="$_source" "$VENV_PYTHON" -c "
import json, os
text = os.environ['VOX_TXT']
print(json.dumps({
    'source':         os.environ['VOX_SRC'],
    'selected_chars': len(text),
    'selected_text':  text,
}))
")" 2>/dev/null

# ─── Auto-translate ──────────────────────────────────────────────────────────

if [ "$_SETTING_VOICE_AUTO_TRANSLATE" = "1" ]; then
    clear
    echo ""
    _header "SELECTION TO VOICE" "⌨→🔊"
    echo ""
    _process "Translating to $(_lang_name "$_SETTING_VOICE_LANG") (${_SETTING_VOICE_LANG})..."
    echo ""
    _translated=$(printf '%s' "$selected_text" | \
        TRANSLATE_TARGET_LANG="$_SETTING_VOICE_LANG" \
        "$VENV_PYTHON" -m src.translate 2>&3)
    if [ -n "$_translated" ]; then
        selected_text="$_translated"
        _source="$_source → $(_lang_name "$_SETTING_VOICE_LANG")"
    else
        _warn "Translation failed — reading original text."
    fi
fi

# ─── Display ─────────────────────────────────────────────────────────────────

_header "SELECTION TO VOICE" "⌨→🔊"
echo ""
_info "Source: $_source  (${#selected_text} chars)"
echo ""
printf "${C_BG_CYAN} %s ${C_RESET}\n" "$selected_text"
echo ""

# ─── TTS ─────────────────────────────────────────────────────────────────────

REC_DIR="$SCRIPT_DIR/recordings/selection-to-voice"
mkdir -p "$REC_DIR"
_FAILED_CHUNKS=()
TTS_OUTPUT="$REC_DIR/output.mp3"
rm -f "$TTS_OUTPUT"

TTS_LOUDNESS="${TTS_LOUDNESS:--16}"
TTS_VOLUME="${TTS_VOLUME:-2.0}"
TTS_CHUNK_THRESHOLD="${TTS_CHUNK_THRESHOLD:-800}"

# Voice for selection: TTS_SELECTION_VOICE_ID from .env.
_sel_voice="${TTS_SELECTION_VOICE_ID:-}"
_sel_lang="${_sel_voice%%-*}"

_normalize_chunk() {
    local src="$1" dst="$2"
    if ffmpeg -y -i "$src" \
            -af "loudnorm=I=${TTS_LOUDNESS}:TP=-1.5:LRA=11,volume=${TTS_VOLUME}" \
            -codec:a libmp3lame -b:a 128k "$dst" 2>/dev/null; then
        mv "$dst" "$src"
    fi
}

_play_audio() {
    if command -v mpv >/dev/null 2>&1; then
        TTS_PLAYER="${TTS_PLAYER:-mpv --no-video}"
        echo ""
        printf "  ${C_BGREEN}🔊 Playing...${C_RESET}\n"
        $TTS_PLAYER "$1" 2>/dev/null
        echo ""
        _success "Playback complete."
    else
        _warn "mpv is not installed — cannot auto-play."
        _info "Install it: sudo apt install mpv"
        _info "Audio saved at: $1"
    fi
}

if [ "${#selected_text}" -gt "$TTS_CHUNK_THRESHOLD" ]; then
    # ── Chunked mode: generate → normalize → play each chunk immediately ──────
    _process "Generating speech (chunked)..."
    CHUNKS_DIR="$REC_DIR/chunks"
    rm -rf "$CHUNKS_DIR"
    mkdir -p "$CHUNKS_DIR"
    CONCAT_LIST="$REC_DIR/.concat_list.txt"
    : > "$CONCAT_LIST"

    # Run Python in background so we can kill it on Ctrl+C.
    _TTS_FIFO=$(mktemp -u /tmp/vox-tts-XXXXXX)
    mkfifo "$_TTS_FIFO"
    # Cleaned-text sidecar: tts.py writes the post-cleaning text here so the
    # display_meta branch can reuse it (no duplicated AI cleaning call).
    _CLEANED_TEXT_FILE="$REC_DIR/.cleaned.txt"
    rm -f "$_CLEANED_TEXT_FILE"
    printf '%s' "$selected_text" | \
        TTS_VOICE_ID="$_sel_voice" TTS_LANG="$_sel_lang" \
        TTS_CLEANED_TEXT_OUT="$_CLEANED_TEXT_FILE" \
        "$VENV_PYTHON" -m src.tts --chunked "$CHUNKS_DIR" > "$_TTS_FIFO" 2>&3 &
    _TTS_PID=$!

    _TTS_STOPPED=0
    _PIPELINE_ERROR=0
    declare -A _PROCESSED_CHUNKS=()
    _tts_stop() {
        _TTS_STOPPED=1
        kill "$_TTS_PID" 2>/dev/null
        rm -f "$_TTS_FIFO"
    }
    trap '_tts_stop' INT TERM
    # Web display lifecycle: ensure server dies on any script exit
    trap '_web_stop' EXIT

    _web_start voice
    _web_push_init voice
    # Watch the cleaned-text sidecar; when tts.py finishes cleaning (~1–2 s),
    # send the cleaned text as `full_text` SSE event (for fulltext mode) and
    # launch display_meta in background on the cleaned text.
    _web_watch_cleaned_then_meta "$_CLEANED_TEXT_FILE"

    # Python prints chunk file paths (or CHUNK_FAILED:<idx>) to the FIFO.
    # Retries are handled in Python to preserve per-chunk voice selection
    # (including quote voice). Bash must fail fast on missing passages.
    while IFS= read -r chunk_file; do
        [ "$_TTS_STOPPED" = "1" ] && break

        # FIFO lines may carry hidden CR/whitespace depending on producers.
        chunk_file="${chunk_file//$'\r'/}"
        chunk_file="${chunk_file#"${chunk_file%%[![:space:]]*}"}"
        chunk_file="${chunk_file%"${chunk_file##*[![:space:]]}"}"
        [ -z "$chunk_file" ] && continue

        # Python already exhausted retries for this passage.
        if [[ "$chunk_file" == CHUNK_FAILED:* ]]; then
            _fail_idx="${chunk_file#CHUNK_FAILED:}"
            _FAILED_CHUNKS+=("$_fail_idx")
            printf "  ${C_BRED}❌ Passage $((_fail_idx + 1)) définitivement échoué.${C_RESET}\n"
            _PIPELINE_ERROR=1
            _TTS_STOPPED=1
            kill "$_TTS_PID" 2>/dev/null
            break
        fi

        _chunk_idx=""
        _base_name="$(basename -- "$chunk_file")"
        if [[ "$_base_name" =~ ^chunk_([0-9]{3})(_retry)?\.mp3$ ]]; then
            _chunk_idx=$((10#${BASH_REMATCH[1]}))
            # Ignore duplicated entries to prevent double-processing/fake failures.
            if [ "${_PROCESSED_CHUNKS[$_chunk_idx]:-0}" = "1" ]; then
                continue
            fi
        fi

        # Some filesystems can expose a short delay between path emission
        # and file visibility. Wait briefly before declaring it missing.
        _chunk_ready=0
        _chunk_path="$chunk_file"
        _canonical_chunk=""
        if [ -n "$_chunk_idx" ]; then
            _canonical_chunk="$CHUNKS_DIR/$(printf 'chunk_%03d.mp3' "$_chunk_idx")"
        fi
        for _wait_n in 1 2 3 4 5 6 7 8 9 10; do
            if [ -s "$_chunk_path" ]; then
                _chunk_ready=1
                break
            fi
            if [ -n "$_canonical_chunk" ] && [ -s "$_canonical_chunk" ]; then
                _chunk_path="$_canonical_chunk"
                _chunk_ready=1
                break
            fi
            sleep 0.2
        done
        if [ "$_chunk_ready" = "0" ]; then
            if [ -n "$_chunk_idx" ]; then
                _FAILED_CHUNKS+=("$_chunk_idx")
                printf "  ${C_BRED}❌ Passage $((_chunk_idx + 1)) introuvable/vide.${C_RESET}\n"
            else
                printf "  ${C_BRED}❌ Chunk introuvable/vide: ${chunk_file}${C_RESET}\n"
            fi
            _PIPELINE_ERROR=1
            _TTS_STOPPED=1
            kill "$_TTS_PID" 2>/dev/null
            break
        fi

        chunk_file="$_chunk_path"
        _normalize_chunk "$chunk_file" "${chunk_file%.mp3}_norm.mp3"
        # Use realpath for ffmpeg concat compatibility
        printf 'file %s\n' "$(realpath "$chunk_file")" >> "$CONCAT_LIST"
        [ -n "$_chunk_idx" ] && _web_send_chunk "$_chunk_idx" "$CHUNKS_DIR"
        _play_audio "$chunk_file"
        [ -n "$_chunk_idx" ] && _PROCESSED_CHUNKS[$_chunk_idx]=1
        [ "$_TTS_STOPPED" = "1" ] && break
    done < "$_TTS_FIFO"

    wait "$_TTS_PID" 2>/dev/null
    rm -f "$_TTS_FIFO"
    if [ "$_PIPELINE_ERROR" = "1" ]; then
        _web_push_error "Lecture interrompue : passage manquant"
    else
        _web_push_done
    fi
    trap - INT TERM

    if [ "$_PIPELINE_ERROR" = "1" ]; then
        echo ""
        _error "Lecture interrompue : au moins un passage est manquant/échoué (aucun trou audio autorisé)."
        while true; do
            echo ""
            _sep
            printf "  ${C_BOLD}[r]${C_RESET} Relancer  ${C_BOLD}[m]${C_RESET} Menu VoxRefiner  ${C_DIM}[Entrée] Quitter${C_RESET} : "
            read -r _fail_action
            case "$_fail_action" in
                r|R)
                    exec "$0"
                    ;;
                m|M)
                    exit 0
                    ;;
                *)
                    exit 1
                    ;;
            esac
        done
    fi

    if [ "$_TTS_STOPPED" = "1" ]; then
        echo ""
        _info "Playback stopped."
        exit 0
    fi

    if [ ! -s "$CONCAT_LIST" ] && [ ${#_FAILED_CHUNKS[@]} -eq 0 ]; then
        echo ""
        _error "TTS failed — check your MISTRAL_API_KEY and connection."
        exit 1
    fi

    # Merge all successful chunks into a single file for replay / save.
    if [ -s "$CONCAT_LIST" ]; then
        ffmpeg -y -f concat -safe 0 -i "$CONCAT_LIST" \
            -codec:a libmp3lame -b:a 128k "$TTS_OUTPUT" 2>/dev/null || true
    fi

else
    # ── Single-file mode (short texts) ───────────────────────────────────────
    _process "Generating speech..."
    if ! printf '%s' "$selected_text" | \
        TTS_VOICE_ID="$_sel_voice" TTS_LANG="$_sel_lang" \
        "$VENV_PYTHON" -m src.tts "$TTS_OUTPUT" 2>&3; then
        echo ""
        _error "TTS failed — check your MISTRAL_API_KEY and connection."
        exit 1
    fi

    TTS_NORM_TMP="$REC_DIR/.norm_tmp.mp3"
    if ffmpeg -y -i "$TTS_OUTPUT" \
            -af "loudnorm=I=${TTS_LOUDNESS}:TP=-1.5:LRA=11,volume=${TTS_VOLUME}" \
            -codec:a libmp3lame -b:a 128k "$TTS_NORM_TMP" 2>/dev/null; then
        mv "$TTS_NORM_TMP" "$TTS_OUTPUT"
    fi
    rm -f "$TTS_NORM_TMP"

    _play_audio "$TTS_OUTPUT"
fi

# ─── Summary of failed chunks ────────────────────────────────────────────────

if [ "${#_FAILED_CHUNKS[@]}" -gt 0 ] 2>/dev/null; then
    echo ""
    printf "  ${C_BRED}⚠️  %d passage(s) n'ont pas pu être lus malgré les tentatives.${C_RESET}\n" "${#_FAILED_CHUNKS[@]}"
fi

# ─── Post-action mini-menu ───────────────────────────────────────────────────
# Skipped when called from another feature (VOXREFINER_MENU=1) so the caller's
# menu takes over immediately after playback.

if [ "${VOXREFINER_MENU:-}" != "1" ]; then
    while true; do
        echo ""
        _sep
        printf "  ${C_BOLD}[l]${C_RESET} Réecouter  ${C_BOLD}[d]${C_RESET} Sauvegarder  ${C_BOLD}[s]${C_RESET} Settings  ${C_BOLD}[m]${C_RESET} Menu VoxRefiner : "
        read -r _action
        case "$_action" in
            l|L)
                _play_audio "$TTS_OUTPUT"
                ;;
            d|D)
                _save_audio_to_downloads "$TTS_OUTPUT" "$selected_text" "selection-to-voice"
                ;;
            s|S)
                _voice_settings_flow
                ;;
            m|M) if [ -n "${VOXREFINER_MENU:-}" ]; then exit 0; fi; exec "$SCRIPT_DIR/vox-refiner-menu.sh" ;;
            *) ;;
        esac
    done
fi

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
    printf '%s' "$selected_text" | \
        TTS_VOICE_ID="$_sel_voice" TTS_LANG="$_sel_lang" \
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
        _play_audio "$chunk_file"
        [ -n "$_chunk_idx" ] && _PROCESSED_CHUNKS[$_chunk_idx]=1
        [ "$_TTS_STOPPED" = "1" ] && break
    done < "$_TTS_FIFO"

    wait "$_TTS_PID" 2>/dev/null
    rm -f "$_TTS_FIFO"
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
        printf "  ${C_BOLD}[l]${C_RESET} Réecouter  ${C_BOLD}[d]${C_RESET} Sauvegarder  ${C_BOLD}[m]${C_RESET} Menu VoxRefiner : "
        read -r _action
        case "$_action" in
            l|L)
                _play_audio "$TTS_OUTPUT"
                ;;
            d|D)
                _save_audio_to_downloads "$TTS_OUTPUT" "$selected_text" "selection-to-voice"
                ;;
            m|M) exec "$SCRIPT_DIR/vox-refiner-menu.sh" ;;
            *) ;;
        esac
    done
fi

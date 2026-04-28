#!/bin/bash
# VoxRefiner — Selection to Insight
# Summarise selected text, then offer search and fact-checking from the same session.
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
# shellcheck disable=SC1091
source "$SCRIPT_DIR/src/text_flows.sh"

if [ ! -x "$VENV_PYTHON" ]; then
    _error "Missing .venv Python interpreter: $VENV_PYTHON"
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

selected_text="$(xclip -o -selection primary 2>/dev/null || true)"
_source="primary selection"

if [ -z "$(printf '%s' "$selected_text" | tr -d '[:space:]')" ]; then
    selected_text="$(xclip -o -selection clipboard 2>/dev/null || true)"
    _source="clipboard"
fi

if [ -z "$(printf '%s' "$selected_text" | tr -d '[:space:]')" ]; then
    _header "SELECTION TO INSIGHT" "⌨→💡"
    echo ""
    _error "No text found in primary selection or clipboard."
    _info "Select some text with your mouse, then run again."
    echo ""
    exit 1
fi

# Debug log session bootstrap (no-op when VOX_DEBUG_LOG is unset).
"$VENV_PYTHON" -m src.debug_log reset --meta "$(VOX_DBG_MODE="insight" VOX_DBG_DM="${VOX_WEB_DISPLAY_MODE:-summary}" "$VENV_PYTHON" -c "
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

# ─── Display + key warnings ──────────────────────────────────────────────────

_header "SELECTION TO INSIGHT" "⌨→💡"
echo ""
_info "Source: $_source  (${#selected_text} chars)"
echo ""
printf "${C_BG_CYAN} %s ${C_RESET}\n" "$selected_text"
echo ""
_warn_missing_keys

# ─── Temp files ──────────────────────────────────────────────────────────────

INSIGHT_DIR="$SCRIPT_DIR/recordings/insight"
mkdir -p "$INSIGHT_DIR"

INSIGHT_META_FILE="$INSIGHT_DIR/.meta"
INSIGHT_PERPLEXITY_FILE="$INSIGHT_DIR/.perplexity"
INSIGHT_GROK_FILE="$INSIGHT_DIR/.grok"
INSIGHT_MODEL_META_FILE="$INSIGHT_DIR/.model_meta"
export INSIGHT_META_FILE INSIGHT_PERPLEXITY_FILE INSIGHT_GROK_FILE INSIGHT_MODEL_META_FILE

SUMMARY_AUDIO="$INSIGHT_DIR/summary.mp3"
SEARCH_AUDIO="$INSIGHT_DIR/search.mp3"
FACTCHECK_AUDIO="$INSIGHT_DIR/factcheck.mp3"
FULL_ARTICLE_AUDIO="$SCRIPT_DIR/recordings/selection-to-voice/output.mp3"

TTS_LOUDNESS="${TTS_LOUDNESS:--16}"
TTS_VOLUME="${TTS_VOLUME:-2.0}"

# ─── Session state ────────────────────────────────────────────────────────────

_search_done=0
_factcheck_done=0
_article_done=0
_summary_done=1   # Summary is generated eagerly in F5
summary_text=""

_SETTING_SUMMARY_REASONING="${INSIGHT_SUMMARY_REASONING:-standard}"
_SETTING_SEARCH_ENGINE="${INSIGHT_SEARCH_ENGINE:-auto}"
_SETTING_FACTCHECK_ENGINE="${INSIGHT_FACTCHECK_ENGINE:-both}"
_SETTING_SYNTHESIS_REASONING="${INSIGHT_SYNTHESIS_REASONING:-standard}"
_SETTING_TRANSLATE_LANG="${TRANSLATE_TARGET_LANG:-${OUTPUT_DEFAULT_LANG:-en}}"

# ─── Step 1: Summarise ────────────────────────────────────────────────────────

_header "SUMMARY" "💡"
echo ""
_process "Analysing and summarising..."
echo ""

summary_text=$(printf '%s' "$selected_text" | \
    INSIGHT_SUMMARY_REASONING="$_SETTING_SUMMARY_REASONING" \
    "$VENV_PYTHON" -m src.insight summarize 2>&3)

if [ -z "$summary_text" ]; then
    _error "Summary failed — check your MISTRAL_API_KEY and connection."
    exit 1
fi

content_type="generic"
if [ -s "$INSIGHT_META_FILE" ]; then
    content_type="$(cat "$INSIGHT_META_FILE")"
fi

# Re-render SUMMARY header with provider/model suffix (available only after the call).
_summary_suffix=""
_summary_suffix="$(_model_label_suffix "${INSIGHT_MODEL_META_FILE:-}")"
if [ -n "$_summary_suffix" ]; then
    _header "SUMMARY${_summary_suffix}" "💡"
    echo ""
fi
_success "Type detected: $content_type"
echo ""
printf "${C_BG_BLUE} %s ${C_RESET}\n" "$summary_text"
echo ""

# Open the parallel web display BEFORE TTS so the full summary is visible
# while audio chunks are still being generated (read-ahead UX).
trap '_web_stop' EXIT
_web_start insight
_web_push_init insight "$summary_text"
# Summary is already AI-cleaned content → feed directly to display_meta.
_web_send_display_meta "$summary_text"

_process "Reading summary..."
_tts_speak "$summary_text" "$SUMMARY_AUDIO"
_web_push_done

# ─── Main menu ────────────────────────────────────────────────────────────────

while true; do
    echo ""
    _sep
    _menu_line="  ${C_BOLD}[l]${C_RESET} Read full  ${C_BOLD}[p]${C_RESET} Search  ${C_BOLD}[f]${C_RESET} Fact-check"
    _menu_line="$_menu_line  ${C_BOLD}[r]${C_RESET} Replay summary  ${C_BOLD}[g]${C_RESET} Re-read summary"
    [ "$_search_done"    -eq 1 ] && _menu_line="$_menu_line  ${C_BOLD}[e]${C_RESET} Replay search"
    [ "$_factcheck_done" -eq 1 ] && _menu_line="$_menu_line  ${C_BOLD}[c]${C_RESET} Replay fact-check"
    [ "$_article_done"   -eq 1 ] && _menu_line="$_menu_line  ${C_BOLD}[a]${C_RESET} Replay article"
    _menu_line="$_menu_line  ${C_BOLD}[d]${C_RESET} Save  ${C_BOLD}[s]${C_RESET} Settings  ${C_BOLD}[m]${C_RESET} Menu VoxRefiner"
    printf "  %b: " "$_menu_line"
    read -r _main_action
    case "$_main_action" in
        l|L) _read_full_article ;;
        p|P) _search_flow "$summary_text" ;;
        f|F) _factcheck_flow "$summary_text" ;;
        r|R) _play_audio "$SUMMARY_AUDIO" ;;
        g|G) _process "Re-generating summary audio..."; _tts_speak "$summary_text" "$SUMMARY_AUDIO" ;;
        e|E) [ "$_search_done"    -eq 1 ] && _play_audio "$SEARCH_AUDIO" ;;
        c|C) [ "$_factcheck_done" -eq 1 ] && _play_audio "$FACTCHECK_AUDIO" ;;
        a|A) [ "$_article_done"   -eq 1 ] && _play_audio "$FULL_ARTICLE_AUDIO" ;;
        d|D)
            if   [ "$_article_done"   -eq 1 ] && [ -f "$FULL_ARTICLE_AUDIO" ]; then
                _save_audio_to_downloads "$FULL_ARTICLE_AUDIO" "$selected_text" "insight-full-article"
            elif [ "$_factcheck_done" -eq 1 ] && [ -f "$FACTCHECK_AUDIO" ]; then
                _save_audio_to_downloads "$FACTCHECK_AUDIO" "$summary_text" "insight-factcheck"
            elif [ "$_search_done"    -eq 1 ] && [ -f "$SEARCH_AUDIO" ]; then
                _save_audio_to_downloads "$SEARCH_AUDIO" "$summary_text" "insight-search"
            else
                _save_audio_to_downloads "$SUMMARY_AUDIO" "$summary_text" "insight-summary"
            fi
            ;;
        s|S) _settings_flow ;;
        m|M) if [ -n "${VOXREFINER_MENU:-}" ]; then exit 0; fi; exec "$SCRIPT_DIR/vox-refiner-menu.sh" ;;
        *)   ;;  # [Enter] and anything else: no-op, redisplay menu
    esac
done

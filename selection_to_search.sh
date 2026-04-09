#!/bin/bash
# VoxRefiner — Selection to Search
# Select text, then search directly — no summary generated upfront.
# The original selection is preserved and can be read aloud or summarised on demand.
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
source "$SCRIPT_DIR/src/insight_common.sh"

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

exec 3>&2

# ─── Get selected text ───────────────────────────────────────────────────────

selected_text="$(xclip -o -selection primary 2>/dev/null || true)"
_source="primary selection"

if [ -z "$(printf '%s' "$selected_text" | tr -d '[:space:]')" ]; then
    selected_text="$(xclip -o -selection clipboard 2>/dev/null || true)"
    _source="clipboard"
fi

if [ -z "$(printf '%s' "$selected_text" | tr -d '[:space:]')" ]; then
    _header "SELECTION TO SEARCH" "⌨→🔍"
    echo ""
    _error "No text found in primary selection or clipboard."
    _info "Select some text with your mouse, then run again."
    echo ""
    exit 1
fi

_header "SELECTION TO SEARCH" "⌨→🔍"
echo ""
_info "Source: $_source  (${#selected_text} chars)"
echo ""
printf "${C_BG_CYAN} %s ${C_RESET}\n" "$selected_text"
echo ""
_warn_missing_keys

# ─── Temp files ──────────────────────────────────────────────────────────────

INSIGHT_DIR="$SCRIPT_DIR/recordings/search"
mkdir -p "$INSIGHT_DIR"

INSIGHT_META_FILE="$INSIGHT_DIR/.meta"
INSIGHT_PERPLEXITY_FILE="$INSIGHT_DIR/.perplexity"
INSIGHT_GROK_FILE="$INSIGHT_DIR/.grok"
export INSIGHT_META_FILE INSIGHT_PERPLEXITY_FILE INSIGHT_GROK_FILE

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
_summary_done=0
summary_text=""

_SETTING_SUMMARY_REASONING="${INSIGHT_SUMMARY_REASONING:-standard}"
_SETTING_SEARCH_ENGINE="${INSIGHT_SEARCH_ENGINE:-auto}"
_SETTING_FACTCHECK_ENGINE="${INSIGHT_FACTCHECK_ENGINE:-both}"
_SETTING_SYNTHESIS_REASONING="${INSIGHT_SYNTHESIS_REASONING:-standard}"

# ─── Step 1: Search directly ─────────────────────────────────────────────────

_search_flow "$selected_text"

# ─── Main menu ────────────────────────────────────────────────────────────────

while true; do
    echo ""
    _sep
    _menu_line="  ${C_BOLD}[p]${C_RESET} New search  ${C_BOLD}[f]${C_RESET} Fact-check  ${C_BOLD}[z]${C_RESET} Summarise  ${C_BOLD}[l]${C_RESET} Read full"
    [ "$_search_done"    -eq 1 ] && _menu_line="$_menu_line  ${C_BOLD}[r]${C_RESET} Replay search"
    [ "$_factcheck_done" -eq 1 ] && _menu_line="$_menu_line  ${C_BOLD}[c]${C_RESET} Replay fact-check"
    [ "$_summary_done"   -eq 1 ] && _menu_line="$_menu_line  ${C_BOLD}[g]${C_RESET} Replay summary"
    [ "$_article_done"   -eq 1 ] && _menu_line="$_menu_line  ${C_BOLD}[a]${C_RESET} Replay article"
    _menu_line="$_menu_line  ${C_BOLD}[d]${C_RESET} Save  ${C_BOLD}[s]${C_RESET} Settings  ${C_BOLD}[m]${C_RESET} Menu VoxRefiner"
    printf "  %b: " "$_menu_line"
    read -r _main_action
    case "$_main_action" in
        p|P) _search_flow "$selected_text" ;;
        f|F) _factcheck_flow "$selected_text" ;;
        z|Z) _generate_summary ;;
        l|L) _read_full_article ;;
        r|R) [ "$_search_done"    -eq 1 ] && _play_audio "$SEARCH_AUDIO" ;;
        c|C) [ "$_factcheck_done" -eq 1 ] && _play_audio "$FACTCHECK_AUDIO" ;;
        g|G) [ "$_summary_done"   -eq 1 ] && _play_audio "$SUMMARY_AUDIO" ;;
        a|A) [ "$_article_done"   -eq 1 ] && _play_audio "$FULL_ARTICLE_AUDIO" ;;
        d|D)
            if   [ "$_article_done"   -eq 1 ] && [ -f "$FULL_ARTICLE_AUDIO" ]; then
                _save_audio_to_downloads "$FULL_ARTICLE_AUDIO" "$selected_text" "search-full-article"
            elif [ "$_factcheck_done" -eq 1 ] && [ -f "$FACTCHECK_AUDIO" ]; then
                _save_audio_to_downloads "$FACTCHECK_AUDIO" "$selected_text" "search-factcheck"
            elif [ "$_search_done"    -eq 1 ] && [ -f "$SEARCH_AUDIO" ]; then
                _save_audio_to_downloads "$SEARCH_AUDIO" "$selected_text" "search-result"
            elif [ "$_summary_done"   -eq 1 ] && [ -f "$SUMMARY_AUDIO" ]; then
                _save_audio_to_downloads "$SUMMARY_AUDIO" "$selected_text" "search-summary"
            else
                _warn "No audio to save yet."
            fi
            ;;
        s|S) _settings_flow ;;
        m|M) exec "$SCRIPT_DIR/vox-refiner-menu.sh" ;;
        *)   ;;
    esac
done

#!/bin/bash
# VoxRefiner — Screen to Text (F8)
# Capture a screen region, extract text via Mistral OCR, copy to clipboard.
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

# Screenshot destination
SCR_DIR="$SCRIPT_DIR/recordings/screen"
mkdir -p "$SCR_DIR"
SCR_FILE="$SCR_DIR/capture.png"

# ─── Screenshot tool detection ───────────────────────────────────────────────

_capture_screen() {
    if command -v maim >/dev/null 2>&1; then
        maim -s "$SCR_FILE"
    elif command -v scrot >/dev/null 2>&1; then
        scrot -s "$SCR_FILE"
    else
        _error "No screenshot tool found."
        echo ""
        echo "  Install one of:"
        echo "    sudo apt install maim     (recommended)"
        echo "    sudo apt install scrot    (fallback)"
        return 1
    fi
}

# ─── OCR helper ──────────────────────────────────────────────────────────────

_run_ocr() {
    clear
    echo ""
    _header "SCREEN TO TEXT" "🖼→📋"
    echo ""
    _process "Processing image..."
    echo ""

    ocr_text=$("$VENV_PYTHON" src/ocr.py "$SCR_FILE" 2>&3)

    if [ -z "$ocr_text" ]; then
        echo ""
        _warn "OCR returned empty result."
        return 1
    fi

    printf '%s' "$ocr_text" | xclip -selection clipboard
    printf '%s' "$ocr_text" | xclip -selection primary

    echo ""
    _header "EXTRACTED TEXT — mistral-ocr-latest" "🖼"
    _success "Copied to clipboard"
    echo ""
    printf "${C_BG_CYAN} %s ${C_RESET}\n" "$ocr_text"
    echo ""
    return 0
}

# ─── Capture ─────────────────────────────────────────────────────────────────

clear
echo ""
_header "SCREEN TO TEXT" "🖼→📋"
echo ""
_info "Select a region of the screen to capture."
echo ""

if ! _capture_screen; then
    echo ""
    if [ "${VOXREFINER_MENU:-}" != "1" ]; then
        printf "  ${C_DIM}Press Enter to exit...${C_RESET}"
        read -r
    fi
    exit 1
fi

# User may press Escape in maim/scrot — no file is created
if [ ! -f "$SCR_FILE" ]; then
    echo ""
    _warn "Screenshot cancelled."
    if [ "${VOXREFINER_MENU:-}" != "1" ]; then
        printf "  ${C_DIM}Press Enter to exit...${C_RESET}"
        read -r
    fi
    exit 0
fi

# ─── First OCR run ───────────────────────────────────────────────────────────

_run_ocr

# ─── Session state ────────────────────────────────────────────────────────────

_translate_done=0
translated_text=""

_SETTING_TRANSLATE_LANG="${TRANSLATE_TARGET_LANG:-${OUTPUT_DEFAULT_LANG:-en}}"
_SETTING_SUMMARY_REASONING="${INSIGHT_SUMMARY_REASONING:-standard}"
_SETTING_SEARCH_ENGINE="${INSIGHT_SEARCH_ENGINE:-auto}"
_SETTING_FACTCHECK_ENGINE="${INSIGHT_FACTCHECK_ENGINE:-both}"
_SETTING_SYNTHESIS_REASONING="${INSIGHT_SYNTHESIS_REASONING:-standard}"

# ─── Post-action menu ────────────────────────────────────────────────────────

while true; do
    clear
    echo ""
    _header "SCREEN TO TEXT" "🖼→📋"
    echo ""
    printf "${C_BG_CYAN} %s ${C_RESET}\n" "$ocr_text"
    echo ""
    _sep
    _menu_line="  ${C_BOLD}[r]${C_RESET} Retry OCR  ${C_BOLD}[n]${C_RESET} New capture  ${C_BOLD}[t]${C_RESET} Translate  ${C_BOLD}[l]${C_RESET} Read aloud  ${C_BOLD}[z]${C_RESET} Summarise  ${C_BOLD}[p]${C_RESET} Search  ${C_BOLD}[f]${C_RESET} Fact-check"
    [ "$_translate_done" -eq 1 ] && _menu_line="$_menu_line  ${C_BOLD}[e]${C_RESET} Replay translation"
    _menu_line="$_menu_line  ${C_BOLD}[s]${C_RESET} Settings  ${C_BOLD}[m]${C_RESET} Menu VoxRefiner"
    printf "  %b: " "$_menu_line"
    read -r _action
    case "$_action" in
        r|R)
            _run_ocr
            ;;
        n|N)
            exec "$0"
            ;;
        t|T)
            _translate_flow "$ocr_text"
            ;;
        l|L)
            # Read aloud: prefer translated text if available, else OCR text.
            _read_text="${translated_text:-$ocr_text}"
            printf '%s' "$_read_text" | xclip -selection primary
            VOXREFINER_MENU=1 "$SCRIPT_DIR/selection_to_voice.sh"
            ;;
        z|Z)
            printf '%s' "$ocr_text" | xclip -selection primary
            VOXREFINER_MENU=1 "$SCRIPT_DIR/selection_to_insight.sh"
            ;;
        p|P)
            printf '%s' "$ocr_text" | xclip -selection primary
            VOXREFINER_MENU=1 "$SCRIPT_DIR/selection_to_search.sh"
            ;;
        f|F)
            printf '%s' "$ocr_text" | xclip -selection primary
            VOXREFINER_MENU=1 "$SCRIPT_DIR/selection_to_factcheck.sh"
            ;;
        e|E)
            [ "$_translate_done" -eq 1 ] && {
                echo ""
                _header "TRANSLATION — mistral-small-latest" "🌐"
                echo ""
                printf "${C_BG_BLUE} %s ${C_RESET}\n" "$translated_text"
                echo ""
            }
            ;;
        s|S) _settings_flow ;;
        m|M)
            if [ -n "${VOXREFINER_MENU:-}" ]; then exit 0; fi
            exec "$SCRIPT_DIR/vox-refiner-menu.sh"
            ;;
        *)
            break
            ;;
    esac
done

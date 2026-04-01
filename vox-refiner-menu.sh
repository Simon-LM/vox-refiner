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

# ─── Shared UI (colors + helpers) ────────────────────────────────────────────
# shellcheck disable=SC1091
source "$SCRIPT_DIR/src/ui.sh"

# ─── API key helpers ─────────────────────────────────────────────────────────

_read_masked() {
    # Read a secret input character by character, displaying * for each char.
    # Supports Backspace to delete the last character.
    # Result is stored in the global variable _MASKED_INPUT.
    _MASKED_INPUT=""
    while IFS= read -r -s -n1 _char; do
        if [[ -z "$_char" ]]; then
            # Enter pressed
            break
        elif [[ "$_char" == $'\x7f' || "$_char" == $'\b' ]]; then
            # Backspace
            if [ -n "$_MASKED_INPUT" ]; then
                _MASKED_INPUT="${_MASKED_INPUT%?}"
                printf '\b \b'
            fi
        else
            _MASKED_INPUT="${_MASKED_INPUT}${_char}"
            printf '*'
        fi
    done
    echo ""
}

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
                _read_masked
                _new_key="$_MASKED_INPUT"
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

_coming_soon() {
    local name="$1" desc="$2"
    clear
    echo ""
    printf "${C_DIM}──────────────────────────────────────────────────────────────────${C_RESET}\n"
    printf "  ${C_BYELLOW}🚧  Coming soon: %s${C_RESET}\n" "$name"
    printf "${C_DIM}──────────────────────────────────────────────────────────────────${C_RESET}\n"
    echo ""
    printf "  ${C_DIM}%s${C_RESET}\n" "$desc"
    echo ""
    printf "  ${C_DIM}Press Enter to return to menu...${C_RESET}"
    read -r
}

show_menu() {
    clear
    echo ""
    echo "╔═══════════════════════════════════════════════════════════════════════╗"
    printf "║                             ${C_BGREEN} VoxRefiner ${C_RESET}                              ║\n"
    echo "╠═══════════════════════════════════════════════════════════════════════╣"
    echo "║  🎙 VOICE                                                              ║"
    echo "║                                                                       ║"
    printf "║  ${C_BOLD}[1]${C_RESET}  🎙→📋  ${C_BOLD}Speak & Refine${C_RESET}     ${C_DIM}speak, AI cleans it, paste${C_RESET}             ║\n"
    printf "║  ${C_BOLD}[2]${C_RESET}  🎙→🔊  ${C_BOLD}Speak & Translate${C_RESET}  ${C_DIM}hear your voice in another language${C_RESET}    ║\n"
    printf "║  ${C_BOLD}[3]${C_RESET}  🎙→📱  ${C_BOLD}Speak & Post${C_RESET}       ${C_DIM}generate a tweet or LinkedIn post${C_RESET}      ║\n"
    echo "║                                                                       ║"
    echo "╠═══════════════════════════════════════════════════════════════════════╣"
    echo "║  ⌨  SELECTION                                                         ║"
    echo "║                                                                       ║"
    printf "║  ${C_BOLD}[4]${C_RESET}  ⌨→🔊  ${C_BOLD}Selection to Voice${C_RESET}   ${C_DIM}selected text → audio in your voice${C_RESET}  ║\n"
    printf "║  ${C_BOLD}[5]${C_RESET}  ⌨→💡  ${C_BOLD}Selection to Insight${C_RESET} ${C_DIM}summary + search${C_RESET}                     ║\n"
    echo "║                                                                       ║"
    echo "╠═══════════════════════════════════════════════════════════════════════╣"
    echo "║  🖼  SCREEN                                                            ║"
    echo "║                                                                       ║"
    printf "║  ${C_BOLD}[6]${C_RESET}  🖼→📋  ${C_BOLD}Screen to Text${C_RESET}       ${C_DIM}screenshot → OCR → clipboard${C_RESET}         ║\n"
    printf "║  ${C_BOLD}[7]${C_RESET}  🖼→🔊  ${C_BOLD}Screen to Voice${C_RESET}      ${C_DIM}screenshot → OCR → audio${C_RESET}             ║\n"
    echo "║                                                                       ║"
    echo "╠═══════════════════════════════════════════════════════════════════════╣"
    echo "║                                                                       ║"
    printf "║  ${C_DIM}[s]${C_RESET}  Settings  ${C_DIM}[c]${C_RESET}  Context  ${C_DIM}[u]${C_RESET}  Update  ${C_DIM}[?]${C_RESET}  Help                  ║\n"
    printf "║  ${C_DIM}[q]${C_RESET}  Quit                                                            ║\n"
    echo "║                                                                       ║"
    echo "╚═══════════════════════════════════════════════════════════════════════╝"
    echo ""
}

# ─── Main loop ────────────────────────────────────────────────────────────────

_check_api_key_at_startup

while true; do
    show_menu
    printf "  ${C_BGREEN}▸${C_RESET} "
    read -r choice

    case "$choice" in
        1)
            # ── Speak & Refine sub-menu ──────────────────────────────────
            while true; do
                _STT_FORMAT="${OUTPUT_PROFILE:-prose}"  # prose is the default
                _STT_LANG="${OUTPUT_LANG:-auto}"
                clear
                echo ""
                echo "╔══════════════════════════════════════════════════════════════════╗"
                printf "║  🎙 → 📋  ${C_BGREEN}SPEAK & REFINE${C_RESET}                                          ║\n"
                echo "╠══════════════════════════════════════════════════════════════════╣"
                echo "║                                                                  ║"
                _STT_COMPARE="${REFINE_COMPARE_MODELS:-false}"
                _STT_HISTORY="${ENABLE_HISTORY:-false}"
                _STT_BULLETS="${HISTORY_MAX_BULLETS:-100}"
                printf "║  ${C_DIM}Format :${C_RESET}       ${C_CYAN}%-20s${C_RESET}                             ║\n" "$_STT_FORMAT"
                printf "║  ${C_DIM}Output lang :${C_RESET}  ${C_CYAN}%-20s${C_RESET}                             ║\n" "$_STT_LANG"
                if [ "$_STT_COMPARE" = "true" ]; then
                    printf "║  ${C_DIM}Compare :${C_RESET}      ${C_CYAN}%-20s${C_RESET}                             ║\n" "on"
                else
                    printf "║  ${C_DIM}Compare :${C_RESET}      ${C_DIM}%-20s${C_RESET}                             ║\n" "off"
                fi
                if [ "$_STT_HISTORY" = "true" ]; then
                    printf "║  ${C_DIM}History :${C_RESET}      ${C_CYAN}on (max %s bullets)%-5s${C_RESET}                        ║\n" "$_STT_BULLETS" ""
                else
                    printf "║  ${C_DIM}History :${C_RESET}      ${C_DIM}%-20s${C_RESET}                            ║\n" "off"
                fi
                echo "║                                                                  ║"
                echo "╠══════════════════════════════════════════════════════════════════╣"
                echo "║                                                                  ║"
                printf "║  ${C_BOLD}[Enter]${C_RESET}  Start recording                                        ║\n"
                printf "║  ${C_BOLD}[f]${C_RESET}      Change format                                          ║\n"
                printf "║  ${C_BOLD}[l]${C_RESET}      Change output language                                 ║\n"
                printf "║  ${C_BOLD}[c]${C_RESET}      Compare models                                         ║\n"
                printf "║  ${C_BOLD}[h]${C_RESET}      Toggle history (permanent)                             ║\n"
                printf "║  ${C_BOLD}[b]${C_RESET}      Max bullets in history (permanent)                     ║\n"
                printf "║  ${C_BOLD}[v]${C_RESET}      View history                                           ║\n"
                printf "║  ${C_BOLD}[e]${C_RESET}      Edit history                                           ║\n"
                printf "║  ${C_BOLD}[m]${C_RESET}      Back to menu                                           ║\n"
                echo "║                                                                  ║"
                echo "╚══════════════════════════════════════════════════════════════════╝"
                echo ""
                printf "  ${C_BGREEN}▸${C_RESET} "
                read -r _stt_choice
                case "$_stt_choice" in
                    "")
                        OUTPUT_PROFILE="$_STT_FORMAT" OUTPUT_LANG="$_STT_LANG" REFINE_COMPARE_MODELS="${REFINE_COMPARE_MODELS:-false}" \
                            ./record_and_transcribe_local.sh
                        while true; do
                            echo ""
                            _sep
                            printf "  ${C_BOLD}[r]${C_RESET} Retry  ${C_BOLD}[n]${C_RESET} New  ${C_BOLD}[v]${C_RESET} View history  ${C_BOLD}[e]${C_RESET} Edit history  ${C_DIM}[Enter] Back${C_RESET}: "
                            read -r _post_action
                            case "$_post_action" in
                                r|R)
                                    OUTPUT_PROFILE="$_STT_FORMAT" OUTPUT_LANG="$_STT_LANG" REFINE_COMPARE_MODELS="${REFINE_COMPARE_MODELS:-false}" \
                                        ./record_and_transcribe_local.sh --retry
                                    ;;
                                n|N)
                                    OUTPUT_PROFILE="$_STT_FORMAT" OUTPUT_LANG="$_STT_LANG" REFINE_COMPARE_MODELS="${REFINE_COMPARE_MODELS:-false}" \
                                        ./record_and_transcribe_local.sh
                                    ;;
                                v|V)
                                    if [ -f history.txt ]; then
                                        _header "HISTORY ($(wc -l < history.txt) lines)" "📜"
                                        echo ""
                                        cat history.txt
                                        echo ""
                                    else
                                        _warn "history.txt does not exist yet."
                                        _info "Enable history with [h] in this submenu."
                                    fi
                                    ;;
                                e|E)
                                    if [ -f history.txt ]; then
                                        ${EDITOR:-nano} history.txt
                                    else
                                        _warn "history.txt does not exist yet."
                                        _info "Enable history with [h] in this submenu."
                                    fi
                                    ;;
                                *) break ;;
                            esac
                        done
                        ;;
                    c|C)
                        if [ "${REFINE_COMPARE_MODELS:-false}" = "true" ]; then
                            REFINE_COMPARE_MODELS=false
                            _info "Compare models off."
                        else
                            REFINE_COMPARE_MODELS=true
                            _info "Compare models on — fallback model will run in parallel."
                        fi
                        export REFINE_COMPARE_MODELS
                        ;;
                    f|F)
                        echo ""
                        printf "${C_DIM}──────────────────────────────────────────────────────────────────${C_RESET}\n"
                        printf "  ${C_BGREEN}OUTPUT FORMAT${C_RESET}\n"
                        printf "${C_DIM}──────────────────────────────────────────────────────────────────${C_RESET}\n"
                        echo ""
                        printf "  ${C_BOLD}[1]${C_RESET} plain       ${C_DIM}no formatting${C_RESET}\n"
                        printf "  ${C_BOLD}[2]${C_RESET} prose       ${C_DIM}clean paragraphs — ideal for accessibility & web${C_RESET}\n"
                        printf "  ${C_BOLD}[3]${C_RESET} structured  ${C_DIM}paragraphs + bullets — ideal for AI chat & brainstorming${C_RESET}\n"
                        printf "  ${C_BOLD}[4]${C_RESET} markdown    ${C_DIM}headers + bullets — ideal for .md files & docs${C_RESET}\n"
                        echo ""
                        printf "  ${C_DIM}Current: ${C_CYAN}${_STT_FORMAT}${C_RESET}  —  Enter = keep current: "
                        read -r _fmt
                        _new_fmt=""
                        case "$_fmt" in
                            1) _new_fmt="plain" ;;
                            2) _new_fmt="prose" ;;
                            3) _new_fmt="structured" ;;
                            4) _new_fmt="technical" ;;
                            "") _new_fmt="$_STT_FORMAT" ;;
                        esac
                        if [ "$_fmt" != "" ]; then
                            echo ""
                            printf "  Save as default? ${C_BOLD}[p]${C_RESET} permanent  ${C_BOLD}[t]${C_RESET} this session only  ${C_DIM}[Enter] session${C_RESET}: "
                            read -r _persist
                            case "$_persist" in
                                p|P)
                                    _set_env_var "OUTPUT_PROFILE" "$_new_fmt"
                                    set -a; source .env; set +a
                                    _success "Saved to .env (permanent)."
                                    ;;
                                *)
                                    _info "Applied for this session only."
                                    ;;
                            esac
                            OUTPUT_PROFILE="$_new_fmt"
                            export OUTPUT_PROFILE
                        fi
                        ;;
                    l|L)
                        echo ""
                        printf "${C_DIM}──────────────────────────────────────────────────────────────────${C_RESET}\n"
                        printf "  ${C_BGREEN}OUTPUT LANGUAGE${C_RESET}\n"
                        printf "${C_DIM}──────────────────────────────────────────────────────────────────${C_RESET}\n"
                        echo ""
                        printf "  ${C_BOLD}[ 1]${C_RESET} Arabic        ${C_BOLD}[ 2]${C_RESET} Chinese       ${C_BOLD}[ 3]${C_RESET} Dutch\n"
                        printf "  ${C_BOLD}[ 4]${C_RESET} English       ${C_BOLD}[ 5]${C_RESET} French        ${C_BOLD}[ 6]${C_RESET} German\n"
                        printf "  ${C_BOLD}[ 7]${C_RESET} Hindi         ${C_BOLD}[ 8]${C_RESET} Italian       ${C_BOLD}[ 9]${C_RESET} Japanese\n"
                        printf "  ${C_BOLD}[10]${C_RESET} Korean        ${C_BOLD}[11]${C_RESET} Portuguese    ${C_BOLD}[12]${C_RESET} Russian\n"
                        printf "  ${C_BOLD}[13]${C_RESET} Spanish\n"
                        printf "  ${C_BOLD}[a]${C_RESET}  auto          ${C_DIM}same as spoken input (default)${C_RESET}\n"
                        echo ""
                        printf "  ${C_DIM}Current: ${C_CYAN}${OUTPUT_LANG:-auto}${C_RESET}  —  Enter = keep current: "
                        read -r _lng
                        _new_lang=""
                        case "$_lng" in
                            1)   _new_lang="ar" ;;
                            2)   _new_lang="zh" ;;
                            3)   _new_lang="nl" ;;
                            4)   _new_lang="en" ;;
                            5)   _new_lang="fr" ;;
                            6)   _new_lang="de" ;;
                            7)   _new_lang="hi" ;;
                            8)   _new_lang="it" ;;
                            9)   _new_lang="ja" ;;
                            10)  _new_lang="ko" ;;
                            11)  _new_lang="pt" ;;
                            12)  _new_lang="ru" ;;
                            13)  _new_lang="es" ;;
                            a|A) _new_lang="" ;;
                            "")  _new_lang="${OUTPUT_LANG:-}" ;;  # keep current
                        esac
                        if [ "$_lng" != "" ]; then
                            echo ""
                            printf "  Save as default? ${C_BOLD}[p]${C_RESET} permanent  ${C_BOLD}[t]${C_RESET} this session only  ${C_DIM}[Enter] session${C_RESET}: "
                            read -r _persist
                            case "$_persist" in
                                p|P)
                                    _set_env_var "OUTPUT_LANG" "$_new_lang"
                                    set -a; source .env; set +a
                                    _success "Saved to .env (permanent)."
                                    ;;
                                *)
                                    _info "Applied for this session only."
                                    ;;
                            esac
                            OUTPUT_LANG="$_new_lang"
                            export OUTPUT_LANG
                        fi
                        ;;
                    h|H)
                        if [ "${ENABLE_HISTORY:-false}" = "true" ]; then
                            _set_env_var "ENABLE_HISTORY" "false"
                            set -a; source .env; set +a
                            _success "History disabled (saved to .env)."
                        else
                            _set_env_var "ENABLE_HISTORY" "true"
                            set -a; source .env; set +a
                            _success "History enabled (saved to .env)."
                        fi
                        ;;
                    b|B)
                        echo ""
                        printf "  ${C_DIM}Current max bullets: ${C_CYAN}${HISTORY_MAX_BULLETS:-100}${C_RESET}  —  Enter = keep current: "
                        read -r _new_bullets
                        if [ -n "$_new_bullets" ] && echo "$_new_bullets" | grep -qE '^[0-9]+$'; then
                            _set_env_var "HISTORY_MAX_BULLETS" "$_new_bullets"
                            set -a; source .env; set +a
                            _success "Max bullets set to $_new_bullets (saved to .env)."
                        elif [ -n "$_new_bullets" ]; then
                            _warn "Invalid value — must be a number."
                        fi
                        ;;
                    v|V)
                        if [ -f history.txt ]; then
                            _header "HISTORY ($(wc -l < history.txt) lines)" "📜"
                            echo ""
                            cat history.txt
                            echo ""
                            printf "  ${C_DIM}Press Enter to return...${C_RESET}"
                            read -r
                        else
                            _warn "history.txt does not exist yet."
                            _info "Enable history with [h] above."
                            sleep 1.5
                        fi
                        ;;
                    e|E)
                        if [ -f history.txt ]; then
                            ${EDITOR:-nano} history.txt
                        else
                            _warn "history.txt does not exist yet."
                            _info "Enable history with [h] above."
                            sleep 1.5
                        fi
                        ;;
                    m|M) break ;;
                esac
            done
            ;;
        2)
            # ── Speak & Translate submenu ─────────────────────────────────
            while true; do
                # Resolve profile status
                _vt_profile_file="$SCRIPT_DIR/recordings/voice-profile/sample.mp3"
                if [ -f "$_vt_profile_file" ]; then
                    _vt_profile_date="$(date -r "$_vt_profile_file" '+%Y-%m-%d %H:%M' 2>/dev/null || echo "recorded")"
                    _vt_profile_status="${C_BGREEN}recorded $_vt_profile_date${C_RESET}"
                else
                    _vt_profile_status="${C_DIM}not recorded${C_RESET}"
                fi
                if [ "${TTS_USE_VOICE_PROFILE:-true}" = "true" ]; then
                    _vt_use_status="${C_BGREEN}on${C_RESET}"
                else
                    _vt_use_status="${C_DIM}off${C_RESET}"
                fi

                clear
                _header "SPEAK & TRANSLATE" "🎙→🔊"
                echo ""
                printf "  ${C_DIM}Voice profile:${C_RESET} %b   ${C_DIM}Use profile:${C_RESET} %b\n" "$_vt_profile_status" "$_vt_use_status"
                echo ""
                _sep
                echo ""
                printf "  ${C_BOLD}[Enter]${C_RESET} Start translation\n"
                printf "  ${C_BOLD}[p]${C_RESET}     Record voice profile (30s)\n"
                printf "  ${C_BOLD}[u]${C_RESET}     Toggle use profile (session)\n"
                printf "  ${C_BOLD}[m]${C_RESET}     Back to menu\n"
                echo ""
                _sep
                printf "  Choice: "
                read -r _vt_action
                case "$_vt_action" in
                    "")
                        ./voice_translate.sh
                        ;;
                    p|P)
                        ./voice_translate.sh --record-profile
                        ;;
                    u|U)
                        if [ "${TTS_USE_VOICE_PROFILE:-true}" = "true" ]; then
                            export TTS_USE_VOICE_PROFILE="false"
                        else
                            export TTS_USE_VOICE_PROFILE="true"
                        fi
                        ;;
                    m|M) break ;;
                esac
            done
            ;;
        3)
            _coming_soon "Speak & Post" \
                "Speak, then get a generated tweet or LinkedIn post — with context per platform."
            ;;
        4)
            _coming_soon "Selection to Voice" \
                "Select text with your mouse, trigger a shortcut, hear it in your own voice."
            ;;
        5)
            _coming_soon "Selection to Insight" \
                "Select text, get an audio summary — then dive deeper or search via Perplexity."
            ;;
        6)
            _coming_soon "Screen to Text" \
                "Take a screenshot, run OCR, copy the result to your clipboard."
            ;;
        7)
            _coming_soon "Screen to Voice" \
                "Take a screenshot, run OCR, hear the content in your own voice."
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

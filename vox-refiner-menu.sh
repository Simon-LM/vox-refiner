#!/bin/bash
# VoxRefiner — Interactive menu
# Launched from the Ubuntu app menu (.desktop file).
# The keyboard shortcut bypasses this and calls record_and_transcribe_local.sh directly.

cd "$(dirname "$0")"
SCRIPT_DIR="$(pwd)"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"
export VOXREFINER_MENU=1  # suppress hints in record_and_transcribe_local.sh

# Save stderr so Python progress messages reach the terminal even when stdout
# is captured by $() substitution (used by on-demand refine in F0).
exec 3>&2

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

_voice_picker() {
    # _voice_picker <ENV_VAR_NAME> <MENU_TITLE> <ALLOW_DISABLE>
    # ALLOW_DISABLE="1" adds [d] Disable option (sets the var to empty string).
    local _vp_var="$1" _vp_title="$2" _vp_allow_disable="${3:-0}"
    local _cur_vid _cur_slug _vpreview_id _vpreview_slug _vchoice _vi _vsample _tts_tmp
    local -a _vids _vslugs

    _vids=(
        "5a271406-039d-46fe-835b-fbbb00eaf08d"
        "49d024dd-981b-4462-bb17-74d381eb8fd7"
        "4adeb2c6-25a3-44bc-8100-5234dfc1193b"
        "2f62b1af-aea3-4079-9d10-7ca665ee7243"
        "e0580ce5-e63c-4cbe-88c8-a983b80c5f1f"
        "a7c07cdc-1c35-4d87-a938-c610a654f600"
        "c69964a6-ab8b-4f8a-9465-ec0925096ec8"
        "1024d823-a11e-43ee-bf3d-d440dccc0577"
        "530e2e20-58e2-45d8-b0a5-4594f4915944"
        "5940190b-f58a-4c3e-8264-a40d63fd6883"
        "98559b22-62b5-4a64-a7cd-fc78ca41faa8"
        "01d985cd-5e0c-4457-bfd8-80ba31a5bc03"
        "cb891218-482c-4392-9878-91e8d999d57a"
        "1f017bcb-02e5-460d-989b-db065c0c6122"
        "e3596645-b1af-469e-b857-f18ddedc7652"
        "d4101b8f-12c3-450d-a812-7d700b3a3245"
        "e8e5b1de-493c-4061-8414-e2170f9f4b6f"
        "390c8a2b-60a6-4882-8437-c49a8bd33b63"
        "8169ab87-bc99-4669-a5ec-6855860ace24"
        "5ad5d44e-6b4e-4a57-a8a8-4cae088034ed"
        "862274a7-8333-48f7-b668-f19c932999e0"
        "82c99ee6-f932-423f-a4a3-d403c8914b8d"
        "a3e41ea8-020b-44c0-8d8b-f6cc03524e31"
        "230ccacf-8800-4aa0-8ac2-8d004f1d9fb7"
        "c7a8eb83-5247-4540-89f3-6650d349100d"
        "e7168caa-f7ed-4e1c-98a1-434251f4f2b0"
        "60844938-221d-4d1e-8233-34203f787d9f"
        "5de47977-6e47-4266-a938-3bc1d76b4676"
        "cbe96cf0-85ec-4a10-accb-0b35c93b6dfd"
        "b35yykvVppLXyw_l"
        "axlOaUiFyOZhy4nv"
        "vMYQUSzm6GRkJX6d"
        "p1fSBpcmVWngBqVd"
        "3mM3xaoFjNMQa22C"
        "J4XbCGPYNMigXcfZ"
        "0LMAi0x_YVG_GLeM"
        "-dOnYAX4N4GqSOee"
        "N8xxxD_d-ZinGVI4"
        "zba0owtqy4Gnewn9"
        "xynYWquoAsrvM7UY"
        "s0PhgjzOTRD5wo5L"
        "HBfu9XA3QfzAG1MN"
    )
    _vslugs=(
        "fr_marie_neutral"    "fr_marie_happy"
        "fr_marie_sad"        "fr_marie_excited"
        "fr_marie_curious"    "fr_marie_angry"
        "en_paul_neutral"     "en_paul_happy"
        "en_paul_sad"         "en_paul_excited"
        "en_paul_confident"   "en_paul_cheerful"
        "en_paul_angry"       "en_paul_frustrated"
        "gb_oliver_neutral"   "gb_oliver_sad"
        "gb_oliver_excited"   "gb_oliver_curious"
        "gb_oliver_confident" "gb_oliver_cheerful"
        "gb_oliver_angry"     "gb_jane_neutral"
        "gb_jane_sarcasm"     "gb_jane_shameful"
        "gb_jane_sad"         "gb_jane_jealousy"
        "gb_jane_frustrated"  "gb_jane_curious"
        "gb_jane_confident"
        "gradium_fr_elise"    "gradium_fr_leo"
        "gradium_fr_olivier"  "gradium_fr_manon"
        "gradium_fr_jade"     "gradium_fr_amelie"
        "gradium_fr_adrien"   "gradium_fr_sarah"
        "gradium_fr_jennifer" "gradium_fr_elodie"
        "gradium_ca_melanie"  "gradium_ca_maxime"
        "gradium_ca_alexandre"
    )
    local _vtext_fr="Bonjour ! Je suis votre assistante vocale. Comment puis-je vous aider aujourd'hui ?"
    local _vtext_en="Hello! I'm your voice assistant. How can I help you today?"
    _vpreview_id=""
    _vpreview_slug=""

    while true; do
        _cur_vid="${!_vp_var}"
        _cur_slug="(not set)"
        if [ -z "$_cur_vid" ] && [ "$_vp_allow_disable" = "1" ]; then
            _cur_slug="(disabled)"
        else
            for _i in "${!_vids[@]}"; do
                if [ "${_vids[$_i]}" = "$_cur_vid" ]; then
                    _cur_slug="${_vslugs[$_i]}"
                    break
                fi
            done
        fi

        clear
        _header "$_vp_title" "🔈"
        echo ""
        printf "  ${C_DIM}Current:${C_RESET} ${C_BGREEN}%s${C_RESET}\n" "$_cur_slug"
        echo ""
        _sep
        echo ""
        printf "  ${C_BGREEN}MISTRAL${C_RESET}\n"
        printf "  ${C_BCYAN}🇫🇷  MARIE (French)${C_RESET}\n"
        printf "  ${C_BOLD}[ 1]${C_RESET} Neutral    ${C_BOLD}[ 2]${C_RESET} Happy     ${C_BOLD}[ 3]${C_RESET} Sad\n"
        printf "  ${C_BOLD}[ 4]${C_RESET} Excited    ${C_BOLD}[ 5]${C_RESET} Curious   ${C_BOLD}[ 6]${C_RESET} Angry\n"
        echo ""
        printf "  ${C_BCYAN}🇺🇸  PAUL (English US)${C_RESET}\n"
        printf "  ${C_BOLD}[ 7]${C_RESET} Neutral    ${C_BOLD}[ 8]${C_RESET} Happy     ${C_BOLD}[ 9]${C_RESET} Sad\n"
        printf "  ${C_BOLD}[10]${C_RESET} Excited    ${C_BOLD}[11]${C_RESET} Confident ${C_BOLD}[12]${C_RESET} Cheerful\n"
        printf "  ${C_BOLD}[13]${C_RESET} Angry      ${C_BOLD}[14]${C_RESET} Frustrated\n"
        echo ""
        printf "  ${C_BCYAN}🇬🇧  OLIVER (English GB)${C_RESET}\n"
        printf "  ${C_BOLD}[15]${C_RESET} Neutral    ${C_BOLD}[16]${C_RESET} Sad       ${C_BOLD}[17]${C_RESET} Excited\n"
        printf "  ${C_BOLD}[18]${C_RESET} Curious    ${C_BOLD}[19]${C_RESET} Confident ${C_BOLD}[20]${C_RESET} Cheerful\n"
        printf "  ${C_BOLD}[21]${C_RESET} Angry\n"
        echo ""
        printf "  ${C_BCYAN}🇬🇧  JANE (English GB)${C_RESET}\n"
        printf "  ${C_BOLD}[22]${C_RESET} Neutral    ${C_BOLD}[23]${C_RESET} Sarcasm   ${C_BOLD}[24]${C_RESET} Shameful\n"
        printf "  ${C_BOLD}[25]${C_RESET} Sad        ${C_BOLD}[26]${C_RESET} Jealousy  ${C_BOLD}[27]${C_RESET} Frustrated\n"
        printf "  ${C_BOLD}[28]${C_RESET} Curious    ${C_BOLD}[29]${C_RESET} Confident\n"
        echo ""
        if [ -z "${GRADIUM_API_KEY:-}" ]; then
            printf "  ${C_BGREEN}GRADIUM${C_RESET}  ${C_DIM}(unavailable — GRADIUM_API_KEY not set, see Settings → API Keys → [e5])${C_RESET}\n"
        else
            printf "  ${C_BGREEN}GRADIUM${C_RESET}\n"
        fi
        printf "  ${C_BCYAN}🇫🇷  GRADIUM — French (France)${C_RESET}\n"
        printf "  ${C_BOLD}[30]${C_RESET} Elise      ${C_BOLD}[31]${C_RESET} Leo       ${C_BOLD}[32]${C_RESET} Olivier\n"
        printf "  ${C_BOLD}[33]${C_RESET} Manon      ${C_BOLD}[34]${C_RESET} Jade      ${C_BOLD}[35]${C_RESET} Amelie\n"
        printf "  ${C_BOLD}[36]${C_RESET} Adrien     ${C_BOLD}[37]${C_RESET} Sarah     ${C_BOLD}[38]${C_RESET} Jennifer\n"
        printf "  ${C_BOLD}[39]${C_RESET} Elodie\n"
        echo ""
        printf "  ${C_BCYAN}🇨🇦  GRADIUM — French (Canada)${C_RESET}\n"
        printf "  ${C_BOLD}[40]${C_RESET} Melanie    ${C_BOLD}[41]${C_RESET} Maxime    ${C_BOLD}[42]${C_RESET} Alexandre\n"
        echo ""
        _sep
        if [ -n "$_vpreview_id" ]; then
            printf "  ${C_DIM}Last preview:${C_RESET} ${C_CYAN}%s${C_RESET}   ${C_BOLD}[s]${C_RESET} Select it" "$_vpreview_slug"
            [ "$_vp_allow_disable" = "1" ] && printf "  ${C_BOLD}[d]${C_RESET} Disable"
            printf "  ${C_BOLD}[m]${C_RESET} Menu settings\n"
        else
            printf "  ${C_DIM}Type a number to listen"
            [ "$_vp_allow_disable" = "1" ] && printf "   ${C_BOLD}[d]${C_RESET} ${C_DIM}Disable"
            printf "   ${C_BOLD}[m]${C_RESET} Menu settings\n"
        fi
        printf "  Choice: "
        read -r _vchoice

        case "$_vchoice" in
            s|S)
                if [ -n "$_vpreview_id" ]; then
                    _set_env_var "$_vp_var" "$_vpreview_id"
                    if [ -f .env ]; then set -a; source .env; set +a; fi
                    _success "Voice set to: $_vpreview_slug"
                    sleep 1
                fi
                ;;
            d|D)
                if [ "$_vp_allow_disable" = "1" ]; then
                    _set_env_var "$_vp_var" ""
                    if [ -f .env ]; then set -a; source .env; set +a; fi
                    _success "Citation voice disabled."
                    sleep 1
                fi
                ;;
            ""|m|M) break ;;
            *)
                if [[ "$_vchoice" =~ ^[0-9]+$ ]] && \
                   [ "$_vchoice" -ge 1 ] && [ "$_vchoice" -le "${#_vids[@]}" ]; then
                    _vi=$(( _vchoice - 1 ))
                    _vpreview_id="${_vids[$_vi]}"
                    _vpreview_slug="${_vslugs[$_vi]}"
                    if [ "$_vchoice" -le 6 ] || [ "$_vchoice" -ge 30 ]; then
                        _vsample="$_vtext_fr"
                    else
                        _vsample="$_vtext_en"
                    fi
                    _tts_tmp="$SCRIPT_DIR/recordings/.voice_preview.mp3"
                    echo ""
                    if ! [[ "$_vpreview_id" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]] && \
                       [ -z "${GRADIUM_API_KEY:-}" ]; then
                        _warn "GRADIUM_API_KEY is not set — cannot preview or select this voice."
                        printf "  ${C_DIM}Add it via Settings → API Keys → [e5] Edit Gradium key.${C_RESET}\n"
                        _vpreview_id=""
                        _vpreview_slug=""
                        sleep 2
                    else
                        _process "Generating preview for $_vpreview_slug..."
                        if printf '%s' "$_vsample" | \
                            TTS_VOICE_ID="$_vpreview_id" \
                            "$VENV_PYTHON" -m src.tts "$_tts_tmp" 2>/dev/null; then
                            TTS_PLAYER="${TTS_PLAYER:-mpv --no-video}"
                            $TTS_PLAYER "$_tts_tmp" 2>/dev/null
                            rm -f "$_tts_tmp"
                        else
                            _warn "Preview failed."
                            _vpreview_id=""
                            _vpreview_slug=""
                        fi
                    fi
                else
                    _warn "Invalid choice."
                    sleep 0.5
                fi
                ;;
        esac
    done
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

_test_eden_key() {
    local key="$1"
    if [ -z "$key" ]; then
        _error "No Eden AI key to test."
        return 1
    fi
    printf "  ${C_CYAN}⚡ Testing Eden AI key...${C_RESET}\n"
    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" \
        -X POST \
        -H "Authorization: Bearer $key" \
        -H "Content-Type: application/json" \
        -d '{"model":"mistral/mistral-small-latest","messages":[{"role":"user","content":"ping"}],"max_tokens":1}' \
        "https://api.edenai.run/v3/llm/chat/completions" \
        --max-time 15 2>/dev/null)
    case "$http_code" in
        200) _success "Eden AI key is valid." ; return 0 ;;
        401) _error  "Invalid Eden AI key (401 Unauthorized)." ; return 1 ;;
        429) _warn   "Rate limited (429) — key exists but quota exceeded." ; return 1 ;;
        000) _error  "No network response — check your internet connection." ; return 1 ;;
        *)   _error  "Unexpected response: HTTP $http_code" ; return 1 ;;
    esac
}

_test_xai_key() {
    local key="$1"
    if [ -z "$key" ]; then
        _error "No xAI key to test."
        return 1
    fi
    printf "  ${C_CYAN}⚡ Testing xAI / Grok key...${C_RESET}\n"
    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "Authorization: Bearer $key" \
        "https://api.x.ai/v1/models" \
        --max-time 15 2>/dev/null)
    case "$http_code" in
        200) _success "xAI key is valid." ; return 0 ;;
        401) _error  "Invalid xAI key (401 Unauthorized)." ; return 1 ;;
        429) _warn   "Rate limited (429) — key exists but quota exceeded." ; return 1 ;;
        000) _error  "No network response — check your internet connection." ; return 1 ;;
        *)   _error  "Unexpected response: HTTP $http_code" ; return 1 ;;
    esac
}

_test_perplexity_key() {
    local key="$1"
    if [ -z "$key" ]; then
        _error "No Perplexity key to test."
        return 1
    fi
    printf "  ${C_CYAN}⚡ Testing Perplexity key...${C_RESET}\n"
    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" \
        -X POST \
        -H "Authorization: Bearer $key" \
        -H "Content-Type: application/json" \
        -d '{"model":"sonar","messages":[{"role":"user","content":"ping"}],"max_tokens":1}' \
        "https://api.perplexity.ai/chat/completions" \
        --max-time 15 2>/dev/null)
    case "$http_code" in
        200) _success "Perplexity key is valid." ; return 0 ;;
        401) _error  "Invalid Perplexity key (401 Unauthorized)." ; return 1 ;;
        429) _warn   "Rate limited (429) — key exists but quota exceeded." ; return 1 ;;
        000) _error  "No network response — check your internet connection." ; return 1 ;;
        *)   _error  "Unexpected response: HTTP $http_code" ; return 1 ;;
    esac
}

_test_gradium_key() {
    local key="$1"
    if [ -z "$key" ]; then
        _error "No Gradium key to test."
        return 1
    fi
    printf "  ${C_CYAN}⚡ Testing Gradium key...${C_RESET}\n"
    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "x-api-key: $key" \
        "https://eu.api.gradium.ai/api/voices/" \
        --max-time 15 2>/dev/null)
    case "$http_code" in
        200) _success "Gradium key is valid." ; return 0 ;;
        401) _error  "Invalid Gradium key (401 Unauthorized)." ; return 1 ;;
        429) _warn   "Rate limited (429) — key exists but quota exceeded." ; return 1 ;;
        000) _error  "No network response — check your internet connection." ; return 1 ;;
        *)   _error  "Unexpected response: HTTP $http_code" ; return 1 ;;
    esac
}

_show_capability_status() {
    # Display which features are available/locked based on configured keys.
    # Intended for display inside _submenu_api_keys.
    local _has_m="${MISTRAL_API_KEY:-}"
    local _has_e="${EDENAI_API_KEY:-}"
    local _has_x="${XAI_API_KEY:-}"
    local _has_p="${PERPLEXITY_API_KEY:-}"
    local _has_g="${GRADIUM_API_KEY:-}"

    echo ""
    printf "  ${C_DIM}── Capabilities ──────────────────────────────────────────────────${C_RESET}\n"
    echo ""

    # Core: Speak & Refine, Insight summary (Mistral required)
    if [ -n "$_has_m" ]; then
        printf "  ${C_BGREEN}✓${C_RESET}  Speak & Refine, Transcription, Insight summary\n"
    else
        printf "  ${C_RED}✗${C_RESET}  ${C_DIM}Speak & Refine / Transcription  — requires MISTRAL_API_KEY${C_RESET}\n"
    fi

    # Web search & fact-check (Perplexity)
    if [ -n "$_has_p" ]; then
        printf "  ${C_BGREEN}✓${C_RESET}  Web search & fact-check  (Perplexity direct)\n"
    elif [ -n "$_has_e" ]; then
        printf "  ${C_BGREEN}✓${C_RESET}  Web search & fact-check  (Perplexity via Eden AI)\n"
    else
        printf "  ${C_DIM}○${C_RESET}  ${C_DIM}Web search / fact-check  — add PERPLEXITY_API_KEY or EDENAI_API_KEY${C_RESET}\n"
    fi

    # Grok web search (Eden or direct)
    if [ -n "$_has_x" ]; then
        printf "  ${C_BGREEN}✓${C_RESET}  Grok web search          (direct)\n"
        printf "  ${C_BGREEN}✓${C_RESET}  Fact-check X/Twitter     (native X/Twitter search via Grok direct)\n"
    elif [ -n "$_has_e" ]; then
        printf "  ${C_BGREEN}✓${C_RESET}  Grok web search          (Grok via Eden AI)\n"
        printf "  ${C_DIM}○${C_RESET}  ${C_DIM}Fact-check X/Twitter     — requires XAI_API_KEY (native X search not available via Eden)${C_RESET}\n"
    else
        printf "  ${C_DIM}○${C_RESET}  ${C_DIM}Grok web search          — add XAI_API_KEY or EDENAI_API_KEY${C_RESET}\n"
        printf "  ${C_DIM}○${C_RESET}  ${C_DIM}Fact-check X/Twitter     — add XAI_API_KEY (native X search)${C_RESET}\n"
    fi

    # Eden AI (redundancy + OCR + Gemini)
    if [ -n "$_has_e" ]; then
        printf "  ${C_BGREEN}✓${C_RESET}  Eden AI                  (fallbacks, OCR, model redundancy)\n"
    else
        printf "  ${C_DIM}○${C_RESET}  ${C_DIM}Eden AI (optional)        — add EDENAI_API_KEY for fallbacks,${C_RESET}\n"
        printf "  ${C_DIM}                             OCR, Gemini, and rate-limit resilience${C_RESET}\n"
    fi

    # Gradium (extended French voice bank)
    if [ -n "$_has_g" ]; then
        printf "  ${C_BGREEN}✓${C_RESET}  Extended voice bank      (Gradium: 13 native French voices)\n"
    else
        printf "  ${C_DIM}○${C_RESET}  ${C_DIM}Extended voice bank       — add GRADIUM_API_KEY for French voices [30]–[42]${C_RESET}\n"
    fi

    echo ""
}

_submenu_api_keys() {
    while true; do
        clear
        _header "API KEYS" "🔑"
        echo ""
        printf "  ${C_BOLD}Mistral${C_RESET}    ${C_RED}(required)${C_RESET}  : ${C_CYAN}%s${C_RESET}  ${C_DIM}min. ~10 € HT${C_RESET}\n" "$(_mask_key "${MISTRAL_API_KEY:-}")"
        printf "  ${C_BOLD}Eden AI${C_RESET}    ${C_DIM}(optional)${C_RESET}  : ${C_CYAN}%s${C_RESET}  ${C_DIM}min. ~5 € HT${C_RESET}\n"  "$(_mask_key "${EDENAI_API_KEY:-}")"
        printf "  ${C_BOLD}xAI / Grok${C_RESET} ${C_DIM}(optional)${C_RESET}  : ${C_CYAN}%s${C_RESET}  ${C_DIM}min. ~10 \$ HT${C_RESET}\n" "$(_mask_key "${XAI_API_KEY:-}")"
        printf "  ${C_BOLD}Perplexity${C_RESET} ${C_DIM}(optional)${C_RESET}  : ${C_CYAN}%s${C_RESET}  ${C_DIM}min. ~50 \$ HT${C_RESET}\n" "$(_mask_key "${PERPLEXITY_API_KEY:-}")"
        printf "  ${C_BOLD}Gradium${C_RESET}    ${C_DIM}(optional)${C_RESET}  : ${C_CYAN}%s${C_RESET}  ${C_DIM}pay-as-you-go${C_RESET}\n"  "$(_mask_key "${GRADIUM_API_KEY:-}")"
        echo ""
        printf "  ${C_DIM}${C_ITALIC}  Estimated amounts, subject to change — minimum credits required for these AI API providers.${C_RESET}\n"
        _show_capability_status
        _sep
        echo ""
        printf "  ${C_BOLD}[t1]${C_RESET}  Test Mistral key       ${C_BOLD}[e1]${C_RESET}  Edit Mistral key\n"
        printf "  ${C_BOLD}[t2]${C_RESET}  Test Eden AI key       ${C_BOLD}[e2]${C_RESET}  Edit Eden AI key\n"
        printf "  ${C_BOLD}[t3]${C_RESET}  Test xAI / Grok key    ${C_BOLD}[e3]${C_RESET}  Edit xAI / Grok key\n"
        printf "  ${C_BOLD}[t4]${C_RESET}  Test Perplexity key    ${C_BOLD}[e4]${C_RESET}  Edit Perplexity key\n"
        printf "  ${C_BOLD}[t5]${C_RESET}  Test Gradium key       ${C_BOLD}[e5]${C_RESET}  Edit Gradium key\n"
        echo ""
        printf "  ${C_BOLD}[m]${C_RESET}  Menu VoxRefiner\n"
        echo ""
        printf "  ${C_BGREEN}▸${C_RESET} "
        read -r _key_action
        case "$_key_action" in
            t1|T1)
                echo ""
                _test_mistral_key "${MISTRAL_API_KEY:-}"
                echo ""
                printf "  ${C_DIM}Press Enter to continue...${C_RESET}"
                read -r
                ;;
            e1|E1)
                echo ""
                printf "  Enter new Mistral API key: "
                _read_masked
                _new_key="$_MASKED_INPUT"
                if [ -z "$_new_key" ]; then
                    _warn "No key entered — unchanged."
                else
                    _set_env_var "MISTRAL_API_KEY" "$_new_key"
                    export MISTRAL_API_KEY="$_new_key"
                    set -a; source .env; set +a
                    _success "Key saved."
                    echo ""
                    _test_mistral_key "$_new_key"
                fi
                echo ""
                printf "  ${C_DIM}Press Enter to continue...${C_RESET}"
                read -r
                ;;
            t2|T2)
                echo ""
                _test_eden_key "${EDENAI_API_KEY:-}"
                echo ""
                printf "  ${C_DIM}Press Enter to continue...${C_RESET}"
                read -r
                ;;
            e2|E2)
                echo ""
                printf "  Enter new Eden AI key: "
                _read_masked
                _new_key="$_MASKED_INPUT"
                if [ -z "$_new_key" ]; then
                    _warn "No key entered — unchanged."
                else
                    _set_env_var "EDENAI_API_KEY" "$_new_key"
                    export EDENAI_API_KEY="$_new_key"
                    set -a; source .env; set +a
                    _success "Eden AI key saved."
                    echo ""
                    _test_eden_key "$_new_key"
                fi
                echo ""
                printf "  ${C_DIM}Press Enter to continue...${C_RESET}"
                read -r
                ;;
            t3|T3)
                echo ""
                _test_xai_key "${XAI_API_KEY:-}"
                echo ""
                printf "  ${C_DIM}Press Enter to continue...${C_RESET}"
                read -r
                ;;
            e3|E3)
                echo ""
                printf "  Enter new xAI / Grok API key: "
                _read_masked
                _new_key="$_MASKED_INPUT"
                if [ -z "$_new_key" ]; then
                    _warn "No key entered — unchanged."
                else
                    _set_env_var "XAI_API_KEY" "$_new_key"
                    export XAI_API_KEY="$_new_key"
                    set -a; source .env; set +a
                    _success "xAI key saved."
                    echo ""
                    _test_xai_key "$_new_key"
                fi
                echo ""
                printf "  ${C_DIM}Press Enter to continue...${C_RESET}"
                read -r
                ;;
            t4|T4)
                echo ""
                _test_perplexity_key "${PERPLEXITY_API_KEY:-}"
                echo ""
                printf "  ${C_DIM}Press Enter to continue...${C_RESET}"
                read -r
                ;;
            e4|E4)
                echo ""
                printf "  Enter new Perplexity API key: "
                _read_masked
                _new_key="$_MASKED_INPUT"
                if [ -z "$_new_key" ]; then
                    _warn "No key entered — unchanged."
                else
                    _set_env_var "PERPLEXITY_API_KEY" "$_new_key"
                    export PERPLEXITY_API_KEY="$_new_key"
                    set -a; source .env; set +a
                    _success "Perplexity key saved."
                    echo ""
                    _test_perplexity_key "$_new_key"
                fi
                echo ""
                printf "  ${C_DIM}Press Enter to continue...${C_RESET}"
                read -r
                ;;
            t5|T5)
                echo ""
                _test_gradium_key "${GRADIUM_API_KEY:-}"
                echo ""
                printf "  ${C_DIM}Press Enter to continue...${C_RESET}"
                read -r
                ;;
            e5|E5)
                echo ""
                printf "  Enter new Gradium API key: "
                _read_masked
                _new_key="$_MASKED_INPUT"
                if [ -z "$_new_key" ]; then
                    _warn "No key entered — unchanged."
                else
                    _set_env_var "GRADIUM_API_KEY" "$_new_key"
                    export GRADIUM_API_KEY="$_new_key"
                    set -a; source .env; set +a
                    _success "Gradium key saved."
                    echo ""
                    _test_gradium_key "$_new_key"
                fi
                echo ""
                printf "  ${C_DIM}Press Enter to continue...${C_RESET}"
                read -r
                ;;
            m|M) break ;;
            *) ;;
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
    echo "╔════════════════════════════════════════════════════════════════════════════╗"
    printf "║                             ${C_BGREEN}    VoxRefiner ${C_RESET}                                ║\n"
    echo "╠════════════════════════════════════════════════════════════════════════════╣"
    echo "║  🎙 VOICE                                                                   ║"
    echo "║                                                                            ║"
    printf "║  ${C_BOLD}[0]${C_RESET}  🎙→📋  ${C_BOLD}Speak & Transcribe${C_RESET} ${C_DIM}raw Voxtral text, refine on demand${C_RESET}          ║\n"
    printf "║  ${C_BOLD}[1]${C_RESET}  🎙→📋  ${C_BOLD}Speak & Refine${C_RESET}     ${C_DIM}speak, AI cleans it, paste${C_RESET}                  ║\n"
    printf "║  ${C_BOLD}[2]${C_RESET}  🎞→📋  ${C_BOLD}Media Translate${C_RESET}    ${C_DIM}audio/video file → translated text${C_RESET}          ║\n"
    printf "║  ${C_BOLD}[3]${C_RESET}  🎙→🔊  ${C_BOLD}Speak & Translate${C_RESET}  ${C_DIM}hear your voice in another language${C_RESET}         ║\n"
    printf "║  ${C_BOLD}[4]${C_RESET}  🎙→🔊  ${C_BOLD}Live Translate${C_RESET}     ${C_DIM}real-time bilingual conversation${C_RESET}            ║\n"
    echo "║                                                                            ║"
    echo "╠════════════════════════════════════════════════════════════════════════════╣"
    echo "║  ⌨  SELECTION                                                              ║"
    echo "║                                                                            ║"
    printf "║  ${C_BOLD}[5]${C_RESET}  ⌨→🔊  ${C_BOLD}Selection to Voice${C_RESET}      ${C_DIM}selected text → read aloud instantly${C_RESET}   ║\n"
    printf "║  ${C_BOLD}[6]${C_RESET}  ⌨→💡  ${C_BOLD}Selection to Insight${C_RESET}    ${C_DIM}summary + search                      ${C_RESET} ║\n"
    printf "║  ${C_BOLD}[7]${C_RESET}  ⌨→🔍  ${C_BOLD}Selection to Search${C_RESET}     ${C_DIM}selected text → search directly       ${C_RESET} ║\n"
    printf "║  ${C_BOLD}[8]${C_RESET}  ⌨→🔬  ${C_BOLD}Selection to Fact-check${C_RESET} ${C_DIM}selected text → fact-check            ${C_RESET} ║\n"
    echo "║                                                                            ║"
    echo "╠════════════════════════════════════════════════════════════════════════════╣"
    echo "║  🖼  SCREEN                                                                 ║"
    echo "║                                                                            ║"
    printf "║  ${C_BOLD}[9]${C_RESET}  🖼→📋  ${C_BOLD}Screen to Text${C_RESET}  ${C_DIM}screenshot → OCR → clipboard + search/voice${C_RESET}    ║\n"
    echo "║                                                                            ║"
    echo "╠════════════════════════════════════════════════════════════════════════════╣"
    echo "╠════════════════════════════════════════════════════════════════════════════╣"
    echo "║  🔧 WORKFLOWS                                                              ║"
    echo "║                                                                            ║"
    printf "║  ${C_BOLD}[W1]${C_RESET} 🎙→📱  ${C_BOLD}Speak & Post${C_RESET}  ${C_DIM}generate a tweet or LinkedIn post${C_RESET}                ║\n"
    echo "║                                                                            ║"
    echo "╠════════════════════════════════════════════════════════════════════════════╣"
    echo "║  ✦  YOUR WORKFLOWS                                                         ║"
    echo "║                                                                            ║"
    printf "║  ${C_BOLD}[P0]${C_RESET} ℹ  ${C_BOLD}Your Workflows${C_RESET}  ${C_DIM}about personalisation + your custom workflows${C_RESET}     ║\n"
    printf "║  ${C_BOLD}[+]${C_RESET}  ✚  ${C_BOLD}Create a workflow${C_RESET}                                                 ║\n"
    echo "║                                                                            ║"
    echo "╠════════════════════════════════════════════════════════════════════════════╣"
    echo "╠════════════════════════════════════════════════════════════════════════════╣"
    echo "║                                                                            ║"
    printf "║  ${C_DIM}[s]${C_RESET} Settings   ${C_DIM}[c]${C_RESET} Context   ${C_DIM}[u]${C_RESET} Update   ${C_DIM}[?]${C_RESET} Help   ${C_DIM}[q]${C_RESET} Quit             ║\n"
    echo "║                                                                            ║"
    echo "╚════════════════════════════════════════════════════════════════════════════╝"
    echo ""
}

# ─── Main loop ────────────────────────────────────────────────────────────────

_check_api_key_at_startup

while true; do
    show_menu
    printf "  ${C_BGREEN}▸${C_RESET} "
    read -r choice

    case "$choice" in
        0)
            # ── Speak & Transcribe — record immediately, no sub-menu ──────
            _f0_refined=0
            ENABLE_REFINE=false ENABLE_HISTORY=false \
                ./record_and_transcribe_local.sh
            while true; do
                echo ""
                _sep
                if [ "$_f0_refined" -eq 0 ]; then
                    printf "  ${C_BOLD}[R]${C_RESET} Refine  ${C_BOLD}[n]${C_RESET} New recording  ${C_BOLD}[m]${C_RESET} Menu VoxRefiner: "
                else
                    printf "  ${C_BOLD}[r]${C_RESET} Retry refine  ${C_BOLD}[n]${C_RESET} New recording  ${C_BOLD}[v]${C_RESET} View history  ${C_BOLD}[e]${C_RESET} Edit history  ${C_BOLD}[m]${C_RESET} Menu VoxRefiner: "
                fi
                read -r _post_action
                case "$_post_action" in
                    r|R)
                        _raw_text="$(cat "$SCRIPT_DIR/recordings/stt/.raw_transcription" 2>/dev/null)"
                        if [ -z "$_raw_text" ]; then
                            _warn "No raw transcription found."
                        else
                            echo ""
                            _process "Refining with Mistral..."
                            echo ""
                            _refined=$(printf '%s' "$_raw_text" | \
                                "$VENV_PYTHON" -m src.refine 2>&3)
                            _final="${_refined:-$_raw_text}"
                            printf '%s' "$_final" | xclip -selection clipboard
                            printf '%s' "$_final" | xclip -selection primary
                            echo ""
                            _header "RAW TRANSCRIPTION — Voxtral" "📝"
                            echo ""
                            printf "${C_BG_CYAN} %s ${C_RESET}\n" "$_raw_text"
                            echo ""
                            _header "REFINED TEXT" "📝"
                            _success "Copied to clipboard"
                            echo ""
                            printf "${C_BG_BLUE} %s ${C_RESET}\n" "$_final"
                            echo ""
                            if [ "${ENABLE_HISTORY:-false}" = "true" ]; then
                                _wc=$(printf '%s' "$_raw_text" | wc -w)
                                _thr="${REFINE_MODEL_THRESHOLD_SHORT:-90}"
                                if [ "$_wc" -ge "$_thr" ]; then
                                    printf '%s' "$_final" | "$VENV_PYTHON" -m src.refine --update-history 2>&3 &
                                    echo "🔄 History context update running in background..."
                                fi
                            fi
                            _f0_refined=1
                        fi
                        ;;
                    n|N)
                        ENABLE_REFINE=false ENABLE_HISTORY=false \
                            ./record_and_transcribe_local.sh
                        _f0_refined=0
                        ;;
                    v|V)
                        if [ "$_f0_refined" -eq 1 ]; then
                            if [ -f history.txt ]; then
                                _header "HISTORY ($(wc -l < history.txt) lines)" "📜"
                                echo ""
                                cat history.txt
                                echo ""
                            else
                                _warn "history.txt does not exist yet."
                            fi
                        fi
                        ;;
                    e|E)
                        if [ "$_f0_refined" -eq 1 ]; then
                            if [ -f history.txt ]; then
                                ${EDITOR:-nano} history.txt
                            else
                                _warn "history.txt does not exist yet."
                            fi
                        fi
                        ;;
                    m|M) break ;;
                    *) ;;
                esac
            done
            ;;
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
                _STT_BULLETS="${HISTORY_MAX_BULLETS:-80}"
                _STT_INJECT="${HISTORY_INJECT_BULLETS_MEDIUM:-40}"
                printf "║  ${C_DIM}Format :${C_RESET}       ${C_CYAN}%-20s${C_RESET}                             ║\n" "$_STT_FORMAT"
                printf "║  ${C_DIM}Output lang :${C_RESET}  ${C_CYAN}%-20s${C_RESET}                             ║\n" "$_STT_LANG"
                if [ "$_STT_COMPARE" = "true" ]; then
                    printf "║  ${C_DIM}Compare :${C_RESET}      ${C_CYAN}%-20s${C_RESET}                             ║\n" "on"
                else
                    printf "║  ${C_DIM}Compare :${C_RESET}      ${C_DIM}%-20s${C_RESET}                             ║\n" "off"
                fi
                if [ "$_STT_HISTORY" = "true" ]; then
                    printf "║  ${C_DIM}History :${C_RESET}      ${C_CYAN}on · max %s · medium → %s%-5s${C_RESET}                ║\n" "$_STT_BULLETS" "$_STT_INJECT" ""
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
                printf "║  ${C_BOLD}[b]${C_RESET}      Max bullets in history file (permanent)                ║\n"
                printf "║  ${C_BOLD}[i]${C_RESET}      Bullets injected for medium texts (permanent)          ║\n"
                printf "║  ${C_BOLD}[v]${C_RESET}      View history                                           ║\n"
                printf "║  ${C_BOLD}[e]${C_RESET}      Edit history                                           ║\n"
                printf "║  ${C_BOLD}[m]${C_RESET}      Menu VoxRefiner                                        ║\n"
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
                            printf "  ${C_BOLD}[r]${C_RESET} Retry  ${C_BOLD}[n]${C_RESET} New  ${C_BOLD}[v]${C_RESET} View history  ${C_BOLD}[e]${C_RESET} Edit history  ${C_BOLD}[m]${C_RESET} Menu VoxRefiner: "
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
                                m|M) break ;;
                                *) ;;
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
                        printf "  ${C_DIM}Current max bullets in file: ${C_CYAN}${HISTORY_MAX_BULLETS:-80}${C_RESET}  —  Enter = keep current: "
                        read -r _new_bullets
                        if [ -n "$_new_bullets" ] && echo "$_new_bullets" | grep -qE '^[0-9]+$'; then
                            _set_env_var "HISTORY_MAX_BULLETS" "$_new_bullets"
                            set -a; source .env; set +a
                            _success "Max bullets set to $_new_bullets (saved to .env)."
                        elif [ -n "$_new_bullets" ]; then
                            _warn "Invalid value — must be a number."
                        fi
                        ;;
                    i|I)
                        echo ""
                        printf "  ${C_DIM}Bullets injected for medium texts (80–240 words): ${C_CYAN}${HISTORY_INJECT_BULLETS_MEDIUM:-40}${C_RESET}  —  Enter = keep current: "
                        read -r _new_inject
                        if [ -n "$_new_inject" ] && echo "$_new_inject" | grep -qE '^[0-9]+$'; then
                            _set_env_var "HISTORY_INJECT_BULLETS_MEDIUM" "$_new_inject"
                            set -a; source .env; set +a
                            _success "Inject bullets (medium) set to $_new_inject (saved to .env)."
                        elif [ -n "$_new_inject" ]; then
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
            _coming_soon "Media Translate" \
                "Extract audio from a video or audio file, then translate it to text."
            ;;
        3)
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
                printf "  ${C_BOLD}[m]${C_RESET}     Menu VoxRefiner\n"
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
        4)
            _coming_soon "Live Translate" \
                "Real-time bilingual conversation mode — translate both speakers instantly."
            ;;
        5)
            VOXREFINER_MENU=0 ./selection_to_voice.sh
            ;;
        6)
            ./selection_to_insight.sh
            ;;
        7)
            ./selection_to_search.sh
            ;;
        8)
            ./selection_to_factcheck.sh
            ;;
        9)
            VOXREFINER_MENU=0 ./screen_to_text.sh
            ;;
        W1|w1)
            _coming_soon "Speak & Post" \
                "Speak, then get a generated tweet or LinkedIn post — with context per platform."
            ;;
        P0|p0)
            _coming_soon "Your Workflows" \
                "Create and manage your own custom workflows by combining VoxRefiner features."
            ;;
        "+")
            _coming_soon "Create a workflow" \
                "Workflow builder coming soon — chain features into your own personal pipeline."
            ;;
        s|S)
            while true; do
                _header "SETTINGS" "⚙"
                echo ""
                printf "  ${C_BOLD}[k]${C_RESET}  API Keys\n"
                printf "  ${C_BOLD}[v]${C_RESET}  Reading voice (Selection to Voice)\n"
                printf "  ${C_BOLD}[c]${C_RESET}  Citation voice (quoted paragraphs)\n"
                printf "  ${C_BOLD}[e]${C_RESET}  Edit .env\n"
                echo ""
                printf "  ${C_BOLD}[m]${C_RESET} Menu VoxRefiner\n"
                echo ""
                printf "  ${C_BGREEN}▸${C_RESET} "
                read -r _set_action
                case "$_set_action" in
                    k|K)
                        _submenu_api_keys
                        ;;
                    v|V)
                        _voice_picker "TTS_SELECTION_VOICE_ID" "READING VOICE" "0"
                        ;;
                    c|C)
                        _voice_picker "TTS_QUOTE_VOICE_ID" "CITATION VOICE" "1"
                        ;;
                    e|E)
                        ${EDITOR:-nano} .env
                        if [ -f .env ]; then
                            set -a; source .env; set +a
                        fi
                        ;;
                    m|M) break ;;
                    *) ;;
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
                printf "  ${C_BOLD}[m]${C_RESET}  Menu VoxRefiner\n"
                echo ""
                printf "  ${C_BGREEN}▸${C_RESET} "
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
                    m|M) break ;;
                    *) ;;
                esac
            done
            ;;
        '?')
            while true; do
                _header "HELP" "?"
                echo ""
                if [ -f docs/troubleshooting.md ]; then
                    cat docs/troubleshooting.md
                else
                    _warn "docs/troubleshooting.md not found."
                fi
                echo ""
                _sep
                echo ""
                printf "  ${C_BOLD}[m]${C_RESET}  Menu VoxRefiner\n"
                echo ""
                printf "  ${C_BGREEN}▸${C_RESET} "
                read -r _help_action
                case "$_help_action" in
                    m|M) break ;;
                    *) ;;
                esac
            done
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

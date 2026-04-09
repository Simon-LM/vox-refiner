#!/bin/bash
# VoxRefiner — Shared helpers for Selection to Insight (F5),
# Selection to Search (F6), and Selection to Fact-check (F7).
#
# Source this file after ui.sh and save_audio.sh.
# Requires globals set by the calling script:
#   SCRIPT_DIR, VENV_PYTHON, TTS_LOUDNESS, TTS_VOLUME
#   INSIGHT_DIR, INSIGHT_META_FILE, INSIGHT_PERPLEXITY_FILE, INSIGHT_GROK_FILE
#   SUMMARY_AUDIO, SEARCH_AUDIO, FACTCHECK_AUDIO, FULL_ARTICLE_AUDIO
#   selected_text, summary_text (initialised to "" in F6/F7)
#   _search_done, _factcheck_done, _article_done, _summary_done
#   _SETTING_SUMMARY_REASONING, _SETTING_SEARCH_ENGINE
#   _SETTING_FACTCHECK_ENGINE, _SETTING_SYNTHESIS_REASONING

# ─── API key warnings ─────────────────────────────────────────────────────────

_warn_missing_keys() {
    if [ -z "${PERPLEXITY_API_KEY:-}" ] && [ -z "${XAI_API_KEY:-}" ]; then
        echo ""
        _warn "No search API key configured."
        _info "  Search and Fact-check require at least one of:"
        _info "    PERPLEXITY_API_KEY  → perplexity.ai/settings/api"
        _info "    XAI_API_KEY         → x.ai/api"
        _info "  Add either to your .env file to unlock Search and Fact-check."
        echo ""
    fi
}

# ─── Audio playback ───────────────────────────────────────────────────────────

_play_audio() {
    local file="$1"
    if [ ! -f "$file" ]; then return; fi
    if command -v mpv >/dev/null 2>&1; then
        TTS_PLAYER="${TTS_PLAYER:-mpv --no-video}"
        $TTS_PLAYER "$file" 2>/dev/null
    else
        _warn "mpv not installed — cannot auto-play."
        _info "Install: sudo apt install mpv"
    fi
}

# ─── TTS pipeline ─────────────────────────────────────────────────────────────

_tts_speak() {
    # Generate TTS using the chunked pipeline (sequential: generate all, then play).
    # Skips AI cleaning (text is already clean Mistral output).
    # Usage: _tts_speak <text> <output_mp3_for_replay>
    local text="$1" out="$2"
    local voice="${TTS_SELECTION_VOICE_ID:-}"
    local lang="${voice%%-*}"

    rm -f "$out"

    local chunks_dir concat_list
    chunks_dir="$(dirname "$out")/chunks_$(basename "${out%.mp3}")"
    concat_list="$(dirname "$out")/.concat_$(basename "${out%.mp3}").txt"
    rm -rf "$chunks_dir"
    mkdir -p "$chunks_dir"
    : > "$concat_list"

    local chunk_output
    chunk_output=$(printf '%s' "$text" | \
        TTS_SKIP_AI_CLEAN=1 \
        TTS_VOICE_ID="$voice" TTS_LANG="$lang" \
        "$VENV_PYTHON" -m src.tts --chunked "$chunks_dir" 2>&3)

    if [ -z "$chunk_output" ]; then
        _warn "TTS failed — text will not be read aloud."
        return 1
    fi

    local tts_ok=1
    local -a chunk_files=()
    while IFS= read -r chunk_file; do
        [ -n "$chunk_file" ] && chunk_files+=("$chunk_file")
    done <<< "$chunk_output"

    for chunk_file in "${chunk_files[@]}"; do
        if [[ "$chunk_file" == CHUNK_FAILED:* ]]; then
            _warn "A TTS passage failed — partial playback."
            tts_ok=0
            continue
        fi
        [ ! -s "$chunk_file" ] && { _warn "Empty/missing chunk: $chunk_file"; tts_ok=0; continue; }

        local norm="${chunk_file%.mp3}_norm.mp3"
        if ffmpeg -y -i "$chunk_file" \
                -af "loudnorm=I=${TTS_LOUDNESS}:TP=-1.5:LRA=11,volume=${TTS_VOLUME}" \
                -codec:a libmp3lame -b:a 128k "$norm" 2>/dev/null; then
            mv "$norm" "$chunk_file"
        fi
        rm -f "$norm"

        printf 'file %s\n' "$(realpath "$chunk_file")" >> "$concat_list"
        _play_audio "$chunk_file"
    done

    if [ -s "$concat_list" ]; then
        ffmpeg -y -f concat -safe 0 -i "$concat_list" \
            -codec:a libmp3lame -b:a 128k "$out" 2>/dev/null || true
    fi
    rm -f "$concat_list"

    [ "$tts_ok" -eq 1 ]
}

# ─── Display + speak ──────────────────────────────────────────────────────────

_show_and_speak() {
    local header_label="$1" emoji="$2" result_text="$3" audio_file="$4"
    _header "$header_label" "$emoji"
    echo ""
    printf "${C_BG_BLUE} %s ${C_RESET}\n" "$result_text"
    echo ""
    _process "Reading aloud..."
    _tts_speak "$result_text" "$audio_file"
}

# ─── Optional summary generation ─────────────────────────────────────────────
# Sets globals: summary_text, _summary_done=1
# Returns 1 on failure (non-fatal for F6/F7).

_generate_summary() {
    if [ -n "${summary_text:-}" ]; then
        _header "SUMMARY" "💡"
        echo ""
        printf "${C_BG_BLUE} %s ${C_RESET}\n" "$summary_text"
        echo ""
        _process "Reading summary..."
        _tts_speak "$summary_text" "$SUMMARY_AUDIO"
        _summary_done=1
        return 0
    fi
    echo ""
    _header "SUMMARY" "💡"
    echo ""
    _process "Analysing and summarising..."
    echo ""
    summary_text=$(printf '%s' "$selected_text" | \
        INSIGHT_SUMMARY_REASONING="$_SETTING_SUMMARY_REASONING" \
        "$VENV_PYTHON" -m src.insight summarize 2>&3)
    if [ -z "$summary_text" ]; then
        _error "Summary failed — check your MISTRAL_API_KEY and connection."
        summary_text=""
        return 1
    fi
    local content_type="generic"
    if [ -s "${INSIGHT_META_FILE:-}" ]; then
        content_type="$(cat "$INSIGHT_META_FILE")"
    fi
    _success "Type detected: $content_type"
    echo ""
    printf "${C_BG_BLUE} %s ${C_RESET}\n" "$summary_text"
    echo ""
    _process "Reading summary..."
    _tts_speak "$summary_text" "$SUMMARY_AUDIO"
    _summary_done=1
}

# ─── Read full article ────────────────────────────────────────────────────────
# Requires globals: $selected_text, $FULL_ARTICLE_AUDIO, $SCRIPT_DIR, $_article_done

_read_full_article() {
    printf '%s' "$selected_text" | xclip -selection primary 2>/dev/null || true
    printf '%s' "$selected_text" | xclip -selection clipboard 2>/dev/null || true
    VOXREFINER_MENU=1 "$SCRIPT_DIR/selection_to_voice.sh"
    [ -f "$FULL_ARTICLE_AUDIO" ] && _article_done=1
}

# ─── Search flow ──────────────────────────────────────────────────────────────
# Usage: _search_flow <context_text>
# Sets globals: search_result, _search_done=1 on success

_search_flow() {
    local context_text="$1"

    if [ -z "${PERPLEXITY_API_KEY:-}" ] && [ -z "${XAI_API_KEY:-}" ]; then
        echo ""
        _error "No search API key set — search unavailable."
        _info "Add PERPLEXITY_API_KEY or XAI_API_KEY to your .env."
        echo ""
        return
    fi

    echo ""
    _header "SEARCH" "🔍"
    echo ""
    _info "Ask your question:"
    printf "  ${C_BOLD}[v]${C_RESET} Voice  ${C_BOLD}[t]${C_RESET} Type  ${C_BOLD}[m]${C_RESET} Back: "
    read -r _input_mode

    local query_text=""
    case "$_input_mode" in
        v|V)
            echo ""
            VOXREFINER_MENU=1 "$SCRIPT_DIR/record_and_transcribe_local.sh"
            query_text="$(xclip -o -selection clipboard 2>/dev/null || true)"
            if [ -z "$(printf '%s' "$query_text" | tr -d '[:space:]')" ]; then
                _warn "No query recorded — search cancelled."
                return
            fi
            echo ""
            _info "Query: $query_text"
            ;;
        t|T)
            echo ""
            printf "  Type your question: "
            read -r query_text
            if [ -z "$query_text" ]; then
                _warn "Empty query — search cancelled."
                return
            fi
            ;;
        *)
            return
            ;;
    esac

    echo ""
    _process "Searching..."
    echo ""

    search_result=$(printf '%s\n%s' "$query_text" "$context_text" | \
        INSIGHT_SEARCH_ENGINE="$_SETTING_SEARCH_ENGINE" \
        "$VENV_PYTHON" -m src.insight search 2>&3)

    if [ -z "$search_result" ]; then
        _error "Search returned no result — check your API keys and connection."
        return
    fi

    _show_and_speak "SEARCH RESULT" "🔍" "$search_result" "$SEARCH_AUDIO"
    _search_done=1
}

# ─── Fact-check flow ──────────────────────────────────────────────────────────
# Usage: _factcheck_flow <input_text>
# Sets globals: factcheck_result, _factcheck_done=1 on success

_factcheck_flow() {
    local input_text="$1"

    if [ -z "${PERPLEXITY_API_KEY:-}" ] && [ -z "${XAI_API_KEY:-}" ]; then
        echo ""
        _error "Neither PERPLEXITY_API_KEY nor XAI_API_KEY is set."
        _info "Add at least one to your .env to use fact-checking."
        echo ""
        return
    fi

    echo ""
    _header "FACT-CHECK" "🔬"
    echo ""
    _info "Verify a specific claim, or check the whole text?"
    printf "  ${C_BOLD}[v]${C_RESET} Voice  ${C_BOLD}[t]${C_RESET} Type  ${C_BOLD}[m]${C_RESET} Back  ${C_DIM}[Enter] Whole text${C_RESET}: "
    read -r _fc_mode

    export INSIGHT_QUERY=""
    local fc_query=""
    case "$_fc_mode" in
        v|V)
            echo ""
            VOXREFINER_MENU=1 "$SCRIPT_DIR/record_and_transcribe_local.sh"
            fc_query="$(xclip -o -selection clipboard 2>/dev/null || true)"
            if [ -n "$(printf '%s' "$fc_query" | tr -d '[:space:]')" ]; then
                INSIGHT_QUERY="$fc_query"
                export INSIGHT_QUERY
                _info "Verifying: $fc_query"
            fi
            ;;
        t|T)
            echo ""
            printf "  Type the claim to verify: "
            read -r fc_query
            if [ -n "$fc_query" ]; then
                INSIGHT_QUERY="$fc_query"
                export INSIGHT_QUERY
            fi
            ;;
        m|M)
            return
            ;;
    esac

    echo ""
    _process "Running fact-check..."
    echo ""

    factcheck_result=$(printf '%s' "$input_text" | \
        INSIGHT_SEARCH_ENGINE="$_SETTING_FACTCHECK_ENGINE" \
        INSIGHT_SYNTHESIS_REASONING="$_SETTING_SYNTHESIS_REASONING" \
        "$VENV_PYTHON" -m src.insight factcheck 2>&3)

    if [ -z "$factcheck_result" ]; then
        _error "Fact-check failed — check your API keys and connection."
        return
    fi

    _show_and_speak "FACT-CHECK RESULT" "🔬" "$factcheck_result" "$FACTCHECK_AUDIO"
    _factcheck_done=1

    if [ -s "${INSIGHT_PERPLEXITY_FILE:-}" ] && [ -s "${INSIGHT_GROK_FILE:-}" ]; then
        echo ""
        printf "  ${C_BOLD}[w]${C_RESET} Perplexity details  ${C_BOLD}[x]${C_RESET} Grok details  ${C_DIM}[Enter] Continue${C_RESET}: "
        read -r _detail_choice
        case "$_detail_choice" in
            w|W)
                local _detail
                _detail="$(cat "$INSIGHT_PERPLEXITY_FILE")"
                _show_and_speak "WEB DETAILS — PERPLEXITY" "🌐" "$_detail" "$INSIGHT_DIR/perplexity_detail.mp3"
                ;;
            x|X)
                local _detail
                _detail="$(cat "$INSIGHT_GROK_FILE")"
                _show_and_speak "X DETAILS — GROK" "𝕏" "$_detail" "$INSIGHT_DIR/grok_detail.mp3"
                ;;
        esac
    fi
}

# ─── Settings sub-menu ────────────────────────────────────────────────────────

_settings_flow() {
    while true; do
        echo ""
        _header "SETTINGS" "⚙"
        echo ""

        if [ -n "${PERPLEXITY_API_KEY:-}" ]; then
            _perplexity_status="${C_BGREEN}✓ key set${C_RESET}"
        else
            _perplexity_status="${C_RED}✗ key missing${C_RESET}"
        fi
        if [ -n "${XAI_API_KEY:-}" ]; then
            _grok_status="${C_BGREEN}✓ key set${C_RESET}"
        else
            _grok_status="${C_RED}✗ key missing${C_RESET}"
        fi
        printf "  Perplexity : %b\n" "$_perplexity_status"
        printf "  Grok       : %b\n" "$_grok_status"
        echo ""

        printf "  ${C_DIM}Summary${C_RESET}\n"
        printf "  ${C_BOLD}[1]${C_RESET} Reasoning (summary)   : ${C_BOLD}%s${C_RESET}  ${C_DIM}(standard · high)${C_RESET}\n" "$_SETTING_SUMMARY_REASONING"
        echo ""
        printf "  ${C_DIM}Search${C_RESET}\n"
        printf "  ${C_BOLD}[2]${C_RESET} Search engine          : ${C_BOLD}%s${C_RESET}  ${C_DIM}(auto · perplexity · grok · both)${C_RESET}\n" "$_SETTING_SEARCH_ENGINE"
        echo ""
        printf "  ${C_DIM}Fact-check${C_RESET}\n"
        printf "  ${C_BOLD}[3]${C_RESET} Fact-check engines     : ${C_BOLD}%s${C_RESET}  ${C_DIM}(both · perplexity · grok)${C_RESET}\n" "$_SETTING_FACTCHECK_ENGINE"
        printf "  ${C_BOLD}[4]${C_RESET} Reasoning (synthesis)  : ${C_BOLD}%s${C_RESET}  ${C_DIM}(standard · high) — only when both engines active${C_RESET}\n" "$_SETTING_SYNTHESIS_REASONING"
        echo ""
        printf "  ${C_BOLD}[m]${C_RESET} Back\n"
        printf "  ${C_BGREEN}▸${C_RESET} "
        read -r _set_choice
        case "$_set_choice" in
            1)
                if [ "$_SETTING_SUMMARY_REASONING" = "standard" ]; then
                    _SETTING_SUMMARY_REASONING="high"
                else
                    _SETTING_SUMMARY_REASONING="standard"
                fi
                _success "Summary reasoning → $_SETTING_SUMMARY_REASONING"
                ;;
            2)
                case "$_SETTING_SEARCH_ENGINE" in
                    auto)        _SETTING_SEARCH_ENGINE="perplexity" ;;
                    perplexity)  _SETTING_SEARCH_ENGINE="grok" ;;
                    grok)        _SETTING_SEARCH_ENGINE="both" ;;
                    *)           _SETTING_SEARCH_ENGINE="auto" ;;
                esac
                _success "Search engine → $_SETTING_SEARCH_ENGINE"
                ;;
            3)
                case "$_SETTING_FACTCHECK_ENGINE" in
                    both)        _SETTING_FACTCHECK_ENGINE="perplexity" ;;
                    perplexity)  _SETTING_FACTCHECK_ENGINE="grok" ;;
                    grok)        _SETTING_FACTCHECK_ENGINE="both" ;;
                    *)           _SETTING_FACTCHECK_ENGINE="both" ;;
                esac
                _success "Fact-check engines → $_SETTING_FACTCHECK_ENGINE"
                ;;
            4)
                if [ "$_SETTING_SYNTHESIS_REASONING" = "standard" ]; then
                    _SETTING_SYNTHESIS_REASONING="high"
                else
                    _SETTING_SYNTHESIS_REASONING="standard"
                fi
                _success "Synthesis reasoning → $_SETTING_SYNTHESIS_REASONING"
                ;;
            m|M) return ;;
            *) ;;
        esac
    done
}

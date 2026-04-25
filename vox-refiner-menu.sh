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

# Load .env — unset optional keys first so removed/renamed entries don't linger
# from a previous session. MISTRAL_API_KEY is required and left as-is.
unset EDENAI_API_KEY XAI_API_KEY PERPLEXITY_API_KEY GRADIUM_API_KEY
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
    local _catalog_file="$SCRIPT_DIR/src/voice_catalog.json"
    local _catalog_dump=""
    local _cur_vid _cur_slug _vchoice _vsample _tts_tmp
    local _vpreview_id _vpreview_slug _vpreview_provider_prefix _vpreview_lang
    local _sel_prefix _sel_number _provider_label _provider_api_env
    local _provider_hint="" _vi _group_has_notes _row_text _rows_printed
    local _provider_has_visible_groups _group_lang _selected_group_lang
    local _lang_filter="all" _lang_filter_label="All languages" _needs_lang_prompt=1
    local _hidden_mode=0 _public_lang_count=0
    local _lang_choice _lang_index _lang_code _lang_label _lang_count
    local _lang_exists _lang_has_voices
    local -a _provider_prefixes _provider_titles _provider_api_envs _provider_keys
    local -a _group_prefixes _group_ids _group_titles _group_langs _group_voice_counts
    local -a _voice_prefixes _voice_group_ids _voice_numbers _voice_labels
    local -a _voice_slugs _voice_ids _voice_sample_langs _voice_menu_notes
    local -a _row_prefixes _row_group_ids _row_texts
    local -a _lang_codes _lang_labels _lang_counts
    local _m_max=0 _g_max=0

    if ! _catalog_dump="$($VENV_PYTHON - "$_catalog_file" <<'PY'
import json
import sys
import unicodedata


def display_width(text: str) -> int:
    width = 0
    for char in text:
        if unicodedata.combining(char):
            continue
        if unicodedata.east_asian_width(char) in ("W", "F"):
            width += 2
        else:
            width += 1
    return width


def ljust_display(text: str, width: int) -> str:
    return text + (" " * max(0, width - display_width(text)))


def format_grid_rows(items, columns=3, gap=4):
    if not items:
        return []
    col_width = max(display_width(item) for item in items)
    rows = []
    for start in range(0, len(items), columns):
        chunk = items[start:start + columns]
        padded = []
        for idx, item in enumerate(chunk):
            if idx < len(chunk) - 1:
                padded.append(ljust_display(item, col_width))
            else:
                padded.append(item)
        rows.append((" " * gap).join(padded))
    return rows

catalog_path = sys.argv[1]
with open(catalog_path, encoding="utf-8") as f:
    data = json.load(f)

for provider in data.get("providers", []):
    prefix = provider["prefix"]
    title = provider["title"]
    api_env = provider.get("api_key_env", "")
    key = provider.get("key", "")
    print(f"PROVIDER\t{prefix}\t{title}\t{api_env}\t{key}")
    provider_index = 1
    for group_idx, group in enumerate(provider.get("groups", []), start=1):
        start_index = group.get("start_index")
        if isinstance(start_index, int) and start_index > 0:
            provider_index = start_index
        group_title = str(group.get("title", "")).replace("\t", " ").replace("\n", " ").strip()
        group_langs = {
            str(voice.get("sample_lang", "")).strip().lower()
            for voice in group.get("voices", [])
            if str(voice.get("sample_lang", "")).strip()
        }
        if len(group_langs) == 1:
            group_lang = next(iter(group_langs))
        elif len(group_langs) > 1:
            group_lang = "mul"
        else:
            group_lang = "und"
        print(f"GROUP\t{prefix}\t{group_idx}\t{group_title}\t{group_lang}")
        group_rows = []
        for voice in group.get("voices", []):
            label = str(voice.get("label", "")).replace("\t", " ").replace("\n", " ").strip()
            note = (voice.get("menu_note", "") or "").replace("\t", " ").replace("\n", " ").strip()
            group_rows.append((provider_index, label, note))
            print(
                "VOICE\t"
                f"{prefix}\t{group_idx}\t{provider_index}\t"
                f"{label}\t{voice['slug']}\t{voice['id']}\t{voice.get('sample_lang', 'en')}\t{note}"
            )
            provider_index += 1
        if prefix != "g" and group_rows and not any(note for _, _, note in group_rows):
            grid_items = [f"[{prefix}{idx}] {label}" for idx, label, _ in group_rows]
            columns = 1 if prefix == "c" else 3
            for row in format_grid_rows(grid_items, columns=columns, gap=4):
                print(f"ROW\t{prefix}\t{group_idx}\t{row}")
PY
)"; then
        _error "Failed to load voice catalog: $_catalog_file"
        sleep 1
        return 1
    fi

    while IFS=$'\t' read -r _kind _f1 _f2 _f3 _f4 _f5 _f6 _f7 _f8 _f9; do
        [ -z "$_kind" ] && continue
        case "$_kind" in
            PROVIDER)
                _provider_prefixes+=("$_f1")
                _provider_titles+=("$_f2")
                _provider_api_envs+=("$_f3")
                _provider_keys+=("$_f4")
                ;;
            GROUP)
                _group_prefixes+=("$_f1")
                _group_ids+=("$_f2")
                _group_titles+=("$_f3")
                _group_langs+=("$_f4")
                ;;
            VOICE)
                _voice_prefixes+=("$_f1")
                _voice_group_ids+=("$_f2")
                _voice_numbers+=("$_f3")
                _voice_labels+=("$_f4")
                _voice_slugs+=("$_f5")
                _voice_ids+=("$_f6")
                _voice_sample_langs+=("$_f7")
                _voice_menu_notes+=("$_f8")
                if [ "$_f1" = "m" ] && [ "$_f3" -gt "$_m_max" ]; then _m_max="$_f3"; fi
                if [ "$_f1" = "g" ] && [ "$_f3" -gt "$_g_max" ]; then _g_max="$_f3"; fi
                ;;
            ROW)
                _row_prefixes+=("$_f1")
                _row_group_ids+=("$_f2")
                _row_texts+=("$_f3")
                ;;
        esac
    done <<< "$_catalog_dump"

    for _gi in "${!_group_ids[@]}"; do
        _lang_count=0
        for _vi in "${!_voice_ids[@]}"; do
            [ "${_voice_prefixes[$_vi]}" != "${_group_prefixes[$_gi]}" ] && continue
            [ "${_voice_group_ids[$_vi]}" != "${_group_ids[$_gi]}" ] && continue
            _lang_count=$((_lang_count + 1))
        done
        _group_voice_counts+=("$_lang_count")
    done

    for _lang_code in fr en de es pt; do
        _lang_has_voices=0
        for _gi in "${!_group_ids[@]}"; do
            [ "${_group_langs[$_gi]}" != "$_lang_code" ] && continue
            if [ "${_group_voice_counts[$_gi]}" -gt 0 ]; then
                _lang_has_voices=1
                break
            fi
        done
        [ "$_lang_has_voices" -eq 0 ] && continue
        case "$_lang_code" in
            fr) _lang_label="French" ;;
            en) _lang_label="English" ;;
            de) _lang_label="German" ;;
            es) _lang_label="Spanish" ;;
            pt) _lang_label="Portuguese" ;;
            eo) _lang_label="Esperanto" ;;
            *)  _lang_label="${_lang_code^^}" ;;
        esac
        _lang_codes+=("$_lang_code")
        _lang_labels+=("$_lang_label")
        _lang_counts+=("0")
    done
    _public_lang_count=${#_lang_codes[@]}

    for _gi in "${!_group_ids[@]}"; do
        _lang_code="${_group_langs[$_gi]}"
        [ "${_group_voice_counts[$_gi]}" -le 0 ] && continue
        _lang_exists=0
        for _li in "${!_lang_codes[@]}"; do
            if [ "${_lang_codes[$_li]}" = "$_lang_code" ]; then
                _lang_exists=1
                break
            fi
        done
        [ "$_lang_exists" -eq 1 ] && continue
        case "$_lang_code" in
            fr) _lang_label="French" ;;
            en) _lang_label="English" ;;
            de) _lang_label="German" ;;
            es) _lang_label="Spanish" ;;
            pt) _lang_label="Portuguese" ;;
            mul) _lang_label="Mixed" ;;
            und) _lang_label="Unknown" ;;
            *)   _lang_label="${_lang_code^^}" ;;
        esac
        _lang_codes+=("$_lang_code")
        _lang_labels+=("$_lang_label")
        _lang_counts+=("0")
    done

    for _li in "${!_lang_codes[@]}"; do
        _lang_count=0
        for _gi in "${!_group_ids[@]}"; do
            [ "${_group_langs[$_gi]}" != "${_lang_codes[$_li]}" ] && continue
            _lang_count=$((_lang_count + ${_group_voice_counts[$_gi]}))
        done
        _lang_counts[$_li]="$_lang_count"
    done

    if [ "${#_voice_ids[@]}" -eq 0 ]; then
        _error "Voice catalog has no entries: $_catalog_file"
        sleep 1
        return 1
    fi

    local _vtext_fr="Au début, tout semble évident. Puis un détail attire l’attention, une nuance apparaît… et la perception change. C’est souvent à ce moment-là que l’on commence vraiment à écouter."
    local _vtext_en="At first, everything seems obvious. Then a detail stands out, a nuance appears… and perception shifts. That’s often when we truly start to listen."
    local _vtext_de="Am Anfang scheint alles offensichtlich. Dann fällt ein Detail auf, eine Nuance tritt hervor … und die Wahrnehmung verändert sich. Oft beginnt genau dann das echte Zuhören."
    local _vtext_es="Al principio, todo parece evidente. Luego un detalle llama la atención, aparece un matiz… y la percepción cambia. A menudo, es justo ahí cuando empezamos a escuchar de verdad."
    local _vtext_pt="No início, tudo parece óbvio. Depois, um detalhe chama a atenção, surge uma nuance… e a perceção muda. É muitas vezes nesse momento que começamos realmente a escutar."
    local _vtext_eo="Komence, ĉio ŝajnas evidenta. Tiam detalo elstaras, nuanco aperas… kaj percepto ŝanĝiĝas. Tio ofte estas kiam ni vere komencas aŭskulti."
    _vpreview_id=""
    _vpreview_slug=""
    _vpreview_provider_prefix=""
    _vpreview_lang=""

    while true; do
        _cur_vid="${!_vp_var}"
        _cur_slug="(not set)"
        if [ -z "$_cur_vid" ] && [ "$_vp_allow_disable" = "1" ]; then
            _cur_slug="(disabled)"
        else
            for _i in "${!_voice_ids[@]}"; do
                if [ "${_voice_ids[$_i]}" = "$_cur_vid" ]; then
                    _cur_slug="${_voice_slugs[$_i]}"
                    break
                fi
            done
        fi

        if [ "$_needs_lang_prompt" -eq 1 ]; then
            while true; do
                clear
                _header "$_vp_title - LANGUAGE" "🌐"
                echo ""
                printf "  ${C_DIM}Choose a language filter before listing voices.${C_RESET}\n"
                echo ""
                _sep
                echo ""
                for _li in "${!_lang_codes[@]}"; do
                    if [ "$_hidden_mode" -eq 0 ] && [ "$_li" -ge "$_public_lang_count" ]; then continue; fi
                    _lang_index=$((_li + 1))
                    printf "  ${C_BOLD}[%s]${C_RESET} %s ${C_DIM}(%s voices)${C_RESET}\n" \
                        "$_lang_index" "${_lang_labels[$_li]}" "${_lang_counts[$_li]}"
                done
                echo ""
                printf "  ${C_BOLD}[a]${C_RESET} All languages\n"
                printf "  ${C_BOLD}[m]${C_RESET} Menu settings\n"
                echo ""
                printf "  ${C_BGREEN}▸${C_RESET} "
                read -r _lang_choice
                case "$_lang_choice" in
                    m|M)
                        return 0
                        ;;
                    a|A|"")
                        _lang_filter="all"
                        _lang_filter_label="All languages"
                        break
                        ;;
                    *)
                        if [[ "$_lang_choice" =~ ^[0-9]+$ ]]; then
                            _lang_index=$((_lang_choice - 1))
                            if [ "$_lang_index" -ge 0 ] && [ "$_lang_index" -lt "${#_lang_codes[@]}" ]; then
                                _lang_filter="${_lang_codes[$_lang_index]}"
                                _lang_filter_label="${_lang_labels[$_lang_index]}"
                                break
                            fi
                        fi
                        ;;
                esac
            done
            _needs_lang_prompt=0
        fi

        clear
        _header "$_vp_title" "🔈"
        echo ""
        printf "  ${C_DIM}Current:${C_RESET} ${C_BGREEN}%s${C_RESET}\n" "$_cur_slug"
        printf "  ${C_DIM}Language:${C_RESET} ${C_BCYAN}%s${C_RESET}\n" "$_lang_filter_label"
        echo ""
        _sep
        echo ""
        for _pi in "${!_provider_prefixes[@]}"; do
            _sel_prefix="${_provider_prefixes[$_pi]}"
            _provider_label="${_provider_titles[$_pi]}"
            _provider_api_env="${_provider_api_envs[$_pi]}"
            _provider_key="${_provider_keys[$_pi]}"
            if [ "$_hidden_mode" -eq 0 ] && [ "$_provider_key" = "comparison" ]; then
                continue
            fi
            if [ "$_lang_filter" = "comparison" ] && [ "$_provider_key" != "comparison" ]; then
                continue
            fi
            if [ "$_lang_filter" != "all" ] && [ "$_lang_filter" != "comparison" ] && [ "$_provider_key" = "comparison" ]; then
                continue
            fi
            _provider_has_visible_groups=0
            for _gi in "${!_group_ids[@]}"; do
                [ "${_group_prefixes[$_gi]}" != "$_sel_prefix" ] && continue
                if [ "$_lang_filter" != "all" ] && [ "$_lang_filter" != "comparison" ] && [ "${_group_langs[$_gi]}" != "$_lang_filter" ]; then
                    continue
                fi
                if [ "${_group_voice_counts[$_gi]}" -gt 0 ]; then
                    _provider_has_visible_groups=1
                    break
                fi
            done
            [ "$_provider_has_visible_groups" -eq 0 ] && continue

            if [ -n "$_provider_api_env" ] && [ -z "${!_provider_api_env:-}" ] && [ "$_sel_prefix" != "m" ]; then
                printf "  ${C_BGREEN}%s${C_RESET}  ${C_DIM}(unavailable — %s not set, see Settings → API Keys)${C_RESET}\n" "$_provider_label" "$_provider_api_env"
            else
                printf "  ${C_BGREEN}%s${C_RESET}\n" "$_provider_label"
            fi

            for _gi in "${!_group_prefixes[@]}"; do
                [ "${_group_prefixes[$_gi]}" != "$_sel_prefix" ] && continue
                _group_lang="${_group_langs[$_gi]}"
                if [ "$_lang_filter" != "all" ] && [ "$_lang_filter" != "comparison" ] && [ "$_group_lang" != "$_lang_filter" ]; then
                    continue
                fi
                [ "${_group_voice_counts[$_gi]}" -le 0 ] && continue
                printf "  ${C_BCYAN}%s${C_RESET}\n" "${_group_titles[$_gi]}"

                _group_has_notes=0
                for _vi in "${!_voice_ids[@]}"; do
                    [ "${_voice_prefixes[$_vi]}" != "$_sel_prefix" ] && continue
                    [ "${_voice_group_ids[$_vi]}" != "${_group_ids[$_gi]}" ] && continue
                    if [ -n "${_voice_menu_notes[$_vi]}" ]; then
                        _group_has_notes=1
                        break
                    fi
                done

                if [ "$_sel_prefix" = "g" ] || [ "$_group_has_notes" = "1" ]; then
                    for _vi in "${!_voice_ids[@]}"; do
                        [ "${_voice_prefixes[$_vi]}" != "$_sel_prefix" ] && continue
                        [ "${_voice_group_ids[$_vi]}" != "${_group_ids[$_gi]}" ] && continue
                        if [ -n "${_voice_menu_notes[$_vi]}" ]; then
                            printf "  ${C_BOLD}[%s%s]${C_RESET} %s ${C_DIM}- %s${C_RESET}\n" \
                                "$_sel_prefix" "${_voice_numbers[$_vi]}" "${_voice_labels[$_vi]}" "${_voice_menu_notes[$_vi]}"
                        else
                            printf "  ${C_BOLD}[%s%s]${C_RESET} %s\n" \
                                "$_sel_prefix" "${_voice_numbers[$_vi]}" "${_voice_labels[$_vi]}"
                        fi
                    done
                else
                    _rows_printed=0
                    for _ri in "${!_row_texts[@]}"; do
                        [ "${_row_prefixes[$_ri]}" != "$_sel_prefix" ] && continue
                        [ "${_row_group_ids[$_ri]}" != "${_group_ids[$_gi]}" ] && continue
                        _row_text="${_row_texts[$_ri]}"
                        printf "  %s\n" "$_row_text"
                        _rows_printed=1
                    done
                    if [ "$_rows_printed" -eq 0 ]; then
                        for _vi in "${!_voice_ids[@]}"; do
                            [ "${_voice_prefixes[$_vi]}" != "$_sel_prefix" ] && continue
                            [ "${_voice_group_ids[$_vi]}" != "${_group_ids[$_gi]}" ] && continue
                            printf "  ${C_BOLD}[%s%s]${C_RESET} %s\n" \
                                "$_sel_prefix" "${_voice_numbers[$_vi]}" "${_voice_labels[$_vi]}"
                        done
                    fi
                fi
                echo ""
            done
        done

        _sep
        _provider_hint=""
        [ "$_m_max" -gt 0 ] && _provider_hint="m1-m$_m_max"
        [ "$_g_max" -gt 0 ] && _provider_hint="${_provider_hint:+${_provider_hint}, }g1-g$_g_max"
        if [ -n "$_vpreview_id" ]; then
            printf "  ${C_DIM}Last preview:${C_RESET} ${C_CYAN}%s${C_RESET}   ${C_BOLD}[s]${C_RESET} Select it" "$_vpreview_slug"
            [ "$_vp_allow_disable" = "1" ] && printf "  ${C_BOLD}[d]${C_RESET} Disable"
            printf "  ${C_BOLD}[l]${C_RESET} Language  ${C_BOLD}[m]${C_RESET} Menu settings\n"
        else
            printf "  ${C_DIM}Type provider+number to listen (%s)" "$_provider_hint"
            [ "$_vp_allow_disable" = "1" ] && printf "   ${C_BOLD}[d]${C_RESET} ${C_DIM}Disable"
            printf "   ${C_BOLD}[l]${C_RESET} Language   ${C_BOLD}[m]${C_RESET} Menu settings\n"
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
            l|L)
                _needs_lang_prompt=1
                ;;
            h|H)
                # Toggle hidden comparison voices
                if [ "$_hidden_mode" -eq 1 ]; then
                    _hidden_mode=0
                    _warn "Hidden comparison voices disabled."
                else
                    _hidden_mode=1
                    _warn "Hidden comparison voices enabled — temporary access for testing."
                fi
                ;;
            ""|m|M) break ;;
            *)
                _vi=-1
                if [[ "$_vchoice" =~ ^([A-Za-z])([0-9]+)$ ]]; then
                    _sel_prefix="${BASH_REMATCH[1],,}"
                    _sel_number="${BASH_REMATCH[2]}"
                    for _i in "${!_voice_ids[@]}"; do
                        if [ "${_voice_prefixes[$_i]}" = "$_sel_prefix" ] && \
                           [ "${_voice_numbers[$_i]}" = "$_sel_number" ]; then
                            _vi="$_i"
                            break
                        fi
                    done
                fi

                if [ "$_vi" -ge 0 ]; then
                    _selected_group_lang=""
                    for _gi in "${!_group_ids[@]}"; do
                        if [ "${_group_prefixes[$_gi]}" = "${_voice_prefixes[$_vi]}" ] && \
                           [ "${_group_ids[$_gi]}" = "${_voice_group_ids[$_vi]}" ]; then
                            _selected_group_lang="${_group_langs[$_gi]}"
                            break
                        fi
                    done
                    if [ "$_lang_filter" != "all" ] && [ "$_lang_filter" != "comparison" ] && [ "$_selected_group_lang" != "$_lang_filter" ]; then
                        _warn "Voice is outside current language filter. Press [l] to change language."
                        sleep 1
                        continue
                    fi
                    if [ "${_voice_prefixes[$_vi]}" = "c" ]; then
                        _cv_id="${_voice_ids[$_vi]}"
                        if [[ "$_cv_id" == google-* ]] && [ -z "${GOOGLE_TTS_API_KEY:-}" ]; then
                            _error "Google TTS comparison voice requires GOOGLE_TTS_API_KEY. Go to Settings → API Keys to configure it."
                            sleep 2
                            continue
                        elif [[ "$_cv_id" == eleven-* || "$_cv_id" == openai-* || "$_cv_id" == amazon-* || "$_cv_id" == deepgram-* ]] && [ -z "${EDENAI_API_KEY:-}" ]; then
                            _error "This comparison voice requires EDENAI_API_KEY. Go to Settings → API Keys to configure it."
                            sleep 2
                            continue
                        fi
                    fi
                    _vpreview_id_saved="$_vpreview_id"
                    _vpreview_slug_saved="$_vpreview_slug"
                    _vpreview_provider_prefix_saved="$_vpreview_provider_prefix"
                    _vpreview_lang_saved="$_vpreview_lang"
                    _vpreview_id="${_voice_ids[$_vi]}"
                    _vpreview_slug="${_voice_slugs[$_vi]}"
                    _vpreview_provider_prefix="${_voice_prefixes[$_vi]}"
                    _vpreview_lang="${_voice_sample_langs[$_vi],,}"
                    case "$_vpreview_lang" in
                        fr|fr-*) _vsample="$_vtext_fr" ;;
                        de|de-*) _vsample="$_vtext_de" ;;
                        es|es-*) _vsample="$_vtext_es" ;;
                        pt|pt-*) _vsample="$_vtext_pt" ;;
                        en|en-*) _vsample="$_vtext_en" ;;
                        eo|eo-*) _vsample="$_vtext_eo" ;;
                        *) _vsample="$_vtext_en" ;;
                    esac
                    _tts_tmp="$SCRIPT_DIR/recordings/.voice_preview.mp3"
                    echo ""
                    _provider_api_env=""
                    for _pi in "${!_provider_prefixes[@]}"; do
                        if [ "${_provider_prefixes[$_pi]}" = "$_vpreview_provider_prefix" ]; then
                            _provider_api_env="${_provider_api_envs[$_pi]}"
                            break
                        fi
                    done
                    # For comparison voices, the required key depends on the voice provider,
                    # not the parent comparison provider (which defaults to GOOGLE_TTS_API_KEY).
                    if [ "$_vpreview_provider_prefix" = "c" ] && [[ "$_vpreview_id" == eleven-* || "$_vpreview_id" == openai-* || "$_vpreview_id" == amazon-* || "$_vpreview_id" == deepgram-* ]]; then
                        _provider_api_env="EDENAI_API_KEY"
                    fi
                    if [ -n "$_provider_api_env" ] && [ -z "${!_provider_api_env:-}" ]; then
                        _warn "$_provider_api_env is not set — cannot preview or select this voice."
                        printf "  ${C_DIM}Add it via Settings → API Keys.${C_RESET}\n"
                        _vpreview_id="$_vpreview_id_saved"
                        _vpreview_slug="$_vpreview_slug_saved"
                        _vpreview_provider_prefix="$_vpreview_provider_prefix_saved"
                        _vpreview_lang="$_vpreview_lang_saved"
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
                            _vpreview_provider_prefix=""
                            _vpreview_lang=""
                        fi
                    fi
                else
                    _warn "Invalid choice. Use mN or gN."
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

_test_google_tts_key() {
    local key="$1"
    if [ -z "$key" ]; then
        _error "No Google TTS key to test."
        return 1
    fi
    printf "  ${C_CYAN}⚡ Testing Google TTS key...${C_RESET}\n"
    # Test with a simple models list call using API key header
    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "x-goog-api-key: $key" \
        "https://generativelanguage.googleapis.com/v1beta/models" \
        --max-time 15 2>/dev/null)
    case "$http_code" in
        200) _success "Google TTS key is valid." ; return 0 ;;
        400) _error  "Bad request (400) — invalid API key format." ; return 1 ;;
        401) _error  "Invalid Google TTS key (401 Unauthorized)." ; return 1 ;;
        403) _error  "Forbidden (403) — check API permissions or billing." ; return 1 ;;
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
        printf "  ${C_BGREEN}✓${C_RESET}  Extended voice bank      (Gradium French voice catalog)\n"
    else
        printf "  ${C_DIM}○${C_RESET}  ${C_DIM}Extended voice bank       — add GRADIUM_API_KEY to unlock Gradium voices (gN)${C_RESET}\n"
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
        printf "  ${C_BOLD}Gradium${C_RESET}    ${C_DIM}(optional)${C_RESET}  : ${C_CYAN}%s${C_RESET}  ${C_DIM}~1hr \$0/month HT | ~5hr \$13/month HT ${C_RESET}\n"  "$(_mask_key "${GRADIUM_API_KEY:-}")"
        printf "  ${C_BOLD}Google TTS${C_RESET} ${C_DIM}(optional)${C_RESET}  : ${C_CYAN}%s${C_RESET}  ${C_DIM}for comparison voices${C_RESET}\n"  "$(_mask_key "${GOOGLE_TTS_API_KEY:-}")"
        echo ""
        printf "  ${C_DIM}  Voice pricing :${C_RESET}\n"
        printf "  ${C_DIM}    Mistral\n${C_RESET}"
        printf "  ${C_DIM}    TTS : ~\$0.016 / 1K chars (~0.7–0.9$/hour audio)${C_RESET}\n" 
        printf "  ${C_DIM}    STT : ~\$0.003 / minute audio (~0.18$/hour)${C_RESET}\n"
        echo ""
        printf "  ${C_DIM}    Gradium\n${C_RESET}"
        printf "  ${C_DIM}    TTS : ~1.6 → 2.6$/hour audio (credits-based)${C_RESET}\n"
        printf "  ${C_DIM}    STT : ~0.65 → 1.00$/hour audio (credits-based)${C_RESET}\n"
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
        printf "  ${C_BOLD}[t6]${C_RESET}  Test Google TTS key    ${C_BOLD}[e6]${C_RESET}  Edit Google TTS key\n"
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
            t6|T6)
                echo ""
                _test_google_tts_key "${GOOGLE_TTS_API_KEY:-}"
                echo ""
                printf "  ${C_DIM}Press Enter to continue...${C_RESET}"
                read -r
                ;;
            e6|E6)
                echo ""
                printf "  Enter new Google TTS API key: "
                _read_masked
                _new_key="$_MASKED_INPUT"
                if [ -z "$_new_key" ]; then
                    _warn "No key entered — unchanged."
                else
                    _set_env_var "GOOGLE_TTS_API_KEY" "$_new_key"
                    export GOOGLE_TTS_API_KEY="$_new_key"
                    set -a; source .env; set +a
                    _success "Google TTS key saved."
                    echo ""
                    _test_google_tts_key "$_new_key"
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

    while true; do
        clear
        echo ""
        printf "  ${C_BYELLOW}🚧  Coming soon: %s${C_RESET}\n" "$name"
        echo ""
        printf "  ${C_DIM}%s${C_RESET}\n" "$desc"
        echo ""
        printf "  ${C_BOLD}[m]${C_RESET} Menu VoxRefiner : "
        
        read -r _post_action
        
        case "$_post_action" in
            m|M) 
                return 
                ;;
            *)                 
                ;;
        esac
    done
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
                    _vt_use_status="${C_BOLD}off${C_RESET}"
                fi

                clear
                _header "SPEAK & TRANSLATE" "🎙 → 🔊"
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
                        printf "  ${C_BOLD}[m]${C_RESET}  Menu Update\n"
                        echo ""
                        while true; do
                            printf "  ${C_BGREEN}▸${C_RESET} "
                            read -r _upd_check_action
                            case "$_upd_check_action" in
                                m|M) break ;;
                                *) ;;
                            esac
                        done
                        ;;
                    a|A)
                        echo ""
                        if ./vox-refiner-update.sh --apply; then
                            echo ""
                            _success "Restart VoxRefiner to use the new version."
                        fi
                        echo ""
                        printf "  ${C_BOLD}[m]${C_RESET}  Menu Update\n"
                        echo ""
                        while true; do
                            printf "  ${C_BGREEN}▸${C_RESET} "
                            read -r _upd_apply_action
                            case "$_upd_apply_action" in
                                m|M) break ;;
                                *) ;;
                            esac
                        done
                        ;;
                    '?')
                        echo ""
                        if [ -f docs/troubleshooting-update.md ]; then
                            cat docs/troubleshooting-update.md
                        else
                            _warn "docs/troubleshooting-update.md not found."
                        fi
                        echo ""
                        printf "  ${C_BOLD}[m]${C_RESET}  Menu Update\n"
                        echo ""
                        while true; do
                            printf "  ${C_BGREEN}▸${C_RESET} "
                            read -r _upd_help_action
                            case "$_upd_help_action" in
                                m|M) break ;;
                                *) ;;
                            esac
                        done
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

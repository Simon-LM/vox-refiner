#!/bin/bash
# VoxRefiner — Reminder entry point
# Adds a new reminder from typed text, voice recording, or OCR screenshot.
# Also used by the daemon to present triggered reminders in the terminal.
#
# Modes:
#   ./reminder.sh              → interactive: type or dictate a new reminder
#   ./reminder.sh --add TEXT   → add reminder from text argument
#   ./reminder.sh --ocr        → add reminder from screenshot (OCR)
#   ./reminder.sh --fire ID    → present a triggered reminder (called by daemon)
set -euo pipefail

cd "$(dirname "$0")"
SCRIPT_DIR="$(pwd)"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"

source "$SCRIPT_DIR/src/ui.sh"

exec 3>&2

[ -f .env ] && set -a && source .env && set +a

if [ ! -x "$VENV_PYTHON" ]; then
    _error "Missing .venv — run ./install.sh"
    exit 1
fi

if [ "${REMINDER_ENABLED:-false}" != "true" ]; then
    _warn "Reminders are disabled on this installation."
    _info "To enable: set REMINDER_ENABLED=true in your .env file."
    exit 0
fi

# ── Phrases (adapts to OUTPUT_LANG: en → English, otherwise French) ──────────
if [ "${OUTPUT_LANG:-}" = "en" ]; then
    _P_DONE="Great, all done!"
    _P_LATER="Sure, I'll remind you later."
    _P_GOING="On you go! I'll check back in 5 minutes."
    _P_CANCELLED="Reminder cancelled."
    _P_ADDED="Reminder added"
else
    _P_DONE="Super, c'est fait !"
    _P_LATER="D'accord, je te rappelle plus tard."
    _P_GOING="Allez, je reviens dans 5 minutes."
    _P_CANCELLED="Rappel annulé."
    _P_ADDED="Rappel ajouté"
fi

# ── Helpers ───────────────────────────────────────────────────────────────────

_chime() {
    command -v mpv >/dev/null 2>&1 || return 0
    local _sounds=(
        "/usr/share/sounds/freedesktop/stereo/bell.oga"
        "/usr/share/sounds/freedesktop/stereo/message.oga"
        "/usr/share/sounds/ubuntu/stereo/message-new-instant.ogg"
    )
    for _s in "${_sounds[@]}"; do
        if [ -f "$_s" ]; then
            # First play wakes up the audio subsystem; second is fully audible.
            mpv --no-video --no-terminal \
                --volume="${REMINDER_VOLUME:-200}" "$_s" 2>/dev/null || true
            mpv --no-video --no-terminal \
                --volume="${REMINDER_VOLUME:-200}" "$_s" 2>&3 || true
            return
        fi
    done
}

_speak() {
    local _text="$1"
    [ -z "$_text" ] && return 0
    command -v mpv >/dev/null 2>&1 || { _warn "mpv not found — no audio."; return 0; }
    local _chunks_dir _voice_id
    _chunks_dir=$(mktemp -d /tmp/vox-speak-XXXXXX)
    _voice_id="${REMINDER_VOICE_ID:-$TTS_SELECTION_VOICE_ID}"
    (
        printf '%s' "$_text" \
            | TTS_SKIP_AI_CLEAN=1 TTS_VOICE_ID="$_voice_id" \
              "$VENV_PYTHON" -m src.tts --chunked "$_chunks_dir" 2>&3 \
            | while IFS= read -r _chunk; do
                [ -z "$_chunk" ] && continue
                [[ "$_chunk" == CHUNK_FAILED:* ]] && continue
                mpv --no-video --really-quiet \
                    --volume="${REMINDER_VOLUME:-150}" "$_chunk" 2>/dev/null || true
              done
    ) || true
    rm -rf "$_chunks_dir"
}

_announce_reminder() {
    local _title="$1"
    local _phrases
    if [ "${OUTPUT_LANG:-}" = "en" ]; then
        _phrases=(
            "Hey! $_title"
            "Don't forget — $_title"
            "Quick reminder: $_title"
            "It's time. $_title"
        )
    else
        _phrases=(
            "Hey ! $_title"
            "N'oublie pas — $_title"
            "Petit rappel : $_title"
            "C'est l'heure. $_title"
        )
    fi
    _chime
    sleep 1
    _speak "${_phrases[$(( RANDOM % ${#_phrases[@]} ))]}"
}

_read_voice_input() {
    # Calls record_and_transcribe_local.sh directly (NOT in $(...)) so prompts stay visible.
    # Writes result into _voice_text; caller must NOT capture this function with $().
    VOXREFINER_MENU=1 ENABLE_REFINE=false OUTPUT_PROFILE=plain \
        bash "$SCRIPT_DIR/record_and_transcribe_local.sh"
    _voice_text=$(xclip -o -selection clipboard 2>/dev/null || echo "")
}

# Ask a single profile question and resolve it.
# Usage: _profile_ask_question "$question_json"  (JSON with id + question fields)
_profile_ask_question() {
    local _q_json="$1"
    local _qid _qtext _answer
    _qid=$(printf '%s' "$_q_json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null) || return 0
    _qtext=$(printf '%s' "$_q_json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('question',''))" 2>/dev/null) || return 0
    if [ -z "$_qid" ] || [ -z "$_qtext" ]; then return 0; fi
    echo ""
    _info "$_qtext"
    printf "  > "
    if ! read -e -r _answer; then return 0; fi
    if [ -z "$_answer" ]; then return 0; fi
    "$VENV_PYTHON" -m src.profile resolve "$_qid" "$_answer" 2>&3 || true
}

# Run the context AI on *text* in background, ask any clarifying question now.
_profile_update() {
    local _text="$1"
    if [ -z "$_text" ]; then return 0; fi
    local _q_json
    _q_json=$("$VENV_PYTHON" -m src.profile update "$_text" 2>&3) || return 0
    if [ -n "$_q_json" ]; then _profile_ask_question "$_q_json"; fi
}

# Ask the first pending profile question if any (called at startup).
_profile_ask_pending() {
    local _q_json
    _q_json=$("$VENV_PYTHON" -m src.profile pending 2>&3) || return 0
    if [ -n "$_q_json" ]; then _profile_ask_question "$_q_json"; fi
}

# Ask a single per-task question and store the answer in the reminder metadata.
# Usage: _task_ask_question <reminder_id> "$question_json"  (JSON with id + question fields)
_task_ask_question() {
    local _rid="$1"
    local _q_json="$2"
    local _qid _qtext _answer
    _qid=$(printf '%s' "$_q_json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null) || return 0
    _qtext=$(printf '%s' "$_q_json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('question',''))" 2>/dev/null) || return 0
    if [ -z "$_qid" ] || [ -z "$_qtext" ]; then return 0; fi
    echo ""
    _info "$_qtext"
    printf "  > "
    if ! read -e -r _answer; then return 0; fi
    if [ -z "$_answer" ]; then return 0; fi
    "$VENV_PYTHON" -m src.reminder.questions resolve "$_rid" "$_qid" "$_answer" 2>&3 || true
}

# Ask every pending question attached to a freshly-created reminder.
# Usage: _task_ask_pending_for <reminder_id>
_task_ask_pending_for() {
    local _rid="$1"
    local _list
    _list=$("$VENV_PYTHON" -m src.reminder.questions for-reminder "$_rid" 2>&3) || return 0
    if [ -z "$_list" ]; then return 0; fi
    local _count
    _count=$(printf '%s' "$_list" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))" 2>/dev/null) || _count=0
    local _idx=0
    while [ "$_idx" -lt "$_count" ]; do
        local _q
        _q=$(printf '%s' "$_list" | python3 -c "import sys,json; print(json.dumps(json.load(sys.stdin)[$_idx], ensure_ascii=False))" 2>/dev/null) || break
        _task_ask_question "$_rid" "$_q"
        _idx=$(( _idx + 1 ))
    done
}

# Surface the most urgent pending task question if any (called at startup).
_task_ask_next_pending() {
    local _entry
    _entry=$("$VENV_PYTHON" -m src.reminder.questions next 2>&3) || return 0
    if [ -z "$_entry" ]; then return 0; fi
    local _rid
    _rid=$(printf '%s' "$_entry" | python3 -c "import sys,json; print(json.load(sys.stdin).get('reminder_id',''))" 2>/dev/null) || return 0
    if [ -z "$_rid" ]; then return 0; fi
    _task_ask_question "$_rid" "$_entry"
}

# Read the user's answer to a conversation question (text by default, voice if
# the user enters the literal "v"). Result is left in the global $_conv_answer.
# If voice capture comes back empty (silence, mic failure, …) we fall back to
# a text prompt rather than silently ending the conversation.
# $_conv_answer_source is set to "voice" when speech-to-text produced the
# answer, "text" otherwise (including the typed fallback after empty voice).
_conv_read_answer() {
    _conv_answer=""
    _conv_answer_source="text"
    local _input
    if ! read -e -r _input; then return 1; fi
    if [ "$_input" = "v" ] || [ "$_input" = "V" ]; then
        _read_voice_input
        _conv_answer="$_voice_text"
        if [ -z "$_conv_answer" ]; then
            echo ""
            _warn "Réponse vocale vide — tapez votre réponse :"
            printf "  > "
            if ! read -e -r _input; then return 1; fi
            _conv_answer="$_input"
            _conv_answer_source="text"
        else
            _info "Réponse captée : $_conv_answer"
            _conv_answer_source="voice"
        fi
    else
        _conv_answer="$_input"
        _conv_answer_source="text"
    fi
    return 0
}

# Run a multi-turn refinement conversation for a freshly-created reminder.
# Mistral asks one question at a time; each question is displayed + spoken.
# Usage: _task_refine_conversation <reminder_id> "<original_text>" "<metadata_json>" [source]
# source: "voice" if the original request was dictated, "text" (default) if typed.
_task_refine_conversation() {
    local _rid="$1"
    local _text="$2"
    local _metadata_json="${3:-{}}"
    local _source="${4:-text}"
    [ -z "$_rid" ] && return 0

    local _start_args=(--text "$_text" --metadata "$_metadata_json")
    if [ "$_source" = "voice" ]; then
        _start_args+=(--voice)
    fi

    local _response _session_id _action _question
    _response=$("$VENV_PYTHON" -m src.reminder.conversation start "$_rid" \
        "${_start_args[@]}" 2>&3) || return 0
    if [ -z "$_response" ]; then return 0; fi
    _session_id=$(printf '%s' "$_response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('session_id',''))" 2>/dev/null) || return 0
    if [ -z "$_session_id" ]; then return 0; fi

    while true; do
        _action=$(printf '%s' "$_response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('action',''))" 2>/dev/null) || break
        if [ "$_action" != "ask" ]; then break; fi
        _question=$(printf '%s' "$_response" | python3 -c "import sys,json; print(json.load(sys.stdin).get('question',''))" 2>/dev/null)
        if [ -z "$_question" ]; then break; fi

        echo ""
        _info "$_question"
        _speak "$_question"
        printf "  > (texte, ou 'v' Enter pour répondre à la voix) : "
        if ! _conv_read_answer; then break; fi
        if [ -z "$_conv_answer" ]; then break; fi

        local _ans_args=("$_session_id" "$_conv_answer")
        if [ "$_conv_answer_source" = "voice" ]; then
            _ans_args+=(--voice)
        fi
        _response=$("$VENV_PYTHON" -m src.reminder.conversation answer \
            "${_ans_args[@]}" 2>&3) || break
    done

    local _fin_result
    _fin_result=$("$VENV_PYTHON" -m src.reminder.conversation finalize "$_session_id" 2>&3) || true
    local _answers_text
    _answers_text=$(printf '%s' "$_fin_result" | python3 -c "
import sys, json
try:
    print(json.load(sys.stdin).get('answers_text', ''))
except Exception:
    print('')
" 2>/dev/null) || true
    if [ -n "$_answers_text" ]; then
        _profile_update "$_answers_text"
    fi
}

_show_reminder_summary_and_correct() {
    local _rid="$1"
    local _source="${2:-text}"
    [ -z "$_rid" ] && return 0

    echo ""
    _sep
    printf "  ${C_BOLD}Récapitulatif${C_RESET}\n"
    echo ""

    "$VENV_PYTHON" -c "
import json, sys
sys.path.insert(0, '.')
from src.reminder.db import _db
C='\033[0;36m'; G='\033[0;32m'; B='\033[1m'; R='\033[0m'
with _db() as conn:
    r = conn.execute('SELECT * FROM reminders WHERE id = ?', ($_rid,)).fetchone()
if not r:
    sys.exit(0)
meta = {}
if r['metadata']:
    try:
        meta = json.loads(r['metadata'])
    except Exception:
        pass
print(f'  {B}Tâche      :{R} {r[\"title\"]}')
print(f'  Catégorie  : {r[\"category\"]}')
rec = r['recurrence']
if rec:
    try:
        d = int(rec)
        lbl = 'quotidien' if d == 1 else (f'toutes les {d//7} sem.' if d % 7 == 0 else f'tous les {d} jours')
    except ValueError:
        lbl = rec
    print(f'  Récurrence : ↻ {lbl}')
if r['event_datetime']:
    print(f'  Date/heure : {C}{r[\"event_datetime\"]}{R}')
if meta.get('screen_free'):
    print(f'  Pomodoro   : {G}✓{R} proposée pendant les pauses')
tc = meta.get('time_constraint')
_tc_windows = []
if isinstance(tc, dict):
    _tc_windows = [tc]
elif isinstance(tc, list):
    _tc_windows = tc
_tc_valid = [w for w in _tc_windows if isinstance(w, dict) and isinstance(w.get('earliest_hour'), int) and isinstance(w.get('latest_hour'), int)]
if _tc_valid:
    _tc_slots = ', '.join(f\"{w['earliest_hour']}h–{w['latest_hour']}h\" for w in _tc_valid)
    print(f'  Créneau    : {C}{_tc_slots}{R}')
if meta.get('location'):
    print(f'  Lieu       : {meta[\"location\"]}')
_ch = meta.get('callable_hours')
if _ch:
    if isinstance(_ch, list):
        def _hm(t):
            _p = t.split(':') if ':' in t else [t, '00']
            return (f\"{int(_p[0])}h{_p[1]}\" if _p[1] != '00' else f\"{int(_p[0])}h\")
        _ch_days = {}
        for _slot in _ch:
            if not isinstance(_slot, dict):
                continue
            _dname = _slot.get('day', '')
            _s = _slot.get('start', '')
            _e = _slot.get('end', '')
            if not (_dname and _s and _e):
                continue
            _ch_days.setdefault(_dname, []).append(f\"{_hm(_s)}–{_hm(_e)}\")
        if _ch_days:
            print('  Horaires   :')
            for _dname, _slots in _ch_days.items():
                print(f'    {_dname[:3]} : {\", \".join(_slots)}')
        else:
            print(f'  Horaires   : {_ch}')
    else:
        print(f'  Horaires   : {_ch}')
if meta.get('requires_daylight'):
    print('  Lumière    : requise')
" 2>&3 || true

    echo ""
    _sep
    printf "  ${C_DIM}Correction ? (texte, ou laisser vide pour terminer)${C_RESET} : "
    local _corr
    if ! read -e -r _corr; then return 0; fi
    [ -z "$_corr" ] && return 0

    local _current_meta
    _current_meta=$("$VENV_PYTHON" -c "
import json, sys
sys.path.insert(0, '.')
from src.reminder.db import _db
with _db() as conn:
    r = conn.execute('SELECT metadata FROM reminders WHERE id = ?', ($_rid,)).fetchone()
print(r['metadata'] if r and r['metadata'] else '{}')
" 2>&3) || _current_meta="{}"

    _task_refine_conversation "$_rid" "$_corr" "$_current_meta" "$_source"
}

_add_reminder_from_text() {
    local text="$1"
    local source="${2:-text}"   # "voice" if dictated, "text" (default) if typed/OCR.
    local result
    local _add_args=(--stdin)
    if [ "$source" = "voice" ]; then
        _add_args+=(--voice)
    fi
    result=$(printf '%s' "$text" | "$VENV_PYTHON" -m src.reminder.add "${_add_args[@]}" 2>&3)
    if [ -z "$result" ]; then
        _error "Failed to parse reminder."
        return 1
    fi

    local count
    count=$(printf '%s' "$result" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(len(data) if isinstance(data, list) else 1)
" 2>&3) || count=0

    if [ "${count:-0}" -eq 0 ]; then
        _error "Failed to parse reminder."
        return 1
    fi

    local i=0
    while [ "$i" -lt "$count" ]; do
        local title category recurrence recurrence_spoken
        title=$(printf '%s' "$result" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(data[$i].get('title',''))
" 2>&3) || true
        category=$(printf '%s' "$result" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(data[$i].get('category',''))
" 2>&3) || true
        local _rid
        _rid=$(printf '%s' "$result" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(data[$i].get('id') or '')
" 2>&3) || true
        local _initial_metadata
        _initial_metadata=$(printf '%s' "$result" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(json.dumps(data[$i].get('metadata') or {}, ensure_ascii=False))
" 2>&3) || _initial_metadata="{}"
        local _recur_raw
        _recur_raw=$(printf '%s' "$result" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(data[$i].get('recurrence') or '')
" 2>&3) || true
        local _recur_info
        _recur_info=$(OUTPUT_LANG="${OUTPUT_LANG:-}" python3 -c "
import sys, os
rec = sys.argv[1]
lang = os.environ.get('OUTPUT_LANG', '')
label = spoken = ''
if rec == 'monthly':
    label = 'monthly'
    spoken = 'every month' if lang == 'en' else 'tous les mois'
elif rec:
    try:
        d = int(rec)
        if d == 1:
            label = 'daily'
            spoken = 'every day' if lang == 'en' else 'tous les jours'
        elif d % 7 == 0:
            w = d // 7
            label = f'every {w}w'
            if lang == 'en':
                spoken = f'every week' if w == 1 else f'every {w} weeks'
            else:
                spoken = 'toutes les semaines' if w == 1 else f'toutes les {w} semaines'
        else:
            label = f'every {d}d'
            spoken = f'every {d} days' if lang == 'en' else f'tous les {d} jours'
    except ValueError:
        label = spoken = rec
print(label)
print(spoken)
" "$_recur_raw" 2>&3) || true
        recurrence=$(printf '%s' "$_recur_info" | head -1)
        recurrence_spoken=$(printf '%s' "$_recur_info" | tail -1)

        local _recur_tag=""
        [ -n "$recurrence" ] && _recur_tag=" [↻ $recurrence]"

        if [ -n "$_rid" ]; then
            _task_refine_conversation "$_rid" "$text" "$_initial_metadata" "$source"
            _show_reminder_summary_and_correct "$_rid" "$source"
        fi

        _success "Reminder added: $title [$category]$_recur_tag"

        if [ -n "$recurrence_spoken" ]; then
            _speak "$_P_ADDED : $title, $recurrence_spoken"
        else
            _speak "$_P_ADDED : $title"
        fi

        i=$(( i + 1 ))
    done

    # Update user profile with any generalizable info from the input text
    _profile_update "$text"
}

# ── Mode: Pomodoro settings ───────────────────────────────────────────────────

_pomodoro_status() {
    if [ -f "/tmp/vox-pomodoro-state.json" ]; then
        local _phase
        _phase=$("$VENV_PYTHON" -c "
import json, sys
try:
    d = json.loads(open('/tmp/vox-pomodoro-state.json').read())
    print(d.get('phase','?'))
except Exception:
    print('?')
" 2>/dev/null)
        echo "● running (${_phase})"
    else
        echo "○ stopped"
    fi
}

_pomodoro_load_cfg() {
    "$VENV_PYTHON" -c "
import json, sys
from pathlib import Path
cfg_path = Path.home() / '.local/share/vox-refiner/pomodoro.json'
defaults = {'work_minutes':25,'break_minutes':5,'break_margin_minutes':5,'break_locked':True,'enabled':False,'idle_reset_minutes':0}
if cfg_path.exists():
    try:
        d = json.loads(cfg_path.read_text())
        defaults.update({k:d[k] for k in defaults if k in d})
    except Exception:
        pass
print(defaults['work_minutes'])
print(defaults['break_minutes'])
print(defaults['break_margin_minutes'])
print('yes' if defaults['break_locked'] else 'no')
print('yes' if defaults['enabled'] else 'no')
print(defaults['idle_reset_minutes'])
" 2>&3
}

_pomodoro_save_cfg() {
    local _work="$1" _break="$2" _margin="$3" _locked="$4" _enabled="$5" _idle="$6"
    "$VENV_PYTHON" -c "
import json
from pathlib import Path
cfg_path = Path.home() / '.local/share/vox-refiner/pomodoro.json'
cfg_path.parent.mkdir(parents=True, exist_ok=True)
data = {
    'work_minutes': int('$_work'),
    'break_minutes': int('$_break'),
    'break_margin_minutes': int('$_margin'),
    'break_locked': '$_locked' == 'yes',
    'enabled': '$_enabled' == 'yes',
    'idle_reset_minutes': int('$_idle'),
}
cfg_path.write_text(json.dumps(data, indent=2))
" 2>&3
}

_mode_pomodoro() {
    while true; do
        # Load current config
        local _cfg _work _break _margin _locked _enabled _idle
        _cfg=$(_pomodoro_load_cfg)
        _work=$(echo "$_cfg" | sed -n '1p')
        _break=$(echo "$_cfg" | sed -n '2p')
        _margin=$(echo "$_cfg" | sed -n '3p')
        _locked=$(echo "$_cfg" | sed -n '4p')
        _enabled=$(echo "$_cfg" | sed -n '5p')
        _idle=$(echo "$_cfg" | sed -n '6p')
        local _status
        _status=$(_pomodoro_status)
        local _break_min _break_max
        _break_min=$(( _break - _margin < 1 ? 1 : _break - _margin ))
        _break_max=$(( _break + _margin ))
        local _idle_display
        if [ "${_idle:-0}" -eq 0 ]; then
            _idle_display="off  ${C_DIM}(away from keyboard → work timer resets, no break)${C_RESET}"
        else
            _idle_display="${_idle} min  ${C_DIM}(away ≥ ${_idle} min → work timer resets, no break)${C_RESET}"
        fi

        clear
        _header "POMODORO" "🍅"
        echo ""
        printf "  Status         : ${C_BOLD}%s${C_RESET}\n" "$_status"
        printf "  Work duration  : ${C_CYAN}%s min${C_RESET}\n" "$_work"
        printf "  Break duration : ${C_CYAN}%s min${C_RESET}  ${C_DIM}(±%s min → %s–%s min)${C_RESET}\n" "$_break" "$_margin" "$_break_min" "$_break_max"
        printf "  Break locked   : ${C_CYAN}%s${C_RESET}\n" "$_locked"
        printf "  Idle reset     : ${C_CYAN}%b${C_RESET}\n" "$_idle_display"
        echo ""
        _sep
        printf "  ${C_BOLD}[w]${C_RESET} Work duration   ${C_BOLD}[b]${C_RESET} Break duration\n"
        printf "  ${C_BOLD}[g]${C_RESET} Break margin    ${C_BOLD}[l]${C_RESET} Toggle lock — currently: ${C_CYAN}%s${C_RESET}\n" "$_locked"
        printf "  ${C_BOLD}[i]${C_RESET} Idle reset      ${C_BOLD}[t]${C_RESET} Test overlay (30 s)\n"
        printf "  ${C_BOLD}[s]${C_RESET} Start           ${C_BOLD}[x]${C_RESET} Stop\n"
        printf "  ${C_BOLD}[m]${C_RESET} Menu: "
        read -e -r _pcmd

        case "$_pcmd" in
            w|W)
                echo ""
                printf "  Work duration in minutes (current: %s): " "$_work"
                read -e -r _val
                if [[ "$_val" =~ ^[0-9]+$ ]] && [ "$_val" -gt 0 ]; then
                    _work="$_val"
                    _pomodoro_save_cfg "$_work" "$_break" "$_margin" "$_locked" "$_enabled" "$_idle"
                    _success "Work duration set to ${_work} min."
                else
                    _warn "Invalid value — must be a positive integer."
                fi
                sleep 1
                ;;
            b|B)
                echo ""
                printf "  Break duration in minutes (current: %s): " "$_break"
                read -e -r _val
                if [[ "$_val" =~ ^[0-9]+$ ]] && [ "$_val" -gt 0 ]; then
                    _break="$_val"
                    _pomodoro_save_cfg "$_work" "$_break" "$_margin" "$_locked" "$_enabled" "$_idle"
                    _success "Break duration set to ${_break} min."
                else
                    _warn "Invalid value — must be a positive integer."
                fi
                sleep 1
                ;;
            g|G)
                echo ""
                printf "  Break margin in minutes (current: %s): " "$_margin"
                read -e -r _val
                if [[ "$_val" =~ ^[0-9]+$ ]]; then
                    _margin="$_val"
                    _pomodoro_save_cfg "$_work" "$_break" "$_margin" "$_locked" "$_enabled" "$_idle"
                    _success "Break margin set to ±${_margin} min."
                else
                    _warn "Invalid value — must be a non-negative integer."
                fi
                sleep 1
                ;;
            l|L)
                if [ "$_locked" = "yes" ]; then
                    _locked="no"
                else
                    _locked="yes"
                fi
                _pomodoro_save_cfg "$_work" "$_break" "$_margin" "$_locked" "$_enabled" "$_idle"
                _success "Break lock set to: ${_locked}."
                sleep 1
                ;;
            i|I)
                echo ""
                printf "  Idle reset in minutes — 0 to disable (current: %s): " "${_idle:-0}"
                read -e -r _val
                if [[ "$_val" =~ ^[0-9]+$ ]]; then
                    _idle="$_val"
                    _pomodoro_save_cfg "$_work" "$_break" "$_margin" "$_locked" "$_enabled" "$_idle"
                    if [ "$_idle" -eq 0 ]; then
                        _success "Idle reset disabled."
                    else
                        _success "Idle reset set to ${_idle} min."
                    fi
                else
                    _warn "Invalid value — must be a non-negative integer."
                fi
                sleep 1
                ;;
            t|T)
                _success "Lancement de l'overlay de test (30 secondes)…"
                sleep 1
                python3 "$SCRIPT_DIR/src/reminder/pomodoro_overlay.py" \
                    --title "Test overlay — 30 s" --minutes 0.5 --locked 2>&3
                ;;
            s|S)
                if [ -f "/tmp/vox-pomodoro-state.json" ]; then
                    _warn "Pomodoro already running."
                    sleep 1
                    continue
                fi
                _enabled="yes"
                _pomodoro_save_cfg "$_work" "$_break" "$_margin" "$_locked" "$_enabled" "$_idle"
                "$VENV_PYTHON" -c "
import sys; sys.path.insert(0,'.')
from src.reminder.pomodoro import start
start()
" 2>&3 && _success "Pomodoro started — work phase: ${_work} min." || _error "Failed to start Pomodoro."
                sleep 1
                ;;
            x|X)
                "$VENV_PYTHON" -c "
import sys; sys.path.insert(0,'.')
from src.reminder.pomodoro import stop
stop()
" 2>&3 && _success "Pomodoro stopped." || _error "Failed to stop Pomodoro."
                _enabled="no"
                _pomodoro_save_cfg "$_work" "$_break" "$_margin" "$_locked" "$_enabled" "$_idle"
                sleep 1
                ;;
            m|M)
                return 0
                ;;
        esac
    done
}

# ── Mode: add from interactive input ─────────────────────────────────────────

_mode_interactive() {
    while true; do
        clear
        _header "REMINDERS" "🔔"
        echo ""
        printf "  ${C_DIM}⚠  Beta feature — work in progress${C_RESET}\n"
        echo ""
        printf "  ${C_BOLD}[k]${C_RESET} Add (type)   ${C_BOLD}[v]${C_RESET} Add (voice)   ${C_BOLD}[s]${C_RESET} Add (screenshot)\n"
        printf "  ${C_BOLD}[l]${C_RESET} List pending   ${C_BOLD}[p]${C_RESET} Profile   ${C_BOLD}[d]${C_RESET} Start daemon\n"
        printf "  ${C_BOLD}[o]${C_RESET} Pomodoro   ${C_BOLD}[x]${C_RESET} Disable feature   ${C_BOLD}[m]${C_RESET} Menu: "
        read -e -r _input_mode

        case "$_input_mode" in
            k|K)
                echo ""
                printf "  Reminder text: "
                read -e -r _text
                [ -z "$_text" ] && continue
                _add_reminder_from_text "$_text"
                echo ""
                ;;
            v|V)
                echo ""
                _info "Recording — describe your reminder..."
                _read_voice_input
                _text="$_voice_text"
                if [ -z "$_text" ]; then
                    _warn "No speech detected."
                    echo ""
                    continue
                fi
                _process "Processing: $_text"
                _add_reminder_from_text "$_text" voice
                echo ""
                ;;
            s|S)
                _mode_ocr || true
                echo ""
                ;;
            l|L)
                _mode_list
                ;;
            p|P)
                _mode_profile
                ;;
            d|D)
                _daemon_term_pid="/tmp/vox-reminder-terminal.pid"
                if [ -f "$_daemon_term_pid" ]; then
                    _existing=$(cat "$_daemon_term_pid" 2>/dev/null) || true
                    if [ -n "$_existing" ] && kill -0 "$_existing" 2>/dev/null; then
                        _warn "Daemon terminal already open — close it before starting a new one."
                        continue
                    fi
                fi
                _daemon_term="${VOXREFINER_TERMINAL:-}"
                _daemon_ok=0
                _open_daemon_terminal() {
                    if ! command -v "$1" >/dev/null 2>&1; then return 1; fi
                    local _dcmd="cd '$SCRIPT_DIR' && '$VENV_PYTHON' -m src.reminder.daemon"
                    # --disable-factory / --wait / --standalone: same reason as
                    # in launch-vox-refiner.sh — keep this terminal independent
                    # of any shared factory so its PID is the real window and
                    # other VoxRefiner shortcuts can manage their own terminals
                    # without colliding.
                    case "$1" in
                        mate-terminal)
                            "$1" --disable-factory --window -- bash -c "$_dcmd" 2>/dev/null & ;;
                        gnome-terminal)
                            "$1" --wait --window -- bash -c "$_dcmd" 2>/dev/null & ;;
                        xfce4-terminal)
                            "$1" --disable-server --standalone -e "bash -c \"$_dcmd\"" 2>/dev/null & ;;
                        konsole)
                            "$1" -e bash -c "$_dcmd" 2>/dev/null & ;;
                        xterm)
                            "$1" -e bash -c "$_dcmd" 2>/dev/null & ;;
                        *) return 1 ;;
                    esac
                    _daemon_ok=1
                }
                if [ -n "$_daemon_term" ]; then
                    if ! _open_daemon_terminal "$_daemon_term"; then
                        _error "Unsupported or missing VOXREFINER_TERMINAL: $_daemon_term"
                    fi
                else
                    for _t in mate-terminal gnome-terminal xfce4-terminal konsole xterm; do
                        if _open_daemon_terminal "$_t"; then break; fi
                    done
                    if [ "$_daemon_ok" -eq 0 ]; then
                        _error "No terminal emulator found. Set VOXREFINER_TERMINAL to one of: mate-terminal, gnome-terminal, xfce4-terminal, konsole, xterm"
                    fi
                fi
                if [ "$_daemon_ok" -eq 1 ]; then
                    echo "$!" > "$_daemon_term_pid"
                    _success "Daemon started in a dedicated terminal."
                fi
                ;;
            o|O)
                _mode_pomodoro
                ;;
            x|X)
                if grep -q "^REMINDER_ENABLED=" .env 2>/dev/null; then
                    sed -i "s/^REMINDER_ENABLED=.*/REMINDER_ENABLED=false/" .env
                else
                    echo "REMINDER_ENABLED=false" >> .env
                fi
                export REMINDER_ENABLED=false
                _success "Reminders disabled on this installation."
                exit 0
                ;;
            m|M)
                exit 0
                ;;
        esac
    done
}

# ── .env writer (mirrors _set_env_var in vox-refiner-menu.sh) ────────────────

_set_env_var() {
    local key="$1" value="$2"
    if [ ! -f "$SCRIPT_DIR/.env" ]; then touch "$SCRIPT_DIR/.env"; fi
    if grep -q "^${key}=" "$SCRIPT_DIR/.env"; then
        sed -i "s|^${key}=.*|${key}=${value}|" "$SCRIPT_DIR/.env"
    else
        printf '\n%s=%s\n' "$key" "$value" >> "$SCRIPT_DIR/.env"
    fi
}

# ── Mode: user profile ───────────────────────────────────────────────────────

_mode_profile() {
    while true; do
        clear
        _header "USER PROFILE" "👤"
        echo ""

        # Display current profile
        "$VENV_PYTHON" -c "
import json, sys
from pathlib import Path
p_path = Path.home() / '.local/share/vox-refiner/user_profile.json'
if not p_path.exists():
    print('  No profile yet — set timezone and language to get started.')
    sys.exit(0)
try:
    p = json.loads(p_path.read_text(encoding='utf-8'))
except Exception:
    print('  Profile file unreadable.')
    sys.exit(0)
tz = p.get('timezone') or '(not set)'
lang = p.get('language') or '(not set)'
print(f'  Timezone : {tz}')
print(f'  Language : {lang}')
sections = p.get('sections', {})
labels = {
    'identity': 'Identity',
    'rhythm': 'Rhythm',
    'recurring_constraints': 'Recurring constraints',
    'preferences': 'Preferences',
    'future_commitments': 'Future commitments',
    'other': 'Other',
}
any_facts = False
for key, label in labels.items():
    entries = sections.get(key, [])
    if entries:
        if not any_facts:
            print('')
        any_facts = True
        print(f'  {label}:')
        for e in entries:
            print(f'    • {e}')
pending = p.get('pending_questions', [])
if pending:
    print('')
    print(f'  Pending questions : {len(pending)}')
" 2>&3 || true

        echo ""
        _sep
        printf "  ${C_BOLD}[k]${C_RESET} Add info (type)   ${C_BOLD}[v]${C_RESET} Add info (voice)\n"
        printf "  ${C_BOLD}[t]${C_RESET} Set timezone   ${C_BOLD}[l]${C_RESET} Set language  —  ${C_CYAN}${OUTPUT_LANG:-auto}${C_RESET}\n"
        printf "  ${C_BOLD}[m]${C_RESET} Menu: "
        read -e -r _pcmd

        case "$_pcmd" in
            k|K)
                echo ""
                printf "  Info to add (e.g. \"I work 9am–6pm Mon–Fri\"): "
                read -e -r _ptext
                if [ -z "$_ptext" ]; then continue; fi
                _process "Processing…"
                _profile_update "$_ptext"
                echo ""
                ;;
            t|T)
                echo ""
                printf "  Timezone (e.g. Europe/Paris, America/New_York): "
                read -e -r _tz
                if [ -z "$_tz" ]; then continue; fi
                "$VENV_PYTHON" -c "
import json
from pathlib import Path
p_path = Path.home() / '.local/share/vox-refiner/user_profile.json'
p_path.parent.mkdir(parents=True, exist_ok=True)
p = {}
if p_path.exists():
    try:
        p = json.loads(p_path.read_text(encoding='utf-8'))
    except Exception:
        pass
p.setdefault('timezone', None)
p.setdefault('language', None)
p.setdefault('sections', {k: [] for k in ['identity','rhythm','recurring_constraints','preferences','future_commitments','other']})
p.setdefault('pending_questions', [])
p['timezone'] = '$_tz'
ident = p['sections']['identity']
p['sections']['identity'] = [e for e in ident if not e.lower().startswith('timezone')]
p['sections']['identity'].insert(0, 'Timezone: $_tz')
p_path.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding='utf-8')
print('ok')
" 2>&3 && _success "Timezone set to: $_tz" || _error "Failed to update profile."
                echo ""
                ;;
            l|L)
                echo ""
                printf "  ${C_BOLD}[ 1]${C_RESET} Arabic        ${C_BOLD}[ 2]${C_RESET} Chinese       ${C_BOLD}[ 3]${C_RESET} Dutch\n"
                printf "  ${C_BOLD}[ 4]${C_RESET} English       ${C_BOLD}[ 5]${C_RESET} French        ${C_BOLD}[ 6]${C_RESET} German\n"
                printf "  ${C_BOLD}[ 7]${C_RESET} Hindi         ${C_BOLD}[ 8]${C_RESET} Italian       ${C_BOLD}[ 9]${C_RESET} Japanese\n"
                printf "  ${C_BOLD}[10]${C_RESET} Korean        ${C_BOLD}[11]${C_RESET} Portuguese    ${C_BOLD}[12]${C_RESET} Russian\n"
                printf "  ${C_BOLD}[13]${C_RESET} Spanish\n"
                printf "  ${C_BOLD}[a]${C_RESET}  auto          ${C_DIM}same as spoken input (default)${C_RESET}\n"
                echo ""
                printf "  ${C_DIM}Current: ${C_CYAN}${OUTPUT_LANG:-auto}${C_RESET}  —  Enter = keep current: "
                read -e -r _lng
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
                    "")  _new_lang="${OUTPUT_LANG:-}" ; _lng="skip" ;;
                esac
                if [ "$_lng" != "skip" ] && [ "$_lng" != "" ]; then
                    _set_env_var "OUTPUT_LANG" "$_new_lang"
                    "$VENV_PYTHON" -c "
import json
from pathlib import Path
p_path = Path.home() / '.local/share/vox-refiner/user_profile.json'
p_path.parent.mkdir(parents=True, exist_ok=True)
p = {}
if p_path.exists():
    try:
        p = json.loads(p_path.read_text(encoding='utf-8'))
    except Exception:
        pass
for k in ['timezone','language','sections','pending_questions']:
    p.setdefault(k, None if k in ('timezone','language') else ({} if k=='sections' else []))
p['sections'] = {s: p['sections'].get(s, []) for s in ['identity','rhythm','recurring_constraints','preferences','future_commitments','other']}
p['language'] = '$_new_lang' if '$_new_lang' else None
p_path.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding='utf-8')
" 2>&3 || true
                    OUTPUT_LANG="$_new_lang"
                    export OUTPUT_LANG
                    if [ -f "$SCRIPT_DIR/.env" ]; then
                        set -a; source "$SCRIPT_DIR/.env"; set +a
                    fi
                    _success "Language set to: ${OUTPUT_LANG:-auto}"
                fi
                echo ""
                ;;
            v|V)
                echo ""
                _info "Recording — describe your schedule, habits, location…"
                _read_voice_input
                _ptext="$_voice_text"
                if [ -z "$_ptext" ]; then
                    _warn "No speech detected."
                else
                    _process "Processing: $_ptext"
                    _profile_update "$_ptext"
                fi
                echo ""
                ;;
            m|M)
                return 0
                ;;
        esac
    done
}

# ── Mode: list pending reminders ─────────────────────────────────────────────

_mode_list() {
    while true; do
        clear
        _header "REMINDERS — Pending" "🔔"
        echo ""
        "$VENV_PYTHON" -c "
import sys, sqlite3
from pathlib import Path
db = Path.home() / '.local/share/vox-refiner/reminders.db'
if not db.exists():
    print('  No reminders found.')
    sys.exit(0)
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row
for _col in ('recurrence', 'recurrence_end'):
    try:
        conn.execute(f'ALTER TABLE reminders ADD COLUMN {_col} TEXT')
        conn.commit()
    except sqlite3.OperationalError:
        pass
rows = conn.execute(
    \"SELECT id, title, category, event_datetime, status, recurrence, recurrence_end FROM reminders \"
    \"WHERE status IN ('pending','snoozed') ORDER BY COALESCE(event_datetime, created_at)\"
).fetchall()
conn.close()
if not rows:
    print('  No pending reminders.')
    sys.exit(0)
for r in rows:
    dt = r['event_datetime'] or '(no date)'
    status = '' if r['status'] == 'pending' else f\" [{r['status']}]\"
    if r['recurrence']:
        rec = r['recurrence']
        try:
            d = int(rec)
            if d == 1: label = 'daily'
            elif d % 7 == 0: label = f'every {d//7}w'
            else: label = f'every {d}d'
        except ValueError:
            label = rec
        until = f\" until {r['recurrence_end']}\" if r['recurrence_end'] else ''
        recur = f\" [↻ {label}{until}]\"
    else:
        recur = ''
    print(f\"  [{r['id']:>3}]  {r['title']}  [{r['category']}]{recur}  {dt}{status}\")
" 2>&3
        echo ""
        printf "  ${C_BOLD}[c+ID]${C_RESET} View   ${C_BOLD}[d+ID]${C_RESET} Delete   ${C_BOLD}[m]${C_RESET} Menu  (ex: c9, d1): "
        read -e -r _cmd || true
        case "$_cmd" in
            m|M) break ;;
        esac
        if ! [[ "$_cmd" =~ ^[cdCD][0-9]+$ ]]; then
            _warn "Unknown command. Use c<ID> to view or d<ID> to delete."
            sleep 1
            continue
        fi
        local _action="${_cmd:0:1}" _rid="${_cmd:1}"

        if [[ "$_action" =~ ^[cC]$ ]]; then
            echo ""
            "$VENV_PYTHON" -c "
import sys, sqlite3, json
from pathlib import Path
db = Path.home() / '.local/share/vox-refiner/reminders.db'
conn = sqlite3.connect(db)
conn.row_factory = sqlite3.Row
for _col in ('recurrence', 'recurrence_end'):
    try:
        conn.execute(f'ALTER TABLE reminders ADD COLUMN {_col} TEXT')
        conn.commit()
    except sqlite3.OperationalError:
        pass
r = conn.execute('SELECT * FROM reminders WHERE id=?', ($_rid,)).fetchone()
conn.close()
if not r:
    print('  Reminder #$_rid not found.')
    sys.exit(0)
print(f\"  ID           : {r['id']}\")
print(f\"  Title        : {r['title']}\")
print(f\"  Category     : {r['category']}\")
print(f\"  Event date   : {r['event_datetime'] or '(not set — no specific date inferred)'}\")
print(f\"  Will notify  : {r['next_trigger'] or '(not set)'}\")
rec_raw = r['recurrence']
if rec_raw:
    try:
        d = int(rec_raw)
        if d == 1: label = 'daily'
        elif d % 7 == 0: label = f'every {d//7} week(s)'
        else: label = f'every {d} days'
    except ValueError:
        label = rec_raw
    rec_str = f\"{label} (until {r['recurrence_end']})\" if r['recurrence_end'] else label
else:
    rec_str = 'none (one-time)'
print(f\"  Recurrence   : {rec_str}\")
print(f\"  Status       : {r['status']}\")
print(f\"  Snooze count : {r['snooze_count']}\")
print(f\"  Added at     : {r['created_at']}\")
if r['metadata']:
    try:
        meta = json.loads(r['metadata'])
        if meta:
            print(f\"  Entities     : {meta}\")
    except Exception:
        pass
if r['full_context'] and r['full_context'] != r['title']:
    print(f\"  Original     : {r['full_context']}\")
" 2>&3 || true
            echo ""
            printf "  ${C_BOLD}[m]${C_RESET} Retour à la liste: "
            read -e -r _back || true
            continue
        fi

        # delete path
        local _title
        _title=$("$VENV_PYTHON" -c "
import sys, sqlite3
from pathlib import Path
db = Path.home() / '.local/share/vox-refiner/reminders.db'
conn = sqlite3.connect(db)
row = conn.execute('SELECT title FROM reminders WHERE id=?', ($_rid,)).fetchone()
conn.close()
print(row[0] if row else '')
" 2>&3) || true
        if [ -z "$_title" ]; then
            _warn "Reminder #$_rid not found."
            sleep 1
            continue
        fi
        printf "  Delete #$_rid \"%s\"? ${C_BOLD}[y/N]${C_RESET}: " "$_title"
        read -e -r _confirm || true
        case "$_confirm" in
            y|Y)
                "$VENV_PYTHON" -c "
import sys, sqlite3
from pathlib import Path
db = Path.home() / '.local/share/vox-refiner/reminders.db'
conn = sqlite3.connect(db)
conn.execute('DELETE FROM reminders WHERE id=?', ($_rid,))
conn.commit()
conn.close()
" 2>&3 && _success "Reminder #$_rid deleted." || _warn "Delete failed."
                sleep 1
                ;;
            *)
                ;;
        esac
    done
}

# ── Mode: add from OCR screenshot ────────────────────────────────────────────

_mode_ocr() {
    local scr_file="/tmp/vox-reminder-ocr.png"
    _process "Select the screen region to capture…"
    if command -v maim >/dev/null 2>&1; then
        maim -s "$scr_file" || { _error "Screenshot cancelled or failed."; return 1; }
    elif command -v scrot >/dev/null 2>&1; then
        scrot -s "$scr_file" || { _error "Screenshot cancelled or failed."; return 1; }
    else
        _error "No screenshot tool found. Install maim:  sudo apt install maim"
        return 1
    fi
    local ocr_text
    ocr_text=$("$VENV_PYTHON" -m src.ocr "$scr_file" 2>&3)
    rm -f "$scr_file"
    if [ -z "$ocr_text" ]; then
        _error "OCR returned empty text."
        return 1
    fi
    _process "OCR extracted text — parsing reminder..."
    _add_reminder_from_text "$ocr_text"
}

# ── Mode: fire a triggered reminder (called by daemon) ───────────────────────

_mode_fire() {
    local reminder_id="$1"
    local reminder_json
    reminder_json=$("$VENV_PYTHON" -c "
import json, sys
sys.path.insert(0, '.')
from src.reminder.db import get_due
due = get_due('9999-01-01 00:00:00')
r = next((x for x in due if x['id'] == $reminder_id), None)
if r:
    print(json.dumps(r))
" 2>&3)

    if [ -z "$reminder_json" ]; then
        _error "Reminder ID $reminder_id not found."
        exit 1
    fi

    local title category
    title=$(printf '%s' "$reminder_json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('title',''))" 2>/dev/null)
    category=$(printf '%s' "$reminder_json" | python3 -c "import sys,json; print(json.load(sys.stdin).get('category',''))" 2>/dev/null)

    clear
    _header "REMINDER" "🔔"
    echo ""
    printf "  ${C_BYELLOW}%s${C_RESET}  [%s]\n" "$title" "$category"
    echo ""
    _sep
    _announce_reminder "$title"

    while true; do
        printf "  ${C_BOLD}[D]${C_RESET} Done   ${C_BOLD}[L]${C_RESET} Later   ${C_BOLD}[G]${C_RESET} Going to do it   ${C_BOLD}[V]${C_RESET} Voice response   ${C_BOLD}[X]${C_RESET} Cancel: "
        read -e -r _key
        echo ""

        case "$_key" in
            d|D)
                _next_t=$("$VENV_PYTHON" -c "
import sys; sys.path.insert(0, '.')
from src.reminder.db import complete_reminder
result = complete_reminder($reminder_id)
print(result or '')
" 2>&3)
                if [ -n "$_next_t" ]; then
                    _success "Done — next occurrence: $_next_t"
                else
                    _success "Marked as done."
                fi
                _speak "$_P_DONE"
                break
                ;;
            l|L)
                REMINDER_JSON="$reminder_json" \
                "$VENV_PYTHON" -c "
import sys, json, os; sys.path.insert(0, '.')
from src.reminder.converse import compute_next_trigger
from src.reminder.db import snooze
r = json.loads(os.environ['REMINDER_JSON'])
next_t = compute_next_trigger(r)
snooze($reminder_id, next_t)
" 2>&3
                _warn "Snoozed. I'll remind you again later."
                _speak "$_P_LATER"
                break
                ;;
            g|G)
                "$VENV_PYTHON" -c "
import sys; sys.path.insert(0, '.')
from src.reminder.db import snooze
from datetime import datetime, timedelta, timezone
nxt = (datetime.now(tz=timezone.utc) + timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')
snooze($reminder_id, nxt)
" 2>&3
                _info "Great! I'll check back in 5 minutes."
                _speak "$_P_GOING"
                break
                ;;
            v|V)
                echo ""
                _info "Recording your response..."
                _read_voice_input
                _response="$_voice_text"
                if [ -z "$_response" ]; then
                    _warn "No speech detected."
                    continue
                fi
                _reply=$(REMINDER_JSON="$reminder_json" REMINDER_RESPONSE="$_response" \
                    "$VENV_PYTHON" -c "
import sys, json, os; sys.path.insert(0, '.')
from src.reminder.converse import converse
r = json.loads(os.environ['REMINDER_JSON'])
reply = converse($reminder_id, r, os.environ['REMINDER_RESPONSE'])
print(reply)
" 2>&3) || true
                echo ""
                if [ -n "$_reply" ]; then
                    _info "$_reply"
                    _speak "$_reply"
                fi
                echo ""
                # Update user profile with any generalizable info from the response
                _profile_update "$_response"
                break
                ;;
            x|X)
                "$VENV_PYTHON" -c "
import sys; sys.path.insert(0, '.')
from src.reminder.db import update_status
update_status($reminder_id, 'cancelled')
" 2>&3
                _warn "Reminder cancelled."
                _speak "$_P_CANCELLED"
                break
                ;;
        esac
    done
}

# ── Main ──────────────────────────────────────────────────────────────────────

main() {
    case "${1:-}" in
        --add)
            shift
            if [ -z "${1:-}" ]; then
                _error "Usage: $0 --add 'reminder text'"
                exit 1
            fi
            _add_reminder_from_text "$*"
            ;;
        --list)
            _mode_list
            ;;
        --ocr)
            _mode_ocr
            ;;
        --fire)
            shift
            if [ -z "${1:-}" ]; then
                _error "Usage: $0 --fire <reminder_id>"
                exit 1
            fi
            _mode_fire "$1"
            ;;
        "")
            _profile_ask_pending
            _task_ask_next_pending
            _mode_interactive
            ;;
        *)
            _error "Unknown option: $1"
            echo "Usage: $0 [--add TEXT | --ocr | --fire ID]"
            exit 1
            ;;
    esac
}

main "$@"

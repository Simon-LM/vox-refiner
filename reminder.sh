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
    if ! read -r _answer; then return 0; fi
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

_add_reminder_from_text() {
    local text="$1"
    local result
    result=$(printf '%s' "$text" | "$VENV_PYTHON" -m src.reminder_add --stdin 2>&3)
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
        local title category missing recurrence recurrence_spoken
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
        missing=$(printf '%s' "$result" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(','.join(data[$i].get('missing_fields') or []))
" 2>&3) || true
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
        _success "Reminder added: $title [$category]$_recur_tag"

        if [ -n "$missing" ]; then
            _warn "Missing information: $missing — follow-up questions not yet implemented."
        fi

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
        printf "  ${C_BOLD}[x]${C_RESET} Disable feature   ${C_BOLD}[m]${C_RESET} Menu: "
        read -r _input_mode

        case "$_input_mode" in
            k|K)
                echo ""
                printf "  Reminder text: "
                read -r _text
                [ -z "$_text" ] && continue
                _add_reminder_from_text "$_text"
                echo ""
                read -rp "  Press Enter to return to menu…" _dummy || true
                ;;
            v|V)
                echo ""
                _info "Recording — describe your reminder..."
                _read_voice_input
                _text="$_voice_text"
                if [ -z "$_text" ]; then
                    _warn "No speech detected."
                    echo ""
                    read -rp "  Press Enter to return to menu…" _dummy || true
                    continue
                fi
                _process "Processing: $_text"
                _add_reminder_from_text "$_text"
                echo ""
                read -rp "  Press Enter to return to menu…" _dummy || true
                ;;
            s|S)
                _mode_ocr || true
                echo ""
                read -rp "  Press Enter to return to menu…" _dummy || true
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
                    local _dcmd="cd '$SCRIPT_DIR' && '$VENV_PYTHON' -m src.reminder_daemon"
                    case "$1" in
                        mate-terminal|gnome-terminal)
                            "$1" --window -- bash -c "$_dcmd" 2>/dev/null & ;;
                        xfce4-terminal)
                            "$1" --standalone -e "bash -c \"$_dcmd\"" 2>/dev/null & ;;
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
        read -r _pcmd

        case "$_pcmd" in
            k|K)
                echo ""
                printf "  Info to add (e.g. \"I work 9am–6pm Mon–Fri\"): "
                read -r _ptext
                if [ -z "$_ptext" ]; then continue; fi
                _process "Processing…"
                _profile_update "$_ptext"
                echo ""
                read -rp "  Press Enter to continue…" _dummy || true
                ;;
            t|T)
                echo ""
                printf "  Timezone (e.g. Europe/Paris, America/New_York): "
                read -r _tz
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
                read -rp "  Press Enter to continue…" _dummy || true
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
                read -rp "  Press Enter to continue…" _dummy || true
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
                read -rp "  Press Enter to continue…" _dummy || true
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
        read -r _cmd || true
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
" 2>&3
            echo ""
            read -rp "  Press Enter to return to list…" _dummy || true
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
        read -r _confirm || true
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
from src.reminder_db import get_due
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
        read -r _key
        echo ""

        case "$_key" in
            d|D)
                _next_t=$("$VENV_PYTHON" -c "
import sys; sys.path.insert(0, '.')
from src.reminder_db import complete_reminder
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
from src.reminder_converse import compute_next_trigger
from src.reminder_db import snooze
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
from src.reminder_db import snooze
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
from src.reminder_converse import converse
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
                read -rp "  Appuie sur Entrée pour fermer…" _dummy || true
                break
                ;;
            x|X)
                "$VENV_PYTHON" -c "
import sys; sys.path.insert(0, '.')
from src.reminder_db import update_status
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

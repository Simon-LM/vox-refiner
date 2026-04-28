#!/bin/bash
# VoxRefiner — Web display helper (sourced by flow scripts).
#
# Starts a local HTTP+SSE server (src/web_display.py) and provides shell
# helpers to push events that the parallel browser window mirrors in real time.
#
# Activation: VOX_WEB_DISPLAY=1 in .env. When unset, all helpers are no-ops —
# the calling flow runs unchanged.
#
# Required globals from caller: SCRIPT_DIR, VENV_PYTHON.
#
# Exposed helpers:
#   _web_start <mode>                            — boot server + browser (idempotent)
#   _web_push_init <mode> [full_text]            — broadcast init event
#   _web_send_display_meta <cleaned_text>        — run display_meta on cleaned text,
#                                                   resolve anchor positions, push
#                                                   `display_chunks` SSE event
#   _web_send_chunk <idx> <chunks_dir>           — push chunk text + char range +
#                                                   audio duration
#   _web_push_done                               — broadcast end-of-playback event
#   _web_push_error <message>                    — broadcast an error event
#   _web_stop                                    — kill server (idempotent)

# ─── State ────────────────────────────────────────────────────────────────────

_WEB_PORT=""
_WEB_PID=""

# ─── Internal: low-level POST ─────────────────────────────────────────────────

_web_push_raw() {
    # Usage: _web_push_raw <json_body>
    [ -z "${_WEB_PORT:-}" ] && return 0
    curl -s --max-time 0.5 -X POST \
        -H "Content-Type: application/json" \
        --data-binary "$1" \
        "http://127.0.0.1:${_WEB_PORT}/push" >/dev/null 2>&1 &
}

# ─── Lifecycle ────────────────────────────────────────────────────────────────

_web_start() {
    # Usage: _web_start <mode>
    [ "${VOX_WEB_DISPLAY:-0}" != "1" ] && return 0
    [ -n "${_WEB_PORT:-}" ] && return 0  # already started

    local mode="${1:-voice}"
    local display_mode="${VOX_WEB_DISPLAY_MODE:-summary}"
    local size="${VOX_WEB_SIZE:-1100x800}"
    local pos="${VOX_WEB_POS:-100x100}"

    local port_file
    port_file="$(mktemp /tmp/vox-web-port-XXXXXX)"

    # Send Python stderr to FD 3 (saved terminal stderr) when available, so
    # browser launch diagnostics are visible. Falls back to /dev/null if FD 3
    # is not open (e.g. sourced from a script that didn't run `exec 3>&2`).
    if { true >&3; } 2>/dev/null; then
        "$VENV_PYTHON" -m src.web_display \
            --mode "$mode" --display-mode "$display_mode" \
            --size "$size" --pos "$pos" \
            --port-file "$port_file" \
            >/dev/null 2>&3 &
    else
        "$VENV_PYTHON" -m src.web_display \
            --mode "$mode" --display-mode "$display_mode" \
            --size "$size" --pos "$pos" \
            --port-file "$port_file" \
            >/dev/null 2>&1 &
    fi
    _WEB_PID=$!

    # Wait up to 2s for the port file
    local _i
    for _i in $(seq 1 20); do
        if [ -s "$port_file" ]; then
            _WEB_PORT="$(cat "$port_file")"
            break
        fi
        sleep 0.1
    done
    rm -f "$port_file"

    if [ -z "${_WEB_PORT:-}" ]; then
        kill "$_WEB_PID" 2>/dev/null
        _WEB_PID=""
        return 1
    fi
    return 0
}

_web_stop() {
    [ -z "${_WEB_PORT:-}" ] && return 0
    _web_push_raw '{"type":"shutdown"}'
    sleep 0.1
    if [ -n "${_WEB_PID:-}" ]; then
        kill -TERM "$_WEB_PID" 2>/dev/null
    fi
    _WEB_PORT=""
    _WEB_PID=""
}

# ─── Event push helpers ───────────────────────────────────────────────────────

_web_push_init() {
    # Usage: _web_push_init <mode> [full_text]
    [ -z "${_WEB_PORT:-}" ] && return 0
    local mode="${1:-voice}"
    local full_text="${2:-}"

    local body
    if [ -n "$full_text" ]; then
        body="$(VOX_INIT_MODE="$mode" VOX_INIT_FULL="$full_text" "$VENV_PYTHON" -c "
import json, os
print(json.dumps({
    'type': 'init',
    'payload': {'mode': os.environ['VOX_INIT_MODE'], 'full_text': os.environ['VOX_INIT_FULL']}
}))
" 2>/dev/null)"
    else
        body="{\"type\":\"init\",\"payload\":{\"mode\":\"$mode\"}}"
    fi

    [ -n "$body" ] && _web_push_raw "$body"
}

_web_send_display_meta() {
    # Usage: _web_send_display_meta <cleaned_text>
    # Runs display_meta.py on the cleaned text, resolves each display chunk's
    # anchor to a character range in the cleaned text, and broadcasts a
    # `display_chunks` SSE event. Skipped when VOX_WEB_DISPLAY_MODE=fulltext.
    [ "${VOX_WEB_DISPLAY:-0}" != "1" ] && return 0
    [ "${VOX_WEB_DISPLAY_MODE:-summary}" = "fulltext" ] && return 0
    [ -z "${_WEB_PORT:-}" ] && return 0

    local _port="$_WEB_PORT"
    local _text="$1"
    (
        # Trace subshell entry — proves the function fired even when it later
        # fails silently somewhere downstream.
        "$VENV_PYTHON" -m src.debug_log set display_meta_pipeline \
            '{"step":"subshell_started"}' >/dev/null 2>&1

        # Capture display_meta stderr to a temp file; log it on failure.
        local _stderr_file
        _stderr_file="$(mktemp /tmp/vox-dm-err-XXXXXX)"
        local _meta
        _meta="$(printf '%s' "$_text" | "$VENV_PYTHON" -m src.display_meta 2>"$_stderr_file")"
        local _dm_exit=$?
        if [ -z "$_meta" ]; then
            local _err
            _err="$(cat "$_stderr_file" 2>/dev/null || true)"
            VOX_DM_ERR="$_err" VOX_DM_EXIT="$_dm_exit" "$VENV_PYTHON" -c "
import json, os
from src import debug_log as _dbg
_dbg.merge_into('display_meta_pipeline', {
    'step': 'display_meta_failed',
    'exit_code': int(os.environ.get('VOX_DM_EXIT', '0') or 0),
    'stderr': os.environ.get('VOX_DM_ERR', ''),
})
" >/dev/null 2>&1
            rm -f "$_stderr_file"
            exit 0
        fi
        rm -f "$_stderr_file"

        local _body
        _body="$(VOX_TEXT="$_text" VOX_META="$_meta" "$VENV_PYTHON" -c "
import json, os, sys
from src import debug_log as _dbg
text = os.environ['VOX_TEXT']
meta = json.loads(os.environ['VOX_META'])
chunks = meta.get('display_chunks', [])
search_from = 0
resolved = []
anchor_failures = []
for i, c in enumerate(chunks):
    anchor = c.get('anchor', '') or ''
    start_fwd = text.find(anchor, search_from) if anchor else -1
    start = start_fwd
    if start < 0 and anchor:
        start = text.find(anchor)  # fallback: from beginning
        if start >= 0:
            anchor_failures.append({'idx': i, 'reason': 'forward-search-failed', 'anchor': anchor[:50]})
        else:
            anchor_failures.append({'idx': i, 'reason': 'not-found', 'anchor': anchor[:50]})
    if start < 0:
        start = search_from  # last-resort fallback
    end = start + max(len(anchor), 1)
    resolved.append({
        'char_start': start,
        'char_end': end,
        'topic': c.get('topic', ''),
        'keywords': c.get('keywords', []),
        'summary_short': c.get('summary_short', ''),
        'quote_short': c.get('quote_short', ''),
    })
    search_from = max(search_from, end)
# Close ranges so each display chunk runs up to the next one's start.
for i in range(len(resolved) - 1):
    if resolved[i + 1]['char_start'] > resolved[i]['char_end']:
        resolved[i]['char_end'] = resolved[i + 1]['char_start']
if resolved:
    resolved[-1]['char_end'] = max(resolved[-1]['char_end'], len(text))

# Debug log: resolved display chunks + anchor failures.
_dbg.set_section('alignment', {
    'total_chars': len(text),
    'display_chunks_resolved': resolved,
    'anchor_failures': anchor_failures,
})

print(json.dumps({
    'type': 'display_chunks',
    'payload': {
        'language': meta.get('language', ''),
        'total_chars': len(text),
        'chunks': resolved,
    },
}))
" 2>"$_stderr_file")"
        local _resolve_exit=$?
        if [ -z "$_body" ]; then
            local _err
            _err="$(cat "$_stderr_file" 2>/dev/null || true)"
            VOX_RES_ERR="$_err" VOX_RES_EXIT="$_resolve_exit" "$VENV_PYTHON" -c "
import json, os
from src import debug_log as _dbg
_dbg.merge_into('display_meta_pipeline', {
    'step': 'anchor_resolution_failed',
    'exit_code': int(os.environ.get('VOX_RES_EXIT', '0') or 0),
    'stderr': os.environ.get('VOX_RES_ERR', ''),
})
" >/dev/null 2>&1
            rm -f "$_stderr_file"
            exit 0
        fi
        rm -f "$_stderr_file"

        # POST to the SSE server. Capture curl exit code so we can tell whether
        # the event actually reached the broadcaster.
        curl -s --max-time 1.0 -X POST \
            -H "Content-Type: application/json" \
            --data-binary "$_body" \
            "http://127.0.0.1:${_port}/push" >/dev/null 2>&1
        local _curl_exit=$?
        VOX_CURL_EXIT="$_curl_exit" VOX_BODY_LEN="${#_body}" "$VENV_PYTHON" -c "
import os
from src import debug_log as _dbg
_dbg.merge_into('display_meta_pipeline', {
    'step': 'curl_done',
    'curl_exit': int(os.environ.get('VOX_CURL_EXIT', '0') or 0),
    'body_bytes': int(os.environ.get('VOX_BODY_LEN', '0') or 0),
})
" >/dev/null 2>&1
    ) &
}

_web_watch_cleaned_then_meta() {
    # Usage: _web_watch_cleaned_then_meta <cleaned_text_file>
    # For voice mode: poll for the cleaned text file written by tts.py
    # (TTS_CLEANED_TEXT_OUT). When it appears, launch _web_send_display_meta
    # in background. No-op when web display is off or in fulltext mode.
    [ "${VOX_WEB_DISPLAY:-0}" != "1" ] && return 0
    [ "${VOX_WEB_DISPLAY_MODE:-summary}" = "fulltext" ] && return 0
    [ -z "${_WEB_PORT:-}" ] && return 0

    local _file="$1"
    (
        # Wait up to 30s (cleaning should finish in 1–2s normally).
        local _i
        for _i in $(seq 1 60); do
            [ -s "$_file" ] && break
            sleep 0.5
        done
        if [ -s "$_file" ]; then
            local _cleaned
            _cleaned="$(cat "$_file")"
            _web_send_display_meta "$_cleaned"
        fi
    ) &
}

_web_send_chunk() {
    # Usage: _web_send_chunk <idx> <chunks_dir>
    # Broadcasts a `chunk` SSE event with text + char range (read from
    # chunk_NNN.json sidecar) + audio duration (ffprobe on chunk_NNN.mp3).
    # Both fields are optional — degrade gracefully when missing.
    [ -z "${_WEB_PORT:-}" ] && return 0
    local idx="$1" dir="$2"
    local text_file json_file mp3_file
    text_file="$(printf '%s/chunk_%03d.txt' "$dir" "$idx")"
    json_file="$(printf '%s/chunk_%03d.json' "$dir" "$idx")"
    mp3_file="$(printf  '%s/chunk_%03d.mp3'  "$dir" "$idx")"
    [ -f "$text_file" ] || return 0

    # Audio duration via ffprobe (silent fallback to 0.0 if unavailable).
    local duration="0.0"
    if [ -f "$mp3_file" ] && command -v ffprobe >/dev/null 2>&1; then
        local _d
        _d="$(ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 "$mp3_file" 2>/dev/null)"
        [ -n "$_d" ] && duration="$_d"
    fi

    local body
    body="$(VOX_CHUNK_IDX="$idx" \
        VOX_CHUNK_FILE="$text_file" \
        VOX_CHUNK_JSON="$json_file" \
        VOX_CHUNK_DURATION="$duration" \
        "$VENV_PYTHON" -c "
import json, os, time
from src import debug_log as _dbg
with open(os.environ['VOX_CHUNK_FILE'], encoding='utf-8') as f:
    text = f.read()
char_start = char_end = -1
jpath = os.environ.get('VOX_CHUNK_JSON', '')
if jpath and os.path.isfile(jpath):
    try:
        with open(jpath, encoding='utf-8') as f:
            meta = json.load(f)
        char_start = int(meta.get('char_start', -1))
        char_end   = int(meta.get('char_end',   -1))
    except Exception:
        pass
try:
    duration = float(os.environ.get('VOX_CHUNK_DURATION', '0') or 0)
except ValueError:
    duration = 0.0
payload = {
    'idx': int(os.environ['VOX_CHUNK_IDX']),
    'text': text,
    'duration_s': duration,
}
if char_start >= 0:
    payload['char_start'] = char_start
    payload['char_end']   = char_end

# Trace the SSE chunk event into the debug log for playback timing analysis.
_dbg.append_to('sse_chunk_events', {
    'sent_at': time.strftime('%H:%M:%S'),
    **payload,
})

print(json.dumps({'type': 'chunk', 'payload': payload}))
" 2>/dev/null)"

    [ -n "$body" ] && _web_push_raw "$body"
}

_web_push_done() {
    [ -z "${_WEB_PORT:-}" ] && return 0
    _web_push_raw '{"type":"done"}'
}

_web_push_error() {
    # Usage: _web_push_error <message>
    [ -z "${_WEB_PORT:-}" ] && return 0
    local msg="${1:-error}"
    local body
    body="$(VOX_ERR="$msg" "$VENV_PYTHON" -c "
import json, os
print(json.dumps({'type':'error','payload':{'message': os.environ['VOX_ERR']}}))
" 2>/dev/null)"
    [ -n "$body" ] && _web_push_raw "$body"
}

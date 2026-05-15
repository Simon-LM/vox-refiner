#!/bin/bash
# VoxRefiner reminder daemon — start / stop / status / restart
# Wraps the systemd user service; falls back to direct process management
# when systemd is not available.
set -euo pipefail

cd "$(dirname "$0")"
SCRIPT_DIR="$(pwd)"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"
SERVICE_NAME="vox-reminder"

source "$SCRIPT_DIR/src/ui.sh"

[ -f .env ] && set -a && source .env && set +a

_check_enabled() {
    local cmd="${1:-}"
    # status/disable/stop are always allowed (to inspect or clean up)
    case "$cmd" in
        status|stop|disable) return 0 ;;
    esac
    if [ "${REMINDER_ENABLED:-false}" != "true" ]; then
        _warn "Reminders are disabled on this installation (REMINDER_ENABLED=false)."
        _info "To enable: set REMINDER_ENABLED=true in your .env file."
        exit 0
    fi
}

_has_systemd() {
    systemctl --user is-system-running >/dev/null 2>&1 || \
        systemctl --user status >/dev/null 2>&1
}

_pid_file() {
    echo "/tmp/vox-reminder-daemon.pid"
}

# ── systemd path ──────────────────────────────────────────────────────────────

_systemd_start() {
    systemctl --user start "$SERVICE_NAME"
    _success "Reminder daemon started (systemd)."
}

_systemd_stop() {
    systemctl --user stop "$SERVICE_NAME"
    _success "Reminder daemon stopped."
}

_systemd_restart() {
    systemctl --user restart "$SERVICE_NAME"
    _success "Reminder daemon restarted."
}

_systemd_status() {
    systemctl --user status "$SERVICE_NAME"
}

_systemd_enable() {
    systemctl --user enable "$SERVICE_NAME"
    _success "Reminder daemon enabled (auto-start on login)."
}

_systemd_disable() {
    systemctl --user disable "$SERVICE_NAME"
    _success "Reminder daemon disabled."
}

# ── Fallback: direct process management ───────────────────────────────────────

_direct_start() {
    if [ ! -x "$VENV_PYTHON" ]; then
        _error "Missing .venv — run ./install.sh first."
        exit 1
    fi

    [ -f .env ] && set -a && source .env && set +a

    _success "Reminder daemon running — Ctrl+C or close this terminal to stop."
    exec "$VENV_PYTHON" -m src.reminder_daemon
}

_direct_stop() {
    _warn "Direct mode runs in foreground. Close the terminal or press Ctrl+C to stop."
}

_direct_status() {
    _warn "Direct mode runs in foreground. Check your open terminals."
}

_direct_restart() {
    _warn "Direct mode runs in foreground. Stop with Ctrl+C, then re-run start."
}

# ── Dispatch ──────────────────────────────────────────────────────────────────

main() {
    local cmd="${1:-}"
    _check_enabled "$cmd"

    if _has_systemd; then
        case "$cmd" in
            start)   _systemd_start   ;;
            stop)    _systemd_stop    ;;
            restart) _systemd_restart ;;
            status)  _systemd_status  ;;
            enable)  _systemd_enable  ;;
            disable) _systemd_disable ;;
            *)
                echo "Usage: $0 {start|stop|restart|status|enable|disable}"
                exit 1
                ;;
        esac
    else
        mkdir -p "$SCRIPT_DIR/logs"
        case "$cmd" in
            start)   _direct_start   ;;
            stop)    _direct_stop    ;;
            restart) _direct_restart ;;
            status)  _direct_status  ;;
            *)
                echo "Usage: $0 {start|stop|restart|status}"
                exit 1
                ;;
        esac
    fi
}

main "$@"

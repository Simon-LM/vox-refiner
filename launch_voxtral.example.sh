#!/bin/bash

# ─── Voxtral Paste — Launcher example ────────────────────────────────────────
#
# This script opens a new terminal window and runs Voxtral Paste.
# Copy it to launch_voxtral.sh and customize it for your setup.
#
# Usage:
#   1. cp launch_voxtral.example.sh launch_voxtral.sh
#   2. Edit SCRIPT_PATH and the terminal command below
#   3. Bind launch_voxtral.sh to a keyboard shortcut in your OS
#
# Terminal examples:
#   MATE:    mate-terminal -- bash -c "\"$SCRIPT_PATH\"; exec bash"
#   GNOME:   gnome-terminal -- bash -c "\"$SCRIPT_PATH\"; exec bash"
#   KDE:     konsole -e bash -c "\"$SCRIPT_PATH\"; exec bash"
#   XFCE:    xfce4-terminal -e "bash -c \"\\\"$SCRIPT_PATH\\\"; exec bash\""
# ──────────────────────────────────────────────────────────────────────────────

# Path to the main script (adjust to your installation)
SCRIPT_PATH="$HOME/.local/bin/voxtral-paste/record_and_transcribe_local.sh"

# PID file to track the previous terminal (avoids duplicate windows)
PID_FILE="/tmp/voxtral_terminal.pid"

# Kill previous terminal if still running
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "⚠️  Closing previous Voxtral terminal..."
        kill "$OLD_PID"
        sleep 0.5
    fi
fi

# Launch a new terminal and save its PID
# ⬇️ Replace with your terminal emulator (see examples above)
mate-terminal -- bash -c "\"$SCRIPT_PATH\"; exec bash" &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"


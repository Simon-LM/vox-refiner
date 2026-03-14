#!/bin/bash

# ─── VoxRefiner — Personal launcher ─────────────────────────────────────────
#
# This script opens a new terminal window and runs VoxRefiner.
# You can bind this file directly to a keyboard shortcut.
#
# Terminal examples:
#   MATE:    mate-terminal -- bash -c "\"$SCRIPT_PATH\"; exec bash"
#   GNOME:   gnome-terminal -- bash -c "\"$SCRIPT_PATH\"; exec bash"
#   KDE:     konsole -e bash -c "\"$SCRIPT_PATH\"; exec bash"
#   XFCE:    xfce4-terminal -e "bash -c \"\\\"$SCRIPT_PATH\\\"; exec bash\""
# ──────────────────────────────────────────────────────────────────────────────

# Path to your main script
SCRIPT_PATH="$HOME/.local/bin/vox-refiner/record_and_transcribe_local.sh"

# PID file to track the previous terminal (avoids duplicate windows)
PID_FILE="/tmp/vox-refiner_terminal.pid"

# Kill previous terminal if still running
if [ -f "$PID_FILE" ]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "⚠️  Closing previous VoxRefiner terminal..."
        kill "$OLD_PID"
        sleep 0.5
    fi
fi

# Launch a new terminal and save its PID
# Replace with your terminal emulator if needed.
mate-terminal -- bash -c "\"$SCRIPT_PATH\"; exec bash" &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"


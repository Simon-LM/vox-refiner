#!/bin/bash

# ─── VoxRefiner — Launcher example ────────────────────────────────────────
#
# This script opens a new terminal window and runs VoxRefiner.
# Copy it to launch_vox-refiner.sh and customize it for your setup.
#
# Usage:
#   1. cp launch_vox-refiner.example.sh launch_vox-refiner.sh
#   2. Edit SCRIPT_PATH and the terminal command below
#   3. Bind launch_vox-refiner.sh to a keyboard shortcut in your OS
#
# Terminal examples:
#   MATE:    mate-terminal -- bash -c "\"$SCRIPT_PATH\"; exec bash"
#   GNOME:   gnome-terminal -- bash -c "\"$SCRIPT_PATH\"; exec bash"
#   KDE:     konsole -e bash -c "\"$SCRIPT_PATH\"; exec bash"
#   XFCE:    xfce4-terminal -e "bash -c \"\\\"$SCRIPT_PATH\\\"; exec bash\""
# ──────────────────────────────────────────────────────────────────────────────

# Path to the main script (adjust to your installation)
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
# ⬇️ Replace with your terminal emulator (see examples above)
mate-terminal -- bash -c "\"$SCRIPT_PATH\"; exec bash" &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"


#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

INSTALL_SYSTEM_DEPS=false
if [ "${1:-}" = "--install-system-deps" ]; then
    INSTALL_SYSTEM_DEPS=true
fi

missing_cmds=()
for cmd in python3 ffmpeg rec xclip; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        missing_cmds+=("$cmd")
    fi
done

venv_module_ok=true
if ! python3 -m venv --help >/dev/null 2>&1; then
    venv_module_ok=false
fi

if [ ${#missing_cmds[@]} -gt 0 ] || [ "$venv_module_ok" = "false" ]; then
    echo "❌ Missing system dependencies:"
    for cmd in "${missing_cmds[@]}"; do
        echo "   - $cmd"
    done
    if [ "$venv_module_ok" = "false" ]; then
        echo "   - python3-venv module"
    fi
    echo ""

    if [ "$INSTALL_SYSTEM_DEPS" = "true" ]; then
        if command -v apt-get >/dev/null 2>&1; then
            echo "🔧 Installing system dependencies via apt..."
            sudo apt-get update
            sudo apt-get install -y python3 python3-venv ffmpeg sox xclip xterm
        else
            echo "❌ --install-system-deps is only supported automatically on apt-based systems."
            exit 1
        fi
    else
        echo "Install them manually, for example on Ubuntu:"
        echo "  sudo apt-get update"
        echo "  sudo apt-get install -y python3 python3-venv ffmpeg sox xclip"
        echo ""
        echo "Then run: ./install.sh"
        exit 1
    fi
fi

if ! command -v mate-terminal >/dev/null 2>&1 \
    && ! command -v gnome-terminal >/dev/null 2>&1 \
    && ! command -v xfce4-terminal >/dev/null 2>&1 \
    && ! command -v konsole >/dev/null 2>&1 \
    && ! command -v xterm >/dev/null 2>&1; then
    echo "⚠️  No supported terminal emulator found for the launcher."
    echo "   Install one of: mate-terminal, gnome-terminal, xfce4-terminal, konsole, xterm"
fi

if [ ! -d ".venv" ]; then
    echo "🐍 Creating virtual environment (.venv)..."
    python3 -m venv .venv
fi

VENV_PYTHON="$(pwd)/.venv/bin/python"

echo "📦 Installing Python dependencies in .venv..."
"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install -r requirements.txt

if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "🧩 Created .env from .env.example"
fi

if [ ! -f "context.txt" ]; then
    cp context.example.txt context.txt
    echo "🧩 Created context.txt from context.example.txt"
fi

if [ ! -f "launch-vox-refiner.sh" ]; then
    cp launch-vox-refiner.example.sh launch-vox-refiner.sh
    echo "🧩 Created launch-vox-refiner.sh from template"
fi

chmod +x record_and_transcribe_local.sh launch-vox-refiner.sh vox-refiner-update.sh install.sh

echo ""
echo "✅ Installation complete."
echo ""
echo "Next steps:"
echo "  1. Edit .env and set MISTRAL_API_KEY"
echo "  2. (Optional) Edit launch-vox-refiner.sh for your terminal app"
echo "  3. Launch: ./launch-vox-refiner.sh"

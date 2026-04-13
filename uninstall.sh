#!/bin/bash
# VoxRefiner — Uninstaller
# Removes the VoxRefiner installation from ~/.local/bin/vox-refiner.
# Run this script from inside the VoxRefiner directory:
#   ./uninstall.sh

set -euo pipefail

cd "$(dirname "$0")"
INSTALL_DIR="$(pwd)"

# ─── Colors ───────────────────────────────────────────────────────────────────
C_BOLD="\033[1m"
C_RED="\033[1;31m"
C_GREEN="\033[1;32m"
C_YELLOW="\033[1;33m"
C_CYAN="\033[0;36m"
C_RESET="\033[0m"

echo ""
printf "${C_BOLD}VoxRefiner — Uninstaller${C_RESET}\n"
printf "${C_CYAN}%s${C_RESET}\n" "$INSTALL_DIR"
echo ""

# ─── Safety check ─────────────────────────────────────────────────────────────
# Must be run from inside the actual VoxRefiner directory.
if [ ! -f "$INSTALL_DIR/launch-vox-refiner.sh" ] || \
   [ ! -f "$INSTALL_DIR/record_and_transcribe_local.sh" ]; then
    printf "${C_RED}❌ This does not look like a VoxRefiner installation.${C_RESET}\n"
    printf "   Run this script from inside the VoxRefiner directory.\n"
    exit 1
fi

# ─── Confirm removal ──────────────────────────────────────────────────────────
printf "${C_YELLOW}⚠  This will permanently delete:${C_RESET}\n"
printf "   %s\n" "$INSTALL_DIR"
echo ""
printf "   Type ${C_BOLD}yes${C_RESET} to confirm, or press Enter to cancel: "
read -r _confirm
if [ "$_confirm" != "yes" ]; then
    printf "${C_CYAN}Uninstall cancelled.${C_RESET}\n"
    exit 0
fi
echo ""

# ─── Personal data (opt-in) ───────────────────────────────────────────────────
_remove_personal=false
if [ -f "$INSTALL_DIR/history.txt" ] || [ -f "$INSTALL_DIR/context.txt" ] || \
   [ -f "$INSTALL_DIR/.env" ]; then
    printf "  Personal data found:\n"
    [ -f "$INSTALL_DIR/history.txt" ] && printf "    - history.txt\n"
    [ -f "$INSTALL_DIR/context.txt" ] && printf "    - context.txt\n"
    [ -f "$INSTALL_DIR/.env" ]        && printf "    - .env (contains your API key)\n"
    echo ""
    printf "  Delete personal data too? [y/N]: "
    read -r _del_personal
    if [[ "$_del_personal" =~ ^[Yy]$ ]]; then
        _remove_personal=true
    else
        printf "  ${C_CYAN}Personal data will be kept in place.${C_RESET}\n"
        echo ""
    fi
fi

# ─── Desktop entry ────────────────────────────────────────────────────────────
_desktop="$HOME/.local/share/applications/vox-refiner.desktop"
if [ -f "$_desktop" ]; then
    rm -f "$_desktop"
    update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
    printf "  ✓ Desktop entry removed.\n"
fi

# ─── Personal data removal ────────────────────────────────────────────────────
if [ "$_remove_personal" = "true" ]; then
    rm -f "$INSTALL_DIR/history.txt" \
          "$INSTALL_DIR/context.txt" \
          "$INSTALL_DIR/.env"
    printf "  ✓ Personal data removed.\n"
fi

# ─── Remove installation directory ───────────────────────────────────────────
# The script is running inside the directory to be deleted.
# We move to /tmp first so the shell does not hold a lock on it.
_target="$INSTALL_DIR"
cd /tmp
rm -rf "$_target"
printf "  ${C_GREEN}✓ VoxRefiner removed: %s${C_RESET}\n" "$_target"
echo ""
printf "${C_GREEN}✅ Uninstall complete.${C_RESET}\n"

# ─── Reminder: keyboard shortcuts ─────────────────────────────────────────────
echo ""
printf "${C_YELLOW}Note:${C_RESET} keyboard shortcuts bound to launch-vox-refiner.sh\n"
printf "  must be removed manually in your desktop environment settings.\n"
echo ""

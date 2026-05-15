#!/bin/bash
set -euo pipefail

cd "$(dirname "$0")"

SCRIPT_NAME="$(basename "$0")"

usage() {
    cat <<EOF
Usage: ./$SCRIPT_NAME [--check|--apply]

  --check    Check whether updates are available
  --apply    Apply updates (fast-forward only)
EOF
}

ensure_git_repo() {
    if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        echo "ERROR: This directory is not a git repository."
        exit 1
    fi
}

resolve_upstream() {
    local branch
    branch="$(git rev-parse --abbrev-ref HEAD)"

    if git rev-parse --abbrev-ref --symbolic-full-name "@{u}" >/dev/null 2>&1; then
        git rev-parse --abbrev-ref --symbolic-full-name "@{u}"
        return
    fi

    if git show-ref --quiet "refs/remotes/origin/$branch"; then
        echo "origin/$branch"
        return
    fi

    echo "origin/main"
}

fetch_remote() {
    local remote
    remote="${1%%/*}"
    git fetch --tags --prune "$remote"
}

count_behind() {
    local upstream
    upstream="$1"
    git rev-list --count "HEAD..$upstream"
}

print_status() {
    local upstream behind current_tag latest_tag
    upstream="$1"
    behind="$2"

    current_tag="$(git describe --tags --abbrev=0 HEAD 2>/dev/null || echo "none")"
    latest_tag="$(git describe --tags --abbrev=0 "$upstream" 2>/dev/null || echo "none")"

    echo "Current branch : $(git rev-parse --abbrev-ref HEAD)"
    echo "Tracking       : $upstream"
    echo "Current tag    : $current_tag"
    echo "Latest tag     : $latest_tag"

    if [ "$behind" -eq 0 ]; then
        echo "Status         : Up to date"
    else
        echo "Status         : Update available ($behind commit(s) behind)"
    fi
}

fix_filemode_drift() {
    # Silently normalize the filesystem for tracked files whose only local change
    # is an executable-bit addition (100644 → 100755). repair_exec_bits() sets
    # chmod +x on scripts that HEAD tracks as 100644, creating a persistent
    # working-tree diff that blocks the clean-tree check.
    # Strategy: restore the filesystem mode to match HEAD (chmod -x) so git sees
    # no change at all — no staged entry, no working-tree diff. repair_exec_bits()
    # will re-apply chmod +x on the scripts that need it after the pull.
    while IFS= read -r path; do
        [ -z "$path" ] && continue
        if git diff -- "$path" | grep -q '^old mode 100644'; then
            chmod -x "$path"
        fi
    done < <(git diff --name-only)
}

ensure_clean_tracked_tree() {
    if ! git diff --quiet || ! git diff --cached --quiet; then
        echo "ERROR: Local tracked changes detected."
        echo "Commit/stash them first, then run ./$SCRIPT_NAME --apply"
        exit 1
    fi
}

collect_deleted_paths() {
    {
        git diff --name-only --diff-filter=D
        git diff --cached --name-only --diff-filter=D
    } | sort -u
}

auto_resolve_obsolete_deletions() {
    local upstream path repaired
    upstream="$1"
    repaired=0

    while IFS= read -r path; do
        [ -z "$path" ] && continue

        # If upstream no longer contains this path, a local deletion is obsolete.
        if git cat-file -e "$upstream:$path" >/dev/null 2>&1; then
            continue
        fi

        if git ls-files --error-unmatch "$path" >/dev/null 2>&1; then
            git restore --staged --worktree -- "$path" >/dev/null 2>&1 || \
                git restore --worktree -- "$path" >/dev/null 2>&1 || true
            echo "Auto-resolved obsolete local deletion: $path"
            repaired=1
        fi
    done < <(collect_deleted_paths)

    if [ "$repaired" -eq 1 ]; then
        echo "Obsolete deletions normalized; continuing update..."
    fi
}

sync_env() {
    # Add keys from .env.example that are completely absent from .env.
    # Keys already present (even commented or with a different value) are left
    # untouched — we never overwrite the user's choices.
    # Each new key is appended together with any comment lines that immediately
    # precede it in .env.example, so the documentation travels with the key.
    local example=".env.example"
    local target=".env"

    if [ ! -f "$example" ] || [ ! -f "$target" ]; then
        return
    fi

    local added=0
    local pending_comments=""
    local in_block=false

    while IFS= read -r line; do
        # Blank line — reset comment accumulator
        if [ -z "$line" ]; then
            pending_comments=""
            in_block=false
            continue
        fi

        # Comment or section header — accumulate
        if [[ "$line" == \#* ]]; then
            pending_comments="${pending_comments:+$pending_comments
}$line"
            in_block=true
            continue
        fi

        # Key=value line
        local key
        key="${line%%=*}"
        if [ -z "$key" ]; then
            pending_comments=""
            in_block=false
            continue
        fi

        # Check if this key exists anywhere in .env (active or commented)
        if ! grep -qE "^#?[[:space:]]*${key}[[:space:]]*=" "$target" 2>/dev/null; then
            # Key is completely absent — append block separator + comments + key
            {
                printf '\n'
                [ -n "$pending_comments" ] && printf '%s\n' "$pending_comments"
                printf '%s\n' "$line"
            } >> "$target"
            echo "  + Added to .env: $key"
            added=$((added + 1))
        fi

        pending_comments=""
        in_block=false
    done < "$example"

    if [ "$added" -gt 0 ]; then
        echo "✅ .env updated: $added new key(s) added from .env.example."
    else
        echo "✓  .env is already up to date."
    fi
}

repair_exec_bits() {
    local scripts=(
        record_and_transcribe_local.sh
        vox-refiner-update.sh
        vox-refiner-menu.sh
        launch-vox-refiner.sh
        install.sh
        uninstall.sh
        voice_translate.sh
        selection_to_voice.sh
        selection_to_insight.sh
        selection_to_search.sh
        selection_to_factcheck.sh
        screen_to_text.sh
        reminder.sh
        reminder-daemon.sh
    )
    for s in "${scripts[@]}"; do
        if [ -f "$s" ]; then chmod +x "$s"; fi
    done
}

sync_python_deps() {
    local venv_python="$(pwd)/.venv/bin/python"
    if [ ! -x "$venv_python" ]; then
        echo "⚠️  .venv not found — skipping Python dependency sync."
        echo "   Run ./install.sh to create the virtual environment."
        return
    fi
    if [ ! -f "requirements.txt" ]; then
        return
    fi
    echo "📦 Syncing Python dependencies..."
    "$venv_python" -m pip install -q -r requirements.txt
    echo "✓  Python dependencies up to date."
}

sync_system_deps() {
    if command -v xdotool >/dev/null 2>&1; then
        return
    fi
    echo "📦 Installing missing system dependency: xdotool..."
    if command -v apt-get >/dev/null 2>&1; then
        sudo apt-get install -y xdotool
        echo "✓  xdotool installed."
    else
        echo "⚠️  xdotool is required for Screen to Text (hides the terminal during capture)."
        echo "   Install it manually:  sudo apt install xdotool"
    fi
}

run_check() {
    local upstream behind
    upstream="$(resolve_upstream)"
    fetch_remote "$upstream"
    behind="$(count_behind "$upstream")"
    print_status "$upstream" "$behind"
}

run_apply() {
    local upstream behind

    upstream="$(resolve_upstream)"
    fetch_remote "$upstream"
    fix_filemode_drift
    auto_resolve_obsolete_deletions "$upstream"
    ensure_clean_tracked_tree
    behind="$(count_behind "$upstream")"

    if [ "$behind" -eq 0 ]; then
        echo "Already up to date."
        repair_exec_bits
        sync_env
        sync_python_deps
        sync_system_deps
        return
    fi

    if git rev-parse --abbrev-ref --symbolic-full-name "@{u}" >/dev/null 2>&1; then
        git pull --ff-only
    else
        git merge --ff-only "$upstream"
    fi

    repair_exec_bits
    sync_env
    sync_python_deps
    sync_system_deps
    echo "Update applied successfully."
    print_status "$upstream" "$(count_behind "$upstream")"
}

main() {
    ensure_git_repo

    case "${1:-}" in
        --check)
            run_check
            ;;
        --apply)
            run_apply
            ;;
        --help|-h|"")
            usage
            ;;
        *)
            echo "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
}

main "$@"

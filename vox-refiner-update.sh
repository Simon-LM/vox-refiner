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

ensure_clean_tracked_tree() {
    if ! git diff --quiet || ! git diff --cached --quiet; then
        echo "ERROR: Local tracked changes detected."
        echo "Commit/stash them first, then run ./$SCRIPT_NAME --apply"
        exit 1
    fi
}

repair_exec_bits() {
    chmod +x record_and_transcribe_local.sh
    chmod +x vox-refiner-update.sh

    if [ -f "launch_vox-refiner.sh" ]; then
        chmod +x launch_vox-refiner.sh
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

    ensure_clean_tracked_tree
    upstream="$(resolve_upstream)"
    fetch_remote "$upstream"
    behind="$(count_behind "$upstream")"

    if [ "$behind" -eq 0 ]; then
        echo "Already up to date."
        repair_exec_bits
        return
    fi

    if git rev-parse --abbrev-ref --symbolic-full-name "@{u}" >/dev/null 2>&1; then
        git pull --ff-only
    else
        git merge --ff-only "$upstream"
    fi

    repair_exec_bits
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

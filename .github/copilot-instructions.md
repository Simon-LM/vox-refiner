<!-- @format -->

# GitHub Copilot — instructions for this repository

## CHANGELOG + commit + tag — MANDATORY workflow

When ready to commit (user asks for a commit name, tag, or release):

**Step 1 — Update CHANGELOG.md FIRST, before anything else:**

- Promote `[Unreleased]` to `[X.Y.Z] — YYYY-MM-DD` (determine the correct semver bump)
- Leave `[Unreleased]` empty (keep the header, no content below it)

**Step 2 — Then propose:**

- Commit message in English (conventional commit format: `type(scope): description`)
- Git tag: `vX.Y.Z`

**This order is non-negotiable.** Never present a commit name or tag without having already edited CHANGELOG.md in step 1. If the file has not been updated, do it immediately before responding.

---

## Semver bump rules

- `patch` (Z): bug fixes, docs, tests, refactor with no API change
- `minor` (Y): new opt-in features, new env vars, new CLI flags
- `major` (X): breaking changes, removed features, incompatible config changes

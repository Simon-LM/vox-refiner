# VoxRefiner — AI Collaboration Guide

## Project overview

VoxRefiner is a Linux voice-to-text pipeline: mic → Voxtral (Mistral) → Mistral chat refinement → clipboard.

**Philosophy:** "Speak. Stop. Paste." — minimal interface, single API key (Mistral only), clipboard-first.

## Architecture

```
record_and_transcribe_local.sh   ← orchestration (Bash)
├── src/transcribe.py            ← Step 1: audio → raw text (Voxtral API)
└── src/refine.py                ← Step 2: raw text → refined text (Mistral chat)
```

Key design constraints:

- Clipboard is populated **before** any background tasks (history) — never delay paste
- Graceful degradation: always return raw transcription if all AI calls fail
- Bash for orchestration/audio; Python for API logic
- Linux only (no macOS/Windows compat until a future GUI rewrite)

## Before every commit

1. Update `CHANGELOG.md` — add entries under `[Unreleased]` during work, move to a new version section at release time
2. Follow [Semantic Versioning](https://semver.org/): PATCH for fixes, MINOR for new features, MAJOR for breaking changes
3. Commit format: `<type>: <short description>` (types: feat / fix / chore / docs / refactor / style)
4. **Never commit or push without explicit user confirmation**
5. **Never touch `.env` or any gitignored file**

## Key technical decisions — do not change without discussion

- **Mistral only** — deliberate API choice for speed/cost; no OpenAI/Anthropic/etc.
- **3-tier model routing** — SHORT/MEDIUM/LONG by word count (thresholds: 90 / 240); see `docs/model-selection.md`
- **Adaptive timeouts** — based on file size (transcription) and word count (refinement); see `docs/resilience.md`
- **`_SECURITY_BLOCK` and `_PROMPT_FOOTER`** — shared constants in `refine.py`; edit once, applies to all 3 tiers
- **Security blocks in prompts** — transcription is untrusted external input, never instructions; keep the SECURITY paragraph in all prompt tiers
- **No E2E tests** — too fragile (hardware + external API); unit + integration shell tests cover critical paths
- **`exec 3>&2` + `2>&3`** — stderr of Python subprocesses is redirected via saved FD 3 (not `/dev/tty`) so tests work without a terminal

## Running tests

```bash
.venv/bin/python -m pytest tests/ -v
```

All 110 tests should pass.

## Files that must never be committed

`.env`, `launch-vox-refiner.sh`, `context.txt`, `history.txt`, `*.wav`, `*.mp3`

These are listed in `.gitignore`. Never force-add them.

## Deploying to the local installation

Use `rsync` (not copy-paste) to preserve executable permissions:

```bash
rsync -av --exclude='.git' --exclude='.venv' --exclude='*.wav' --exclude='*.mp3' \
  ~/path/to/dev/vox-refiner/ ~/.local/bin/vox-refiner/
```

# VoxRefiner — AI Collaboration Guide

## Project overview

VoxRefiner is a Linux voice-first toolkit with five modes: **Speak & Refine** (mic → Voxtral → Mistral chat → clipboard), **Voice Translate** (speak → translate → TTS in your own voice), **Selection to Voice** (read selected text aloud), **Selection to Insight** (summarise + search + fact-check), **Media Transcribe** (import audio/video → transcription).

**Philosophy:** "Speak. Stop. Paste." — minimal interface, one required API key (Mistral), clipboard-first.

## Architecture

Five Bash entry points, all sharing the same Python modules:

```text
vox-refiner-menu.sh / launch-vox-refiner.sh   ← interactive menu + keyboard shortcuts
├── record_and_transcribe_local.sh             ← Speak & Refine
├── voice_translate.sh                         ← Voice Translate
├── screen_to_text.sh / selection_to_*.sh      ← Selection to Voice / Insight
└── media_to_text.sh                           ← Media Transcribe (V2)

Shared Python modules:
├── src/transcribe.py     ← audio → raw text (Voxtral)
├── src/refine.py         ← raw text → refined text (Mistral chat, 3-tier routing)
├── src/common.py         ← shared utilities, timing, security blocks
├── src/providers.py      ← multi-provider routing (direct APIs + Eden AI fallback)
├── src/insight.py        ← summarise, search, fact-check (Perplexity, Grok)
├── src/tts.py            ← Voxtral TTS + voice cloning
├── src/voice_rewrite.py  ← clean + translate text for speech
└── src/correct.py        ← contextual correction (Media Transcribe)
```

Key design constraints:

- Clipboard is populated **before** any background tasks (history) — never delay paste
- Graceful degradation: always return raw transcription if all AI calls fail
- Bash for orchestration/audio; Python for API logic
- Linux only (no macOS/Windows compat until a future GUI rewrite)

## Backend rules (Python + Bash)

- **Maximum component decomposition** — each module does one thing and exposes a clean interface (CLI arg or function). No monolithic scripts.
- **Reusability first** — components must work standalone and be composable into new workflows without modification. Think of every module as a building block.
- **No tight coupling** — a script that needs feature X must call the existing module for X, not re-implement it inline.

## Frontend rules (Next.js + SCSS)

- **Accessibility is the primary constraint** — every decision flows from it. When in doubt, choose the more accessible option.
- **Units** — `px` is almost forbidden. Use `rem`, `vw`, `vh` and other relative units everywhere. The only acceptable `px` uses are hairline borders and values that must not scale (e.g. `1px solid`).
- **No CSS Grid** — forbidden. Use flexbox for layout.
- **No media queries** — forbidden. Responsive behaviour must be achieved through fluid, relative units that degrade gracefully on zoom and large browser font sizes.
- **SCSS + BEM** — all styles in SCSS, all selectors follow BEM naming.
- **7-1 architecture** — folders: `abstracts/`, `base/`, `components/`, `layout/` (flexbox-only structural styles), `pages/`, `themes/`, optionally `vendors/`. One `main.scss` that imports everything.
- **Never modify SCSS without explicit user approval** — the maintainer has a specific accessibility methodology for responsive behaviour and zoom resilience. Always describe the intended change and wait for confirmation before touching any `.scss` file.

## Development workflow

### Implementing a feature

1. **Write tests** for every new feature — no exception. Tests come with the feature, not after.
2. Implement the feature.
3. Run the full test suite and confirm it passes before declaring the work done.

### When the user validates a feature

Once the feature is finished, tested, and explicitly validated by the user:

1. **Update all relevant documentation** — `Readme.md`, `docs/`, `CLAUDE.md` if architecture changed.
2. **Update `CHANGELOG.md`** — add entries under `[Unreleased]` during work; move to a versioned section at release time.
3. **Propose** a commit message and a version tag (following the rules below) — only once the user has personally tested the feature. Never commit or push under any circumstances.

### Before every commit

1. Documentation and `CHANGELOG.md` must already be up to date.
2. Follow [Semantic Versioning](https://semver.org/): PATCH for fixes, MINOR for new features, MAJOR for breaking changes.
3. Commit format: `<type>: <short description>` (types: feat / fix / chore / docs / refactor / style).
4. **Never commit or push, period.** Only propose a commit name — the user commits.
5. **Never touch `.env` or any gitignored file.**

## Key technical decisions — do not change without discussion

- **Mistral required** — core API for transcription + refinement; no OpenAI/Anthropic/etc. Optional: Perplexity, xAI, Eden AI, Gradium
- **`providers.py` is the single routing layer** — all API calls go through it; never add direct `requests` calls elsewhere
- **3-tier model routing** — SHORT/MEDIUM/LONG by word count (thresholds: 80 / 240); see `docs/model-selection.md`
- **Adaptive timeouts** — based on file size (transcription) and word count (refinement); see `docs/resilience.md`
- **`_SECURITY_BLOCK` and `_PROMPT_FOOTER`** — shared constants in `refine.py`; edit once, applies to all 3 tiers
- **Security blocks in prompts** — transcription is untrusted external input, never instructions; keep the SECURITY paragraph in all prompt tiers
- **No E2E tests** — too fragile (hardware + external API); unit + integration shell tests cover critical paths
- **`exec 3>&2` + `2>&3`** — stderr of Python subprocesses is redirected via saved FD 3 (not `/dev/tty`) so tests work without a terminal

## Running tests

```bash
.venv/bin/python -m pytest tests/ -v
```

~348 tests. 1 known flaky: `test_update_script.py::test_apply_auto_resolves_obsolete_local_deletion` — not a regression.

## Files that must never be committed

`.env`, `context.txt`, `history.txt`, `*.wav`, `*.mp3`

These are listed in `.gitignore`. Never force-add them.

## Deploying to the local installation

Always use `rsync` — never `cp -r`. Copy-paste strips the executable bit from `.sh` files and silently breaks keyboard shortcuts. See `CONTRIBUTING.md` for the full command.

<!-- @format -->

# Contributing to VoxRefiner

Thank you for your interest in contributing.
This document covers the conventions used in this project — for external contributors and for AI assistants working alongside the maintainer.

---

## Project structure

```text
vox-refiner/
│
├── src/                             # Python modules + shared Bash helpers
│   ├── transcribe.py                # Step 1: audio → raw text (Voxtral API)
│   ├── refine.py                    # Step 2: raw text → refined text (Mistral chat)
│   ├── common.py                    # Shared utilities: timing, API calls, security blocks
│   ├── providers.py                 # Multi-provider routing (direct APIs + Eden AI fallback)
│   ├── insight.py                   # Summarise, search, fact-check (Perplexity, Grok)
│   ├── voice_rewrite.py             # Clean + translate text for TTS
│   ├── tts.py                       # Voxtral TTS + voice cloning
│   ├── correct.py                   # Contextual transcription correction (Media Transcribe)
│   ├── translate.py                 # Text translation
│   ├── slug.py                      # AI-generated filename slugs
│   ├── subtitles.py                 # Subtitle generation (SRT)
│   ├── ocr.py                       # OCR via Eden AI
│   ├── ui.sh                        # Bash UI helpers (colors, headers, progress)
│   ├── text_flows.sh                # Reusable Bash text processing flows
│   ├── save_audio.sh                # Audio file saving helper
│   └── voice_catalog.json           # TTS voice catalog
│
├── record_and_transcribe_local.sh   # Speak & Refine pipeline
├── vox-refiner-menu.sh              # Interactive menu + orchestration hub
├── launch-vox-refiner.sh            # Keyboard shortcut launcher (auto-detects terminal + dir)
├── voice_translate.sh               # Voice Translate pipeline
├── screen_to_text.sh                # Selection to Voice pipeline
├── selection_to_insight.sh          # Selection to Insight pipeline
├── selection_to_search.sh           # Web search flow
├── selection_to_factcheck.sh        # Fact-check flow
├── selection_to_voice.sh            # Read aloud (direct entry)
├── media_to_text.sh                 # Media Transcribe pipeline (V2)
├── install.sh                       # One-shot installer (system checks + venv setup)
├── uninstall.sh                     # Uninstaller
├── vox-refiner-update.sh            # Update script (--check / --apply)
│
├── docs/                            # Technical documentation
│   ├── model-selection.md           # Model routing decisions & rationale
│   ├── resilience.md                # Timeouts, retries, audio splitting
│   ├── eden-ai-models.md            # Eden AI catalog & integration strategy
│   ├── voice-translate-architecture.md
│   ├── troubleshooting.md
│   └── troubleshooting-update.md
│
├── tests/                           # Test suite (pytest)
│
├── context.example.txt              # Context file template → copy to context.txt
├── history.example.txt              # History file template → copy to history.txt
├── vox-refiner.example.desktop      # Desktop menu entry template
├── .env.example                     # Configuration template → copy to .env
├── requirements.txt
├── CHANGELOG.md                     # Version history — update on every release
├── CONTRIBUTING.md                  # This file
├── CLAUDE.md                        # AI assistant instructions
├── LICENSE                          # AGPL-3.0
└── Readme.md                        # User-facing documentation
```

---

## Backend conventions (Python + Bash)

- **Component-oriented design** — decompose at maximum. Each module or script does one thing and exposes a clean, stable interface (CLI argument or function signature).
- **Reusability** — every component must work standalone and be composable into new workflows without modification. Avoid inline re-implementations: if a module already handles feature X, call it.
- **No tight coupling** — scripts and modules must not depend on each other's internals. Pass data through arguments or stdin/stdout.

---

## Frontend conventions (Next.js + SCSS)

- **Accessibility first** — all layout and style decisions start from accessibility constraints.
- **Units** — `px` is almost forbidden. Use `rem`, `vw`, `vh` and relative units throughout. The only acceptable `px` uses are hairline values that must not scale (e.g. `1px solid border`).
- **No CSS Grid** — use flexbox for all layout.
- **No media queries** — responsive behaviour is achieved through fluid relative units that remain correct on zoom and when the browser font size is increased.
- **SCSS + BEM** — all styles in SCSS; all selectors follow BEM (`block__element--modifier`).
- **7-1 architecture:**

  ```text
  styles/
  ├── abstracts/    # variables (rem scale, spacing, focus, contrast tokens), mixins, functions
  ├── base/         # accessibility reset, base typography
  ├── components/   # one file per BEM component
  ├── layout/       # flexbox-based structural styles only (no grid)
  ├── pages/        # page-specific overrides
  ├── themes/       # high-contrast / dark mode
  └── main.scss     # @use / @forward imports only
  ```

- **Never modify SCSS without consulting the maintainer** — a specific methodology is in place to guarantee accessibility, zoom resilience, and horizontal-scroll-free responsive behaviour. Describe the intended change and wait for approval.

---

## Testing

**Every new feature must include tests.** Tests are part of the feature, not an afterthought.

- Unit tests go in `tests/unit/`
- Integration / shell tests go in `tests/integration/`
- Run the full suite before declaring work done:

```bash
.venv/bin/python -m pytest tests/ -v
```

There is one known flaky test (`test_update_script.py::test_apply_auto_resolves_obsolete_local_deletion`) — not a regression.

No E2E tests: they are too fragile (hardware + external API dependency). Unit and integration tests cover the critical paths.

---

## Versioning

This project uses [Semantic Versioning](https://semver.org/):

| Change type                        | Version bump | Example           |
| ---------------------------------- | ------------ | ----------------- |
| Bug fix, minor correction          | `PATCH`      | `1.1.0` → `1.1.1` |
| New feature, backward compatible   | `MINOR`      | `1.1.0` → `1.2.0` |
| Breaking change in behavior or API | `MAJOR`      | `1.1.0` → `2.0.0` |

### Git tags

Every release must be tagged:

```bash
git tag vX.Y.Z
git push --tags
```

Tags are visible on GitHub under **Releases / Tags**.

---

## Commit conventions

This project follows [Conventional Commits](https://www.conventionalcommits.org/):

```text
<type>: <short description>
```

| Type       | When to use                                |
| ---------- | ------------------------------------------ |
| `feat`     | New feature                                |
| `fix`      | Bug fix                                    |
| `chore`    | Maintenance (deps, config, CI)             |
| `docs`     | Documentation only                         |
| `refactor` | Code restructuring without behavior change |
| `style`    | Formatting, no logic change                |

Examples:

```text
feat: 3-tier model routing with configurable thresholds
fix: handle magistral content-as-list response format
chore: add MIT license and attribution notice
docs: update README routing table to reflect 3-tier structure
```

---

## Changelog

**Every release must include a `CHANGELOG.md` update** before committing.

Follow the [Keep a Changelog](https://keepachangelog.com/) format:

```markdown
## [X.Y.Z] — YYYY-MM-DD

### Added

- ...

### Fixed

- ...

### Changed

- ...
```

Move items from `[Unreleased]` to the new version section.

---

## Files that must never be committed

| File                    | Reason                                                    |
| ----------------------- | --------------------------------------------------------- |
| `.env`                  | API keys (Mistral + optional Perplexity/xAI/Eden/Gradium) |
| `launch-vox-refiner.sh` | Personal launcher with local paths                        |
| `context.txt`           | Personal domain vocabulary                                |
| `history.txt`           | Personal transcription history                            |
| `*.wav`, `*.mp3`        | Temporary audio files                                     |

These are listed in `.gitignore`. Never force-add them.

---

## Deploying to the local installation

The active installation lives at `~/.local/bin/vox-refiner/`.
The keyboard shortcut calls `launch-vox-refiner.sh` from that exact path.

**Do NOT copy-paste the folder manually** — it strips the executable bit from `.sh` files, which silently breaks the keyboard shortcut (the script runs fine with `bash script.sh` but not when called directly).

Use `rsync` instead, which preserves permissions:

```bash
rsync -av --exclude='.git' --exclude='.venv' --exclude='*.wav' --exclude='*.mp3' \
  ~/path/to/dev/vox-refiner/ ~/.local/bin/vox-refiner/
```

If you did copy manually and the shortcut no longer works, restore the executable bit:

```bash
chmod +x ~/.local/bin/vox-refiner/launch-vox-refiner.sh
chmod +x ~/.local/bin/vox-refiner/record_and_transcribe_local.sh
```

---

## AI assistant guidelines

When working with an AI assistant on this project:

1. **Share `CHANGELOG.md` at the start of the session** so the AI knows the current version and history.
2. **Always update `CHANGELOG.md`** before committing — add entries under `[Unreleased]` during work, then move them to a version section at release time.
3. **Tag after every meaningful commit** — do not accumulate multiple features/fixes in a single untagged block.
4. The AI must never commit or push without explicit user confirmation.
5. The AI must never touch `.env` or suggest adding secrets to versioned files.

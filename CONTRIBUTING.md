<!-- @format -->

# Contributing to Voxtral Paste

Thank you for your interest in contributing.
This document covers the conventions used in this project — for external contributors and for AI assistants working alongside the maintainer.

---

## Project structure

```text
voxtral-paste/
├── src/
│   ├── transcribe.py       # Step 1: audio → raw transcription (Voxtral API)
│   └── refine.py           # Step 2: raw text → refined text (Mistral chat API)
├── record_and_transcribe_local.sh   # Main entry point (bash pipeline)
├── launch_voxtral.example.sh        # Keyboard shortcut launcher template
├── context.txt             # User domain vocabulary (injected into refinement prompt)
├── .env.example            # Configuration template
├── requirements.txt
├── CHANGELOG.md            # Version history — update on every release
├── CONTRIBUTING.md         # This file
├── LICENSE                 # MIT
└── Readme.md               # User-facing documentation
```

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

| File                | Reason                             |
| ------------------- | ---------------------------------- |
| `.env`              | Contains the Mistral API key       |
| `launch_voxtral.sh` | Personal launcher with local paths |
| `*.wav`, `*.mp3`    | Temporary audio files              |

These are listed in `.gitignore`. Never force-add them.

---

## AI assistant guidelines

When working with an AI assistant on this project:

1. **Share `CHANGELOG.md` at the start of the session** so the AI knows the current version and history.
2. **Always update `CHANGELOG.md`** before committing — add entries under `[Unreleased]` during work, then move them to a version section at release time.
3. **Tag after every meaningful commit** — do not accumulate multiple features/fixes in a single untagged block.
4. The AI must never commit or push without explicit user confirmation.
5. The AI must never touch `.env` or suggest adding secrets to versioned files.

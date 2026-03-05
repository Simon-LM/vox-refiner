<!-- @format -->

# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [1.1.0] — 2026-03-06

### Added

- 3-tier model routing based on transcription length:
  - < 80 words → `devstral-small-latest` (fast)
  - 80–200 words → `magistral-small-latest` (balanced)
  - > 200 words → `magistral-medium-latest` (deep reasoning)
- Configurable thresholds and models via `.env` (`REFINE_MODEL_THRESHOLD_SHORT`, `REFINE_MODEL_THRESHOLD_LONG`, etc.)
- Correct fallback message displayed in terminal when primary model is unavailable

### Fixed

- `AttributeError: 'list' object has no attribute 'strip'` — reasoning models (magistral) return `content` as a list of blocks; now handled properly
- Fallback terminal message was never displayed due to a logic bug — now shows `⚠️ primary unavailable — switching to fallback: <model>`

### Changed

- Medium tier fallback set to `mistral-medium-latest` (was `mistral-small-latest`)
- Updated `.env.example` and README routing table to reflect 3-tier structure

---

## [1.0.1] — 2026-03-05

### Added

- MIT License (`LICENSE` file) with copyright notice
- License badge in README
- License section at the bottom of README

### Fixed

- `setsid rec` — isolates the recording process into its own session to prevent double SIGINT on Ctrl+C

---

## [1.0.0] — 2026-03-05

### Added

- Initial release
- Full voice-to-text pipeline: record → speed up → silence removal → MP3 → Voxtral transcription → Mistral refinement → clipboard
- 2-tier model routing (short / long) with fallback chain
- `context.txt` for user domain vocabulary injection into the refinement prompt
- Graceful degradation: returns raw transcription if all models fail
- `.env` configuration with `.env.example` template
- `launch_voxtral.example.sh` for keyboard shortcut setup (multi-terminal documented)
- `.gitignore` excluding `.env`, `launch_voxtral.sh`, audio files

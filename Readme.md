<!-- @format -->

# VoxRefiner

<!-- markdownlint-disable-next-line MD033 -->
<p align="center">
  <!-- markdownlint-disable-next-line MD033 -->
  <img src="Logo/VoxRefiner_subtitile_Logo.svg" alt="VoxRefiner logo" width="360" />
</p>

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**VoxRefiner — Speak naturally. AI refines it. Just paste.**

---

## What is VoxRefiner?

VoxRefiner turns your voice into clean, ready-to-paste text — instantly. Speak naturally,
let AI refine your words, and paste the result anywhere. No typing, no manual cleanup.

Powered by a personal context file (your projects, tech stack, vocabulary) and a smart
history that gets better the more you use it, VoxRefiner understands you — not just
your words.

One API key. No complex UI. Just speak → paste.

---

## How it works

1. You launch VoxRefiner from the terminal or via a keyboard shortcut
2. Recording starts immediately
3. You speak
4. You stop the recording (**Ctrl+C**)
5. The recording is captured to a temporary WAV, sanity-checked, then processed locally (tempo adjustment × 1.5 by default, configurable via `AUDIO_TEMPO`, silence removal, MP3 conversion)
6. **Step 1 — Transcription:** the audio is sent to **Mistral Voxtral** for speech-to-text
7. **Step 2 — Refinement _(optional, on by default)_:** the raw transcription is passed to a **Mistral chat model** which:
   - removes hesitations, filler words and repetitions
   - corrects likely transcription errors using your personal context
   - rewrites the text cleanly, without altering your intent
8. The refined text is automatically copied to:
   - the standard clipboard (Ctrl+V)
   - the primary selection (middle-click paste on Linux)
9. _(Optional)_ If `ENABLE_HISTORY=true` and the text is ≥ 80 words: key facts are extracted
   **in the background** and added to `history.txt` — the clipboard is always populated first
10. You paste it anywhere (chat, form, editor, terminal, etc.)

---

## Intelligent model routing

The refinement step automatically selects the right model based on the length of the transcription:

| Transcription length | Primary model           | Fallback                  |
| -------------------- | ----------------------- | ------------------------- |
| < 80 words           | `mistral-small-latest`  | `devstral-small-latest`   |
| 80 – 240 words       | `mistral-medium-latest` | `magistral-small-latest`  |
| > 240 words          | `mistral-medium-latest` | `magistral-medium-latest` |

If a model is unavailable (rate limit, timeout), the next one is tried automatically.
If all models fail, the raw Voxtral transcription is returned — the tool never crashes.

The threshold and models are fully configurable via `.env`.

---

## History context (optional)

VoxRefiner can automatically build a `history.txt` file by extracting key facts from
your longer transcriptions. Enable it with `ENABLE_HISTORY=true` in your `.env`.

**What is stored:**

- Ongoing projects, tools, recurring topics, decisions — general context to help the AI
  understand your work over time
- Each bullet carries a `[YYYY-MM-DD HH:MM:SS]` timestamp, added by the application (not the AI)
- On each update the model consolidates the list: duplicates are removed, stale facts are
  dropped and new ones are merged within the `HISTORY_MAX_BULLETS` limit (default: 60)

**What is NOT stored:**

- Short dictations (< `REFINE_MODEL_THRESHOLD_SHORT` words, default 80)
- Passwords, credentials or any text not sent to the refinement step

**Clipboard-first:** the history update runs in the background **after** the clipboard is
populated. It never delays your paste.

`history.txt` stays on your machine — it is listed in `.gitignore` and never committed.
See `history.example.txt` for an example and `.env.example` for all configurable
parameters (`HISTORY_MAX_BULLETS`, `HISTORY_EXTRACTION_MODEL`).

---

## Advanced options

### Recording safeguards

To reduce failures caused by interrupted sessions or corrupted audio artifacts,
the recorder now applies defensive checks before transcription:

- Existing `local_audio.wav` / `local_audio.mp3` files are removed before a new recording.
- Capture is written to a temporary file in `/tmp` and promoted to `local_audio.wav` only after validation.
- A maximum WAV size guard rejects abnormally large/corrupted files before `ffmpeg`.

You can override the WAV size limit with:

```dotenv
MAX_WAV_BYTES=100000000
```

Default is `100000000` bytes (100 MB).

### Voxtral-only mode (no AI refinement)

Set `ENABLE_REFINE=false` in `.env` to skip the refinement step entirely.
The raw Voxtral transcription is copied to clipboard as-is — no Mistral chat call is made.
Useful if you want maximum speed or are testing Voxtral output in isolation.

### Side-by-side comparison

Set `REFINE_COMPARE_MODELS=true` in `.env` to run both the primary and fallback model on every
transcription and display their outputs in the terminal.

- The **primary result is copied to clipboard immediately** — behaviour is unchanged.
- The terminal shows a **3-way view** in order:
  1. `[1] Raw Voxtral` — unmodified speech-to-text output
  2. `[2] Primary (model-name) — copied to clipboard` — exact model name shown
  3. `[3] Fallback (model-name)` — exact model name shown

This mode is useful for evaluating model quality and tuning your routing configuration.

### Retry without re-recording

If a transcription fails or the result is unsatisfactory, you can replay the pipeline on the
already-captured audio without going back to the microphone:

```bash
bash record_and_transcribe_local.sh --retry
# or shorter:
bash record_and_transcribe_local.sh -r
```

This skips the recording and audio processing steps and reuses the existing `local_audio.mp3`.
The command is also printed at the end of each run as a reminder.

---

### Personal context

Use `context.example.txt` as a template, then create your local `context.txt`.
This file is injected into the refinement prompt so the AI understands your
technical terms and corrects transcription errors accordingly.

```bash
cp context.example.txt context.txt
${EDITOR:-nano} context.txt
```

`context.txt` is personal and ignored by git (`.gitignore`), so updates do not
overwrite your custom context.

Example:

```text
I am a developer. I work mainly in Python, React and TypeScript.
Frequent terms: API, pipeline, transcription, pull request, backend, deployment.
```

---

## Why VoxRefiner?

- Designed for **speed and simplicity**
- **One API key only** — Mistral
- Two-step pipeline: faithful transcription + intelligent cleanup
- Context-aware: adapts to your domain and vocabulary
- Perfect for:
  - quick messages
  - forms and chatbots
  - development workflows
  - reflective or long-form dictation
  - accessibility use cases

---

## Getting started

### Requirements

- Linux (tested on Ubuntu / MATE)
- `ffmpeg` (with `libmp3lame` support) installed
- Python 3.10+
- A [Mistral API key](https://console.mistral.ai/api-keys)

### Installation

```bash
# 1. Clone the repository into your local bin
git clone https://github.com/Simon-LM/vox-refiner.git ~/.local/bin/vox-refiner
cd ~/.local/bin/vox-refiner

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Configure your API key
cp .env.example .env
# Edit .env and set your MISTRAL_API_KEY

# 4. Make the scripts executable
chmod +x record_and_transcribe_local.sh launch_vox-refiner.sh vox-refiner-update.sh

# 5. (Optional) Create and edit personal context
cp context.example.txt context.txt
# Edit context.txt to describe your domain

# 6. Test it
bash record_and_transcribe_local.sh
```

> **Important:** always use `git clone` or `rsync` to install — do not copy-paste the folder manually.
> A manual copy strips the executable bit from `.sh` files, which silently breaks the keyboard shortcut.
> If you did copy manually and the shortcut no longer works, run: `chmod +x ~/.local/bin/vox-refiner/*.sh`

### Updating

To update to a newer version:

```bash
cd ~/.local/bin/vox-refiner
./vox-refiner-update.sh --check
./vox-refiner-update.sh --apply
```

Manual fallback (if needed):

```bash
git pull --ff-only
chmod +x record_and_transcribe_local.sh launch_vox-refiner.sh vox-refiner-update.sh
```

### Keyboard shortcut (recommended)

For the best experience, bind VoxRefiner to a keyboard shortcut so you can launch it with a single key press from anywhere.

1. Set up the launcher script:

   ```bash
   cp launch_vox-refiner.example.sh launch_vox-refiner.sh
   ```

# Edit launch_vox-refiner.sh:

# - set SCRIPT_PATH to the full path of record_and_transcribe_local.sh

# - set your terminal emulator (mate-terminal, gnome-terminal, konsole…)

chmod +x launch_vox-refiner.sh

````

2. Bind it to a keyboard shortcut in your desktop environment:

| Desktop   | Where to configure                             |
| --------- | ---------------------------------------------- |
| **MATE**  | System → Preferences → Keyboard Shortcuts      |
| **GNOME** | Settings → Keyboard → Custom Shortcuts         |
| **KDE**   | System Settings → Shortcuts → Custom Shortcuts |
| **XFCE**  | Settings → Keyboard → Application Shortcuts    |

Set the command to the full path of your launcher:

```text
/home/your-username/.local/bin/vox-refiner/launch_vox-refiner.sh
````

3. Press your shortcut → speak → stop (Ctrl+C) → paste anywhere.

---

## Philosophy

VoxRefiner is intentionally minimal.

You provide your Mistral API key once, and the tool just works.

The goal is to remove friction between speaking and writing — including the friction caused by imperfect voice recognition.

**Speak. Stop. Paste.**

---

## Current platform & stack

- Platform: **Linux** (tested on Ubuntu / MATE)
- Stack:
  - Bash — audio recording & orchestration
  - Python — transcription and refinement via Mistral API
  - `sox`, `ffmpeg`, `lame` — local audio processing
  - `requests`, `python-dotenv` — Python dependencies
- Interface: terminal-based

---

## Known limitations (current version)

- Stopping the recording relies on **Ctrl+C**
- No graphical interface
- Linux-only

These limitations are **known and accepted** for the current stage.

---

## Roadmap

### Desktop application (cross-platform)

The next major step is a real desktop application with:

- A minimal window with Start / Stop buttons
- Clear visual feedback (recording / processing / done)
- Global keyboard shortcut (works outside the terminal)
- Cross-platform: Linux, Windows, macOS

**Stack under consideration:**

#### Option A — Tauri (Rust + React / TypeScript)

- Lightweight native app
- Web-oriented development workflow (React / TypeScript)
- Same model as VS Code, Obsidian, etc.
- Easy to distribute and open source
- Requires learning Rust for the backend layer

#### Option B — Electron (Node.js + React / TypeScript)

- Full JavaScript/TypeScript stack
- Larger binary size, higher memory usage
- Same cross-platform reach

#### Option C — Python + Qt (PyQt6 / PySide6)

- Same language as the existing pipeline
- Native desktop look
- Good fit if you are already comfortable with Python

---

## Status

VoxRefiner is an **open source personal utility**, shared as-is.

It is functional, minimal, and intentionally simple.
The core pipeline is stable. The graphical interface is the next planned step.

---

## Core idea (unchanged)

No matter how the tool evolves, the core principle will remain the same:

> **Speak. Stop. Paste.**

---

## License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.

Copyright © 2026 [Simon LM](https://github.com/Simon-LM)

You are free to use, modify, and distribute this software. If you do, **you must keep the copyright notice and license file** in all copies or substantial portions of the code. Attribution is required.

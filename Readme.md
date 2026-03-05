<!-- @format -->

# Voxtral Paste

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**Voxtral Paste — Speak, get text, paste it anywhere.**

---

## What is Voxtral Paste?

Voxtral Paste is a small and simple voice-to-text tool that lets you speak and instantly paste the resulting text wherever you want.

You start recording, you speak, you stop — and the transcription is automatically cleaned up and copied to your clipboard.

One API key. No complex UI. Just speak → paste.

---

## How it works

1. You launch Voxtral Paste from the terminal or via a keyboard shortcut
2. Recording starts immediately
3. You speak
4. You stop the recording (**Ctrl+C**)
5. The audio is processed locally (speed up × 1.5, silence removal, MP3 conversion)
6. **Step 1 — Transcription:** the audio is sent to **Mistral Voxtral** for speech-to-text
7. **Step 2 — Refinement:** the raw transcription is passed to a **Mistral chat model** which:
   - removes hesitations, filler words and repetitions
   - corrects likely transcription errors using your personal context
   - rewrites the text cleanly, without altering your intent
8. The refined text is automatically copied to:
   - the standard clipboard (Ctrl+V)
   - the primary selection (middle-click paste on Linux)
9. You paste it anywhere (chat, form, editor, terminal, etc.)

---

## Intelligent model routing

The refinement step automatically selects the right model based on the length of the transcription:

| Transcription length | Primary model             | Fallback               |
| -------------------- | ------------------------- | ---------------------- |
| < 80 words           | `devstral-small-latest`   | `mistral-small-latest` |
| ≥ 80 words           | `magistral-medium-latest` | `mistral-large-latest` |

If a model is unavailable (rate limit, timeout), the next one is tried automatically.
If all models fail, the raw Voxtral transcription is returned — the tool never crashes.

The threshold and models are fully configurable via `.env`.

---

## Personal context

Edit `context.txt` to describe your domain, stack, and vocabulary.
This file is injected into the refinement prompt so the AI understands your technical terms and corrects transcription errors accordingly.

Example:

```text
I am a developer. I work mainly in Python, React and TypeScript.
Frequent terms: API, pipeline, transcription, pull request, backend, deployment.
```

---

## Why Voxtral Paste?

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
- `sox`, `ffmpeg`, `lame` installed
- Python 3.10+
- A [Mistral API key](https://console.mistral.ai/api-keys)

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/your-username/voxtral-paste.git
cd voxtral-paste

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Configure your API key
cp .env.example .env
# Edit .env and set your MISTRAL_API_KEY

# 4. (Optional) Edit context.txt to describe your domain

# 5. Run
bash record_and_transcribe_local.sh
```

### Keyboard shortcut (recommended)

For the best experience, bind Voxtral Paste to a keyboard shortcut so you can launch it with a single key press from anywhere.

1. Set up the launcher script:

   ```bash
   cp launch_voxtral.example.sh launch_voxtral.sh
   # Edit launch_voxtral.sh — set your terminal emulator and script path
   chmod +x launch_voxtral.sh
   ```

2. Bind it to a keyboard shortcut in your desktop environment:

   | Desktop   | Where to configure                             |
   | --------- | ---------------------------------------------- |
   | **MATE**  | System → Preferences → Keyboard Shortcuts      |
   | **GNOME** | Settings → Keyboard → Custom Shortcuts         |
   | **KDE**   | System Settings → Shortcuts → Custom Shortcuts |
   | **XFCE**  | Settings → Keyboard → Application Shortcuts    |

   Set the command to the full path of your launcher, e.g.:

   ```text
   /home/your-username/.local/bin/voxtral-paste/launch_voxtral.sh
   ```

3. Press your shortcut → speak → stop (Ctrl+C) → paste anywhere.

---

## Philosophy

Voxtral Paste is intentionally minimal.

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

Voxtral Paste is an **open source personal utility**, shared as-is.

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

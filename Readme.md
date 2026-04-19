<!-- @format -->

# VoxRefiner

<!-- markdownlint-disable-next-line MD033 -->
<p align="center">
  <!-- markdownlint-disable-next-line MD033 -->
  <img src="Logo/VoxRefiner_Logo.avif"g alt="VoxRefiner logo" width="360" />
</p>

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](LICENSE)

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
5. The recording is captured to a temporary WAV, sanity-checked, then processed locally (silence removal, tempo adjustment, MP3 conversion). The speed multiplier is `×1.25` by default in `.env` (safer for fast speakers), `×1.5` if `AUDIO_TEMPO` is unset — see `.env.example` for guidance.
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

| Transcription length | Primary model             | Fallback                |
| -------------------- | ------------------------- | ----------------------- |
| < 80 words           | `mistral-small-latest`    | `mistral-medium-latest` |
| 80 – 240 words       | `magistral-small-latest`  | `mistral-medium-latest` |
| > 240 words          | `magistral-medium-latest` | `mistral-medium-latest` |

Magistral models (reasoning) are used as primary because they follow instructions more
faithfully — they won't add content, answer questions or deviate from the transcription.
Mistral models serve as fast emergency fallbacks.

If a model is unavailable (rate limit, timeout), the next one is tried automatically.
If all models fail, the raw Voxtral transcription is returned — the tool never crashes.

Thresholds and models are fully configurable via `.env`.

---

## Output formatting profiles

For medium and long transcriptions (≥ 80 words), VoxRefiner can structure the output.
Set `OUTPUT_PROFILE` in your `.env`:

| Profile      | Alias           | Format                          | Best for                                   |
| ------------ | --------------- | ------------------------------- | ------------------------------------------ |
| `plain`      | —               | Flowing text (default)          | Quick messages, form fields                |
| `prose`      | `accessibility` | Clean paragraphs, no lists      | General use, accessibility, screen readers |
| `structured` | `dev`           | Paragraphs + bullet points      | Developers, meeting notes, chatbot input   |
| `technical`  | —               | Markdown (## headers + bullets) | Documentation, AI chat prompts             |

**Quick start:** use `OUTPUT_PROFILE=dev` for development workflows, or
`OUTPUT_PROFILE=accessibility` for screen-reader-friendly output.

Short transcriptions (< 80 words) are always `plain`, regardless of this setting.

---

## Output language

By default, VoxRefiner replies in the same language you speak.
Set `OUTPUT_LANG=en` in your `.env` to always get English output — useful for
developers working in English-only tools (VS Code, Claude Code) while speaking
another language.

```bash
OUTPUT_LANG=en    # force English output regardless of input language
```

Technical terms (`commit`, `push`, `refactor`, etc.) stay in English naturally.

---

## History context (optional)

VoxRefiner can automatically build a `history.txt` file by extracting key facts from
your longer transcriptions. Enable it with `ENABLE_HISTORY=true` in your `.env`.

**What is stored:**

- Ongoing projects, tools, recurring topics, decisions — general context to help the AI
  understand your work over time
- Each bullet carries a `[YYYY-MM-DD HH:MM:SS]` timestamp, added by the application (not the AI)
- On each update the model consolidates the list: duplicates are removed, stale facts are
  dropped and new ones are merged within the `HISTORY_MAX_BULLETS` limit (default: 100)
- To avoid saturation, the app only sends the most recent 80% of history entries to the
  model, keeping 20% capacity available for new bullets on each update

**What is NOT stored:**

- Short dictations (< `REFINE_MODEL_THRESHOLD_SHORT` words, default 80)
- Passwords, credentials or any text not sent to the refinement step

**Clipboard-first:** the history update runs in the background **after** the clipboard is
populated. It never delays your paste.

`history.txt` stays on your machine — it is listed in `.gitignore` and never committed.
See `history.example.txt` for an example and `.env.example` for all configurable
parameters (`HISTORY_MAX_BULLETS`, `HISTORY_EXTRACTION_MODEL`, `HISTORY_TIMEOUT_MULTIPLIER`).

---

## Speak & Translate

Speak in your language, get an audio translation played back in your own cloned voice.

1. Press your `--speak-translate` shortcut (or choose **Speak & Translate** from the menu)
2. Speak — recording starts immediately
3. Stop with **Ctrl+C**
4. VoxRefiner transcribes, translates to the target language, synthesises the result in
   your own voice, and plays it automatically

The target language is configurable in `.env` (`TRANSLATE_TARGET_LANG=en` by default).
You can also change it on the fly from the interactive settings menu.

Your voice is cloned from a short audio sample captured at the start of recording —
no pre-recording step required.

---

## Selection to Voice

Read any selected text (or clipboard content) aloud in a chosen voice.

1. Select text in any application (browser, editor, PDF viewer…)
2. Press your `--selection-voice` shortcut (or choose **Selection to Voice** from the menu)
3. VoxRefiner reads the selection out loud

**AI-powered preprocessing** (enabled by default):

Before reading, the text is cleaned for natural speech:

- Detects content type (news article, Wikipedia, email, documentation…) and applies
  type-specific rules
- Removes navigation menus, breadcrumbs, cookie banners, and other web clutter
- **Tables** are rewritten as spoken sentences: each row becomes
  "Column A: value. Column B: value."
- **Math formulas** (Wikipedia) are verbalised: `f(x)` → "f de x",
  `∀x ∈ S` → "pour tout x appartenant à S"
- **Quotations** are isolated into separate paragraphs so a distinct citation voice
  can be applied

**Dual-voice support:** configure `TTS_QUOTE_VOICE_ID` in `.env` to use a different
voice for quoted passages (press articles, speeches, etc.).

Both the reading voice and the citation voice are configurable from the settings menu.

---

## Selection to Insight

Get an instant audio summary of any selected text, then search or fact-check without leaving the session.

1. Select text in any application (browser, editor, PDF viewer…)
2. Press your `--selection-insight` shortcut (or choose **Selection to Insight** from the menu)
3. VoxRefiner detects the content type, generates a bullet-point summary, and reads it aloud
4. From the post-summary menu, choose what to do next

**Post-summary menu:**

| Key   | Action                                                              |
| ----- | ------------------------------------------------------------------- |
| `[l]` | Read the full original text aloud (hands off to Selection to Voice) |
| `[p]` | Search via Perplexity                                               |
| `[f]` | Fact-check (Perplexity + Grok)                                      |
| `[s]` | Replay the summary                                                  |
| `[q]` | Quit                                                                |

**Perplexity search (`[p]`):**

1. Dictate `[v]` or type `[t]` your question
2. The question is sent to Perplexity with the summary as context
3. The answer is read aloud
4. Post-search menu: replay the answer · replay the summary · read full article · new search

**Fact-check (`[f]`):**

1. Optionally target a specific claim — dictate `[v]` or type `[t]` (press Enter to verify the full article)
2. Perplexity (web sources) and Grok (X / Twitter reactions) run **in parallel**
3. Mistral synthesises a verdict: reliability label + 2-sentence synthesis + one line per source
4. The verdict is read aloud
5. Post-factcheck menu: replay verdict · web details · X details · replay summary · read full article

**API keys required:**

| Feature    | Key needed                                                          |
| ---------- | ------------------------------------------------------------------- |
| Summary    | `MISTRAL_API_KEY` (already required for core features)              |
| Search     | `PERPLEXITY_API_KEY` (optional)                                     |
| Fact-check | `PERPLEXITY_API_KEY` + `XAI_API_KEY` (both optional; one is enough) |

Add optional keys to your `.env` or configure them via **Settings → API Keys** in the interactive menu.
A warning is displayed at launch if keys are missing — the summary still works with Mistral alone.

---

## Advanced options

### Voxtral-only mode (no AI refinement)

Set `ENABLE_REFINE=false` in `.env` to skip the refinement step entirely.
The raw Voxtral transcription is copied to clipboard as-is — no Mistral chat call is made.
Useful if you want maximum speed or are testing Voxtral output in isolation.

### Show raw Voxtral output

`SHOW_RAW_VOXTRAL=true` is **enabled by default** so you can immediately see the
difference between what Voxtral heard and what the AI produced — without any extra
API call, cost, or delay.

- The terminal shows a **2-way view**:
  1. `[1] Raw Voxtral` — unmodified speech-to-text output
  2. `[2] Result — copied to clipboard`

Set `SHOW_RAW_VOXTRAL=false` in `.env` to hide the raw output once you no longer need it.

### Side-by-side comparison

Set `REFINE_COMPARE_MODELS=true` in `.env` to run the primary and fallback model
**in parallel** on every transcription and display their outputs in the terminal.

- The **primary result is copied to clipboard immediately** — behaviour is unchanged.
- Both models run simultaneously: total time is `max(primary, fallback)` instead of `primary + fallback`.
- The terminal shows a **3-way view** in order:
  1. `[1] Raw Voxtral` — unmodified speech-to-text output
  2. `[2] Primary (model-name) — copied to clipboard`
  3. `[3] Fallback (model-name)`

This mode is useful for evaluating model quality and tuning your routing configuration.

### Retry without re-recording

If a transcription fails or the result is unsatisfactory, you can replay the pipeline on the
already-captured audio without going back to the microphone:

```bash
bash record_and_transcribe_local.sh --retry
# or shorter:
bash record_and_transcribe_local.sh -r
```

This skips the recording and audio processing steps and reuses the existing `recordings/stt/source.mp3`.
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
- `ffmpeg` (with `libmp3lame` support)
- `sox` (for microphone recording via `rec`)
- `xclip` (clipboard integration)
- Python 3.10+
- A [Mistral API key](https://console.mistral.ai/api-keys)

### Installation

```bash
# 1. Clone the repository into your local bin
git clone https://github.com/Simon-LM/vox-refiner.git ~/.local/bin/vox-refiner
cd ~/.local/bin/vox-refiner

# 2. Run the installer (creates .venv, installs Python deps, sets chmod,
#    and creates missing local files from templates)
./install.sh

# 3. Configure your API key
# Edit .env and set your MISTRAL_API_KEY

# 4. Launch VoxRefiner (interactive menu)
./launch-vox-refiner.sh

# 5. (Recommended) Configure keyboard shortcuts
# Each mode can have its own shortcut — use the full path with the matching flag:
#
#   Speak & Refine (record, AI cleans, paste):
#   /home/your-username/.local/bin/vox-refiner/launch-vox-refiner.sh --speak-refine
#
#   Speak & Translate (record, translate, play in your voice):
#   /home/your-username/.local/bin/vox-refiner/launch-vox-refiner.sh --speak-translate
#
#   Selection to Voice (read selected or clipboard text aloud):
#   /home/your-username/.local/bin/vox-refiner/launch-vox-refiner.sh --selection-voice
#
#   Selection to Insight (summary + search + fact-check):
#   /home/your-username/.local/bin/vox-refiner/launch-vox-refiner.sh --selection-insight
#
#   Interactive menu (all features):
#   /home/your-username/.local/bin/vox-refiner/launch-vox-refiner.sh

# 6. (Optional) Create a desktop menu entry
# The .desktop entry uses the plain launcher (interactive menu — no flag).
cp vox-refiner.example.desktop ~/.local/share/applications/vox-refiner.desktop
# Edit /home/your-username in that file, then validate:
# desktop-file-validate ~/.local/share/applications/vox-refiner.desktop
```

> **Important:** always use `git clone` or `rsync` to install — do not copy-paste the folder manually.
> A manual copy strips the executable bit from `.sh` files, which silently breaks the keyboard shortcut.
> If you did copy manually and the shortcut no longer works, run: `chmod +x ~/.local/bin/vox-refiner/*.sh`
> **Venv note:** daily usage does **not** require `source .venv/bin/activate`.
> The launcher and scripts use `./.venv/bin/python` directly.

### Updating

To update to a newer version:

```bash
cd ~/.local/bin/vox-refiner
./vox-refiner-update.sh --check
./vox-refiner-update.sh --apply
```

`vox-refiner-update.sh --apply` now auto-normalizes local deletions for files
already removed upstream (legacy rename cleanup), so you do not need to
manually restore those files before updating.

Manual fallback (if needed):

```bash
git pull --ff-only
chmod +x record_and_transcribe_local.sh launch-vox-refiner.sh vox-refiner-update.sh
```

### Keyboard shortcut (recommended)

For the best experience, bind each VoxRefiner mode to its own keyboard shortcut.
The launcher auto-detects your terminal (`mate-terminal` → `gnome-terminal` → `xfce4-terminal` → `konsole` → `xterm`) and the install directory — no configuration needed.

To force a specific terminal, set `VOXREFINER_TERMINAL` in your environment.

**Available launch flags:**

| Flag                  | What it does                                          |
| --------------------- | ----------------------------------------------------- |
| `--speak-refine`      | Record, AI refines, copies to clipboard (most common) |
| `--speak-translate`   | Record, translate, play in your own voice             |
| `--selection-voice`   | Read selected or clipboard text aloud                 |
| `--selection-insight` | Summarise selected text, search, or fact-check        |
| _(no flag)_           | Open the interactive menu                             |

**Configure your shortcuts:**

| Desktop   | Where to configure                             |
| --------- | ---------------------------------------------- |
| **MATE**  | System → Preferences → Keyboard Shortcuts      |
| **GNOME** | Settings → Keyboard → Custom Shortcuts         |
| **KDE**   | System Settings → Shortcuts → Custom Shortcuts |
| **XFCE**  | Settings → Keyboard → Application Shortcuts    |

Example commands to bind (replace `your-username` with your actual username):

```text
# Speak & Refine — bind to e.g. Super+V
/home/your-username/.local/bin/vox-refiner/launch-vox-refiner.sh --speak-refine

# Speak & Translate — bind to e.g. Super+T
/home/your-username/.local/bin/vox-refiner/launch-vox-refiner.sh --speak-translate

# Selection to Voice — bind to e.g. Super+R
/home/your-username/.local/bin/vox-refiner/launch-vox-refiner.sh --selection-voice

# Selection to Insight — bind to e.g. Super+I
/home/your-username/.local/bin/vox-refiner/launch-vox-refiner.sh --selection-insight
```

Compatibility note:

- Ubuntu MATE 24.04: bind keyboard shortcuts directly to the launcher script.
- Ubuntu Budgie 24.04: both the launcher and `vox-refiner.desktop` may work,
  but the direct launcher script remains the recommended default.

Press your shortcut → speak → stop (Ctrl+C) → paste anywhere.

### Desktop menu entry (.desktop, optional)

If you want VoxRefiner to appear in your desktop app menu, use the template file:

1. Copy the template to your local applications folder:

```bash
mkdir -p ~/.local/share/applications
cp vox-refiner.example.desktop ~/.local/share/applications/vox-refiner.desktop
```

1. Edit `~/.local/share/applications/vox-refiner.desktop` and replace
   `/home/your-username/` with your actual home path.

1. Validate and enable it:

```bash
desktop-file-validate ~/.local/share/applications/vox-refiner.desktop
chmod +x ~/.local/share/applications/vox-refiner.desktop
```

1. Refresh your desktop app cache (optional on some environments):

```bash
update-desktop-database ~/.local/share/applications 2>/dev/null || true
```

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
  - `sox`, `ffmpeg`, `xclip` — local audio/clipboard integration
  - `requests`, `python-dotenv` — Python dependencies
- Interface: terminal-based

---

## Known limitations (current version)

- Stopping the recording relies on **Ctrl+C**
- No graphical interface
- Linux-only

These limitations are **known and accepted** for the current stage.

---

## Status

VoxRefiner is an **open source personal utility**, shared as-is.

It is functional, minimal, and intentionally simple.
The core pipeline is stable and actively maintained.

---

## Core idea (unchanged)

No matter how the tool evolves, the core principle will remain the same:

> **Speak. Stop. Paste.**

---

## Author

Built by **[Simon LM](https://simon-lm.dev)** · [GitHub](https://github.com/Simon-LM)

<p align="center">
  <a href="https://simon-lm.dev"><img src="Logo/LostInTab_Logo.avif" alt="LostInTab" height="320" /></a>
</p>

---

## License

This project is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)** — see the [LICENSE](LICENSE) file for details.

Copyright © 2026 Simon LM — LostInTab

You are free to use, modify, and distribute this software under the terms of the AGPL-3.0. If you modify VoxRefiner and make it available over a network (e.g. as a web service), you must publish the source code of your modified version. See the license for full terms.

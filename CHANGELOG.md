<!-- @format -->

# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [4.0.2] — 2026-04-10

### Fixed

- **`selection_to_voice.sh` — Feature 4 from main menu:** `VOXREFINER_MENU=0`
  override added so the post-playback menu is shown when Feature 4 is launched
  from the VoxRefiner main menu (was silently suppressed by the global
  `VOXREFINER_MENU=1` export).
- **Menu navigation — `[m]` harmonized:** `[m]` is now consistently labeled
  `Menu VoxRefiner` in all feature menus that exit to the main menu; `Menu settings`
  in the voice-picker sub-menu (returns to Settings).
- **Menu navigation — `[Enter]` audit:** `[Enter]` is no longer used for navigation
  or quit in any feature post-action menu. Each menu has an explicit key: `[m] Menu
  VoxRefiner`, `[q] Quit`, or `[m] Back`. `[Enter]` remains valid only as a launch
  action (e.g. `[Enter] Start translation` in Feature 2) and as `[Enter] Quit` in
  the standalone `record_and_transcribe_local.sh` direct mode.
- **`vox-refiner-menu.sh` — Settings menu:** `Press Enter to return...` replaced
  with `[m] Menu VoxRefiner` + `▸` prompt; `[Enter]` is now a no-op.
- **`vox-refiner-menu.sh` — API Keys sub-menu:** `[m] Edit Mistral key` renamed to
  `[e] Edit Mistral key`; `[m]` freed for `Menu VoxRefiner` navigation; `▸` prompt
  added; `[Enter]` is now a no-op.
- **`vox-refiner-menu.sh` — Update sub-menu:** `Press Enter to return...` replaced
  with `[m] Menu VoxRefiner` + `▸` prompt; `[Enter]` is now a no-op.
- **`vox-refiner-menu.sh` — Help screen:** proper `HELP` header added; `Press Enter
  to return...` replaced with `[m] Menu VoxRefiner` + `▸` prompt; `[Enter]` is now
  a no-op.

---

## [4.0.1] — 2026-04-09

### Added

- **`selection_to_insight.sh` — `[s] Settings` sub-menu:** session-only settings
  accessible from the main menu at any time:
  - `[1]` Reasoning (summary): `standard` ↔ `high` — controls `reasoning_effort`
    for the Mistral summary call.
  - `[2]` Search engine: cycles `auto → perplexity → grok → both` — overrides
    `INSIGHT_SEARCH_ENGINE` for the session.
  - `[3]` Fact-check engines: cycles `both → perplexity → grok` — controls which
    sources are queried in fact-check.
  - `[4]` Reasoning (synthesis): `standard` ↔ `high` — controls `reasoning_effort`
    for Mistral fact-check synthesis (only active when both engines return results).
  - API key status shown at the top of the settings screen: Perplexity and Grok
    each display `✓ key set` (green) or `✗ key missing` (red).
  - Current value shown in bold; available cycle values shown in dim parentheses.
- **`src/insight.py` — `INSIGHT_SUMMARY_REASONING`:** new env var (`standard` /
  `high`). Previously `reasoning_effort: "high"` was hardcoded in `summarize()`;
  it is now opt-in (default: `standard`).
- **`src/insight.py` — `INSIGHT_FACTCHECK_ENGINE`:** new env var (`both` /
  `perplexity` / `grok`) to restrict which sources are queried in `factcheck()`,
  independently of `INSIGHT_SEARCH_ENGINE`.

### Changed

- **`selection_to_insight.sh` — main menu redesigned:**
  - `[Enter]` is now a no-op (rebouces menu) — no accidental exit.
  - `[m]` exits to the VoxRefiner main menu (explicit, never accidental).
  - Replay buttons are **dynamic**: `[e] Replay search`, `[c] Replay fact-check`,
    `[a] Replay article` appear only after the corresponding action has been
    performed in the session.
  - `[r]` replays the summary; `[g]` re-generates it via TTS.
  - Post-search and post-factcheck sub-menus removed — results return directly
    to the main menu, keeping full session context always accessible.
  - `[d] Save` saves the most contextually relevant audio of the session
    (article > fact-check > search > summary, in priority order).
  - Input prompts for voice/text query now use `[m] Back` instead of
    `[Enter] Cancel` to avoid accidental dismissal.
- **`selection_to_insight.sh` — `[l] Read full`:** calls `selection_to_voice.sh`
  with `VOXREFINER_MENU=1` so Feature 4's own post-playback menu is suppressed
  and control returns directly to Feature 5's main menu.
- **`selection_to_voice.sh` — post-playback menu:** guarded by
  `VOXREFINER_MENU != 1` so it is skipped when called from Feature 5.
- **`record_and_transcribe_local.sh` — mic health check rewritten:**
  pre-launch device check via `pactl` (~10–50ms); `trap 'exit 0' SIGINT` set
  before any device check; `stop_recording` trap set immediately after `rec`
  starts — no window without a Ctrl+C handler. `_try_reset_mic()` removed.
- **`record_and_transcribe_local.sh` — PipeWire restart sleep:** 1s → 2s.

### Fixed

- **`src/tts.py` — number-text collision:** `_merge_split_identifiers` regex
  fixed with `(?<!\w)` lookbehind — word-final letters (e.g. `l` in `avril 2026`)
  no longer merged with adjacent numbers.
- **`selection_to_insight.sh` — settings prompt:** replaced `→` with `▸` (green)
  to match the VoxRefiner main menu prompt style.

---

## [4.0.0] — 2026-04-09

### Added

- **`[5] Selection to Insight`:** new feature — select any text, get an instant
  audio bullet-point summary, then search or fact-check from the same session.
  - **`selection_to_insight.sh`:** orchestration script. Captures selected text
    (primary selection → clipboard fallback), calls `src/insight.py summarize`,
    reads the summary aloud via TTS, then presents a main menu:
    `[l]` read full article · `[p]` search · `[f]` fact-check · `[s]` replay ·
    `[g]` re-read · `[d]` save summary · `[Enter]` quit.
  - **Search flow (`[p]`):** user dictates (Feature 1 component) or types a question;
    sent to the active search engine with the summary as context. Result is read aloud.
    Post-search menu: `[r]` replay · `[d]` save · `[p]` new search · `[f]` fact-check ·
    `[s]` replay summary · `[l]` read full.
  - **Fact-check flow (`[f]`):** user can optionally target a specific claim (voice or
    text); Perplexity (web) and Grok (`web_search + x_search`) run in **parallel**;
    Mistral synthesises a verdict when both sources are present. Post-factcheck menu
    offers `[w]`/`[x]` source-detail buttons — only shown when both sources returned
    results.
  - **`[l] Read full article`:** pre-loads the original text into both clipboards and
    calls `selection_to_voice.sh` seamlessly — no re-selection required.
  - **Adaptive search engine** (`INSIGHT_SEARCH_ENGINE`: `auto` / `perplexity` /
    `grok` / `both`): in `auto` mode, Perplexity is prioritised; Grok (`grok-4-fast`)
    is used as fallback. Fact-check synthesis via Mistral only when both sources are
    present simultaneously.
  - API key warnings at startup; Mistral-only users can still use the summary;
    Perplexity and/or xAI keys unlock search and fact-check.
- **`src/insight.py`:** new Python module.
  - `summarize(text)` — `mistral-small-latest` with `reasoning_effort: high`.
  - `search_perplexity(query, context_summary)` — Perplexity `sonar-pro`.
  - `search_grok(query, context_summary, system)` — xAI SDK with `web_search +
    x_search` server-side tools (requires `grok-4` family; default `grok-4-fast`).
  - `search()` dispatcher — routes to Perplexity, Grok, or both based on
    `INSIGHT_SEARCH_ENGINE` and available API keys.
  - `factcheck(summary, query_hint)` — Perplexity + Grok in parallel via
    `ThreadPoolExecutor`; Mistral synthesis with `INSIGHT_SYNTHESIS_REASONING`
    (`standard` / `high`) when both sources succeed; single-source graceful degradation.
  - CLI subcommands: `summarize`, `search`, `factcheck` (stdin/stdout protocol).
- **`src/save_audio.sh`:** new shared component — `_save_audio_to_downloads()` helper
  used by `voice_translate.sh`, `selection_to_voice.sh`, and `selection_to_insight.sh`.
  Single point of change for save-audio behaviour across all features.
- **`src/tts.py` — `detect_content_type()`:** extracted as a public importable
  function, reused by `src/insight.py`.
- **`src/slug.py` — `--fallback` CLI argument:** allows callers to override the
  default fallback filename at runtime without modifying the module.
- **`vox-refiner-menu.sh` — API Keys submenu:** shows and allows editing of
  `PERPLEXITY_API_KEY` and `XAI_API_KEY` alongside Mistral.
- **`.env.example`:** added `PERPLEXITY_API_KEY`, `XAI_API_KEY`, `INSIGHT_SEARCH_ENGINE`,
  `INSIGHT_SYNTHESIS_REASONING`, and advanced model overrides (`INSIGHT_SUMMARY_MODEL`,
  `INSIGHT_SYNTHESIS_MODEL`, `INSIGHT_PERPLEXITY_MODEL`, `INSIGHT_GROK_MODEL`).
- **`requirements.txt`:** added `xai-sdk==1.11.0` (only `grok-4` family supports
  server-side tools; `grok-4-fast` is the default).
- **Tests:** 34 unit tests in `tests/unit/test_insight.py` covering all public
  functions, adaptive engine routing, graceful degradation, and API key guards.

### Changed

- **`selection_to_insight.sh` — voice query (search & fact-check):** now calls
  `record_and_transcribe_local.sh` directly (reusing Feature 1 as a component) and
  reads the result from the clipboard, instead of a `$(...)` subshell capture.
- **`record_and_transcribe_local.sh` — mic health check rewritten:**
  - Replaced two-stage post-launch WAV-size check (~1s latency) with a fast
    pre-launch device check via `pactl list sources short` (~10–50ms).
  - If no device found: restarts PipeWire once, waits 2s, re-checks with clear
    on-screen message.
  - Ctrl+C trap set in two phases: `trap 'exit 0' SIGINT` before the device check,
    then `trap stop_recording SIGINT` immediately after `rec` starts — no window
    without a trap, ever. Removed `_try_reset_mic()` and its `trap '' SIGINT` dance.
  - `stop_recording` kill timeout reduced from 3s to 1s.
- **`voice_translate.sh` / `selection_to_voice.sh`:** save-audio logic replaced by
  shared `_save_audio_to_downloads` from `src/save_audio.sh`.
- **`launch-vox-refiner.sh`:** added `--selection-insight` flag.
- **`vox-refiner-menu.sh` — Feature 5:** replaced `_coming_soon` placeholder with
  actual call to `./selection_to_insight.sh`.
- **`install.sh` / `vox-refiner-update.sh`:** `selection_to_insight.sh` added to
  `chmod +x` and `repair_exec_bits`.
- **`Readme.md`:** added Selection to Insight documentation and
  `--selection-insight` flag.

### Fixed

- **`src/tts.py` — number-text collision:** `_merge_split_identifiers` regex was
  stripping spaces between word-final letters and following numbers
  (e.g. `"avril 2026"` → `"avril2026"`, `"de 55 ans"` → `"de55 ans"`).
  Fixed with `(?<!\w)` lookbehind — only word-initial single-letter math identifiers
  (e.g. `C 1`) are merged.

---

## [3.9.0] — 2026-04-07

### Added

- **`uninstall.sh`:** new uninstall script. Prompts for explicit confirmation (`yes`),
  offers opt-in removal of personal data (`history.txt`, `context.txt`, `.env`),
  removes the `.desktop` entry if present, then deletes the installation directory.
  Reminds the user to remove keyboard shortcuts manually.
- **`vox-refiner-update.sh` — `sync_env`:** after every `--apply` (including when
  already up to date), new keys present in `.env.example` but absent from `.env` are
  automatically appended, with their documentation comments. Keys already present —
  even with a different value or commented out — are never touched.
- **`src/refine.py` — per-tier history injection:** history is no longer injected
  unconditionally. Short texts (< 80 words) receive no history; medium texts (80–240
  words) receive only the most recent `HISTORY_INJECT_BULLETS_MEDIUM` bullets (default
  40); long texts (> 240 words) receive the full history.
- **`vox-refiner-menu.sh` — `[i]` Bullets injected for medium texts:** new settings
  entry to configure `HISTORY_INJECT_BULLETS_MEDIUM` from the Speak & Refine submenu.
  History status line now shows `on · max 80 · medium → 40`.
- **`tests/unit/test_history_injection.py`:** 9 unit tests covering `_load_history`
  capping and per-tier injection logic (short/medium/long).

### Changed

- **`src/refine.py` — history prompt wording (medium + long tiers):** `<history>` is
  now described as a contextual aid to resolve ambiguity, not a vocabulary list.
  The model is explicitly told to ignore it when the transcription is already clear,
  and never to use it as a reason to add content or reformulate unambiguous text.
- **`src/refine.py` — short tier prompt:** reference to `<history>` removed entirely
  since history is no longer injected for short texts.
- **`HISTORY_MAX_BULLETS` default:** changed from 100 to 80.
- **`.env.example` — `HISTORY_INJECT_BULLETS_MEDIUM=40`:** new variable documented
  with per-tier injection explanation.

### Fixed

- **`record_and_transcribe_local.sh` — empty recording not detected:** a WAV file
  below `MIN_WAV_BYTES` (default 4096, configurable) is now rejected before ffmpeg
  with "Recording too short or empty". Catches Ctrl+C with no audio captured (mic
  silent or very brief press).
- **`record_and_transcribe_local.sh` — silent MP3 after silenceremove:** an MP3
  below `MIN_MP3_BYTES` (default 1000, configurable) is rejected after ffmpeg with
  "Audio contains only silence".
- **`record_and_transcribe_local.sh` — ffmpeg exit code not checked:** ffmpeg failures
  now abort the pipeline immediately instead of passing an invalid file to Voxtral.
- **`record_and_transcribe_local.sh` — Ctrl+C re-entry in `stop_recording`:** `trap ''
  SIGINT` is now set at the start of the handler, preventing the function from being
  called multiple times if the user presses Ctrl+C repeatedly during cleanup.

---

## [3.8.0] — 2026-04-07

### Added

- **`src/tts.py` — two-AI cleaning architecture:** content-type detection and text
  cleaning are now two separate API calls. `mistral-small-latest` identifies the content
  type in a single word (news_article, email, wikipedia, social_media, documentation,
  assistant_response, generic); `devstral-latest` cleans with a focused, type-specific
  prompt. All prompts use `textwrap.dedent("""...""")` for readability.
- **`src/tts.py` — per-type AI cleaning rules (`_CLEAN_RULES`):** each content type
  has dedicated instructions — news articles enforce media name + date → title →
  chapeau → author → body output order; Wikipedia verbalises math formulas; emails
  preserve Objet/Date/sender; social media keeps @handles and reply context;
  documentation and assistant_response rewrite tables and code blocks for speech.
- **`src/tts.py` — table verbalization (`_verbalize_tables`):** programmatic
  conversion of tabular content to accessible spoken prose before the AI call.
  Handles three formats: Markdown pipe tables (`| col |`), tab-separated tables, and
  space-aligned tables (≥ 3 columns, ≥ 3 rows). Each data row becomes a sentence:
  "Column A: value. Column B: value." Dash-only cells (—, –) are skipped. Space-aligned
  detection requires at least 3 rows to limit false positives on prose.
- **`src/tts.py` — math verbalization pipeline:** NFKC normalisation converts Unicode
  math italic letters (𝐸→E); `_collapse_math_lines` collapses Wikipedia one-char-per-line
  formula rendering; `_merge_split_identifiers` fuses `E v a l` → `Eval`; `_expand_math_symbols`
  substitutes 28 symbols (×→"croix", ∈→"appartient à", etc.); `_expand_function_calls`
  expands `f(x)` → "f de x" iteratively; colon verbalization on math lines: ` : ` →
  "fonction de" (type signatures) or "," (other colons on math lines).
- **`src/tts.py` — citation voice fallback:** after 3 failed attempts with the citation
  voice, the system automatically falls back to the main reading voice for the same
  chunk (attempts 4–5), reducing silent failures on quoted passages.
- **`tests/unit/test_tts_tables.py`:** 12 unit tests covering pipe tables, tab tables,
  space-aligned tables, false-positive guards, and `_clean_text` integration.
- **`Readme.md` — Speak & Translate section:** new dedicated section documenting the
  voice translation workflow (record → translate → play in your own voice).
- **`Readme.md` — Selection to Voice section:** new section covering AI preprocessing,
  table reading, math verbalization, quotation isolation, and dual-voice support.
- **`Readme.md` — keyboard shortcut flags:** installation step 5 and the dedicated
  shortcut section now document all four launch flags (`--speak-refine`,
  `--speak-translate`, `--selection-voice`, no flag) with example commands and suggested
  key bindings.

### Changed

- **`.env.example` — `SHOW_RAW_VOXTRAL=true` by default:** new users immediately see
  the raw Voxtral output alongside the refined result, making the AI improvement
  instantly visible. Was `false`.
- **`Readme.md` — "Show raw Voxtral output" section** updated to reflect the new default.

### Fixed

- **`src/tts.py` — `_is_quoted_paragraph`:** detection was too strict (required both
  opening and closing quote on the same line). Now triggers on any paragraph that starts
  with `«`, `"` or `"`.
- **`src/tts.py` — `_expand_math_symbols` — `×` (U+00D7) excluded by accented-letter
  range:** the `_MATH_TOKEN_LINE` regex now excludes U+00C0–U+00D6 and U+00D8–U+00F6
  and U+00F8–U+024F, intentionally keeping U+00D7 (×) and U+00F7 (÷).
- **`src/tts.py` — NFKC applied too late:** `unicodedata.normalize("NFKC", text)` is
  now called at the start of `_ai_clean_text`, before the API call, so Wikipedia math
  italic letters are normalised before any processing.
- **`vox-refiner-menu.sh` — `[q]` conflict in Settings:** the Citation voice shortcut
  was `[q]` which conflicts with the quit key; changed to `[c]`.

---

## [3.7.0] — 2026-04-03

### Added

- **`src/tts.py` — structural chunking (`_make_chunks` rewrite):** chunks are now
  split on paragraph boundaries (`\n\n`) first, preserving editorial structure.
  Consecutive short paragraphs are grouped into a single chunk when they fit within
  `TTS_CHUNK_SIZE`. Oversized paragraphs are sub-split at sentence boundaries.
  The text is never cut mid-paragraph.
- **`src/tts.py` — content-type detection + specialized AI cleaning:** the
  `_AI_CLEAN_SYSTEM` prompt now asks `devstral-latest` to silently detect the
  content type (news_article, email, wikipedia, social_media, generic) and apply
  type-specific cleaning rules in a single call. News articles strip "Lire aussi"
  encarts; Wikipedia strips `[1][2]` references and warning banners; emails strip
  technical headers and automatic footers; social media strips counters and pure
  hashtags.
- **`src/tts.py` — citation voice (`TTS_QUOTE_VOICE_ID`):** if the environment
  variable `TTS_QUOTE_VOICE_ID` is set, paragraphs that are entirely a quotation
  (`"..."`, `«...»`, `"..."`) are emitted as separate chunks using this voice UUID,
  giving citations a distinct voice. When the variable is unset, behaviour is
  unchanged (no extra API calls, no rate-limiting risk).
- **`vox-refiner-menu.sh` — `_voice_picker` function:** the 150-line inline voice
  picker is now a reusable `_voice_picker <ENV_VAR> <TITLE> <ALLOW_DISABLE>` function.
- **`vox-refiner-menu.sh` — Settings `[c]` Citation voice:** new entry in the
  Settings submenu to pick `TTS_QUOTE_VOICE_ID` using the same numbered voice list
  (1–29). Includes a `[d] Disable` option to set the variable to empty and turn off
  the citation voice feature.

### Fixed

- **`selection_to_voice.sh` — chunk playback integrity:** shell-side chunk
  regeneration has been removed in chunked mode so retries stay in Python, preserving
  per-chunk voice assignment (including quote voice) across failures.
- **`selection_to_voice.sh` — fail-fast on missing/failed chunk:** playback now
  stops immediately when a passage is missing or definitively failed, preventing
  silent holes in the final listening experience.
- **`selection_to_voice.sh` — robust FIFO chunk handling:** incoming FIFO lines are
  sanitized, chunk indices are deduplicated, and a short visibility wait is applied
  before declaring a chunk missing, reducing false negatives like "passage OK" then
  "introuvable/vide".
- **`selection_to_voice.sh` — failure recovery UX:** on pipeline error, a dedicated
  mini-menu offers `[r]` relaunch or `[m]` return to main menu instead of abrupt
  fallback behavior.

---

## [3.6.0] — 2026-04-02

### Added

- **`src/tts.py` — AI text cleaning (`_ai_clean_text`):** before chunked TTS,
  the selected text is sent to `mistral-small-latest` with an accessibility-focused
  prompt. Removes web UI noise (share buttons, metadata, nav links, `(Nouvelle
fenêtre)` annotations, agency credits) while preserving all editorial content,
  section headings, and image captions (prefixed "Photo :"). Falls back to
  minimal heuristic cleaning if the AI call fails.
- **`src/tts.py` — cleaned text display:** the AI-cleaned text is printed to the
  terminal with a blue background before TTS generation starts, so the user can
  verify what will be read aloud.
- **`src/tts.py` — `_strip_markdown`:** strips `**bold**`, `*italic*`, `# headings`
  that Mistral sometimes emits in its output before the text reaches the TTS engine.
- **`selection_to_voice.sh` — post-action menu always visible:** the
  `[l] Réécouter / [d] Sauvegarder` menu now runs regardless of `VOXREFINER_MENU`,
  so the user stays on the option-4 screen after playback even when launched from
  the main menu.

### Changed

- **`src/tts.py` — chunked mode (`--chunked`):** complete rewrite of the pipeline.
  - `max_workers` raised to **3** with a 0.5 s stagger between submissions to keep
    2–3 chunks pre-generating without hammering the API.
  - **5 retry attempts** per chunk (up from 3) with escalating delays (2 s, 4 s,
    8 s, 15 s) before a chunk is declared failed.
  - Output file validated after each synthesis call (≥ 1 KB); an empty or truncated
    response is treated as a failure and retried automatically.
- **`selection_to_voice.sh` — inline retry on failed chunks:** when a chunk fails
  (Python sentinel `CHUNK_FAILED:<idx>` or empty file), bash retries it immediately
  on the spot (up to 3 further attempts) before continuing. The listener sees
  `⏳ Passage N en attente — tentative X/3…` in real time; playback of subsequent
  chunks is held until the current one succeeds or is definitively abandoned.
- **`selection_to_voice.sh` — `realpath` in concat list:** ffmpeg concat demuxer
  now receives absolute paths, fixing the incomplete `[l]` replay issue.
- **`_make_chunks`:** paragraph breaks (`\n+`) are now collapsed to a single space
  (previously `.`) so the TTS engine no longer reads an audible "point" between
  paragraphs.
- **`_clean_text`:** simplified to a minimal pre-filter (removes `\ufffc` icons and
  excess whitespace only); full cleaning is now delegated to the AI step.
- **`_AI_CLEAN_SYSTEM` prompt** updated for low-vision accessibility context
  (malvoyants who can see images but find reading tiring).

---

## [3.5.1] — 2026-04-01

### Changed

- **`launch-vox-refiner.sh`** is now committed to the repository and auto-detects
  its install directory (`INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"`). No manual
  copy or path configuration needed after rsync.
- **`launch-vox-refiner.example.sh`** deleted — superseded by the versioned launcher.
- **Launcher flags renamed** for clarity and future scalability:
  - `--direct` → `--speak-refine` (Speak & Refine)
  - `--selection` → `--selection-voice` (Selection to Voice)
  - Added `--speak-translate` (Speak & Translate)
- **`install.sh`:** removed `cp launch-vox-refiner.example.sh` step; added
  `voice_translate.sh` and `selection_to_voice.sh` to `chmod +x`.
- **`.gitignore`:** removed `launch-vox-refiner.sh` entry.
- **DBUS/display fix** in launcher for reliable keyboard shortcut launch
  (`DISPLAY` and `DBUS_SESSION_BUS_ADDRESS` exported if not set).

---

## [3.5.0] — 2026-04-01

### Added

- **`selection_to_voice.sh`:** new standalone script — reads selected text (primary
  selection, fallback clipboard) aloud using a configured preset voice. Launcha­ble
  via keyboard shortcut or from the menu.
  - Post-action mini-menu: `[l]` listen again, `[d]` save to `~/Downloads/VoxRefiner/`,
    `[Enter]` quit.
- **Option `[4]` Selection to Voice:** now active in `vox-refiner-menu.sh`; calls
  `./selection_to_voice.sh` directly.
- **`launch-vox-refiner.example.sh`:** added `--selection` flag (opens
  `selection_to_voice.sh` in a terminal); added `DISPLAY` and
  `DBUS_SESSION_BUS_ADDRESS` exports for reliable keyboard shortcut launch.
- **Settings → `[v]` Reading voice:** voice picker with all 30 Mistral preset voices
  grouped by character (Marie FR / Paul US / Oliver GB / Jane GB), each with a live
  listen preview before confirming. Saves `TTS_SELECTION_VOICE_ID` permanently to
  `.env`.
- **`src/tts.py` voice system:** added `_LANG_VOICE_MAP` (language code → UUID),
  `voice_id` parameter to `synthesize()`, and `TTS_VOICE_ID` / `TTS_LANG` env var
  support. `voice_translate.sh` passes `TTS_LANG` so the target-language preset voice
  is used when no voice sample is available.

### Changed

- **Default reading voice:** `fr_marie_curious` (`e0580ce5`) — French, curious tone.
- **`language` field removed** from TTS API payload (not accepted by Mistral API).
- **Menu description** for `[4]` updated to "read aloud instantly".

---

## [3.4.0] — 2026-04-01

### Added

- **Speak & Translate submenu (`[2]`):** dedicated interactive sub-menu with live status
  header showing voice profile state (recorded date or "not recorded") and use-profile
  on/off toggle.
  - `[Enter]` Start translation (launches `voice_translate.sh`).
  - `[p]` Record a 30-second voice profile (launches `voice_translate.sh --record-profile`).
  - `[u]` Toggle use of voice profile for the session (`TTS_USE_VOICE_PROFILE`).
  - `[m]` Back to main menu.
- **Voice profile pre-recording (`voice_translate.sh --record-profile`):** records 30 s
  at 48 kHz, trims seconds 0–5 and 25–30, exports a 20 s / 128 kbps MP3 to
  `recordings/voice-profile/sample.mp3` — optimal quality for Mistral TTS voice cloning.
  Displays a predefined French text to guide the recording.
- **Voice profile auto-use in `_translate_and_speak()`:** when a profile file exists and
  `TTS_USE_VOICE_PROFILE` is not `false`, it is passed directly to the TTS step instead
  of extracting a sample from the current recording.

### Changed

- **`voice_translate.sh` entry point:** now handles `--record-profile` flag; routes to
  `_record_voice_profile()` and exits, leaving the translate pipeline unchanged for
  normal invocations.

---

## [3.3.0] — 2026-04-01

### Added

- **`src/ui.sh`:** shared ANSI color palette and UI helpers (`_header`, `_success`,
  `_warn`, `_error`, `_info`, `_sep`, etc.) sourced by all shell scripts — single
  source of truth for the visual language.
- **`voice_translate.sh`:** Voice Translate extracted from the menu into a dedicated
  standalone script; can be launched directly via keyboard shortcut like
  `record_and_transcribe_local.sh`.
- **Speak & Refine submenu (`[1]`):** full interactive sub-menu with live status header
  showing current Format, Output lang, Compare, and History settings.
  - `[f]` Change format (plain / prose / structured / markdown) — permanent or session.
  - `[l]` Change output language (13 Voxtral-supported languages + auto) — permanent or session.
  - `[c]` Compare models — runs primary and fallback in parallel, displays 3-way output (raw / primary / fallback).
  - `[h]` Toggle history on/off — permanent (saved to `.env`).
  - `[b]` Set max bullets in history — permanent (saved to `.env`).
  - `[v]` View `history.txt` inline.
  - `[e]` Edit `history.txt` in `$EDITOR` (default: nano).
  - `[m]` Back to menu (replaces `[q]` for clarity).
- **Post-recording mini-menu:** after each transcription, `[r] Retry`, `[n] New`,
  `[v] View history`, `[e] Edit history`, `[Enter] Back` — without relaunching
  recording for view/edit actions.
- **Python stderr indentation:** all user-facing progress messages in `transcribe.py`,
  `refine.py`, and `common.py` now carry 2-space indent to align with bash output.
- **`REFINE_COMPARE_MODELS` session override:** menu-set values now take precedence
  over `.env` defaults for `OUTPUT_PROFILE`, `OUTPUT_LANG`, and `REFINE_COMPARE_MODELS`.

### Changed

- **`vox-refiner-menu.sh`:** colors and UI helpers removed — now sourced from `src/ui.sh`.
  Voice Translate functions removed — now in `voice_translate.sh`.
- **`record_and_transcribe_local.sh`:** colors and UI helpers removed — now sourced from `src/ui.sh`.
- **`[h] History`** removed from the main menu footer; history management moved into
  the Speak & Refine submenu.
- **`[c] Toggle compare mode`** renamed to `[c] Compare models` for clarity.
- **`OUTPUT_PROFILE` default** changed to `prose` (was `plain`) in `refine.py` and `.env.example`.
- **`SHOW_RAW_VOXTRAL` default** changed to `true` (was `false`).

### Fixed

- **`[n] New recording`** in the post-result mini-menu now launches a new recording
  immediately instead of returning to the submenu.
- **`[v]` / `[e]` history actions** no longer re-trigger a recording after use.
- **`REFINE_COMPARE_MODELS`** environment variable was being overridden by `.env` source;
  caller-provided values are now preserved after `source .env`.

---

## [3.2.0] — 2026-03-31

### Added

- **Settings submenu (`[s]`):** replaces the direct `nano .env` shortcut with a
  sub-menu offering `[k] API Keys` and `[e] Edit .env`.
- **API key management (`[k]`):** displays the Mistral key masked (last 4 chars),
  allows editing via hidden input (`read -rs`), and runs a live API test
  automatically after saving.
- **API key validation at startup:** on every launch, VoxRefiner checks the
  `MISTRAL_API_KEY` in `.env`:
  - Key absent → yellow warning box, offer to configure it.
  - Key present but invalid (HTTP 401) → red warning box, offer to update it.
  - Key valid or no network → silent, no delay beyond 5s max timeout.
- **Help menu (`[?]`)** in the main menu: displays `docs/troubleshooting.md`
  directly in the terminal.
- **`docs/troubleshooting.md`:** covers microphone, clipboard, TTS, voice
  cloning, and empty transcription issues.
- **`docs/troubleshooting-update.md`:** covers update-specific issues (blocked
  update, not a git repo, update without effect). Displayed via `[?]` in the
  Update submenu.

### Fixed

- **Update submenu:** `✓ Restart VoxRefiner to use the new version.` now only
  appears when `vox-refiner-update.sh --apply` exits successfully (was always
  shown even on error).

---

## [3.1.0] — 2026-03-31

### Added

- **Voice Translate — save audio (`[d]`):** after a translation, press `[d]` to
  save the generated MP3 to `~/Downloads/VoxRefiner/` (or `~/Téléchargements/VoxRefiner/`
  — detected automatically via `xdg-user-dir`). Filename format:
  `YYYY-MM-DD_HHhMM_<slug>.mp3`.
- **AI-generated filename slugs (`src/slug.py`):** Mistral generates a short
  3–5 word slug from the raw transcription (source language). Model chain:
  `mistral-small-latest` → `mistral-medium-latest` → `"voice-translate"` fallback.
  The user is shown the suggestion and can confirm or type a custom name.
- **`SAVE_SLUG_LANG`** env var: `auto` (slug in source language, default) or
  `en` (always English).
- **Interactive post-action menu in direct STT mode:** when launched via keyboard
  shortcut (not from the menu), the passive hints block is replaced by an
  interactive prompt: `[r] Retry  [n] New recording  [m] Open menu  [Enter] Quit`.

### Changed

- **Model names in STT output headers:** the header now shows both the function
  and the model, e.g. `REFINED TEXT — mistral-small-latest`,
  `FALLBACK MODEL — mistral-medium-latest`, or `RAW TRANSCRIPTION — Voxtral`.
  When refinement fails, the header reads `RAW TRANSCRIPTION — refinement failed`
  instead of the misleading `REFINED TEXT`.
- **Clipboard fix in Voice Translate:** the `✓ Copied to clipboard` message now
  only appears after a successful copy. Both `clipboard` and `primary` X11
  selections are populated (same as STT). The silently-suppressed `2>/dev/null`
  has been removed.

---

## [3.0.0] — 2026-03-29

### Added — Voice Translate

- **Voice Translate mode:** speak in one language, get an audio translation
  in your own voice. Full pipeline: mic → Voxtral STT → Mistral chat
  (clean + adapt for speech + translate) → Voxtral TTS with voice cloning
  → auto-play via mpv.
- **Interactive menu** (`vox-refiner-menu.sh`): launched from the Ubuntu app
  menu, offers Speech-to-Text, Voice Translate, and Settings. The keyboard
  shortcut continues to launch direct Speech-to-Text as before.
- **Language selection sub-menu:** 9 languages (en, fr, de, es, pt, it, nl,
  hi, ar) with `►` marker on the default and Enter to keep it.
- **`src/voice_rewrite.py`:** new module that cleans, restructures for spoken
  delivery (short sentences, spoken connectors), and translates in a single
  Mistral chat call. Prompt optimised for TTS output, not screen reading.
  Tiered reasoning: short texts (<120 words) use fast params, longer texts
  enable `reasoning_effort=high` for complex restructuring.
- **`src/tts.py`:** Voxtral TTS API module with voice cloning support.
  Extracts a 15s voice sample from the original WAV (preserving natural
  pitch/timbre). Falls back to preset voice for short recordings.
- **`src/common.py`:** shared utilities extracted from `refine.py`
  (`call_model`, `SECURITY_BLOCK`, `load_context`, timing helpers).
- **EBU R128 loudness normalization:** TTS output is normalized to -16 LUFS
  (podcast standard) with configurable volume boost on top (`TTS_LOUDNESS`,
  `TTS_VOLUME`).
- **Post-action menus:** `[r] Replay` and `[n] New recording` after Voice
  Translate; `[n] New recording` after Speech-to-Text — stay in the same
  mode without returning to the main menu.
- **Translation failure detection:** shows "TRANSLATION FAILED" header when
  both models fail, instead of silently returning raw text as if translated.
- **New `.env` variables:** `TRANSLATE_TARGET_LANG`, `TTS_MODEL`,
  `TTS_DEFAULT_VOICE_ID`, `TTS_LOUDNESS`, `TTS_VOLUME`, `TTS_PLAYER`,
  `TTS_VOICE_SKIP_SECONDS`, `TTS_VOICE_SAMPLE_DURATION`,
  `VOICE_REWRITE_MODEL`, `VOICE_REWRITE_MODEL_FALLBACK`,
  `VOICE_REWRITE_RETRIES`.
- **`mpv` added to system dependencies** in `install.sh` for TTS playback.
- **Architecture document:** `docs/voice-translate-architecture.md`.

### Changed

- **Recordings directory:** all audio files moved from `/tmp/` and project
  root to `recordings/` with sub-folders per mode (`stt/` for Speech-to-Text,
  `voice-translate/` for Voice Translate). Fixed filenames, overwritten each
  run. No more temp files in `/tmp/`.
- **Launcher** (`launch-vox-refiner.example.sh`): defaults to interactive
  menu for .desktop/app launcher; `--direct` flag launches direct STT for
  keyboard shortcuts. Added `INSTALL_DIR` variable for easy configuration.
- **License:** changed from MIT to AGPL-3.0 to protect against commercial
  exploitation while keeping the project fully open source.
- **LONG tier fallback:** `mistral-large-latest` → `mistral-medium-latest`
  (aligned code, docs, and `.env.example`).

---

## [2.4.4] — 2026-03-28

### Fixed

- **Mic health check false positive:** removed file-size check that triggered
  even when the mic was working (SoX buffers audio data for ~2s before writing
  to disk). The check now only verifies that the `rec` process is still alive.

---

## [2.4.3] — 2026-03-28

### Improved

- **Zero-delay microphone start:** recording starts immediately instead of
  waiting for a blocking pre-check (~2.5s SoX init overhead). The health
  check now runs _after_ launch — if the mic is broken, PipeWire is restarted
  and recording is relaunched automatically.
- **Removed unnecessary delay:** dropped the 200ms sleep after orphan cleanup.

---

## [2.4.2] — 2026-03-28

### Improved

- **Microphone pre-check timeout:** increased from 0.5s to 1s to accommodate
  slow PipeWire initialization.
- **Immediate feedback:** `🎙️ Initializing microphone...` displayed at
  startup to eliminate blank-screen perception.

---

## [2.4.1] — 2026-03-27

### Fixed

- **`reasoning_effort` compatibility:** only `mistral-small-latest` supports
  `reasoning_effort`; the parameter is now stripped from API payloads for all
  other models (whitelist guard). Fixes HTTP 400 when `.env` overrides MEDIUM
  to a non-compatible model.
- **History extraction:** primary history model now receives
  `reasoning_effort=high` for better structured extraction quality.

---

## [2.4.0] — 2026-03-27

### Changed — Per-tier API parameters and MEDIUM model routing

- **MEDIUM tier:** `magistral-small-latest` → `mistral-small-latest` with
  `reasoning_effort=high`. Mistral Small 4's reasoning mode provides similar quality
  to Magistral Small, faster and at lower cost.
- **Per-tier API parameters:** each tier now sends `temperature` and `top_p` to the
  primary model for tighter control over output fidelity:
  - SHORT: `temperature=0.2, top_p=0.85` (conservative corrections)
  - MEDIUM: `temperature=0.3, top_p=0.9, reasoning_effort=high`
  - LONG: `temperature=0.4, top_p=0.9` (fluent prose)
- **Fallback models** use Mistral defaults (no extra parameters) for reliability.
- **Timeout calculation:** `reasoning_effort` triggers an additional ×1.8 timeout
  multiplier to account for thinking time.

---

## [2.3.3] — 2026-03-27

### Fixed

- **`OUTPUT_LANG` validation:** unsupported values (e.g. `fr`, `es`) now print a
  warning to stderr and fall back to the default behaviour (same language as input),
  instead of being silently ignored.
- **`.env.example` clarified:** `OUTPUT_LANG` documentation now explicitly explains
  the three cases (empty/unset, `en`, unsupported) to avoid confusion.

---

## [2.3.2] — 2026-03-27

### Fixed

- **Microphone pre-check always failed:** `rec` cannot write to `/dev/null`
  (it infers format from the file extension); replaced with a temp `.wav` file.
- **Audio reset now uses PipeWire:** replaced `pactl suspend-source/sink`
  (requires `pulseaudio-utils`) with `systemctl --user restart pipewire
pipewire-pulse`, which works on modern Linux without extra packages.

---

## [2.3.1] — 2026-03-27

### Fixed

- **`.directory` added to `.gitignore`:** KDE/Dolphin auto-generated file was
  tracked by git, causing `vox-refiner-update.sh --apply` to fail with
  "Local tracked changes detected" on installations where the file manager
  had modified or deleted it.

---

## [2.3.0] — 2026-03-27

### Added

- **`OUTPUT_LANG=en`:** force English output regardless of spoken input language.
  Useful for developers working in English-only tools (VS Code, Claude Code) while
  speaking French or another language. Technical terms stay in English naturally.
  Set in `.env`; unset or empty preserves the default behaviour (reply in the same
  language as the input).

---

## [2.2.1] — 2026-03-27

### Fixed

- **Microphone not activating via keyboard shortcut:** removed `setsid` from `rec`
  so PulseAudio/PipeWire grants microphone access when launched from a `.desktop`
  shortcut (session isolation was preventing device access).
- **Pre-check microphone access:** added a 0.1 s probe before recording; if the
  device is locked, VoxRefiner automatically resets PulseAudio sources/sinks and
  retries, with a clear error message if recovery fails.
- **Orphan `rec` cleanup:** previous interrupted runs can leave a zombie `rec`
  process holding the device; VoxRefiner now kills orphan `rec.*local_audio`
  processes at startup (pattern is specific to VoxRefiner — visio/webcam apps are
  never affected).

---

## [2.2.0] — 2026-03-20

### Changed — Mistral model routing (deprecation adaptation)

- **SHORT tier:** `devstral-small-latest` → `mistral-small-latest` (primary),
  `mistral-small-latest` → `mistral-medium-latest` (fallback).
  `devstral-small-latest` is deprecated (end of life: 2026-03-31);
  `mistral-small-latest` v4 is a MoE that integrates devstral-small and covers
  both technical and conversational short texts.
- **HISTORY extraction:** `magistral-small-latest` → `mistral-small-latest` (primary),
  `mistral-medium-latest` (fallback). Avoids rate-limit contention with the
  MEDIUM refinement tier (magistral-small).
- `mistral-medium-latest` is now the universal fallback across all tiers.

### Added

- **Model name display:** the terminal always shows which model produced the
  clipboard text — whether primary, fallback, or raw Voxtral (refinement failed).
  Previously only visible in `REFINE_COMPARE_MODELS` mode.
- **OUTPUT_PROFILE aliases:** `dev` (→ `structured`) and `accessibility`
  (→ `prose`) for more intuitive configuration.
- `SHOW_RAW_VOXTRAL` documentation added to README.

### Fixed

- `_THRESHOLD_SHORT` default corrected from `90` to `80` — the value had drifted
  during a refactor.
- History extraction now injects `context.txt` as `<user_context>` so the model
  can identify relevant facts and avoid re-extracting information already in the
  permanent context.
- `docs/model-selection.md` model tables and rationale corrected (primary/fallback
  were inverted in SHORT and MEDIUM tiers).
- `docs/resilience.md` speed factors corrected: `magistral-small-latest` × 3.0,
  `magistral-medium-latest` × 4.5.

### Other

- Logo files renamed to English convention (`subtitle`, `text`).
- LostInTab branding added to README and LICENSE.
- `.markdownlint.json` updated to allow `p`, `a`, `img` HTML elements.

### Tests

- Added `SHOW_RAW_VOXTRAL` unit and integration tests.
- Integration sandbox fake `refine.py` now writes `VOXTRAL_MODELS_FILE` to
  match real model-name display behaviour.

---

## [2.1.2] — 2026-03-16

### Added

- `SHOW_RAW_VOXTRAL` env var: shows the raw Voxtral transcription alongside
  the refined result without running a second model. Produces a 2-way view
  (`[1] Raw Voxtral` / `[2] Result`) at no extra API cost or delay.
  `REFINE_COMPARE_MODELS=true` continues to imply a 3-way view and supersedes
  this option.

---

## [2.1.1] — 2026-03-16

### Fixed

- `.env.example`: model routing was inverted for all three tiers — primary and
  fallback were swapped. Corrected to match the code defaults and the decisions
  documented in `[1.4.0]` (magistral/devstral as primary, mistral as fallback).

### Changed

- `AUDIO_TEMPO` accepted range narrowed from `[0.5, 2.0]` to `[1.0, 2.0]` in
  `record_and_transcribe_local.sh` — values below 1.0 slow down transcription
  without meaningful quality gain.
- `.env.example` `AUDIO_TEMPO` default set to `1.25` (conservative starting point
  for fast speakers or strong accents); the code default remains `1.5` when
  `AUDIO_TEMPO` is not defined in `.env`.
- `.env.example` reorganised into three tiers: **Required** / **Features**
  (`OUTPUT_PROFILE`, `ENABLE_HISTORY`, `AUDIO_TEMPO`) / **Advanced** (model
  routing, history models, modes, resilience) — with clearer comments throughout.
- `Readme.md` routing table corrected to show the actual default models.
- `Readme.md` audio tempo description updated to reflect the `1.25` / `1.5`
  distinction and added guidance for fast speakers.
- `Readme.md` new **Output formatting profiles** section documents all four
  `OUTPUT_PROFILE` values with their use cases.
- `Readme.md` compare mode description updated to mention parallel execution.
- `Readme.md` recording safeguards removed from Advanced options (implementation
  detail not relevant to end-user configuration).

---

## [2.1.0] — 2026-03-15

### Added

- **Parallel compare mode**: primary and fallback models now run simultaneously
  when `REFINE_COMPARE_MODELS=true`. Total wall-clock time is `max(primary, fallback)`
  instead of `primary + fallback`. Compare result is displayed only if primary
  succeeded; if primary fails the compare thread result is discarded.
- **Output formatting profiles** (`OUTPUT_PROFILE` env var): four named profiles
  inject a `FORMAT:` instruction into the system prompt for MEDIUM and LONG tiers.
  Short texts are always plain regardless of the setting.
  - `plain` (default) — no change, current behaviour preserved
  - `prose` — clean paragraphs, no lists; best for general use and screen readers
  - `structured` — paragraphs + bullet points for key ideas; best for developers
  - `technical` — Markdown (headers, paragraphs, bullets); best for docs / AI chat
- `OUTPUT_PROFILE` documented in `.env.example` with descriptions of each profile.

### Changed

- `_PROMPT_FOOTER` now includes a `{format_block}` placeholder rendered at
  runtime from `_FORMAT_INSTRUCTIONS[OUTPUT_PROFILE]`; all three prompt
  templates are updated accordingly.

---

## [2.0.0] — 2026-03-15

### Fixed

- `_get_audio_duration()` now raises `RuntimeError` instead of crashing with
  `ValueError` when ffprobe returns an empty or invalid result.
- `_detect_silences()` now logs a warning and returns an empty list (hard cuts)
  when ffmpeg exits with a non-zero code, instead of silently proceeding.
- ffmpeg chunk-creation in `_split_audio()` now logs a warning when a chunk
  fails to encode.
- `_transcribe_single()` now validates the Voxtral JSON response structure and
  raises `RuntimeError` on a missing or non-string `"text"` field.
- `_call_model()` now wraps nested JSON response access in a try/except and
  raises `RuntimeError` on unexpected API response structure.
- `history.txt` write is now atomic: written to `.tmp` then renamed via
  `Path.replace()`, preventing corruption on interrupted writes.
- `2>/dev/tty` replaced by `2>&3` (saved stderr FD) in all Python subprocess
  calls in the shell script — avoids failure when no controlling terminal is
  available (e.g. test sandboxes, systemd units).
- Two integration tests (`test_recording_mode_cleans_and_rebuilds_audio_artifacts`,
  `test_retry_mode_skips_recording_and_processing`) that were failing due to the
  `/dev/tty` issue are now passing.

### Added

- `CLAUDE.md`: AI collaboration guide covering architecture, technical decisions,
  commit rules, and deployment instructions.
- `record_and_transcribe_local.sh`: cleanup trap (`trap _cleanup EXIT`) removes
  temp files on any exit, preventing orphaned files in `/tmp`.
- `record_and_transcribe_local.sh`: `AUDIO_TEMPO` is now validated at startup
  (must be in `[0.5, 2.0]`); an informative error is shown if out of range.
- `record_and_transcribe_local.sh`: xclip result is now checked; a warning is
  shown if clipboard copy fails instead of silently reporting success.

### Changed

- `_SECURITY_BLOCK` and `_PROMPT_FOOTER` extracted as shared constants in
  `refine.py`; the 3 system prompt templates are now built by concatenation,
  eliminating duplicated security and footer blocks.
- `requirements.txt`: dependencies pinned to exact versions for reproducibility
  (`requests==2.32.5`, `python-dotenv==1.2.2`).

---

## [1.9.3] — 2026-03-15

### Fixed

- History updates no longer wipe existing entries when the model returns only
  newly extracted bullets; existing bullets are preserved automatically.
- History rotation now drops the oldest bullets first by keeping the most
  recent entries when the file exceeds the configured limit.

### Changed

- `HISTORY_MAX_BULLETS` default increased to `100`.
- History extraction now sends only the most recent 80% of existing bullets to
  the model, reserving 20% capacity for new entries on each update.

---

## [1.9.2] — 2026-03-15

### Fixed

- History extraction fallback now handles network/request exceptions (including
  read timeouts) and switches to the fallback model instead of aborting early.

### Changed

- Added a history-only timeout multiplier (`HISTORY_TIMEOUT_MULTIPLIER`, default
  `1.5`) to increase timeout headroom for non-blocking background history updates.
- Documented `HISTORY_TIMEOUT_MULTIPLIER` in `.env.example` and README.

---

## [1.9.1] — 2026-03-15

### Fixed

- `vox-refiner-update.sh --apply` now auto-normalizes local deletions for files
  already removed upstream (legacy rename cleanup), instead of failing with
  "Local tracked changes detected"
- Updater post-update permission repair is now resilient when optional runtime
  files are absent in minimal clones/tests

### Added

- Integration coverage for updater behavior when a tracked file is deleted both
  locally and upstream before `--apply`

### Changed

- README update section now documents that obsolete local deletions are handled
  automatically during `--apply`

---

## [1.9.0] — 2026-03-14

### Added

- `install.sh` one-shot installer:
  - checks required system tools (`python3`, `python3-venv`, `ffmpeg`, `sox`, `xclip`)
  - creates `.venv` and installs Python dependencies
  - creates missing local files from templates (`.env`, `context.txt`, launcher)
  - applies executable permissions (`chmod +x`) on runtime scripts

### Changed

- `record_and_transcribe_local.sh` now uses `./.venv/bin/python` explicitly
  (no manual `source .venv/bin/activate` required for keyboard/desktop launches)
- README installation flow simplified around `./install.sh`
- README requirements clarified: `ffmpeg`, `sox`, and `xclip` are system dependencies
- Renamed desktop entry template file to follow the `*.example.*` convention:
  `vox-refiner.desktop.example` → `vox-refiner.example.desktop`
- Updated `Readme.md` and `CONTRIBUTING.md` references to the new template name
- Removed accidental tracked personal launcher `launch_vox-refiner.sh` from the repository
- Added backward-compatible ignore rule for legacy personal launcher name
  (`launch_vox-refiner.sh`) in `.gitignore`
- Clarified in README why `launch-vox-refiner.example.sh` is kept: shared template
  vs local personal launcher copy
- `launch-vox-refiner.example.sh` now auto-detects a terminal emulator with fallback order:
  `mate-terminal` -> `gnome-terminal` -> `xfce4-terminal` -> `konsole` -> `xterm`
- Added optional `VOXREFINER_TERMINAL` override in launcher template
- README updated to document terminal fallback and override
- `install.sh` now installs `xterm` when using `--install-system-deps` and warns
  when no supported terminal emulator is detected

---

## [1.8.8] — 2026-03-14

### Added

- `vox-refiner.desktop.example` template to simplify desktop menu launcher setup

### Changed

- README keyboard shortcut section formatting fixed and expanded with
  `.desktop` setup steps and validation commands

---

## [1.8.7] — 2026-03-14

### Changed

- Launcher naming harmonized to kebab-case:
  - `launch_vox-refiner.sh` → `launch-vox-refiner.sh`
  - `launch_vox-refiner.example.sh` → `launch-vox-refiner.example.sh`
- Updated launcher references in docs and scripts (`Readme.md`, `CONTRIBUTING.md`,
  `.gitignore`, `vox-refiner-update.sh`)
- Harmonized `launch-vox-refiner.sh` content with the launcher template style
  and naming conventions
- Fixed README keyboard-shortcut section formatting and command block rendering

---

## [1.8.6] — 2026-03-14

### Changed

- Scripts renamed for naming consistency with the `vox-refiner` repo slug:
  - `launch_voxtral.sh` → `launch_vox-refiner.sh`
  - `launch_voxtral.example.sh` → `launch_vox-refiner.example.sh`
  - `voxrefiner-update.sh` → `vox-refiner-update.sh`
- PID temp file renamed `/tmp/voxtral_terminal.pid` → `/tmp/vox-refiner_terminal.pid`
- All references updated in `Readme.md`, `CONTRIBUTING.md`, `record_and_transcribe_local.sh`,
  `vox-refiner-update.sh` (self-reference), and tests

---

## [1.8.5] — 2026-03-14

### Added

- `vox-refiner-update.sh` with:
  - `--check`: fetch remote refs/tags and report update status
  - `--apply`: fast-forward-only update flow with tracked-tree safety checks
- `context.example.txt` template for personal domain vocabulary/context

### Changed

- `context.txt` is now ignored by git and intended as a local file created from
  `context.example.txt`
- End-of-run quick commands now include update commands:
  - `./vox-refiner-update.sh --check`
  - `./vox-refiner-update.sh --apply`
- README installation/update flow now documents the new context and update
  workflow

---

## [1.8.4] — 2026-03-14

### Changed

- `silenceremove` filter: switched to `detection=peak` (faster than default `rms`)
  and added `start_periods=1` to also strip leading silence before the first word

---

## [1.8.3] — 2026-03-14

### Added

- New logo asset set under `Logo/`:
  - `Logo/VoxRefiner_Logo.svg`
  - `Logo/VoxRefiner_subtitile_Logo.svg`
  - `Logo/VoxRefiner_old.svg` (archived previous variant)
- New test coverage for recording script safeguards:
  - `tests/integration/test_record_and_transcribe_script.py`: executes the shell
    script in a sandbox with stubbed `rec`/`ffmpeg`/`xclip`; covers clean-start,
    WAV size rejection, and retry mode
  - `tests/unit/test_record_script_structure.py`: asserts key safety primitives
    are present in the script

### Changed

- README logo reference now uses `Logo/VoxRefiner_subtitile_Logo.svg` and updated
  hero sizing/tagline copy.
- Recording pipeline hardening in `record_and_transcribe_local.sh`:
  - clean audio artifacts (`local_audio.wav`, `local_audio.mp3`) before new recording
  - record to temporary WAV and promote only after validation
  - reject abnormally large WAV files via configurable `MAX_WAV_BYTES`
- `docs/resilience.md`: new _Recording-stage safeguards_ section documenting the
  three shell-level guards

### Fixed

- `tests/unit/test_refine_timing.py`: aligned timeout factor expectations with
  current `_MODEL_SPEED_FACTOR` values (`magistral-medium-latest` ×4.5,
  `magistral-small-latest` ×3.0)

### Removed

- Legacy root logo file `VoxRefiner.svg` removed (replaced by assets in `Logo/`).

---

## [1.8.2] — 2026-03-13

### Changed

- **Project rebrand**: renamed public project name from **Voxtral Paste** to
  **VoxRefiner** to avoid trademark confusion with third-party commercial names
- **Repository and install paths**: updated documentation/examples from
  `voxtral-paste` to `vox-refiner`
- **README branding refresh**: updated title/text references to VoxRefiner and
  added project logo (`VoxRefiner.svg`)
- **README messaging refresh**: updated the product tagline and intro copy to the
  new VoxRefiner branding narrative
- **Supporting docs/examples/tests**: aligned naming references across
  `CONTRIBUTING.md`, `docs/*`, `history.example.txt`, launcher examples, and
  prompt-related test fixtures

### Fixed

- **README markdown lint compatibility**: adjusted logo rendering with scoped
  markdownlint directives while preserving centered display on GitHub

---

## [1.8.1] — 2026-03-11

### Changed

- **Model speed factors recalibrated**: `magistral-small-latest` ×2.5 → ×3.0,
  `magistral-medium-latest` ×3.0 → ×4.5 — observed timeouts on long transcriptions
  (≥ 240 words) confirmed the previous factors were too low for reasoning models
- **System prompts hardened** (SHORT, MEDIUM, LONG):
  - New `SECURITY` block: explicitly identifies the `<transcription>` content as
    untrusted external input and guards against prompt-injection patterns
    ("ignore previous instructions", "you are now…", "pretend that…")
  - `IMPORTANT` block: extended to cover questions addressed to an AI assistant;
    added "The speaker is talking to someone else" clarification to prevent the model
    from treating spoken questions as requests directed at itself
  - Point 1 (SHORT) and Point 3 (MEDIUM/LONG): sources for vocabulary correction now
    explicitly include `<history>` in addition to `<context>`; guard added to forbid
    injecting any name, concept, or technical detail absent from those sources;
    `<history>` inaccuracy warning added
  - Point 5 (MEDIUM/LONG): reinforced with explicit prohibition on completing reasoning
    chains, answering spoken questions, or adding unstated examples/conclusions;
    open-ended output must remain open-ended
  - LONG Point 4: "voice" removed from "speaker's words, voice, and register" —
    the model receives text only, not audio

---

## [1.8.0] — 2026-03-11

### Added

- **Voxtral-only mode** (`ENABLE_REFINE=false`): skip AI refinement entirely — the raw
  Voxtral transcription is copied to clipboard as-is, with no Mistral chat call
- **Side-by-side comparison** (`REFINE_COMPARE_MODELS=true`): after the primary model
  succeeds, the fallback also runs; 3-way display in the terminal (raw Voxtral → primary
  with model name → fallback with model name); primary copied to clipboard immediately,
  behaviour unchanged
- **Retry without re-recording** (`--retry` / `-r` flag): reuses the existing
  `local_audio.mp3` and skips microphone capture and audio processing — useful when
  Voxtral transcription failed or refinement produced an unexpected result
- Both new env vars (`ENABLE_REFINE`, `REFINE_COMPARE_MODELS`) added to `.env.example`
  and `.env`

### Fixed

- Startup error: `cd` and `SCRIPT_NAME=` were concatenated on the same line, causing
  `cd` to fail with a path-not-found error; newline restored
- History update was evaluated against refined-text word count instead of raw Voxtral
  word count — AI models often compress text significantly, incorrectly suppressing
  history updates for MEDIUM/LONG recordings; now uses `raw_transcription` word count
  (consistent with Python model routing)
- Fallback compare result was printed to the terminal _during_ Python execution (before
  the primary was displayed); reordered via temp file so display is always raw → primary
  → fallback

---

## [1.7.0] — 2026-03-11

### Added

- **Per-model speed factors** (`_MODEL_SPEED_FACTOR`): Magistral models (chain-of-thought
  reasoning) receive a 2.5–3× timeout multiplier; `_effective_timeout(base, model)` applies
  the factor at call time
- `docs/resilience.md`: new "Per-model speed factors" and "History extraction timeout" sections

### Changed

- **Audio pipeline**: replaced separate `sox` + `ffmpeg` + `lame` commands (3 tools, 2 temp
  files) with a single `ffmpeg` command — silence removal, tempo shift and MP3 encoding in one
  pass; `sox` and `lame` are no longer required
- **Timeout bases reduced (Option A)** to compensate for the multipliers: range is now 3–80 s
  (was 3–180 s); column renamed "Base timeout" in `docs/resilience.md`
- Default model routing updated in `.env.example`:
  - SHORT: `mistral-small-latest` / `devstral-small-latest`
  - MEDIUM: `mistral-medium-latest` / `magistral-small-latest`
  - LONG: `mistral-medium-latest` / `magistral-medium-latest`
  - HISTORY: `magistral-small-latest` / `mistral-medium-latest`

---

## [1.6.2] — 2026-03-11

### Added

- `background` parameter to `_refine_timing()`: passing `background=True` doubles the
  base timeout — history extraction is a fire-and-forget task that should not constrain
  foreground timeouts

### Fixed

- `_extract_and_update_history()` was using the same foreground timeout as `refine()`;
  it now calls `_refine_timing(wc, background=True)` to get a doubled base timeout,
  preventing spurious timeouts on background history updates

---

## [1.6.1] — 2026-03-11

### Fixed

- `requests.Timeout` (ReadTimeout) was not caught inside `_transcribe_single()`, so it
  escaped the retry loop and propagated as an unhandled exception; it is now caught and
  retried like other transient errors
- First-tier Voxtral timeout raised from 2 s to 3 s — a 177 KB file reliably triggered
  a ReadTimeoutError at 2 s under normal load

---

## [1.6.0] — 2026-03-10

### Added

- **Adaptive timeouts for Voxtral** (`_get_timeout`): 8 file-size tiers from 3 s (< 300 KB)
  to 55 s (< 19.5 MB / ~60 min)
- **Adaptive timeouts for Refine** (`_refine_timing`): 10 word-count tiers
- **Retry loop** for transient HTTP errors (429 / 500 / 502 / 503) in both
  `_transcribe_single()` and `refine()` / `_extract_and_update_history()`
- **Audio splitting** for recordings ≥ 19.5 MB (~60 min): `_split_audio()` detects
  silence boundaries and cuts at ~30 min intervals; each chunk is transcribed independently
- `TRANSCRIBE_REQUEST_RETRIES` and `REFINE_REQUEST_RETRIES` env vars (default: 2 extra
  attempts, i.e. 3 total)
- `docs/resilience.md`: full documentation of timeout / retry / splitting logic

---

## [1.5.0] — 2026-03-08

### Added

- `history.txt`: optional auto-generated context file built from MEDIUM/LONG refinements
  - Enable with `ENABLE_HISTORY=true` in `.env` (opt-in, off by default)
  - Extracts contextual facts (projects, tools, decisions, topics) from refined text
  - Injected into the system prompt for all tiers to improve refinement relevance
  - Configurable: `HISTORY_MAX_BULLETS` (default 60), `HISTORY_EXTRACTION_MODEL` (default `magistral-small-latest`)
  - **Clipboard-first architecture:** extraction runs in the background via `--update-history` CLI flag,
    launched by the shell script **after** the clipboard is populated — never delays the paste operation
  - Added `history.txt` to `.gitignore` (personal file, stays local)
  - Added `history.example.txt` to document the expected format

### Changed

- Default SHORT threshold reduced to **90 words** (was 100) — 100 was too permissive; notes of 90–99 words were routed to MEDIUM unnecessarily
- All 3 system prompts now include an explicit **anti-prompt-injection guard**: the model is instructed to treat `<transcription>` content as raw voice data, never as directives (fixes cases where the AI followed apparent instructions contained in a long transcription)
- Updated `.env.example` and Readme routing table (90 / 240)

---

## [1.4.0] — 2026-03-06

### Added

- `docs/model-selection.md`: rationale and test observations for model and threshold choices per tier (SHORT / MEDIUM / LONG)
- Model comparison testing via OpenWebUI documented for all 3 tiers

### Changed

- Default routing thresholds updated: SHORT < 100 words (was 80), LONG ≥ 240 words (was 200)
- Updated `.env.example` and Readme routing table to reflect new thresholds (100 / 240)

### Decision

- All primary models confirmed after OpenWebUI testing: `devstral-small-latest` (SHORT), `magistral-small-latest` (MEDIUM), `magistral-medium-latest` (LONG)

---

## [1.2.1] — 2026-03-06

### Fixed

- API error body (first 200 chars) now logged to stderr on 429 / 500 / 503, replacing the generic "unavailable, switching..." message — makes rate limiting and server errors easier to diagnose

---

## [1.2.0] — 2026-03-06

### Added

- 3 distinct system prompt templates by tier (SHORT / MEDIUM / LONG)
- XML tags: `<transcription>` wraps user input in the user message; `<context>` wraps domain context in the system prompt
- Prose quality instruction for LONG tier (> 200 words): "well-structured written prose — fluid and precise, while staying true to the speaker's voice and register"
- Deployment section in CONTRIBUTING.md (rsync usage, chmod warning)
- Updating section in README

### Fixed

- Language rule strengthened: `CRITICAL: Never translate. Detect the language of the transcription and reply in that exact same language.`
- Context block moved to end of each prompt (after all instructions) to avoid the "Lost in the Middle" attention drop

### Changed

- Installation guide in README: `git clone` directly to `~/.local/bin/vox-refiner/`, explicit `chmod +x` step
- `.markdownlint.json` added to suppress MD013 / MD024 false positives in CHANGELOG and CONTRIBUTING

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
- `launch-vox-refiner.example.sh` for keyboard shortcut setup (multi-terminal documented)
- `.gitignore` excluding `.env`, `launch-vox-refiner.sh`, audio files

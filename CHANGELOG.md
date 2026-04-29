<!-- @format -->

# Changelog

All notable changes to this project will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [4.14.5] — 2026-04-29

### Changed

- **Display mode buttons reorganized**: 3 primary modes (Résumé, Mots-clés, Citations) + 2 bridge buttons with `↔` arrows (summary_keywords, keywords_quote) + separated "Texte exact" with visual divider (`frontend/components/TtsDisplay.tsx`, `frontend/styles/TtsDisplay.module.scss`).
- **Bridge buttons**: taller/narrower layout with arrow below label, dot-dashed border, `font-size: 1rem` arrows (`frontend/styles/TtsDisplay.module.scss`).
- **Bottom bar alignment**: all primary buttons share `min-height: 2.5rem`; fulltext button keeps auto height (`frontend/styles/TtsDisplay.module.scss`).
- **Keyboard shortcuts extended** to 6 keys (1–6) (`frontend/components/TtsDisplay.tsx`).

### Removed

- Deprecated `"dual"` display mode and its associated SCSS classes (`.dual`, `.dualInner`, `.dualCapsules`, `.dualBody`) (`frontend/components/TtsDisplay.tsx`, `frontend/styles/TtsDisplay.module.scss`).
- Hard-coded number badges on mode buttons (`frontend/styles/TtsDisplay.module.scss`).
- Horizontal dash (`—`) pseudo-element before "Texte exact" button (`frontend/styles/TtsDisplay.module.scss`).

---

## [4.14.4] — 2026-04-29

### Fixed

- **`\n` line breaks now rendered in fulltext mode** (`frontend/styles/TtsDisplay.module.scss`).
  Added `white-space: pre-line` on `.fulltextSmall` so newlines inside the spoken
  text (e.g. multiple bullet points) are displayed as actual line breaks instead
  of being collapsed into a single space.
- **Before/after context hidden in fulltext mode** (`frontend/components/TtsDisplay.tsx`).
  The two `.ctx` divs (previous/next chunk) are no longer rendered when
  `displayMode === "fulltext"`, since the fulltext view already shows the entire
  current chunk content and the extra context is redundant.

### Changed

- **Topic badge moved from status bar to standalone bar** (`frontend/components/TtsDisplay.tsx`,
  `frontend/styles/TtsDisplay.module.scss`).
  The topic label is no longer displayed inline in the `.status` header. It now
  lives in a dedicated `.topicBar` row between the status bar and the stage,
  symmetrical to `.progressBar` below the stage — same font-size, padding, and
  `$highlight-bg` background, with `$accent` text colour and a `border-bottom`
  separator.

---

## [4.14.3] — 2026-04-29

### Fixed

- **Proper names kept whole in display-meta keywords** (`src/display_meta.py`).
  The system prompt now explicitly instructs Mistral to keep proper names
  (people, organisations, places) intact as multi-word entries instead of
  splitting them across keywords. Examples: "Sadio Camara", "Abdelkarim B.",
  "Africa Corps", "FLA".
- **Keywords separator changed from middle dot `·` to em-dash `—`**
  (`frontend/components/TtsDisplay.tsx`).
  Both the keywords display mode and the dual-mode capsule now use an em-dash
  separator (`—`) instead of the middle dot (`·`), for better visual
  separation and consistency with the `quote_short` display.

---

## [4.14.2] — 2026-04-28

### Fixed

- **Dual mode keywords now inside the spoken-text bubble** (`frontend/components/TtsDisplay.tsx`,
  `frontend/styles/TtsDisplay.module.scss`).
  Previously the dual mode rendered large keywords inside `.current` + a separate `.dualSub` line
  below the bubble. The keywords are now shown inside a capsule badge (dark pill, white text,
  rounded corners) at the top of `.current`, with the summary/quote text below it — both inside
  a single visual bubble. The standalone `.dualSub` element is removed.
- **Progress bar moved below the stage** (`frontend/components/TtsDisplay.tsx`,
  `frontend/styles/TtsDisplay.module.scss`).
  The chunk-position indicator was cramped in the header next to the topic badge. It now lives
  in a dedicated `.progressBar` row between `.stage` and the bottom bar, with a `$highlight-bg`
  background for visual separation.
- **`.ctx` paragraphs no longer clipped by `max-height`** (`frontend/styles/TtsDisplay.module.scss`).
  Replaced brittle `max-height: 12vh` with CSS `line-clamp: 2` (with WebKit prefix), which
  consistently truncates at exactly 2 lines regardless of container geometry.

### Changed

- **Static export regenerated** (`frontend/out/`).

---

## [4.14.1] — 2026-04-28

### Fixed

- **Bubble no longer crushed by fixed viewport height** (`frontend/styles/TtsDisplay.module.scss`).
  The `.app` root container was locked at `height: 100vh`, which compressed the `.stage` (including
  the current-text bubble) when the content exceeded the viewport. Changed to `min-height: 100vh` so
  the bubble's natural height is respected and the page scrolls instead of crushing.
- **`overflow: hidden` removed from `html, body`** (`frontend/app/globals.scss`).
  The global rule was blocking vertical scrolling on the display page. Removed so any overflow
  from the bubble (or other content) scrolls naturally rather than being clipped.

### Added

- **Bubble auto-centered on first chunk via `scrollIntoView`** (`frontend/components/TtsDisplay.tsx`).
  A new `useEffect` fires once when `state.current >= 0` (first chunk received) and calls
  `bubbleRef.current.scrollIntoView({ block: "center" })`. This ensures the spoken text is
  visually centered when the display opens, while the user remains free to scroll to the header,
  footer, or player controls manually.

---

## [4.14.0] — 2026-04-28

### Added

- **5 display modes (was 3): `summary` / `keywords` / `quote` / `dual` / `fulltext`** (`frontend/components/TtsDisplay.tsx`, `frontend/styles/TtsDisplay.module.scss`).
  - `summary` — extractive 1-sentence summary that REUSES the spoken vocabulary.
  - `keywords` — 3–5 single words, very large.
  - `quote` — a verbatim 8–15-word substring of the chunk being spoken (perfect spoken/display alignment).
  - `dual` — keywords (large) + a secondary line with the summary/quote (small).
  - `fulltext` — exact spoken chunk text, in a smaller font for readability.
- **Keyboard shortcuts `1`–`5` to toggle modes live** during playback (ignored when typing in inputs).
- **Mode selector buttons** in the top-right corner with key hint + label, click-to-switch, active state highlighted.
- **`quote_short` field added to `display_meta` output** (`src/display_meta.py`).
- **Opt-in debug log: `src/debug_log.py` + `VOX_DEBUG_LOG` env var.**
  - Set `VOX_DEBUG_LOG=1` for the default location (`recordings/debug/last-session.json`) or any custom path.
  - Captures cleaning/chunking, audio chunk generation, display_meta raw+parsed payload, alignment, and SSE chunk events.

### Fixed

- **Silent failure of `_web_send_display_meta`** (`src/web_display.sh`, `src/display_meta.py`).
  Diagnostics are no longer swallowed; failures are traceable (especially with `VOX_DEBUG_LOG=1`).
- **`display_meta` JSON truncation from Mistral** (`src/display_meta.py`).
  Increased token cap (`DISPLAY_META_MAX_TOKENS`), enforced JSON output (`response_format={"type": "json_object"}`),
  retries on transient HTTP errors, and finish reason logging.

### Changed

- **`displayMode` is now stateful in the frontend** — it can be changed live via keyboard/buttons; URL param remains the initial value.
- Static export artifacts regenerated (`frontend/out/`).

---

## [4.13.0] — 2026-04-27

### Added

- **3-mode browser display: `fulltext` / `summary` / `keywords` (`frontend/components/TtsDisplay.tsx`, `frontend/styles/TtsDisplay.module.scss`).**
  A new `?displayMode=` URL parameter selects the reading mode (default: `summary`).
  - `fulltext` — shows the exact text being spoken.
  - `summary` — shows a 1-sentence AI summary for the current section.
  - `keywords` — shows 3–5 key nouns in very large font (`clamp(3rem, 8vw, 8rem)`),
    ideal for low-vision / peripheral reading.
    A topic label appears above the current chunk in `summary` and `keywords` modes,
    and a compact `displayMode` badge is added to the status bar.
- **Decoupled audio / display layers with character-position alignment.**
  The display layer is independent of Voxtral's audio chunking — Mistral Small
  produces its own (typically shorter) display chunks optimised for visual
  readability. A character-position alignment in the cleaned text bridges the
  two layers, so a single audio chunk can cover several display chunks (long
  prose) and several short audio chunks (citations) can fall inside one display
  chunk.
- **`src/display_meta.py` — Mistral Small display metadata generator.**
  Receives the **cleaned text** (not the raw selection) and produces a list of
  `display_chunks` each carrying:
  - `anchor` — verbatim ~30-char prefix from the cleaned text (used by the bash
    flow to resolve the chunk's character range via string search);
  - `topic`, `keywords`, `summary_short` — content for the three frontend modes.
    Single `mistral-small-latest` call per session. Skipped entirely in `fulltext`
    mode. Configurable via `DISPLAY_META_MODEL` and `DISPLAY_META_TIMEOUT`.
- **No redundant AI cleaning calls — cleaned text reused across branches.**
  `src/tts.py --chunked` now writes the post-cleaning text to `TTS_CLEANED_TEXT_OUT`
  (atomic tmp+rename) so the bash flow can feed `display_meta` exactly the same
  text Voxtral reads, without re-running `_ai_clean_text()`. For mode 5 (Voice),
  the bash watches the sidecar (200 ms polling) and launches `display_meta` in
  background as soon as cleaning finishes — Voxtral synthesis runs in parallel.
  For mode 6 (Insight), the summary is already AI-cleaned so it goes straight
  to `display_meta`.
- **`chunk_NNN.json` sidecars with character ranges.**
  `tts.py --chunked` now writes a JSON sidecar next to each `chunk_NNN.txt` /
  `.mp3` containing `{char_start, char_end}` of the chunk inside the cleaned
  text. The bash flow uses these ranges (plus `ffprobe`-measured audio
  durations) when emitting SSE `chunk` events, so the frontend can interpolate
  the speaker's character position in real time.
- **`display_chunks` SSE event type with anchor resolution.**
  New event broadcast and replayed on late connects (stored alongside `init`
  and the last `chunk`). The bash helper `_web_send_display_meta` runs
  `display_meta.py` in background, resolves each anchor to a character range
  in the cleaned text, closes inter-chunk gaps, and broadcasts the resolved
  list. The previous `chunk_meta` event is removed.
- **Time-based progression in the frontend (`requestAnimationFrame` loop).**
  When an audio chunk K arrives, the frontend records its `receivedAt` timestamp,
  `duration_s`, and char range. A `requestAnimationFrame` loop interpolates the
  estimated character position inside K and looks up the matching display chunk.
  Switching display chunks within a single audio chunk is therefore smooth and
  proportional to elapsed playback time.
- **`--display-mode` argument for `src/web_display.py`.**
  The Python server now receives the display mode at startup and appends
  `?displayMode=<mode>` to the URL it opens in the browser. Controlled via
  `VOX_WEB_DISPLAY_MODE` env var (default: `summary`) or `--display-mode` CLI flag.
- **`?mock&displayMode=keywords` dev preview.**
  The mock fixture now includes resolved `displayChunks` with character ranges
  and respects `?displayMode=` so all three modes can be tested without a Python
  backend.

### Fixed

- **Static export now works with query strings (`src/web_display.py`).**
  The `do_GET` handler stripped the path before query params, so opening the
  browser at `/?displayMode=summary` was returning 404. The query string is now
  removed before resolving the file path.

---

## [4.12.1] — 2026-04-27

### Fixed

- **`TtsDisplay` — rem units throughout (`styles/TtsDisplay.module.scss`).**
  All `px` values converted to `rem` (font sizes, padding, margin, gap, border,
  border-radius) and `em` for `letter-spacing`. `clamp(28px, 5vw, 64px)` →
  `clamp(1.75rem, 5vw, 4rem)`. Respects the user's browser font-size preference
  for accessibility.
- **`TtsDisplay` — `afterText` visible in voice mode (`components/TtsDisplay.tsx`).**
  The next-chunk slot was always empty in `voice` mode because only `insight` mode
  checked `fullChunks`. Now also reads `chunks[current + 1]`, so the after-context
  renders whenever the chunk is available (real playback or mock).

### Added

- **`?mock` URL parameter for dev preview (`components/TtsDisplay.tsx`).**
  Opening `http://localhost:3000?mock` injects fixture data (5 voice chunks, chunk 2
  active) so the full layout — before / current / after — is visible without a running
  Python backend. Ignored in production (EventSource used as normal).

---

## [4.12.0] — 2026-04-27

### Changed

- **Display page migrated to Next.js + SCSS (static export).**
  The embedded `_HTML_PAGE` Python string has been replaced by a proper Next.js
  project (`frontend/`) compiled to a static export (`frontend/out/`). The Python
  server now serves those static files instead of an inline HTML string.
  End-users need no Node.js at runtime — the built `out/` directory is committed to
  git and served directly by `src/web_display.py`.

### Added

- **`frontend/` — Next.js 15 project (App Router, TypeScript, SCSS).**
  - `components/TtsDisplay.tsx` — React client component replacing the vanilla JS
    display logic; uses `useEffect` + `useState` + `EventSource('/events')`.
  - `styles/_variables.scss` — SCSS design tokens (colors).
  - `styles/TtsDisplay.module.scss` — component styles using SCSS modules and
    `@use 'variables'`.
  - `app/globals.scss` — global reset and body styles.
  - `next.config.js` — `output: 'export'`, `sassOptions.includePaths` configured.
  - `pnpm` as package manager (`packageManager: pnpm@10.4.0`).
- **`src/web_display.py` — `_serve_file()` static file handler.**
  Replaces the single `_send_html(_HTML_PAGE)` route with a general static file
  handler that serves any path from `frontend/out/`, with path traversal protection.

---

## [4.11.2] — 2026-04-26

### Fixed

- **`VOX_WEB_BROWSER` browser family aliases (`src/web_display.py`).**
  The variable now accepts short family names (`brave`, `chromium`, `chrome`, `edge`)
  in addition to exact binary names and Flatpak app-ids. `brave` resolves to
  `brave-browser` → `brave` → `com.brave.Browser` (first installed wins), solving
  the mismatch between the apt binary name (`brave-browser`) and the intuitive alias.

---

## [4.11.1] — 2026-04-25

### Changed

- **Browser support limited to Chromium-based browsers only (`src/web_display.py`).**
  Firefox, LibreWolf, qutebrowser, falkon, epiphany, midori, and xdg-open have been
  removed. Only browsers that support true `--app=` mode are kept: chromium, brave,
  google-chrome, and microsoft-edge (native deb/rpm + Flatpak variants for each).
  This guarantees a consistent app-window experience (no tab bar, no URL bar, precise
  window size and position) across all installations.
  If none of the supported browsers is available, a clear install hint is printed.

### Fixed

- **Flatpak browser support (`src/web_display.py`).**
  Auto-detection now includes Flatpak variants for all four families
  (`org.chromium.Chromium`, `com.brave.Browser`, `com.google.Chrome`,
  `com.microsoft.Edge`), interleaved after their native counterpart so Flatpak
  Chromium is preferred over google-chrome deb.
  Profile directories for Flatpak browsers are placed in
  `~/.var/app/<app-id>/data/vox-refiner` — always writable from the sandbox
  regardless of manifest `--filesystem` grants.
  `VOX_WEB_BROWSER` now also accepts a Flatpak app-id directly
  (e.g. `VOX_WEB_BROWSER=org.chromium.Chromium`).
  Flatpak availability is checked via `os.path.isdir` on standard install paths
  (instantaneous, no subprocess).

---

## [4.11.0] — 2026-04-25

### Added

- **Synchronized browser display for TTS playback (Phase 1).**
  New opt-in feature that opens a parallel browser window showing the spoken text
  in real time, synchronized with audio chunks. Phase 1 displays the exact
  transcribed text with the current chunk shown big and centered. Activated via
  `VOX_WEB_DISPLAY=1` in `.env`.
- **`src/web_display.py` (NEW) — local HTTP+SSE server.**
  Stdlib-only `ThreadingHTTPServer` that serves an embedded HTML page with
  `EventSource`-based SSE updates. Endpoints: `GET /` (HTML), `GET /events`
  (SSE stream with replay-on-connect), `POST /push` (broadcast event),
  `POST /shutdown` (graceful exit). Picks a free port automatically and writes
  it to `--port-file` for the bash caller. Runs as `python -m src.web_display`.
- **Browser detection with per-family isolated profiles.**
  All browsers launch with a dedicated, persistent cache profile so the user's
  main browsing session (tabs, extensions, cookies, history) is **never**
  touched. Each browser family gets its own profile dir under
  `~/.cache/vox-refiner/<family>-profile`.
  Priority order:
  1. **Chromium-based** in `--app=` mode with `--user-data-dir`:
     `chromium-browser` (chromium-profile), `chromium` (chromium-profile),
     `brave-browser` (brave-profile), `brave` (brave-profile),
     `google-chrome` (chrome-profile). Window size & position controlled via
     `--window-size`/`--window-position`.
  2. **Firefox family** with `--no-remote --profile <path> --new-window`:
     `firefox` (firefox-profile), `librewolf` (librewolf-profile). The
     `--no-remote` flag prevents connecting to an existing Firefox instance
     so a fully isolated process is spawned. No native --app mode → window
     has its usual chrome (URL bar, tabs); CLI window-size unsupported.
  3. **Lightweight fallbacks**: `qutebrowser`, `falkon` (`--geometry=WxH+X+Y`),
     `epiphany --new-window`, `midori`.
  4. **Last resort**: `xdg-open` (system default browser).
     Override via `VOX_WEB_BROWSER` env var. Window size: `VOX_WEB_SIZE="1100x800"`,
     position: `VOX_WEB_POS="100x100"` (chromium-only).
- **Snap-confined browsers auto-skipped.**
  Snap-installed `chromium`, `brave`, `midori`, etc. enforce an AppArmor
  policy that rejects custom `--user-data-dir` paths (`SingletonLock:
Permission denied`). The auto-detection chain skips them with an `ℹ`
  notice and falls through to a non-snap binary (e.g. `google-chrome` from
  `/opt/google/chrome`, or `firefox`). When a snap binary is forced via
  `VOX_WEB_BROWSER`, a warning is printed before attempting the launch.
- **Crash-aware fallback chain.**
  Each candidate browser is checked 400 ms after `Popen`; if it has exited,
  its stderr is captured and the next candidate is tried. Previously a single
  failed launcher resulted in no browser opening.
- **Browser launcher diagnostics.**
  `_web_start` in `src/web_display.sh` now routes Python stderr to the saved
  terminal FD 3 (set by flow scripts via `exec 3>&2`). Browser launch
  diagnostics, snap skips, and crash messages are visible in the terminal
  when `VOX_WEB_DISPLAY=1`.
- **`src/web_display.sh` (NEW) — bash helper.**
  Sourced by flow scripts. Exposes `_web_start`, `_web_push_init`,
  `_web_send_chunk`, `_web_push_done`, `_web_push_error`, `_web_stop`. All
  helpers no-op when `VOX_WEB_DISPLAY != 1`. Backgrounded `curl` POSTs keep the
  audio playback path latency-free. Reads `chunk_NNN.txt` files written by
  `tts.py`'s chunked mode.
- **`selection_to_voice.sh` integration.** Boots web display before TTS,
  pushes a `chunk` event before each `_play_audio` call, fires `done` (or
  `error`) at end. EXIT trap kills the server cleanly.
- **`src/text_flows.sh _tts_speak()` integration.** Pushes `chunk` events
  during the playback loop using `declare -F` guard so non-display callers are
  unaffected. `_show_and_speak` re-inits the display with each new content
  block (search result, fact-check result, web/X details).
- **`selection_to_insight.sh` integration.** Opens the web display
  immediately after the summary is generated and pushes `init` with the full
  summary text — the user sees the full summary before audio starts (read-ahead
  UX). Chunks are pushed as audio plays. EXIT trap kills the server.

### Notes

- **Phase 2** (later): keyword extraction mode + giant-font display for
  visually impaired users. Forward-compatible: protocol already supports adding
  `keywords` field to `chunk` payloads.
- **Phase 3** (later): flows [7] Selection to Search, [8] Fact-check,
  [9] Screen to Text.
- **Single-file mode** (texts under `TTS_CHUNK_THRESHOLD=800` chars in
  `selection_to_voice.sh`): no web display in Phase 1, since there are no
  chunks to sync. Long texts (chunked mode) get the full feature.

---

## [4.10.7] — 2026-04-25

### Added

- **`vox-refiner-menu.sh` — Provider filter in voice picker dev mode.**
  In hidden comparison mode (`h`), a new `[p]` key opens a provider sub-menu
  listing all 10 providers: Mistral, Gradium, Google, ElevenLabs, OpenAI,
  Amazon Neural, Amazon Standard, Deepgram, Grok. Selecting one filters the
  voice list to that provider only. The active filter is shown in the header
  (`Provider: Grok (xAI)`). Resetting to `h=off` clears the filter.
  New `_vid_matches_pf()` helper handles voice-ID-prefix matching for
  comparison sub-providers. No changes outside `vox-refiner-menu.sh`.

---

## [4.10.6] — 2026-04-25

### Added

- **`vox-refiner-menu.sh` — TTS latency display in voice picker dev mode.**
  When hidden comparison voices are active (`h` toggle), the "Last preview" line
  shows the synthesis time in milliseconds: `Last preview: grok-ara-fr  ⏱ 1234 ms`.
  Timing is measured in Bash with `date +%s%3N` around the Python subprocess call
  and stored in `_last_tts_ms` — displayed on every menu redraw until the next preview.
  No changes to `tts.py`.

---

## [4.10.5] — 2026-04-25

### Added

- **`src/voice_catalog.json` — xAI Grok TTS voices (C1550–C1569).**
  20 voices in 4 groups: 🇫🇷 French (C1550), 🇺🇸 English (C1555),
  🇪🇸 Spanish Spain (C1560), 🇲🇽 Spanish Mexico (C1565).
  Each group contains all 5 Grok voices: Eve, Ara, Rex, Sal, Leo.
  Voice IDs use the format `grok-<voice>-<language>` (e.g. `grok-ara-fr`, `grok-rex-es-ES`).
  Require `XAI_API_KEY`. Marked `"temporary": true` (comparison/hidden).
- **`src/tts.py` — Grok TTS routing via xAI direct API.**
  Added `_synthesize_grok_tts()`: splits `grok-<voice>-<lang>` on `-` (maxsplit=2)
  to extract voice and language, calls `POST https://api.x.ai/v1/tts` directly.
  Response is raw MP3 bytes — no intermediate URL download.
  Uses `XAI_API_KEY` (already present in project for Grok search/fact-check).
- **`vox-refiner-menu.sh` — API key guard extended to `grok-*` voices.**
  `grok-*` comparison voices require `XAI_API_KEY` (separate from Eden AI voices).
  Preview flow override added for `grok-*` → `XAI_API_KEY`.

---

## [4.10.4] — 2026-04-25

### Added

- **`src/voice_catalog.json` — Deepgram Aura 2 voices via Eden AI (C1500–C1510).**
  11 voices in 3 groups: 🇫🇷 French (C1500, Agathe/Hector),
  🇺🇸 English US (C1502, Thalia/Andromeda/Helena/Apollo/Arcas/Aries),
  🇪🇸 Spanish (C1508, Celeste/Estrella/Nestor).
  Voice IDs use the format `deepgram-aura-2-<name>-<lang>` (e.g. `deepgram-aura-2-thalia-en`).
  Model: `audio/tts/deepgram/aura-2` via Eden AI universal endpoint. Require `EDENAI_API_KEY`.
  Marked `"temporary": true` (comparison/hidden).
- **`src/tts.py` — Deepgram Aura 2 routing via Eden AI.**
  Added `_synthesize_deepgram_aura2()`: strips `deepgram-` prefix to recover the full
  Deepgram model name used as the `voice` parameter (e.g. `aura-2-thalia-en`).
  Routing inserted before Amazon, before Gradium.
- **`vox-refiner-menu.sh` — API key guard extended to `deepgram-*` voices.**
  `deepgram-*` comparison voices now require `EDENAI_API_KEY`.

---

## [4.10.3] — 2026-04-25

### Added

- **`src/voice_catalog.json` — Amazon Neural (Polly) voices via Eden AI (C1400–C1427).**
  28 voices in 6 groups: 🇫🇷 French France (C1400, Lea/Remi), 🇨🇦 French Canada (C1402, Gabrielle/Liam),
  🇧🇪 French Belgique (C1404, Isabelle), 🇺🇸 English US (C1405, 13 voices),
  🇬🇧 English British (C1418, Amy/Emma/Brian/Arthur), 🌍 English Variants (C1422,
  Olivia/Niamh/Aria/Jasmine/Ayanda/Kajal). Model: `audio/tts/amazon/neural` via Eden AI.
  Voice IDs use the format `amazon-<PollyName>` (e.g. `amazon-Lea`).
  Require `EDENAI_API_KEY`. Marked `"temporary": true` (comparison/hidden).
- **`src/tts.py` — Amazon Neural routing via Eden AI.**
  Added `_synthesize_amazon_neural()`: strips `amazon-` prefix to get the Polly voice name,
  calls Eden AI with model `audio/tts/amazon/neural`, downloads audio from
  `output.audio_resource_url`. Routing inserted after OpenAI, before Gradium.
- **`vox-refiner-menu.sh` — API key guard extended to `amazon-*` voices.**
  `amazon-*` comparison voices now require `EDENAI_API_KEY` (same as `eleven-*` and `openai-*`).
- **`src/voice_catalog.json` — Amazon Standard (Polly) voices via Eden AI (C1450–C1469).**
  20 voices in 5 groups: 🇫🇷 French France (C1450, Celine/Lea/Mathieu), 🇨🇦 French Canada (C1453, Chantal),
  🇺🇸 English US (C1454, 8 voices), 🇬🇧 English British (C1462, Amy/Brian/Emma/Geraint),
  🌍 English Variants (C1466, Nicole/Russell/AU + Aditi/Raveena/IN).
  Voice IDs use the format `amazon-std-<PollyName>` (e.g. `amazon-std-Celine`).
  Model: `audio/tts/amazon/standard` via Eden AI. Require `EDENAI_API_KEY`.
- **`src/tts.py` — Amazon Standard routing and shared `_synthesize_amazon_polly()` helper.**
  Refactored both Amazon variants to delegate to `_synthesize_amazon_polly(model=...)`.
  Added `_synthesize_amazon_standard()` wrapper. Routing: `amazon-std-*` is checked before
  `amazon-*` to prevent prefix collision.

---

## [4.10.2] — 2026-04-24

### Added

- **`src/voice_catalog.json` — OpenAI TTS voices via Eden AI (C1300–C1325).**
  13 voices (Alloy, Ash, Ballad, Cedar, Coral, Echo, Fable, Marin, Nova, Onyx, Sage, Shimmer, Verse)
  in two groups: 🇫🇷 French (C1300–C1312) and 🇬🇧 English (C1313–C1325).
  Model: `gpt-4o-mini-tts` via Eden AI universal endpoint. Require `EDENAI_API_KEY`.
  Marked `"temporary": true` (comparison/hidden).
- **`src/tts.py` — OpenAI TTS routing via Eden AI.**
  Added `_synthesize_openai_tts()`: strips `openai-` prefix to get the voice name,
  calls Eden AI with model `audio/tts/openai/gpt-4o-mini-tts`, downloads audio
  from `output.audio_resource_url`. Routing inserted before Gradium check.
- **`vox-refiner-menu.sh` — API key guard extended to `openai-*` voices.**
  `openai-*` comparison voices now require `EDENAI_API_KEY` (same as `eleven-*`).

---

## [4.10.1] — 2026-04-25

### Added

- **`src/voice_catalog.json` — ElevenLabs voices via Eden AI (C1000–C1250), 3 models.**
  Same 5 language groups (French Parisien / French Canadien / English / English American /
  English British) duplicated across 3 ElevenLabs models for comparison:
  - **Multilingual V2** (C1000–C1050): `eleven_multilingual_v2`
  - **Eleven V3** (C1100–C1150): `eleven_v3`
  - **Flash V2.5** (C1200–C1250): `eleven_flash_v2_5`
    Voice IDs use the format `eleven-<model_key>-<elevenlabs_voice_id>`
    (e.g. `eleven-v3-6FXyooAOTqUK8m2HWm32`). All groups require `EDENAI_API_KEY`,
    marked `"temporary": true` (comparison/hidden).
- **`src/tts.py` — ElevenLabs routing via Eden AI.**
  Added `_ELEVEN_MODELS` dict and `_synthesize_elevenlabs_eden()`: parses model key
  (`v2`/`v3`/`flash`) from the voice ID prefix, calls Eden AI universal endpoint
  (`POST https://api.edenai.run/v3/universal-ai/`), extracts `output.audio_resource_url`
  from the response, and downloads the MP3 in a second request. Routing is inserted
  before the Gradium check: voice IDs starting with `eleven-` are dispatched here.
- **`vox-refiner-menu.sh` — per-voice API key check for comparison voices.**
  Replaced hardcoded `GOOGLE_TTS_API_KEY` guard with voice-ID-aware checks:
  `google-*` voices require `GOOGLE_TTS_API_KEY`; `eleven-*` voices require
  `EDENAI_API_KEY`. Added override of `_provider_api_env` for `eleven-*` voices
  in the preview/select flow so the correct key is checked instead of the comparison
  provider's default (`GOOGLE_TTS_API_KEY`).

---

## [4.10.0] — 2026-04-22

### Added

- **`src/voice_catalog.json` — Google TTS locale groups (30 voices each).**
  Added complete groups for 🇨🇦 Français Canadien, 🇪🇸 Español España,
  🇲🇽 Español México, 🇺🇸 English US, 🇬🇧 English UK, and 🇦🇺 English Australia,
  all using Gemini 3.1 Flash TTS. These groups are intended for voice comparison
  and are hidden from the language picker by default.
- **`src/voice_catalog.json` — Google TTS base group relabelled to Esperanto.**
  The base Google TTS group (C1–C30) now uses `sample_lang: "eo"` and reads
  Esperanto preview text, serving as a language-neutral comparison baseline.
- **`src/tts.py` — Google TTS multi-locale parsing.**
  Extended `_synthesize_google_tts()` to parse language suffixes in voice slugs
  (e.g., `google-kore-fr-ca`) and pass the correct `language_code` (fr-CA,
  es-ES, es-MX, en-US, en-GB, en-AU) to the Gemini TTS API.
- **Esperanto added to all language dictionaries.**
  `"eo": "Esperanto"` added to `src/insight.py`, `src/refine.py`,
  `src/translate.py`, `src/voice_rewrite.py`, and `vox-refiner-menu.sh`.
- **`vox-refiner-menu.sh` — Esperanto preview text.**
  Added `_vtext_eo` and wired `eo|eo-*` in the voice sample selector.

### Changed

- **Voice picker language menu — test languages hidden by default.**
  Languages beyond the five public ones (French, English, German, Spanish,
  Portuguese) no longer appear in the language selection menu. They remain
  accessible by selecting `[a] All languages` then pressing `h` in the voice
  list. The public/hidden boundary is tracked via `_public_lang_count`.

---

## [4.9.9] — 2026-04-24

### Added

- **`src/tts.py` — French language support for Google TTS.**
  Added `language_code` parameter to `SpeechConfig` in `_synthesize_google_tts()`,
  enabling French voice synthesis with Gemini 3.1 Flash TTS API.

---

## [4.9.8] — 2026-04-23

### Added

- **`src/tts.py` — Google TTS integration via Gemini 3.1 Flash TTS.**
  Added `_synthesize_google_tts()` function using `google-genai` library for
  expressive voice synthesis with support for tags like `[excited]`, `[whispers]`.
  Voices start with "google-" prefix (e.g., "google-kore").
- **`src/voice_catalog.json` — temporary comparison voices provider.**
  New "comparison" provider with prefix "c" containing Google TTS voices (Kore,
  Aoede, Zephyr, Puck) marked as `temporary: true` for demo purposes only.
- **`vox-refiner-menu.sh` — truly hidden comparison voices menu.**
  Comparison voices are now hidden by default; press `h` (secret key, not displayed)
  to toggle visibility temporarily. Voices require `GOOGLE_TTS_API_KEY` and are not
  saved permanently.
- **`vox-refiner-menu.sh` — Google TTS API key management.**
  Added Google TTS key to API Keys submenu with test/edit actions ([t6]/[e6]),
  displayed as optional for comparison voices.
- **`vox-refiner-menu.sh` — error message for missing comparison API key.**
  When selecting a comparison voice without valid API key, displays clear error
  message directing to Settings → API Keys.
- **`requirements.txt` — google-genai dependency.**
  Added `google-genai` for Google TTS support.

### Changed

- **`vox-refiner-menu.sh` — voice picker filtering supports comparison mode.**

## [4.9.7] — 2026-04-22

### Added

- **`vox-refiner-menu.sh` — multilingual voice preview samples.**
  Added dedicated preview sample texts for German (`de`), Spanish (`es`), and
  Portuguese (`pt`) in addition to existing French/English samples, so voice
  tests now sound natural in each language.

### Changed

- **`vox-refiner-menu.sh` — language-aware preview sample routing.**
  Voice preview text selection now uses a language-based switch (`fr`, `en`,
  `de`, `es`, `pt`, including locale variants like `fr-*`) with an English
  fallback, ensuring the tested sample matches the selected voice language.
- **`vox-refiner-menu.sh` — Update submenu return flow standardized.**
  The `Check for updates`, `Apply update`, and `Troubleshooting` screens now
  return via explicit `[m]  Menu Update` prompts instead of `Press Enter to
return...`, with consistent spacing after command output for readability.

---

## [4.9.6] — 2026-04-22

### Added

- **`vox-refiner-menu.sh` — language pre-menu for voice picker.**
  A new language-selection step now appears before listing voices in the picker,
  so users can filter by language first instead of browsing the full catalog at
  once. The menu includes per-language voice counts, an `All languages` option,
  and an in-picker `[l] Language` shortcut to change the filter on demand.

### Changed

- **`vox-refiner-menu.sh` — robust language filtering based on catalog data.**
  Group language is now derived from voice `sample_lang` metadata during catalog
  parsing, then used for filtering. This avoids fragile title-based matching and
  keeps the picker stable even if group titles or emojis change.
- **`vox-refiner-menu.sh` — robust Mistral grid alignment with Unicode-aware width.**
  Grid row formatting is now generated in Python with display-width handling for
  Unicode characters, then rendered in Bash as preformatted rows. This removes
  spacing drift caused by variable label lengths and multi-width characters.

---

## [4.9.5] — 2026-04-21

### Added

- **`src/voice_catalog.json` — 50 German Gradium voices appended after English groups.**
  Added a new `🇩🇪 German (Germany)` group at the end of the Gradium catalog,
  preserving the existing French/English order while extending the picker with
  50 additional German voices. The German group now starts at `g300` to keep
  room for future English additions.
- **`src/voice_catalog.json` — Spanish Gradium groups added with fixed block start.**
  Added new groups for `🇪🇸 Spanish (Spain)`, `🇲🇽 Spanish (Mexico)`, and
  `🌍 Spanish (Others)`. The Spain group starts at `g400` to reserve room for
  future expansions before the Spanish block.
- **`src/voice_catalog.json` — Portuguese Gradium groups added with fixed block start.**
  Added new groups for `🇧🇷 Portuguese (Brazil)` and `🇵🇹 Portuguese (Portugal)`.
  The Brazil group starts at `g500` to reserve room for future additions before
  the Portuguese block.

---

## [4.9.4] — 2026-04-21

### Added

- **`src/voice_catalog.json` — major Gradium voice catalog expansion.**
  Added many new Gradium voices across French and English families, including
  French (France), French (Canada), English (US), English (UK), English
  (Australia), and English (Others), with concise per-voice metadata shown in
  the picker.

### Changed

- **`vox-refiner-menu.sh` + `src/voice_catalog.json` — stable provider-prefixed numbering and ordering.**
  Gradium numbering is now explicitly controlled by per-group `start_index`
  values so the picker keeps a consistent sequence (for example US starting at
  `g100`) while preserving a clear language-first order in the menu.
- **Gradium catalog presentation in voice picker.**
  Gradium entries are displayed with compact descriptors (age/gender/style)
  directly next to each voice name for faster selection.

---

## [4.9.3] — 2026-04-21

### Fixed

- **`requirements.txt` — `gradium` package added.**
  `gradium==0.5.11` was missing from the dependency list, so production installs
  updated via `vox-refiner-update.sh` never received the SDK. Gradium voices
  silently failed on any machine that had not manually installed the package.

---

## [4.9.2] — 2026-04-20

### Fixed

- **`vox-refiner-menu.sh` — stale optional API keys cleared at startup.**
  `EDENAI_API_KEY`, `XAI_API_KEY`, `PERPLEXITY_API_KEY`, and `GRADIUM_API_KEY`
  are now explicitly unset before `.env` is sourced. Previously, renaming or
  removing a key in `.env` had no effect because `source .env` never unsets
  variables — the old value lingered in the process environment from the
  previous session.
- **`src/tts.py` — 30 s timeout on Gradium WebSocket connection.**
  Gradium uses WebSockets with no built-in connection timeout. The TTS call
  now runs under `asyncio.wait_for(..., timeout=30.0)` so a failed or
  unreachable connection raises `TimeoutError` after 30 s instead of
  blocking the process indefinitely.
- **Voice picker — previous Mistral preview preserved on failed Gradium selection.**
  When a Gradium voice is selected without `GRADIUM_API_KEY`, the picker now
  restores the previously staged preview instead of clearing it, so the user
  does not lose a Mistral voice they had already queued for selection.

---

## [4.9.1] — 2026-04-20

### Fixed

- **Voice picker — Gradium voices blocked when `GRADIUM_API_KEY` is not set.**
  Selecting a Gradium voice without a key now shows a clear error
  ("GRADIUM_API_KEY is not set — cannot preview or select this voice.") and
  prevents the voice from being saved. The previously staged Mistral preview
  is preserved — the selection is restored to what it was before the failed
  attempt.
- **Voice picker — `GRADIUM` section header shows unavailability notice.**
  When `GRADIUM_API_KEY` is absent, the section header now reads
  `GRADIUM  (unavailable — GRADIUM_API_KEY not set, see Settings → API Keys → [e5])`
  so the user understands immediately why the voices are locked.
- **`src/tts.py` — Gradium WebSocket timeout added.**
  Gradium uses WebSockets with no built-in connection timeout. The TTS call
  now runs under `asyncio.wait_for(..., timeout=30.0)` so a failed or
  unreachable connection raises `TimeoutError` after 30 s instead of
  blocking the process indefinitely.

---

## [4.9.0] — 2026-04-20

### Added

- **Gradium TTS integration — 13 native French voices in the voice picker.**
  VoxRefiner can now synthesise speech via Gradium AI in addition to Mistral.
  Voice picker extended with two new groups: 🇫🇷 **GRADIUM — French (France)**
  [30]–[39] (Elise, Leo, Olivier, Manon, Jade, Amelie, Adrien, Sarah, Jennifer,
  Elodie) and 🇨🇦 **GRADIUM — French (Canada)** [40]–[42] (Melanie, Maxime,
  Alexandre). French preview text is used automatically for choices [30]–[42].
- **`src/tts.py` — Gradium routing in `synthesize()`.**
  Added `_is_gradium_voice()` (UUID vs. short alphanumeric ID detection),
  `_synthesize_gradium()` (async call via `gradium.client.GradiumClient`), and
  early-exit routing at the top of `synthesize()`. Requires the `gradium` package
  (`pip install gradium`) and `GRADIUM_API_KEY` in `.env`.
- **API Keys submenu — Gradium key management.**
  `[t5]` test and `[e5]` edit actions added for `GRADIUM_API_KEY`. Key is tested
  against `GET https://eu.api.gradium.ai/api/voices/` with `x-api-key` header.
  Capability status now shows "Extended voice bank (Gradium: 13 native French
  voices)" when the key is configured.
- **`.env.example` — `GRADIUM_API_KEY` documented.**
  New optional key entry with description, usage note, and link to Gradium.

---

## [4.8.2] — 2026-04-19

### Added

- **`src/ui_py.py` — centralised Python UI output library.**
  New shared module providing `error()`, `info()`, `process()`, `success()`,
  `warn()` helpers and ANSI colour constants (`BG_BLUE`, `WHITE`, `BGREEN`,
  `RESET`). All Python modules (`ocr`, `providers`, `refine`, `slug`,
  `transcribe`, `translate`, `tts`, `voice_rewrite`) migrated from raw
  `print(..., file=sys.stderr)` calls to these helpers, giving consistent
  styling and prefix characters across the whole Python layer.
- **`src/tts.py` — cleaned-text display block uses centralised colours.**
  The blue-background "Texte nettoyé" display block now imports colour
  constants from `ui_py` instead of inlining escape codes, and the label is
  translated to English ("Cleaned text — ready for text-to-speech.").

### Changed

- **`vox-refiner-menu.sh` — indicative amounts note translated to English.**
  The italicised footnote under the API keys section now reads "Estimated
  amounts, subject to change — minimum credits required for these AI API
  providers."

### Fixed

- **Search — selected text is context for disambiguation, not a question to answer.**
  The system prompt and user-content framing have been redesigned across two
  iterations. The selected text is now presented as "what the user is reading —
  context only, not a question to answer", and the user's own question is
  labelled distinctly as "User's question". A rule explicitly instructs the
  engine to answer the user's question, not any question that may appear inside
  the selected text. When a term is ambiguous, the engine favours the
  interpretation consistent with the selected text.

- **Fact-check output now respects the Settings target language.**
  The Settings menu persists the target language as `TRANSLATE_TARGET_LANG`,
  but `insight.py` only read `OUTPUT_DEFAULT_LANG`. When the latter was
  unset, prompts kept the generic rule _"Write in the same language as the
  input/question/summary/reports"_ — Perplexity interpreted that against
  the English query scaffolding and responded in English, while Grok
  matched the input and responded in the source language, producing mixed
  reports and a biased synthesis. `_OUTPUT_DEFAULT_LANG` now falls back to
  `TRANSLATE_TARGET_LANG`, so the Settings menu value drives all insight,
  search and fact-check output.
- **Fact-check detail prompt `[w]`/`[x]` can now be toggled.**
  The prompt offering Perplexity (`[w]`) or Grok (`[x]`) details was a
  single-shot `read` — once a side was chosen, the user had to relaunch
  the whole fact-check to hear the other. The prompt is now wrapped in a
  loop; `[w]` and `[x]` can be picked in any order, and `[Enter]` (or any
  other key) exits back to the main menu.
- **Voice Translate — dedicated language variable and persistent default.**
  `VOICE_TRANSLATE_TARGET_LANG` (default `en`) replaces the use of
  `TRANSLATE_TARGET_LANG` as the default for the 🎙→🔊 module. The two
  variables have opposite semantics: `TRANSLATE_TARGET_LANG` means "output
  AI content in this native language" (set to `fr` by the Settings menus),
  whereas Voice Translate needs "translate TO this foreign language". With a
  shared variable, setting the language in Fact-check Settings was silently
  overriding the Voice Translate default to `fr`. The pipeline now reads
  `VOICE_TRANSLATE_TARGET_LANG` and exports `TRANSLATE_TARGET_LANG` only
  for the child Python processes. When the user selects a different language
  in the picker, a `Save as default? [y/N]` prompt immediately offers to
  persist it to `.env` — no need to remember a post-menu action.

---

## [4.8.1] — 2026-04-19

### Added

- **API Keys menu — numbered shortcuts and test for every provider.**
  Actions renamed `[t1]/[e1]` … `[t4]/[e4]` (Mistral → Eden AI → xAI →
  Perplexity). Two new test functions added: `_test_xai_key()` (GET
  `api.x.ai/v1/models`) and `_test_perplexity_key()` (minimal POST to
  `api.perplexity.ai/chat/completions`); both auto-run after a successful
  key edit, consistent with the existing Mistral and Eden AI behaviour.
  Key display reordered (Mistral, Eden AI, xAI, Perplexity) and minimum
  top-up amounts shown inline for each provider (indicative, may change):
  Mistral ~10 € HT, Eden AI ~5 € HT, xAI ~10 $ HT, Perplexity ~50 $ HT.

### Fixed

- **Capability status — accuracy fixes.**
  Perplexity via Eden AI now shows `✓` (it is a working capability, not
  degraded). Grok split into two lines: _Grok web search_ (`✓` with either
  xAI direct or Eden AI) and _Fact-check X/Twitter_ (`✓` only with
  `XAI_API_KEY` direct, `○` via Eden because native X/Twitter search is not
  exposed through the Eden AI API). "Tip" hint for Perplexity removed.

---

## [4.8.0] — 2026-04-19

### Added

- **`TTS_AUTO_TRANSLATE` — auto-translate before reading aloud (Selection to
  Voice).** When `TTS_AUTO_TRANSLATE=1`, `selection_to_voice.sh` translates
  the selected text via `src.translate` before passing it to TTS, so the
  audio is always in the user's preferred language regardless of the source
  text. Target language = `TRANSLATE_TARGET_LANG` (or `OUTPUT_DEFAULT_LANG`
  fallback) — the same variables already used by all other translation flows.
  Default `0` (off) — no behaviour change for existing users.
  - **Runtime settings mini-menu** (`[s] Settings`) added to the
    Selection to Voice post-action menu. Exposes two toggleable options:
    `[1] Auto-translate : on/off` and `[2] Target language` (persisted to
    `.env` via the same `sed` pattern as the insight settings flow).
  - **`.env.example`** documents `TTS_AUTO_TRANSLATE` with rationale.

### Fixed

- **Fact-check result returned in English when input was non-English.**
  `factcheck()` passed `_FACTCHECK_GROK_SYSTEM` to Grok but omitted the
  system-prompt argument for Perplexity, causing `search_perplexity` to fall
  back to `_SEARCH_SYSTEM` (which anchors language on the _question_, not the
  _input summary_). The hardcoded English query `"Verify the main factual
claims in this content."` then forced English output regardless of the
  selected text's language. Fixed by passing `_FACTCHECK_PERPLEXITY_SYSTEM`
  as the third argument, consistent with the existing Grok call.
- **`EDEN_MODEL_MAP` only covered Mistral, breaking Eden fallback for search /
  fact-check when `PERPLEXITY_API_KEY` (or `XAI_API_KEY`) was absent but
  `EDENAI_API_KEY` was set.** `_prepare_eden_opts()` could not translate the
  canonical model name (e.g. `sonar-pro`) to the Eden identifier
  (`perplexityai/sonar-pro`), so the payload went out with a name Eden
  rejects with HTTP 400 "Model(s) not found or inactive". Added Perplexity
  and xAI entries; contract tests added for both.
- **Shell scripts invoked Python modules as files, breaking `from src.X`
  imports at runtime.** All six call sites switched to `python -m src.X`.

---

## [4.7.0] — 2026-04-19

### Added

- **`src/providers.py` — provider resolution layer:** new central module
  registering all AI providers (Mistral direct, Eden AI routes, xAI/Grok direct,
  Perplexity direct) in a declarative table. Exposes `resolve(capability)` →
  ordered list of available providers filtered by key presence, `is_available()`,
  and `call()` with ping-pong retry/fallback (3 attempts per provider, backoff
  2→4→8→15→30 s). Not yet wired into existing flows — migration is progressive.
- **XDG key-validation cache** (`~/.local/share/vox-refiner/keys-cache.json`):
  provider keys are validated on first use and re-validated only when the key
  changes (SHA-256 prefix hash) or on live 401 (`mark_invalid()`). No periodic
  TTL — revalidation is event-driven.
- **`EDENAI_API_KEY` support:** Eden AI added as optional fallback provider for
  Mistral, Grok, Perplexity, and OCR routes. Menu now shows the Eden AI key
  with `[n]` edit / `[v]` test options.
- **Capability status in the API Keys menu:** Settings → API Keys now shows a
  live capability table after the key listing — each capability shows ✓ (direct
  key), ~ (Eden route), or ○ (not available) with a pedagogical hint explaining
  what each missing key would unlock.
- **`docs/eden-ai-models.md`:** added OCR async endpoint section (separate
  `/v3/universal-ai/async` path, job-creation flow, polling).
- **`tests/ping_eden_models.py`:** added OCR async probe (`ocr/ocr_async/mistral`);
  `--only ocr` filter; split into `_ping_chat()` and `_ping_ocr()` adapters.
  Added `mistral/magistral-small-latest` to the probe list now that it is
  actively used on Mistral direct (fallback for `mistral-small + reasoning_effort`).
  Expanded catalog so every key and every fallback-target in
  `EDEN_FALLBACK_CHAINS` is probeable — covers Grok 4.1 vs 4 endpoint variants
  (`*-latest` suffix), Perplexity `sonar` / `sonar-reasoning-pro`, and Amazon
  Bedrock fallback targets (`mistral-large-3`, `magistral-small-2509`,
  `qwen3-next-80b`) plus `ovhcloud/gpt-oss-120b`.
- **`XAI_FALLBACK_MAP` and `PERPLEXITY_FALLBACK_MAP`** in `src/providers.py`:
  internal fallback tables for direct xAI / Perplexity APIs, mirroring
  `MISTRAL_FALLBACK_MAP`. Used on retry when the sticky policy keeps the call
  on a single provider (e.g. `fact_check_x` stays on Grok direct for native
  X/Twitter search). Values use canonical API names (no `xai/` or
  `perplexityai/` prefix — that's Eden's format). Both maps use cyclic chains
  (no `""` terminal) so retries rotate between model tiers on 429; safe under
  the `_MAX_ATTEMPTS = 6` hard cap.
- **`CallResult` dataclass** in `src/providers.py`: `call()` now returns a
  structured result exposing `text`, `provider`, `effective_model`,
  `requested_model`, `substituted`, and `attempts`. Business code can display
  the provider + actual model to the user even after a pingpong fallback or
  an Eden-side substitution (e.g. `mistral-small + reasoning_effort` →
  `mistral/magistral-small-latest`).
- **`docs/eden-ai-models.md`:** documented `mistral/magistral-small-latest` as
  the Eden substitute for `mistral-small-latest + reasoning_effort`.
- **`tests/unit/test_providers.py`:** 79 unit tests covering PROVIDERS/CAPABILITIES
  table invariants, `resolve()` filtering, `is_available()`, cache round-trip,
  key-hash rotation detection, `mark_invalid()`, `call()` happy path, ping-pong
  retry, sticky policy, Eden model mapping & substitution, `CallResult` fields,
  non-429 immediate failure, and backoff timing.
- **`.env.example`:** restructured API key section with priority rules, per-key
  rationale, and `GEMINI_API_KEY` as a documented-but-inactive placeholder.

### Changed

- **xAI endpoints updated to Grok 4.20 generation:** `EDEN_FALLBACK_CHAINS` and
  `XAI_FALLBACK_MAP` now reference the new xAI models
  (`grok-4.20-0309-reasoning`, `grok-4.20-0309-non-reasoning`,
  `grok-4.20-multi-agent-0309`, `grok-4-1-fast-reasoning`,
  `grok-4-1-fast-non-reasoning`). Note: direct xAI API dropped the `beta-`
  prefix, but Eden AI still carries it (`xai/grok-4.20-beta-0309-*`) until
  their catalog catches up — the two nomenclatures are intentionally kept in
  sync with each provider's current naming.
- **Default Grok model** in `_call_xai_adapter`: `grok-4-fast` →
  `grok-4-1-fast-non-reasoning` (fallback when `INSIGHT_GROK_MODEL` is unset).
- **`call()` now consumes the Layer-1 fallback maps** (`MISTRAL_FALLBACK_MAP`,
  `XAI_FALLBACK_MAP`, `PERPLEXITY_FALLBACK_MAP`) via a new `_advance_cascade()`
  helper. On each `RateLimitError` from a direct provider, the cascade walks
  the map and the next retry uses the fallback model — per-provider state, so
  each provider tracks its own chain independently. Compound keys
  (`<model>+<option>`) strip unsupported options on fallback (e.g. a retry
  after `mistral-small-latest + reasoning_effort` drops the effort flag and
  swaps to `magistral-small-latest`). Reaching a terminal `""` value marks
  the provider exhausted; it is removed from the live set but other providers
  keep retrying. Eden providers continue to cascade server-side through the
  `fallbacks` payload field (no client-side advance). Previously, `call()`
  only rotated providers without ever swapping models — the maps were data
  structures with no consumer.
- **Direct cascade is suppressed when Eden redundancy is active** (pingpong
  policy with an Eden route present): a 429 on a direct provider is typically
  an account-wide rate limit, so swapping to another model on the same
  account rarely helps — Eden provides real redundancy via a separate account
  with its own server-side fallback chain. The direct cascade therefore only
  fires when there is no live Eden route OR the policy is `sticky` (e.g.
  `fact_check_x`, where pingpong never rotates to Eden so Eden's presence
  in `live` provides zero real redundancy).
- **`src/insight.py::summarize()` migrated** to `providers.call("insight", ...)`.
  The function now routes through the pingpong Mistral-direct ↔ Eden/Mistral
  path instead of a bare `requests.post` to the Mistral endpoint. A new
  `_log_call_result()` helper prints a single stderr line when the answering
  provider/model differs from the happy path (pingpong fallback to Eden,
  Eden-side substitution, or cascade to another model) so the user always
  knows which route produced the summary. Availability check switched from
  `MISTRAL_API_KEY is set` to `is_available("insight")` — the function now
  runs with Eden-only keys too. Tests in `TestSummarize` rewritten to mock
  `src.insight.call` instead of `requests.post`; the previously-failing
  `test_reasoning_effort_high_in_payload` is replaced by paired tests that
  verify the flag is passed when `INSIGHT_SUMMARY_REASONING=high` and absent
  otherwise.
- **`src/insight.py::search_grok()` migrated** to
  `providers.call("fact_check_x", ...)`. Grok direct stays primary under the
  sticky policy (Eden is a last-resort fallback, kept out of the pingpong
  rotation because Eden does not expose the native X/Twitter search tool so
  losing it would degrade results silently). The inline `xai_sdk` import and
  Client/chat boilerplate are gone — the xAI SDK call lives in
  `providers._call_xai_adapter()` exclusively. `_log_call_result()` reuses the
  same stderr reporting as `summarize()`. The default `INSIGHT_GROK_MODEL`
  was raised from `grok-4-fast` to `grok-4-1-fast-non-reasoning` to match the
  Grok 4.1/4.20 model family used in the fallback maps and avoid implicit
  xAI server-side rerouting. `TestSearchGrok`, the Grok-touching tests in
  `TestSearch`, and `TestFactcheck` were rewritten to mock `src.insight.call`
  instead of patching `sys.modules["xai_sdk"]`; the now-unused `_mock_xai_sdk`
  helper was removed.
- **`src/insight.py::search_perplexity()` migrated** to
  `providers.call("search", ...)`. Perplexity direct first, Eden/Perplexity as
  pingpong fallback on 429. Added a `system` override parameter symmetric with
  `search_grok()` so future callers can pass `_FACTCHECK_PERPLEXITY_SYSTEM`
  without another signature change.
- **Mistral synthesis in `search()` (both-engines branch) and `factcheck()`
  migrated** to `providers.call("insight", ...)`. Both synthesis paths now
  inherit the pingpong Mistral-direct ↔ Eden/Mistral fallback automatically
  and report their effective provider/model via `_log_call_result()`. The
  `search()` synthesis keeps its graceful degradation: on `ProviderError` it
  returns the two raw results concatenated instead of failing the whole
  search.
- **Search and fact-check dispatchers now resolve availability through
  `is_available()`** instead of reading direct-API env-var module globals.
  Concretely, `search()`, `factcheck()`, `_cmd_search()`, and
  `_cmd_factcheck()` route on `is_available("search")`,
  `is_available("fact_check_x")`, and `is_available("insight")`. This closes
  the gap where an Eden-only setup (no `PERPLEXITY_API_KEY` / `XAI_API_KEY`,
  only `EDENAI_API_KEY`) could not use the search/factcheck flows even though
  Eden's Perplexity and xAI routes were ready to serve. Error messages were
  updated to mention `EDENAI_API_KEY` alongside the direct keys.
- **Tests rewritten:** `TestSearchPerplexity` now mocks `src.insight.call`
  instead of `requests.post` and covers the `search` capability contract
  (Eden-only acceptance, `system` override, timeout/model kwargs,
  `ProviderError → RuntimeError` wrap). `TestSearch` and `TestFactcheck` were
  rewritten around a new `_route_by_capability()` side-effect helper that
  dispatches `call()` invocations on the capability argument
  (`search` / `fact_check_x` / `insight`), so a single `patch("src.insight.call")`
  can back all three of Perplexity, Grok, and Mistral synthesis in one test.
  A `_clear_search_env()` fixture unsets every key the host `.env` may prime
  so the no-provider guards are reachable in isolation.
- **`src/refine.py` migrated to the provider layer.** Both `refine()` and
  `_extract_and_update_history()` now call `providers.call("refine", ...)`
  and `providers.call("history", ...)` respectively, so the 3-tier
  SHORT/MEDIUM/LONG flow and the background history extraction both inherit
  pingpong Mistral-direct ↔ Eden/Mistral fallback, the direct cascade on
  429, and Eden-side substitution/native fallback chains. The parallel
  compare thread (`REFINE_COMPARE_MODELS=true`) also routes through the
  provider layer. Availability check switched from `MISTRAL_API_KEY is set`
  to `is_available("refine")` / `is_available("history")` — refinement now
  runs with an Eden-only configuration. A new `_log_refine_result()` helper
  (mirroring `insight.py::_log_call_result()`) prints a single stderr line
  labelled `Refine (short|medium|long)` or `History` whenever the answering
  provider/model differs from the happy path. A local
  `_strip_unsupported_params()` keeps the safety net that drops
  `reasoning_effort` when the requested model is not `mistral-small-latest`
  (covers user overrides like `REFINE_MODEL_MEDIUM=magistral-small-latest`).
- **`_call_model()`, `_API_URL`, `_TRANSIENT_HTTP_CODES`, `REFINE_REQUEST_RETRIES`,
  and the direct `requests.post` import are gone** from `refine.py` — retries,
  backoff, and transient-HTTP handling are now the provider layer's concern.
  In-tier `ProviderError` from the primary model still triggers the existing
  tier fallback (primary → fallback model without per-tier params), so the
  app-level graceful-degradation path (returning the raw transcription when
  every model is exhausted) is preserved. Auth failures (401/403) no longer
  propagate as `HTTPError` — they surface as `ProviderError` from the
  provider layer, are caught by the tier loop, and degrade to raw text
  rather than aborting the paste (behavior change, intentional UX
  improvement — see `TestRefineFallbackOnProviderError`).
- **`tests/integration/test_refine_fallback.py` fully rewritten.** All tests
  now mock `src.refine.call` instead of `requests.post`, inspect the opts
  passed to `call()` (capability, model, timeout, temperature,
  reasoning_effort) via `mock.call_args.kwargs`, and use a
  `_route_by_model()` side-effect helper for compare-mode determinism.
  `TestRefineFallbackOn429` is renamed `TestRefineFallbackOnProviderError`
  to reflect the new capability-level error surface. A `_clear_refine_env()`
  fixture unsets `MISTRAL_API_KEY` / `EDENAI_API_KEY` after import so the
  `is_available("refine") == False` guard is reachable even when the host
  `.env` populates both keys.
- **`tests/unit/test_content_parsing.py` rewritten** to exercise the content
  parser (plain string vs. magistral list-of-blocks) through
  `providers.call("refine", ...)` with a mocked `requests.post`. The
  coverage surface is the same (string returned as-is, list joined, missing
  `text` key safe), but the tests now target the new home of the logic
  (`_call_openai_adapter` in `providers.py`).
- **Provider/effective-model exposed in CLI headers** for every flow already
  routed through `src/providers.py` (refine + summary/search/factcheck).
  The Python side writes a small plain-text "meta" file (paths: existing
  `VOXTRAL_MODELS_FILE` for refine, new `INSIGHT_MODEL_META_FILE` for
  insight); the shell side reads it and appends a suffix to the result
  header so the user always sees which provider answered, e.g.
  `REFINED TEXT — mistral-small-latest` (happy path, direct provider),
  `REFINED TEXT — mistral/mistral-small-latest (via Eden AI)` (Eden
  pingpong fallback), `SUMMARY — magistral-small-latest (substituted from
mistral-small-latest)` (Eden substitution to an equivalent model).
  Translate and OCR keep their hardcoded labels until their own migration
  steps — no placeholder plumbing introduced where it would be dead code.
- **`src/insight.py` — `_write_model_meta(result)` helper** called from
  `_log_call_result()` so every migrated capability (summarize, perplexity,
  grok, search synthesis, factcheck synthesis) emits the meta-file
  automatically. In multi-step flows the last call wins, which is the
  user-visible model (e.g. synthesis for factcheck). File format: 5 lines
  — requested model, effective model, provider internal name (e.g.
  `mistral_direct`, `eden_mistral`), provider display name, substituted
  flag.
- **`src/refine.py` — `VOXTRAL_MODELS_FILE` format extended** with
  lines 3-6 (effective model, provider internal name, provider display
  name, substituted flag). Lines 1-2 unchanged (succeeded model, fallback
  model) so legacy readers continue to work — the existing record-and-
  transcribe integration sandbox writes only the legacy 2 lines and the
  shell reader degrades to "plain model" output without provider
  annotation.
- **`src/text_flows.sh` — `_model_label_suffix` helper** shared by
  `_generate_summary`, `_search_flow`, `_factcheck_flow`, and
  `selection_to_insight.sh`. Rules: empty/missing meta file → empty
  suffix (legacy look); provider name ends in `_direct` → `" — {model}"`
  (plus `"(substituted from ...)"` if a substitution flag was set but the
  model changed); provider name starts with `eden_` → `" — {model} (via
Eden AI)"`; other providers → `" — {model} (via {display})"` with the
  trailing `" (direct)"` stripped.
- **`record_and_transcribe_local.sh`** uses the same internal-name-based
  branching as `_model_label_suffix` so the STT flow's "REFINED TEXT" header
  stays consistent with the insight flows.
- **`selection_to_insight.sh` / `selection_to_search.sh` /
  `selection_to_factcheck.sh`** each export `INSIGHT_MODEL_META_FILE=
"$INSIGHT_DIR/.model_meta"` alongside the existing `INSIGHT_META_FILE`
  and friends.
- **`tests/unit/test_model_meta.py`** (6 tests): locks the 5-line format
  written by `insight._write_model_meta` and the 6-line format written by
  `refine.refine`, including the substituted-by-Eden path.
- **`tests/integration/test_model_label_suffix.py`** (7 tests): sources
  `src/text_flows.sh` in a subshell and asserts the exact output of
  `_model_label_suffix` for the full matrix of happy path, any
  `*_direct` provider, Eden route, Eden substitution, direct-with-
  substitution, empty meta file, and missing provider fields.
- **`src/providers.py` — `call_ocr_async()`** implements the Eden AI async
  OCR job flow: POST job to `/v3/universal-ai/async` with base64 image →
  receive `public_id` → poll GET until `status == "completed"` → extract
  text from the response. Handles four observed Eden response shapes (A:
  `output[0].prediction.pages[].markdown`, B: `prediction.text`, C:
  `result.pages[].markdown`, D: top-level `text`) by trying each in order.
  Raises `ProviderError` on missing key, HTTP failure, job failure status,
  or polling timeout (`_OCR_JOB_TIMEOUT_DEFAULT = 120 s`).
  A companion `_extract_eden_ocr_text()` helper centralises the shape-
  detection logic.
- **`src/ocr.py` migrated to the provider layer — 4-tier cascade.**
  `ocr()` calls `resolve("ocr")` and iterates the returned provider list,
  dispatching to the right API function based on `provider.adapter_type` /
  `provider.name`. No `MISTRAL_API_KEY` / `EDENAI_API_KEY` checks in
  business code — key-based tier selection is entirely owned by
  `providers.resolve()`. Active tiers depend on available keys:
  `MISTRAL_API_KEY` only → tiers 1+3; `EDENAI_API_KEY` only → tiers 2+4;
  both → all four in order. Cascade:
  (1) `mistral-ocr-latest` via `/v1/ocr` — provider `mistral_ocr`
  (new registry entry, `MISTRAL_API_KEY`);
  (2) Eden OCR async via `call_ocr_async()` — provider `eden_ocr_mistral`
  (`EDENAI_API_KEY`);
  (3) `pixtral-large-latest` via chat completions — provider
  `mistral_vision` (new registry entry, `MISTRAL_API_KEY`);
  (4) `mistral/pixtral-large-latest` via Eden chat — provider
  `eden_mistral` (`EDENAI_API_KEY`).
  Each successful tier writes a 5-line meta file to
  `VOXREFINER_OCR_META_FILE` (same format as `INSIGHT_MODEL_META_FILE`)
  so the shell header shows the actual provider that answered.
- **`providers.py` — two new OCR providers** added to the PROVIDERS
  registry: `mistral_ocr` (`adapter_type="mistral_ocr"`, endpoint
  `/v1/ocr`) and `mistral_vision` (`adapter_type="openai"`, endpoint
  `/v1/chat/completions`), both requiring `MISTRAL_API_KEY`.
  `CAPABILITIES["ocr"]` updated to the ordered 4-provider list
  `["mistral_ocr", "eden_ocr_mistral", "mistral_vision", "eden_mistral"]`.
  `_dispatch_adapter()` raises `ProviderError` for `adapter_type =
"mistral_ocr"` (same guard as the existing `eden_ocr` case) to prevent
  accidental routing through `call()`.
- **`screen_to_text.sh`** exports `VOXREFINER_OCR_META_FILE` and calls
  `_model_label_suffix` to build the `EXTRACTED TEXT` header suffix.
  Default falls back to `— mistral-ocr-latest` when the meta file is
  absent (e.g. legacy or test environments).
- **`tests/unit/test_ocr.py`** (26 tests): 4-tier cascade ordering with
  both keys, Mistral-only (tiers 1→3, Eden tiers skipped), Eden-only
  (tiers 2→4, Mistral tiers skipped), all-fail error, meta-file provider
  names at each tier, `call_ocr_async()` for all four response shapes,
  pending→completed polling, job failure, no key, and missing `public_id`.

### Fixed

- **Fact-check result returned in English when input was non-English.**
  `factcheck()` passed `_FACTCHECK_GROK_SYSTEM` to Grok but omitted the
  system-prompt argument for Perplexity, causing `search_perplexity` to fall
  back to `_SEARCH_SYSTEM` (which anchors language on the _question_, not the
  _input summary_). The hardcoded English query `"Verify the main factual
claims in this content."` then forced English output regardless of the
  selected text's language. Fixed by passing `_FACTCHECK_PERPLEXITY_SYSTEM`
  as the third argument, consistent with the existing Grok call.

- **`EDEN_MODEL_MAP` only covered Mistral, breaking Eden fallback for search /
  fact-check when `PERPLEXITY_API_KEY` (or `XAI_API_KEY`) was absent but
  `EDENAI_API_KEY` was set.** `_prepare_eden_opts()` could not translate the
  canonical model name (e.g. `sonar-pro`) to the Eden identifier
  (`perplexityai/sonar-pro`), so the payload went out with a name Eden
  rejects with HTTP 400 "Model(s) not found or inactive". It also meant
  `EDEN_FALLBACK_CHAINS` was never consulted (keyed on Eden-format names) so
  the Eden-side server fallback was silently disabled. Added Perplexity
  (`sonar`, `sonar-pro`, `sonar-reasoning-pro`, `sonar-deep-research`) and
  xAI (`grok-4-1-fast-non-reasoning`, `grok-4-1-fast-reasoning`,
  `grok-4.20-0309-non-reasoning`, `grok-4.20-0309-reasoning`,
  `grok-4.20-multi-agent-0309`) entries. Also broadened the comment:
  `EDEN_MODEL_MAP` is now explicitly "canonical model (Mistral / Perplexity /
  xAI) → Eden identifier", not "canonical Mistral model".
- **Contract tests added** (`test_eden_model_map_covers_all_perplexity_fallbacks`,
  `test_eden_model_map_covers_all_xai_fallbacks`): mirror the existing
  Mistral test so any future `PERPLEXITY_FALLBACK_MAP` / `XAI_FALLBACK_MAP`
  key without an Eden translation now fails CI instead of silently producing
  HTTP 400 at runtime.
- **Shell scripts invoked Python modules as files, breaking `from src.X`
  imports at runtime.** `record_and_transcribe_local.sh`, `voice_translate.sh`,
  `screen_to_text.sh`, and `vox-refiner-menu.sh` launched the Python entry
  points with `"$VENV_PYTHON" src/ocr.py` / `src/refine.py` / `src/transcribe.py`,
  which puts `src/` on `sys.path` but not the project root — so
  `from src.providers import ...` raised `ModuleNotFoundError: No module named
'src'`. OCR failed silently in the post-capture menu (stderr redirected via
  FD 3 but the exception was caught and returned as empty text), and refine
  failures were masked by the graceful-degradation fallback that returns the
  raw transcription on any error. All six shell call sites switched to
  `"$VENV_PYTHON" -m src.ocr` / `-m src.refine` / `-m src.transcribe`,
  matching the convention already used in `src/text_flows.sh` and
  `src/save_audio.sh`. Unit tests were unaffected because they inject
  `src/` into `sys.path` explicitly in `conftest.py`, so the regression did
  not surface there.

---

## [4.6.3] — 2026-04-14

### Fixed

- **Screen to Text post-menu stacked visually after returning from subcommands:**
  pressing `[z] Summarise`, `[p] Search`, `[f] Fact-check`, or `[l] Read aloud`
  then `[m] Back` left the sub-feature output and the F9 menu stacked on screen
  with no separator. The while loop now clears the screen and redisplays the
  OCR header + extracted text before each menu prompt, so the context is always
  visible regardless of which action was last taken.

---

## [4.6.2] — 2026-04-14

### Fixed

- **`--loudness` binary artefact committed to repo:** a TTS pipeline bug
  (wrong `--output` flag) created a file literally named `--loudness` (407 KB
  audio). It was accidentally tracked and pushed in v4.6.0. Removed from git
  history tracking and added to `.gitignore` alongside `--output` to prevent
  recurrence.

---

## [4.6.1] — 2026-04-14

### Fixed

- **`fix_filemode_drift()` created a staged change that blocked updates:**
  `git update-index --chmod=+x` moved the mode drift from the working tree
  into the index, which `ensure_clean_tracked_tree` caught as a staged change
  → infinite "local tracked changes detected" loop. Fixed by using `chmod -x`
  to normalize the filesystem to HEAD instead of staging a mode change.
  `repair_exec_bits()` re-applies `+x` after the pull as intended.
- **`uninstall.sh` tracked as `100644` in git:** caused a persistent
  executable-bit drift on every update. Now tracked as `100755`.

---

## [4.6.0] — 2026-04-14

### Added

- **`OUTPUT_DEFAULT_LANG` (`.env`):** new master language variable. When set,
  all AI-generated content (summaries, fact-check results, search answers,
  translations) responds in the specified language, regardless of the input
  text's language. When unset, the AI responds in the same language as the
  input text (natural behaviour). Supported codes: `en`, `fr`, `de`, `es`,
  `pt`, `it`, `nl`, `hi`, `ar`, `zh`, `ja`, `ko`, `ru`, `pl`, `sv`.
  `TRANSLATE_TARGET_LANG` remains available as an explicit override for
  translation only (takes precedence over `OUTPUT_DEFAULT_LANG`).

### Fixed

- **Summary source-line hallucination:** when no publication date or media
  name was present in the article, the model generated placeholder text
  (`Publié le jour mois 2024 à heure.`) instead of skipping the source line.
  Prompt now explicitly forbids inventing or approximating values and uses
  `[actual date]` / `[actual time]` labels to signal that real extracted
  values are required.

### Changed

- **`src/translate.py`:** target language now resolved from
  `TRANSLATE_TARGET_LANG` → `OUTPUT_DEFAULT_LANG` → `en` (was hardcoded
  to `en` when `TRANSLATE_TARGET_LANG` was unset).
- **`src/text_flows.sh`**, **`screen_to_text.sh`**,
  **`selection_to_insight.sh`**, **`selection_to_search.sh`**,
  **`selection_to_factcheck.sh`:** `_SETTING_TRANSLATE_LANG` initialisation
  updated to the same three-level fallback chain.

---

## [4.5.0] — 2026-04-11

### Added

- **`[t] Translate` in Screen to Text (F9):** translates OCR text using
  `mistral-small-latest` (no reasoning). Result copied to both clipboards.
  `[l] Read aloud` automatically reads the translation if one exists.
  `[e] Replay translation` appears in the post-menu after a first translation.
- **`src/translate.py`:** new standalone Python module — pure translation,
  structure-preserving (line breaks, lists, paragraphs). Target language set
  via `TRANSLATE_TARGET_LANG` in `.env` (default: `en`). Falls back to
  `mistral-medium-latest` on transient errors. Reusable from any script via
  stdin/stdout.
- **`_translate_flow()` in `src/text_flows.sh`:** reusable shell helper —
  calls `src/translate.py`, copies result to clipboard, displays it.
  Any future feature or workflow can call `_translate_flow "$text"`.
  Language choice (inline prompt or `[s] Settings → [5]`) is persisted
  to `.env` (`TRANSLATE_TARGET_LANG`) and survives across sessions.
- **`screen_to_text.sh`:** now sources `src/text_flows.sh`; `[s] Settings`
  added to post-action menu, exposing all flow settings including translate
  language (`[5]`).

---

## [4.4.0] — 2026-04-11

### Changed

- **`src/insight_common.sh` → `src/text_flows.sh`:** renamed to reflect the
  file's actual role as a general-purpose library of reusable text-processing
  flow helpers (`_search_flow`, `_factcheck_flow`, `_generate_summary`,
  `_tts_speak`, `_settings_flow`, …). The previous name implied a scope
  limited to the Insight feature; the new name matches the file's real reach
  across all text-based features and future workflows.
  All consumers (`selection_to_insight.sh`, `selection_to_search.sh`,
  `selection_to_factcheck.sh`) updated to source `src/text_flows.sh`.
- **`launch-vox-refiner.sh`:** terminal window geometry set to `125x50` for
  all supported emulators (mate-terminal, gnome-terminal, xfce4-terminal,
  konsole, xterm).
- **`vox-refiner-menu.sh`:** `[q] Quit` moved onto the same bottom bar as
  Settings / Context / Update / Help — one line instead of two.

---

## [4.3.3] — 2026-04-11

### Fixed

- **`vox-refiner-update.sh` — filemode drift blocks every update:** `repair_exec_bits()`
  runs `chmod +x` on tracked scripts, producing a persistent `100644 → 100755`
  diff that caused `ensure_clean_tracked_tree` to block `--apply` on every run.
  New `fix_filemode_drift()` silently aligns the git index to match the
  filesystem for mode-only changes before the clean-tree check; no real content
  change is ever discarded.

---

## [4.3.2] — 2026-04-11

### Fixed

- **`docs/troubleshooting.md`:** added entry for "Fact-check fails — xai-sdk
  package not installed" with fix (`./install.sh`).

---

## [4.3.1] — 2026-04-11

### Fixed

- **`vox-refiner-update.sh` — Python deps not synced after update:** `--apply`
  now runs `pip install -q -r requirements.txt` in the `.venv` after every pull
  (and even when already up to date). Fixes missing packages (e.g. `xai-sdk`)
  after a git update that added new dependencies.
- **`repair_exec_bits()` — incomplete script list:** `vox-refiner-menu.sh`,
  `install.sh`, `voice_translate.sh`, `selection_to_voice.sh`,
  `selection_to_search.sh`, `selection_to_factcheck.sh`, and `screen_to_text.sh`
  were missing from the `chmod +x` list; added.

---

## [4.3.0] — 2026-04-10

### Added

- **`[9] Screen to Text`** (was `[8]`): new feature — select a screen region,
  extract text via Mistral OCR (`mistral-ocr-latest`), copy result to clipboard.
  Post-action menu: `[r] Retry OCR  [n] New capture  [l] Read aloud  [i] Insight
[p] Search  [f] Fact-check  [m] Menu VoxRefiner`.
  - **`screen_to_text.sh`:** captures a region with `maim -s` (preferred) or
    `scrot -s` (fallback), pipes the PNG to `src/ocr.py`, copies extracted text
    to both clipboards.
  - **`src/ocr.py`:** new Python module — encodes image as base64, calls
    `mistral-ocr-latest` (primary) with `pixtral-large-latest` as fallback via
    `/v1/chat/completions`. Retries on transient errors (429, 5xx) with 2s delay.
  - **`install.sh`:** warns if neither `maim` nor `scrot` is found.
    `screen_to_text.sh`, `selection_to_search.sh`, `selection_to_factcheck.sh`
    added to `chmod +x` list.
  - **`launch-vox-refiner.sh`:** `--screen-text` flag added.

### Changed

- **Menu architecture overhaul** — features renumbered into stable 0-9 base
  layer + Workflows + Your Workflows sections:
  - `[2]` → `Media Translate` (coming soon)
  - `[3]` → `Speak & Translate` (was `[2]`)
  - `[4]` → `Live Translate` (coming soon)
  - `[5]` → `Selection to Voice` (was `[4]`)
  - `[6]` → `Selection to Insight` (was `[5]`)
  - `[7]` → `Selection to Search` (was `[6]`)
  - `[8]` → `Selection to Fact-check` (was `[7]`)
  - `[9]` → `Screen to Text` (was `[8]`)
  - `[W1]` → `Speak & Post` (coming soon, was `[3]`)
  - `[P0]` → `Your Workflows` (coming soon)
  - `[+]` → `Create a workflow` (coming soon)

- **`screen_to_text.sh` — post-action menu:** `[z] Summarise` replaces
  `[i] Insight`; sub-scripts called with `VOXREFINER_MENU=1` so their
  post-action menus are suppressed and control returns to `screen_to_text.sh`.
  OCR text forced into primary selection before calling selection scripts.

### Fixed

- **`[m] Menu VoxRefiner` — stacked menus:** all feature scripts
  (`screen_to_text.sh`, `selection_to_voice.sh`, `selection_to_insight.sh`,
  `selection_to_search.sh`, `selection_to_factcheck.sh`,
  `record_and_transcribe_local.sh`) now `exit 0` when `VOXREFINER_MENU` is
  set, instead of `exec`-ing a new menu instance. This eliminates the stacked
  menu bug where pressing `[q]` after `[m]` required multiple presses.

---

## [4.2.2] — 2026-04-10

### Fixed

- **`uninstall.sh` — git filemode:** was committed as `100644` (non-executable)
  while `repair_exec_bits()` in the update script set it to `755` after every
  pull, creating a persistent `git diff` that blocked subsequent updates.
  Corrected to `100755` in the git index.

---

## [4.2.1] — 2026-04-10

### Added

- **`launch-vox-refiner.sh`:** three new launch modes for keyboard shortcuts:
  - `--speak-transcribe` → F0 (`record_and_transcribe_local.sh` with
    `ENABLE_REFINE=false ENABLE_HISTORY=false`)
  - `--selection-search` → F6 (`selection_to_search.sh`)
  - `--selection-factcheck` → F7 (`selection_to_factcheck.sh`)
  - `SCRIPT_ENV` variable added so inline env overrides are passed correctly
    into the terminal emulator command.

---

## [4.2.0] — 2026-04-10

### Added

- **`[0] Speak & Transcribe`:** new feature — press `[0]`, record, get raw Voxtral
  text in clipboard immediately (no AI refinement). Refinement is available on demand
  via `[R]`. After a first refine, `[r] Retry refine` re-runs refinement on the same
  raw text without re-recording. History update triggered only after an explicit
  refine with `ENABLE_HISTORY=true`. No sub-menu — records immediately using `.env`
  defaults.
  - **`vox-refiner-menu.sh` — case `0)`:** direct recording with `ENABLE_REFINE=false
ENABLE_HISTORY=false`. Dynamic post-action menu: `[R] Refine / [n] New / [m]`
    before first refine; expands to `[r] Retry / [n] / [v] View history / [e] Edit /
[m]` after. `exec 3>&2` added so Python stderr reaches the terminal during
    on-demand refine.
  - **`record_and_transcribe_local.sh`:** raw transcription persisted to
    `recordings/stt/.raw_transcription` after Voxtral. `ENABLE_REFINE` and
    `ENABLE_HISTORY` now protected from `.env` override (saved before `source .env`,
    restored after).

---

## [4.1.0] — 2026-04-10

### Added

- **`[6] Selection to Search`:** new feature — select any text, ask a question
  (voice or text), get a web search result read aloud. The original selection is
  preserved and can be read aloud (`[l]`), summarised on demand (`[z]`), or
  fact-checked (`[f]`) from the same session.
  - **`selection_to_search.sh`:** orchestration script. Captures selected text,
    calls `_search_flow` directly (no upfront summary), then presents a main menu
    with dynamic replay buttons.
- **`[7] Selection to Fact-check`:** new feature — select any text, press
  `[Enter]` to fact-check the whole text, or dictate/type a specific claim.
  Result is read aloud. Search (`[p]`) and optional summary (`[z]`) available
  from the same session.
  - **`selection_to_factcheck.sh`:** orchestration script, symmetric to
    `selection_to_search.sh` with fact-check as the primary entry point.
- **`src/insight_common.sh`:** new shared library sourced by F5, F6, and F7.
  Extracts: `_warn_missing_keys`, `_play_audio`, `_tts_speak`, `_show_and_speak`,
  `_generate_summary`, `_read_full_article`, `_search_flow`, `_factcheck_flow`,
  `_settings_flow`. Single point of change for all selection-based intelligence
  features.

### Changed

- **`vox-refiner-menu.sh` — menu layout:** `[6]` and `[7]` (Screen features)
  shifted to `[8]` and `[9]`; `[6] Selection to Search` and
  `[7] Selection to Fact-check` added in the SELECTION section.
- **`selection_to_insight.sh` — refactored:** now sources `src/insight_common.sh`
  instead of defining helpers inline. `_search_flow` and `_factcheck_flow` now
  receive context as a parameter (`$summary_text`) instead of relying on a
  hardcoded global. All French error/warning strings replaced with English.

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
  expands `f(x)` → "f de x" iteratively; colon verbalization on math lines: `:` →
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

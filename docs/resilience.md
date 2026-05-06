<!-- @format -->

# Resilience — Timeouts, Retries & Audio Splitting

This document describes the retry and timeout strategy used by VoxRefiner
to handle transient API errors and large audio files gracefully.

---

## Overview

Two distinct components make HTTP calls to the Mistral API:

| Component                                    | File                | Purpose                                       |
| -------------------------------------------- | ------------------- | --------------------------------------------- |
| `transcribe()`                               | `src/transcribe.py` | Audio → raw text (Voxtral)                    |
| `refine()` / `_extract_and_update_history()` | `src/refine.py`     | Raw text → refined text (Mistral / Magistral) |

Each has its own adaptive timeout logic and shares the same retry mechanic.

Before any API call is made, the shell recording pipeline now also includes
defensive guards against stale or corrupted local audio artifacts.

---

## Recording-stage safeguards (shell)

The recorder (`record_and_transcribe_local.sh`) hardens the pre-transcription
path to prevent invalid local files from reaching `ffmpeg` or the API:

1. **Clean start**: `local_audio.wav` and `local_audio.mp3` are deleted before
   each non-retry recording.
2. **Temporary capture**: microphone input is written to a temporary WAV in `/tmp`
   and only moved to `local_audio.wav` after checks pass.
3. **Size sanity check**: the WAV is rejected if it exceeds `MAX_WAV_BYTES`
   (default `100000000`, i.e. 100 MB), which protects against corrupted files
   reporting unrealistic sizes.

This keeps retry mode unchanged (`--retry` still reuses `local_audio.mp3`) while
reducing failures after interrupted or abnormal recording sessions.

---

## Retry behaviour (both components)

Retries are triggered **only on transient HTTP errors**: 429 (rate limit),
500, 502, 503 (server errors).

- **Timeout** and **ConnectionError** are NOT retried. Whether the fallback model
  is tried depends on `REFINE_TIMEOUT_FALLBACK_ENABLED` (commented out in
  `.env.example`, meaning disabled by default). When disabled, a timeout returns
  the raw transcription immediately without attempting the fallback.
- **401 / 403** (authentication) and **404** are never retried.
- On 429, the stderr message explicitly says "rate limit" to distinguish it from
  server errors.

Number of extra attempts is configurable (default: 2, i.e. 3 total attempts):

```dotenv
TRANSCRIBE_REQUEST_RETRIES=2   # for Voxtral
REFINE_REQUEST_RETRIES=2       # for Mistral / Magistral
```

Set to `0` to disable retries entirely.

---

## Voxtral — adaptive timeout by file size

The audio file sent to Voxtral is MP3 @64 kbps, with speech accelerated (×1.25 by
default in `.env.example`, ×1.5 if `AUDIO_TEMPO` is unset) and long silences removed.
File size is therefore a reliable proxy for audio duration.

The timeout is computed in `_get_timeout(file_size)`:

| File size | ≈ speech duration    | Timeout             |
| --------- | -------------------- | ------------------- |
| < 300 KB  | ≈ 80 words / ~37 s   | 3 s                 |
| < 800 KB  | ≈ 240 words / ~110 s | 3 s                 |
| < 1.5 MB  | ≈ 500 words / ~4 min | 5 s                 |
| < 4 MB    | ≈ 10 min             | 12 s                |
| < 8 MB    | ≈ 20 min             | 20 s                |
| < 12 MB   | ≈ 30 min             | 30 s                |
| < 14.5 MB | ≈ 45 min             | 42 s                |
| < 19.5 MB | ≈ 60 min             | 55 s                |
| ≥ 19.5 MB | > 60 min             | → split (see below) |

The retry delay for Voxtral is fixed at **2 s** (the task is near-instantaneous
when the API is healthy; a short pause is enough to absorb a transient spike).

---

## Voxtral — audio splitting for files > 60 min

Files ≥ 19.5 MB (~60 min of speech after processing) exceed what can reasonably
be sent in a single API call. They are automatically split before transcription.

### How splitting works (`_split_audio`)

1. **Detect silences** — `ffmpeg silencedetect` scans the file for pauses ≥ 0.5 s
   at −35 dB.
2. **Choose cut points** — every ~30 minutes, the nearest silence within ±2 minutes
   of the boundary is used as the actual cut point. If no silence is found nearby,
   a hard cut is made at exactly 30 min.
3. **Extract chunks** — `ffmpeg -c copy` extracts each segment without re-encoding.
4. **Transcribe sequentially** — each chunk is sent to Voxtral independently,
   with its own adaptive timeout based on its size.
5. **Concatenate** — results are joined with a space; temporary chunk files are
   deleted immediately after use.

This avoids cutting in the middle of a sentence in the vast majority of cases.

---

## Refine — adaptive timeout by word count

After transcription, the raw text is refined by a Mistral or Magistral model.
The base timeout (and retry delay) scale with the word count of the text,
computed by `_refine_timing(word_count)`:

| Word count    | Base timeout | Retry delay |
| ------------- | ------------ | ----------- |
| < 30          | 3 s          | 1 s         |
| 30 – 89       | 4 s          | 1 s         |
| 90 – 179      | 6 s          | 1.5 s       |
| 180 – 239     | 8 s          | 2 s         |
| 240 – 399     | 11 s         | 2 s         |
| 400 – 599     | 15 s         | 2 s         |
| 600 – 999     | 20 s         | 3 s         |
| 1 000 – 1 999 | 30 s         | 4 s         |
| 2 000 – 3 999 | 50 s         | 5 s         |
| ≥ 4 000       | 80 s         | 8 s         |

These are **base timeouts**. The effective timeout applied at runtime is
`_effective_timeout(base, model)`, which multiplies the base by a per-model
speed factor (see below).

---

## Per-model speed factors

Magistral models produce chain-of-thought reasoning before their final answer,
making them intrinsically 3–4.5× slower than plain completion models.
When `reasoning_effort=high` is active on a Mistral model, the compound key
`model+reasoning_effort` is looked up first; unknown models with reasoning fall
back to a generic × 1.8 multiplier applied on top of the base factor.

| Model / compound key                        | Factor | Notes                                |
| ------------------------------------------- | ------ | ------------------------------------ |
| `devstral-small-latest`                     | × 1.0  | Deprecated — kept for safety         |
| `devstral-latest`                           | × 1.0  | Replaces devstral-small-latest       |
| `mistral-small-latest`                      | × 1.0  |                                      |
| `mistral-medium-latest`                     | × 1.2  | Slightly heavier than small          |
| `mistral-medium-3.5`                        | × 1.2  |                                      |
| `magistral-small-latest`                    | × 3.0  | Native chain-of-thought              |
| `magistral-medium-latest`                   | × 4.5  | Native chain-of-thought              |
| `mistral-large-latest`                      | × 1.5  |                                      |
| `mistral-small-latest+reasoning_effort`     | × 3.0  | Compound key: reasoning_effort=high  |
| `mistral-medium-3.5+reasoning_effort`       | × 4.0  | Compound key: reasoning_effort=high  |
| `mistral-medium-latest+reasoning_effort`    | × 4.0  | Compound key: reasoning_effort=high  |

Unknown models default to × 1.0 (× 1.8 if `reasoning_effort=high` is active).

**Example:** 202 words → base = 8 s. With `magistral-medium-latest` (× 4.5)
the effective timeout is **36 s**. With `mistral-small-latest` + reasoning (× 3.0)
the effective timeout is **24 s**.

---

## Timeout enabled flag

By default, **`ENABLE_TIMEOUT=false`** — VoxRefiner sets no timeout on AI calls.
Requests wait as long as the server needs. This prevents silent failures caused by
slow reasoning models or brief API load spikes.

Set `ENABLE_TIMEOUT=true` in `.env` to activate per-model, word-count-based limits.
Use this only in automated pipelines where predictable upper bounds are required.
With slow models (`magistral-medium-latest`) or large texts, the computed limit may
still be too short and produce unexpected "model failed" errors.

When `ENABLE_TIMEOUT=false`, all timeout computations in this document are inert —
they run but return `None`, which disables the timeout entirely on the HTTP request.

---

## History extraction timeout

The same `_refine_timing()` function is used for history extraction calls,
using the word count of the refined text. Because the call is made
**in the background** (the clipboard is already populated at that point),
the base timeout is **doubled** via `_refine_timing(wc, background=True)` —
giving history extraction extra slack without ever delaying the paste operation.
The per-model speed factor is applied on top of the doubled base.

---

## Fallback model chain

Both `refine()` and `_extract_and_update_history()` have a two-model fallback:

```text
primary model  →  (retry up to N times on 429/5xx)
                       ↓ if all attempts fail
fallback model →  (retry up to N times on 429/5xx)
                       ↓ if all attempts fail
refine()             : returns raw transcription unchanged (graceful degradation)
_extract_and_update_history() : raises RuntimeError (caller logs and continues)
```

401 / 403 errors skip the fallback and raise immediately — retrying with a
different model will not fix an authentication problem.

<!-- @format -->

# Resilience — Timeouts, Retries & Audio Splitting

This document describes the retry and timeout strategy used by Voxtral Paste
to handle transient API errors and large audio files gracefully.

---

## Overview

Two distinct components make HTTP calls to the Mistral API:

| Component                                    | File                | Purpose                                        |
| -------------------------------------------- | ------------------- | ---------------------------------------------- |
| `transcribe()`                               | `src/transcribe.py` | Audio → raw text (Voxtral)                     |
| `refine()` / `_extract_and_update_history()` | `src/refine.py`     | Raw text → refined text (Devstral / Magistral) |

Each has its own adaptive timeout logic and shares the same retry mechanic.

---

## Retry behaviour (both components)

Retries are triggered **only on transient HTTP errors**: 429 (rate limit),
500, 502, 503 (server errors).

- **Timeout** and **ConnectionError** are NOT retried — there is no point waiting
  again if the server did not respond at all. The fallback model is tried immediately.
- **401 / 403** (authentication) and **404** are never retried.
- On 429, the stderr message explicitly says "rate limit" to distinguish it from
  server errors.

Number of extra attempts is configurable (default: 2, i.e. 3 total attempts):

```dotenv
TRANSCRIBE_REQUEST_RETRIES=2   # for Voxtral
REFINE_REQUEST_RETRIES=2       # for Devstral / Magistral
```

Set to `0` to disable retries entirely.

---

## Voxtral — adaptive timeout by file size

The audio file sent to Voxtral is MP3 @64 kbps, with speech accelerated ×1.5
and long silences removed. File size is therefore a reliable proxy for audio duration.

The timeout is computed in `_get_timeout(file_size)`:

| File size | ≈ speech duration    | Timeout             |
| --------- | -------------------- | ------------------- |
| < 300 KB  | ≈ 80 words / ~37 s   | 2 s                 |
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

After transcription, the raw text is refined by Devstral or Magistral.
The timeout (and retry delay) scale with the word count of the text,
computed by `_refine_timing(word_count)`:

| Word count    | Timeout | Retry delay |
| ------------- | ------- | ----------- |
| < 30          | 3 s     | 1 s         |
| 30 – 89       | 5 s     | 1 s         |
| 90 – 179      | 8 s     | 2 s         |
| 180 – 239     | 12 s    | 2 s         |
| 240 – 399     | 18 s    | 3 s         |
| 400 – 599     | 25 s    | 3 s         |
| 600 – 999     | 35 s    | 4 s         |
| 1 000 – 1 999 | 55 s    | 5 s         |
| 2 000 – 3 999 | 90 s    | 8 s         |
| ≥ 4 000       | 150 s   | 10 s        |

Magistral models (MEDIUM and LONG tiers) do chain-of-thought reasoning, which makes
them intrinsically slower than Devstral. The higher timeouts in the upper tiers
account for this.

The same `_refine_timing()` function is also used for history extraction calls,
using the word count of the refined text.

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

<!-- @format -->

# Model Selection — Decisions & Rationale

This document records the reasoning behind the model choices and routing thresholds
used in VoxRefiner. It will be updated as further testing is done.

---

## Routing thresholds

| Parameter                      | Initial value | Current value | Changed in |
| ------------------------------ | ------------- | ------------- | ---------- |
| `REFINE_MODEL_THRESHOLD_SHORT` | 80            | **80**        | v1.4.0     |
| `REFINE_MODEL_THRESHOLD_LONG`  | 200           | **240**       | v1.4.0     |

**Rationale for 80:**
80 words matches actual usage patterns well: notes of 80–90 words are typically
short messages better handled by a fast model. Testing at 100 (v1.4.0) was
too permissive; 90 (v1.5.0) was briefly used but 80 was confirmed as the best
boundary after further observation.

**Rationale for 240 (was 200):**
200 words was considered slightly conservative for the MEDIUM tier. 240 words (~1 min 45 s
of speech) better matches a "developed thought / full paragraph" before switching to
the heavier LONG model. Values above ~300 were judged too high (risk of under-using
LONG on genuine extended monologues).

---

## Tier 1 — SHORT (< 80 words)

| Role     | Model                   |
| -------- | ----------------------- |
| Primary  | `devstral-small-latest` |
| Fallback | `mistral-small-latest`  |

**Why devstral-small as default:**
The most important quality for VoxRefiner is strict instruction-following: the model
must clean up the transcription without paraphrasing, adding content, or inventing
details. Devstral-small excels at this regardless of content type — even on
conversational or non-technical short notes. Mistral-small is available as a reliable
fallback for general-purpose coverage.

---

## Tier 2 — MEDIUM (80–240 words)

| Role     | Model                    |
| -------- | ------------------------ |
| Primary  | `magistral-small-latest` |
| Fallback | `mistral-medium-latest`  |

**Why magistral-small as default:**
Magistral models follow instructions more faithfully than standard completion models —
they won't add content, answer questions embedded in the transcription, or deviate from
the speaker's words. This matters most at medium length where the risk of AI
paraphrasing or "helpfully" expanding the text is highest. Mistral-medium is a fast,
reliable fallback with acceptable quality.

---

## Tier 3 — LONG (> 240 words)

| Role     | Model                     |
| -------- | ------------------------- |
| Primary  | `magistral-medium-latest` |
| Fallback | `mistral-medium-latest`   |

**Why magistral-medium over mistral-large:**
Both models were compared on the same extended transcription (~350 words, French,
architecture review with 3 distinct points). Key observations:

- `mistral-large-2411`: produced fluent, well-structured output but systematically
  shifted the narrator from "je" to "nous" throughout ("nous avons accumulé",
  "nous sommes obligés"). The original used first person singular. This is a
  significant fidelity error — the model reframed a personal note as a collective
  statement.
- `magistral-medium-2509`: preserved the first-person voice, used precise technical
  terms (`try-except` with correct dash, `Pydantic Settings` with correct casing),
  produced clean transitions (Premièrement / Deuxièmement / Enfin), and was more
  concise without losing content.

**magistral-medium-latest confirmed as primary.**

Mistral-medium is the recommended fallback: lighter and faster than mistral-large,
with acceptable quality for extended transcriptions when magistral-medium is unavailable.

> Further testing needed: mistral-large on English content (the "nous" phenomenon
> may be specific to French); comparison with magistral-large-latest.

---

## History extraction model

| Role     | Model                   |
| -------- | ----------------------- |
| Primary  | `devstral-small-latest` |
| Fallback | `mistral-small-latest`  |

**Why devstral-small:**
History extraction is a structured extraction task, not a reasoning task. The model must
parse existing bullets, identify new facts from the voice note, merge/deduplicate, and
respect strict output format rules (`- bullet`, no timestamps, max N entries). The
critical quality is instruction-following discipline — not hallucinating, not inventing
bullets, not drifting from the format. This is the same quality that makes devstral-small
the primary for the SHORT tier.

Using a reasoning model (magistral-small) here would create rate-limit contention with
the MEDIUM refinement tier (80–240 words), which is the most frequent use case.
Devstral-small runs on a separate quota, is faster (×1.0), and cheaper — all
advantages for a background task where the user is not waiting.

---

## Summary table (current defaults)

| Tier    | Words  | Primary                   | Fallback                 | Status       |
| ------- | ------ | ------------------------- | ------------------------ | ------------ |
| SHORT   | < 80   | `devstral-small-latest`   | `mistral-small-latest`   | ✅ Confirmed |
| MEDIUM  | 80–240 | `magistral-small-latest`  | `mistral-medium-latest`  | ✅ Confirmed |
| LONG    | > 240  | `magistral-medium-latest` | `mistral-medium-latest`  | ✅ Confirmed |
| HISTORY | any    | `devstral-small-latest`   | `mistral-small-latest`   | ✅ Confirmed |

All values are overridable via `.env` — see `.env.example` for the full list of
configurable parameters.

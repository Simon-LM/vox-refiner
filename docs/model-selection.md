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

| Role     | Model                   | Parameters                    |
| -------- | ----------------------- | ----------------------------- |
| Primary  | `mistral-small-latest`  | `temperature=0.2, top_p=0.85` |
| Fallback | `mistral-medium-latest` | Mistral defaults              |

**Why mistral-small as default:**
`devstral-small-latest` is deprecated (end of life: 2026-03-31). `mistral-small-latest`
v4 is a MoE model that integrates devstral-small as one of its experts — it inherits
the instruction-following discipline needed for short transcriptions (no paraphrasing,
no added content) while covering the full range of content types (technical and
conversational). `mistral-medium-latest` serves as a reliable fallback.

---

## Tier 2 — MEDIUM (80–240 words)

| Role     | Model                   | Parameters                                           |
| -------- | ----------------------- | ---------------------------------------------------- |
| Primary  | `mistral-small-latest`  | `temperature=0.3, top_p=0.9, reasoning_effort=high`  |
| Fallback | `mistral-medium-latest` | Mistral defaults                                     |

**Why mistral-small + reasoning_effort=high (was magistral-small):**
Mistral Small 4 with `reasoning_effort=high` provides similar quality to Magistral Small
(same underlying model architecture) but is faster and cheaper. The reasoning mode
activates chain-of-thought when needed without the full overhead of a dedicated reasoning
model. `temperature=0.3` and `top_p=0.9` keep the output faithful to the original text
while allowing natural lexical diversity. Fallback uses Mistral defaults for reliability.

---

## Tier 3 — LONG (> 240 words)

| Role     | Model                     | Parameters                   |
| -------- | ------------------------- | ---------------------------- |
| Primary  | `magistral-medium-latest` | `temperature=0.4, top_p=0.9` |
| Fallback | `mistral-medium-latest`   | Mistral defaults             |

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

**Why mistral-small:**
History extraction is a structured extraction task: parse existing bullets, identify new
facts, merge/deduplicate, and respect strict output format rules (`- bullet`, no
timestamps, max N entries). The critical quality is instruction-following discipline —
not hallucinating, not inventing bullets, not drifting from the format.

`mistral-small-latest` v4 (MoE with devstral-small) covers this well: fast, cheap, and
no rate-limit contention with the MEDIUM refinement tier (magistral-small). As a
background task where the user is not waiting, it is the right balance of quality and
cost. Upgrade to `devstral-latest` via `.env` if extraction quality proves insufficient.

---

## Summary table (current defaults)

| Tier | Words | Primary | Fallback | Key params | Status |
| --- | --- | --- | --- | --- | --- |
| SHORT | < 80 | `mistral-small-latest` | `mistral-medium-latest` | temp=0.2, top_p=0.85 | Confirmed |
| MEDIUM | 80-240 | `mistral-small-latest` | `mistral-medium-latest` | temp=0.3, top_p=0.9, reasoning=high | Confirmed |
| LONG | > 240 | `magistral-medium-latest` | `mistral-medium-latest` | temp=0.4, top_p=0.9 | Confirmed |
| HISTORY | any | `mistral-small-latest` | `mistral-medium-latest` | reasoning=high | Confirmed |

All model and parameter values are overridable via `.env` — see `.env.example` for the
full list of configurable parameters. Per-tier parameters (temperature, top_p,
reasoning_effort) are only applied to the primary model; fallbacks use Mistral defaults
for maximum reliability.

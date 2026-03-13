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
| Primary  | `mistral-small-latest`  |
| Fallback | `devstral-small-latest` |

**Why mistral-small as default:**
Devstral-small excels on technical short notes (code, paths, API names) but
mistral-small is a safer default for general use (reminders, messages, mixed content).
Devstral-small is still the recommended primary for developers — override via
`REFINE_MODEL_SHORT=devstral-small-latest` in `.env`.

---

## Tier 2 — MEDIUM (80–240 words)

| Role     | Model                    |
| -------- | ------------------------ |
| Primary  | `mistral-medium-latest`  |
| Fallback | `magistral-small-latest` |

**Why mistral-medium as default:**
mistral-medium is fast, reliable and produces clean output without the chain-of-thought
latency of magistral models. For medium texts (80–240 words) this is a good balance
between quality and speed. Magistral-small remains available as fallback and as
the recommended primary for users who prefer reasoning-model quality
(`REFINE_MODEL_MEDIUM=magistral-small-latest`).

---

## Tier 3 — LONG (> 240 words)

| Role     | Model                     |
| -------- | ------------------------- |
| Primary  | `magistral-medium-latest` |
| Fallback | `mistral-large-latest`    |

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

Mistral Large remains the fallback: when magistral-medium is unavailable, its output
quality is still acceptable despite the "nous" drift.

> Further testing needed: mistral-large on English content (the "nous" phenomenon
> may be specific to French); comparison with magistral-large-latest.

---

## Summary table (current defaults)

| Tier    | Words  | Primary                  | Fallback                  | Status       |
| ------- | ------ | ------------------------ | ------------------------- | ------------ |
| SHORT   | < 80   | `mistral-small-latest`   | `devstral-small-latest`   | ✅ Confirmed |
| MEDIUM  | 80–240 | `mistral-medium-latest`  | `magistral-small-latest`  | ✅ Confirmed |
| LONG    | > 240  | `mistral-medium-latest`  | `magistral-medium-latest` | ✅ Confirmed |
| HISTORY | any    | `magistral-small-latest` | `mistral-medium-latest`   | ✅ Confirmed |

All values are overridable via `.env` — see `.env.example` for the full list of
configurable parameters.

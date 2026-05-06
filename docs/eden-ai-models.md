<!-- @format -->

# Eden AI — Model Catalog & Integration Strategy

> **Status: Integrated.** Eden AI is live in `src/providers.py` as a fallback layer.
> This document describes the model catalog and integration strategy.

---

## Why Eden AI

Eden AI is a meta-API aggregator that provides a single, OpenAI-compatible chat
endpoint for models from multiple providers (xAI, Perplexity, Google, Mistral,
Amazon Bedrock, OVHcloud). For VoxRefiner it offers:

- **Redundancy** — alternative route to Mistral when the native API is rate-limited
- **Provider diversity** — access to Grok, Perplexity, Gemini, and European
  (OVH) models behind a single key
- **Unified billing** — single invoice across all providers
- **Sovereignty option** — OVHcloud models are Europe-hosted and currently free
  (but may be unstable / relocated without notice)

### Priority rules (reference)

1. **Direct Mistral API** for refinement / insight / summary (rate-limit-aware)
2. **Direct xAI API** for Twitter/X fact-check (Grok's native search)
3. **Eden AI** only as fallback or for models that have no direct path (Gemini,
   Perplexity Sonar, OVH)

---

## Endpoint

```http
POST https://api.edenai.run/v3/llm/chat/completions
Authorization: Bearer ${EDENAI_API_KEY}
```

Payload is OpenAI-compatible. Model identifier format: `provider/model-name`.

Web search (Gemini only):

```json
"web_search_options": { "search_context_size": "low" | "medium" | "high" }
```

> ⚠️ Do **not** send `web_search_options` to Perplexity models — their internal
> retrieval engine already drives the search; adding the flag can override or
> conflict with it.

---

## Model catalog

### xAI — Grok family

| Model ID (Eden)                           | Use case                  | Notes                                                    |
| ----------------------------------------- | ------------------------- | -------------------------------------------------------- |
| `xai/grok-4.20-multi-agent-beta-0309`     | General chat + web search | Primary Eden route for Grok (maps to `grok-4.3` direct)  |
| `xai/grok-4.20-beta-0309-non-reasoning`   | Pure generation, no CoT   | Fastest Grok path via Eden                               |
| `xai/grok-4.20-beta-0309-reasoning`       | Reasoning tasks           | CoT enabled                                              |

> Models `grok-4-1-fast*` and `grok-4-latest` were retired by xAI on 2026-05-15.
> Backward-compat entries in `EDEN_MODEL_MAP` redirect them to `xai/grok-4.20-multi-agent-beta-0309`.

**Direct API preferred** for fact-check / X search (native tool-use, `grok-4.3`).
Eden route (`xai/grok-4.20-multi-agent-beta-0309`) serves as fallback — X search not available via Eden.

### Perplexity — Sonar family

| Model ID (Eden)                       | Use case                  | Notes                                           |
| ------------------------------------- | ------------------------- | ----------------------------------------------- |
| `perplexityai/sonar-pro`              | Web-grounded Q&A          | Built-in web search — no `web_search_options`   |
| `perplexityai/sonar-deep-research`    | Multi-hop deep research   | Slower, heavier — reserve for explicit command  |

### Google — Gemini family

| Model ID (Eden)                | Use case                           | Notes                                          |
| ------------------------------ | ---------------------------------- | ---------------------------------------------- |
| `google/gemini-flash-latest`   | Fast, low-cost general chat        | Accepts `web_search_options` (low/medium/high) |
| `google/gemini-pro-latest`     | High-quality reasoning / long ctx  | Accepts `web_search_options`                   |

### Mistral — via Eden (redundancy only)

| Model ID (Eden)                   | Direct-API equivalent     | When to use Eden route                                       |
| --------------------------------- | ------------------------- | ------------------------------------------------------------ |
| `mistral/mistral-small-latest`    | `mistral-small-latest`    | Only if direct API is rate-limited                           |
| `mistral/mistral-medium-latest`   | `mistral-medium-latest`   | Only if direct API is rate-limited                           |
| `mistral/mistral-large-latest`    | `mistral-large-latest`    | Only if direct API is rate-limited                           |
| `mistral/magistral-small-latest`  | `magistral-small-latest`  | Substitute for `mistral-small` + `reasoning_effort` on Eden  |
| `mistral/magistral-medium-latest` | `magistral-medium-latest` | Only if direct API is rate-limited                           |

> Default remains the direct Mistral API. Eden-Mistral is purely a resilience path.

### Amazon Bedrock

| Model ID (Eden)                              | Notes                            |
| -------------------------------------------- | -------------------------------- |
| `amazon/mistral.mistral-large-2402-v1:0`     | Mistral-Large hosted on Bedrock  |

### OVHcloud — sovereign / free tier

| Model ID (Eden)                               | Notes                                       |
| --------------------------------------------- | ------------------------------------------- |
| `ovhcloud/Mistral-Small-3.2-24B-Instruct-2506` | Europe-hosted; free but unstable           |
| `ovhcloud/Mistral-7B-Instruct-v0.3`           | Legacy 7B, low cost                         |
| `ovhcloud/Mixtral-8x7B-Instruct-v0.1`         | MoE baseline                                |
| `ovhcloud/Meta-Llama-3_3-70B-Instruct`        | Non-Mistral option                          |
| `ovhcloud/Llama-3.1-8B-Instruct`              | Lightweight Llama                           |
| `ovhcloud/Qwen2.5-Coder-32B-Instruct`         | Code-oriented                               |
| `ovhcloud/DeepSeek-R1-Distill-Llama-70B`      | Reasoning (R1 distill)                      |

> ⚠️ OVH model IDs change frequently (models are added, retired, renamed
> without notice). **Run `tests/ping_eden_models.py` before relying on any OVH
> model in a release.**

---

## Integration reference

Eden AI is integrated in `src/providers.py`. Key structures:

- **`EDEN_MODEL_MAP`** — translates canonical model names (`grok-4.3`, `sonar-pro`…)
  to Eden provider IDs (`xai/grok-4.20-multi-agent-beta-0309`, `perplexityai/sonar-pro`…).
  Backward-compat entries for retired model names are included.
- **`EDEN_FALLBACK_CHAINS`** — server-side fallback order within the Eden route,
  keyed by Eden provider ID.
- **`eden_xai` / `eden_perplexity` / `eden_mistral`** — registered provider instances
  with `adapter_type="eden"` and a `ping_model_id` for availability checks.

Priority rule: direct API (Mistral, xAI, Perplexity) is always tried first.
Eden is used only as fallback (rate-limit or unavailability) or for models
with no direct path (Gemini, OVH).

---

## OCR endpoint — async path

Eden AI exposes OCR via a **different endpoint** from the chat API (async job model):

```http
POST https://api.edenai.run/v3/universal-ai/async
Authorization: Bearer ${EDENAI_API_KEY}
Content-Type: application/json

{
  "model": "ocr/ocr_async/mistral",
  "input": { ... },
  "show_original_response": false
}
```

Response:

```json
{ "public_id": "<job-id>" }
```

Then **poll** the job endpoint until completed:

```http
GET https://api.edenai.run/v3/universal-ai/async/<job-id>
```

> This endpoint is intentionally separate from the LLM chat endpoint.
> Do **not** send it to `EDEN_CHAT_URL` (`/v3/llm/chat/completions`).

In `src/providers.py` this path is registered as the `eden_ocr_mistral` provider
with `adapter_type="eden_ocr"`. The `call()` helper raises `ProviderError` if
you attempt to route OCR via `call()` — use the dedicated `call_ocr_async()`
function (to be implemented when the OCR fallback flow is wired).

---

## Availability check

See [tests/ping_eden_models.py](../tests/ping_eden_models.py) — a standalone
script that issues a minimal chat request against every model listed above and
prints a pass/fail matrix. Also pings the OCR async endpoint (job creation
only — does not wait for completion). Run it before each release, and any time
an OVH model misbehaves.

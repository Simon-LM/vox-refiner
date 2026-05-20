#!/usr/bin/env python3
"""VoxRefiner — Fact-checking.

Verifies the main factual claims of a text summary using one or both of
Perplexity (web) and Grok (web + X), then synthesises the results with Mistral.

CLI:
  python -m src.factcheck
      Reads context summary from stdin.
      Optional env INSIGHT_QUERY for a targeted hint.
      Writes synthesis (or direct result) to stdout.
      Writes full Perplexity detail to INSIGHT_PERPLEXITY_FILE (if set).
      Writes full Grok detail to INSIGHT_GROK_FILE (if set).

All progress/status messages go to stderr so stdout can be captured by the shell.

Environment variables (loaded from .env):
  MISTRAL_API_KEY           — required for synthesis
  PERPLEXITY_API_KEY        — enables Perplexity fact-check
  XAI_API_KEY               — enables Grok fact-check (web + X)
  EDENAI_API_KEY            — fallback for all providers

  INSIGHT_SYNTHESIS_MODEL   — Mistral model for synthesis (default: mistral-small-latest)
  INSIGHT_SYNTHESIS_REASONING — reasoning effort: standard | high (default: standard)
  INSIGHT_FACTCHECK_ENGINE  — fact-check sources: both | perplexity | grok (default: both)
  INSIGHT_QUERY             — optional targeted aspect to verify (CLI only)
  INSIGHT_PERPLEXITY_FILE   — path to write full Perplexity detail (CLI only)
  INSIGHT_GROK_FILE         — path to write full Grok detail (CLI only)
  OUTPUT_DEFAULT_LANG       — default output language code (e.g. fr, en).
                               Falls back to TRANSLATE_TARGET_LANG when unset.
"""

import os
import sys
import textwrap
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from src.common import log_call_result, with_lang               # noqa: E402
from src.providers import ProviderError, call, is_available     # noqa: E402
from src.search import search_grok, search_perplexity           # noqa: E402
from src.ui_py import error, info, process, success, warn       # noqa: E402

# ── Models ────────────────────────────────────────────────────────────────────
_SYNTHESIS_MODEL     = os.environ.get("INSIGHT_SYNTHESIS_MODEL",     "mistral-small-latest")
_SYNTHESIS_REASONING = os.environ.get("INSIGHT_SYNTHESIS_REASONING", "standard")

# ── Behaviour flags ───────────────────────────────────────────────────────────
_FACTCHECK_ENGINE = os.environ.get("INSIGHT_FACTCHECK_ENGINE", "both")

# ── Timeouts ──────────────────────────────────────────────────────────────────
_SYNTHESIS_TIMEOUT = 20

# ── Language override ─────────────────────────────────────────────────────────
_OUTPUT_LANG = (
    os.environ.get("OUTPUT_DEFAULT_LANG", "").strip().lower()
    or os.environ.get("TRANSLATE_TARGET_LANG", "").strip().lower()
)

# ── Prompts ───────────────────────────────────────────────────────────────────

_FACTCHECK_PERPLEXITY_SYSTEM = with_lang(textwrap.dedent("""
    You are a fact-checking assistant. You will receive a summary of a piece of
    content the user has selected. Your task is to verify the main factual claims
    using your web search capability.

    RULES:
    - Assess the main claims: are they confirmed, contested, or unverifiable?
    - Cite 1-3 sources briefly (name + date if available).
    - Write 3 to 5 sentences.
    - Write in the same language as the input summary.
    - Plain text only, no markdown.
    - Be factual and neutral — no opinion.
""").strip(), _OUTPUT_LANG)

_FACTCHECK_GROK_SYSTEM = with_lang(textwrap.dedent("""
    You are a fact-checking assistant with access to real-time web search and
    X (formerly Twitter) posts via Grok. Use BOTH sources to verify the main
    claims in the summary you receive.

    - Web search: verify against official sources, news, and scientific literature.
    - X search: check for reactions, corrections, expert opinions, and real-time context.

    RULES:
    - Assess the main claims: are they confirmed, contested, or unverifiable?
    - Note any significant divergence between web sources and X reactions.
    - Cite 1-3 sources briefly (name + date if available).
    - Write 3 to 5 sentences.
    - Write in the same language as the input summary.
    - Plain text only, no markdown.
    - Be factual and neutral.
""").strip(), _OUTPUT_LANG)

_SYNTHESIS_SYSTEM = with_lang(textwrap.dedent("""
    You are a fact-checking synthesis assistant for visually impaired users.
    You will receive two fact-checking reports on the same content:
    - Report A: from Perplexity (web search — general sources).
    - Report B: from Grok (combined web + X search).

    Your task: produce a short spoken-word verdict.

    OUTPUT FORMAT (plain text, no markdown, same language as the reports):
    Line 1: "Reliability: [Confirmed / Contested / Unverifiable / Mixed]"
    Line 2: blank line
    Line 3-4: 2-sentence synthesis of what both sources say.
    Line 5: blank line
    Line 6: "Perplexity: [1 sentence summarising Report A]"
    Line 7: "Grok: [1 sentence summarising Report B]"

    If the two reports contradict each other, start line 3 with:
    "The two sources diverge: [explain briefly]"

    RULES:
    - Plain text only.
    - Write in the same language as the reports.
    - Do NOT add any preamble or commentary.
    - If one report is missing or empty, note it: "Source unavailable."
""").strip(), _OUTPUT_LANG)


# ── Public API ────────────────────────────────────────────────────────────────

def factcheck(
    context_summary: str,
    query_hint: str = "",
) -> tuple[str, str, str]:
    """Run an adaptive fact-check.

    - Both keys available: Perplexity (web) + Grok (web+X) in parallel →
      Mistral synthesis.
    - One key only: direct result from that source (no Mistral call needed).

    Args:
        context_summary: bullet summary of the selected text.
        query_hint: optional targeted aspect to verify (empty = full article).

    Returns:
        (synthesis_or_direct_result, perplexity_detail, grok_detail)
        Any unavailable source is represented as an empty string.

    Raises RuntimeError if synthesis provider is missing or no source is available.
    """
    _has_search  = is_available("search")
    _has_grok    = is_available("fact_check_x")
    _has_insight = is_available("insight")

    if not _has_insight:
        raise RuntimeError(
            "No provider available for synthesis. "
            "Set MISTRAL_API_KEY or EDENAI_API_KEY."
        )

    if not _has_search and not _has_grok:
        raise RuntimeError(
            "No fact-check source available. "
            "Set PERPLEXITY_API_KEY, XAI_API_KEY, or EDENAI_API_KEY."
        )

    query = query_hint if query_hint else "Verify the main factual claims in this content."

    perplexity_result: str = ""
    grok_result: str       = ""

    _use_perplexity = _has_search and _FACTCHECK_ENGINE in ("both", "perplexity", "auto")
    _use_grok       = _has_grok   and _FACTCHECK_ENGINE in ("both", "grok",       "auto")
    if _FACTCHECK_ENGINE == "auto":
        _use_perplexity = _has_search
        _use_grok       = _has_grok

    if not _use_perplexity and not _use_grok:
        raise RuntimeError(
            f"No fact-check source available for engine '{_FACTCHECK_ENGINE}'. "
            "Check API keys and INSIGHT_FACTCHECK_ENGINE setting."
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        tasks: dict = {}
        if _use_perplexity:
            tasks["perplexity"] = pool.submit(
                search_perplexity, query, context_summary, _FACTCHECK_PERPLEXITY_SYSTEM
            )
        if _use_grok:
            tasks["grok"] = pool.submit(
                search_grok, query, context_summary, _FACTCHECK_GROK_SYSTEM
            )

        for name, future in tasks.items():
            try:
                r = future.result()
                if name == "perplexity":
                    perplexity_result = r
                else:
                    grok_result = r
            except Exception as exc:
                warn(f"Fact-check source failed — {name}: {exc}")

    if not perplexity_result and not grok_result:
        raise RuntimeError(
            "All fact-check sources failed. Check API keys and connection."
        )

    if not _use_perplexity:
        info(f"Perplexity skipped (engine: {_FACTCHECK_ENGINE}).")
    if not _use_grok:
        info(f"Grok skipped (engine: {_FACTCHECK_ENGINE}).")

    if not (perplexity_result and grok_result):
        direct = perplexity_result or grok_result
        return direct, perplexity_result, grok_result

    synthesis_user = (
        f"Report A (Perplexity — web search):\n{perplexity_result}\n\n"
        f"Report B (Grok — web + X search):\n{grok_result}"
    )

    opts: dict = {
        "model":       _SYNTHESIS_MODEL,
        "temperature": 0.2,
        "timeout":     _SYNTHESIS_TIMEOUT,
    }
    if _SYNTHESIS_REASONING == "high":
        opts["reasoning_effort"] = "high"

    process("Synthesising fact-check results...")
    try:
        result = call(
            "insight",
            [
                {"role": "system", "content": _SYNTHESIS_SYSTEM},
                {"role": "user",   "content": synthesis_user},
            ],
            **opts,
        )
    except ProviderError as exc:
        raise RuntimeError(f"Fact-check synthesis failed: {exc}") from exc

    log_call_result(result, label="Fact-check synthesis")
    success(f"Synthesis ready ({len(result.text)} chars).")
    return result.text, perplexity_result, grok_result


# ── CLI entry point ───────────────────────────────────────────────────────────

def _cmd_factcheck() -> None:
    context_summary = sys.stdin.read().strip()
    query_hint = os.environ.get("INSIGHT_QUERY", "")

    if not is_available("insight"):
        print(
            "❌ No provider available for synthesis.\n"
            "   Add MISTRAL_API_KEY or EDENAI_API_KEY to your .env file.",
            file=sys.stderr,
        )
        sys.exit(1)

    if not is_available("search") and not is_available("fact_check_x"):
        print(
            "❌ No fact-check source available.\n"
            "   Add PERPLEXITY_API_KEY, XAI_API_KEY, or EDENAI_API_KEY to your .env file.",
            file=sys.stderr,
        )
        sys.exit(2)

    try:
        synthesis, perplexity_detail, grok_detail = factcheck(
            context_summary, query_hint
        )
    except RuntimeError as exc:
        error(str(exc))
        sys.exit(1)

    perplexity_file = os.environ.get("INSIGHT_PERPLEXITY_FILE", "")
    if perplexity_file and perplexity_detail:
        Path(perplexity_file).write_text(perplexity_detail, encoding="utf-8")

    grok_file = os.environ.get("INSIGHT_GROK_FILE", "")
    if grok_file and grok_detail:
        Path(grok_file).write_text(grok_detail, encoding="utf-8")

    print(synthesis)


if __name__ == "__main__":
    _cmd_factcheck()

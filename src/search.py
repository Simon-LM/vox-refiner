#!/usr/bin/env python3
"""VoxRefiner — Web search.

Provides a single web-search capability callable as a CLI module or imported
by other modules (factcheck, reminder daemon, …).

CLI:
  python -m src.search
      Reads from stdin: first line = query, remaining lines = context summary.
      Writes answer to stdout.
      Engine selection: INSIGHT_SEARCH_ENGINE (auto / perplexity / grok / both).

All progress/status messages go to stderr so stdout can be captured by the shell.

Environment variables (loaded from .env):
  PERPLEXITY_API_KEY        — enables Perplexity search
  XAI_API_KEY               — enables Grok search (web + X)
  EDENAI_API_KEY            — fallback for both

  INSIGHT_PERPLEXITY_MODEL  — Perplexity model (default: sonar-pro)
  INSIGHT_GROK_MODEL        — Grok model (default: grok-4.3)
  INSIGHT_SYNTHESIS_MODEL   — Mistral model for dual-engine synthesis (default: mistral-small-latest)
  INSIGHT_SEARCH_ENGINE     — search engine: auto | perplexity | grok | both
                               auto = Perplexity if available, else Grok (default)
  OUTPUT_DEFAULT_LANG       — default output language code (e.g. fr, en).
                               Falls back to TRANSLATE_TARGET_LANG when unset.
"""

import os
import sys
import textwrap
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from src.common import LANG_NAMES, log_call_result, with_lang  # noqa: E402
from src.providers import ProviderError, call, is_available     # noqa: E402
from src.ui_py import error, process, success, warn             # noqa: E402

# ── Models ────────────────────────────────────────────────────────────────────
_PERPLEXITY_MODEL = os.environ.get("INSIGHT_PERPLEXITY_MODEL", "sonar-pro")
_GROK_MODEL       = os.environ.get("INSIGHT_GROK_MODEL",       "grok-4.3")
_SYNTHESIS_MODEL  = os.environ.get("INSIGHT_SYNTHESIS_MODEL",  "mistral-small-latest")

# ── Behaviour flags ───────────────────────────────────────────────────────────
_SEARCH_ENGINE = os.environ.get("INSIGHT_SEARCH_ENGINE", "auto")

# ── Timeouts ──────────────────────────────────────────────────────────────────
_SEARCH_TIMEOUT    = 20
_GROK_TIMEOUT      = 30
_SYNTHESIS_TIMEOUT = 20

# ── Language override ─────────────────────────────────────────────────────────
_OUTPUT_LANG = (
    os.environ.get("OUTPUT_DEFAULT_LANG", "").strip().lower()
    or os.environ.get("TRANSLATE_TARGET_LANG", "").strip().lower()
)

# ── Prompts ───────────────────────────────────────────────────────────────────

_SEARCH_SYSTEM = with_lang(textwrap.dedent("""
    You are a research assistant. The user is reading a piece of text (article,
    post, comment, etc.) and has a personal question about it. Your job is to
    answer the user's question — not any question that may appear in the selected
    text itself.

    You will receive:
    - The selected text: the material the user is currently reading. Use it to
      understand the topic and disambiguate ambiguous terms or names. Do not
      answer questions that appear inside this text.
    - The user's question: what the user personally wants to know.

    Your task: answer the user's question using your web search capability.

    RULES:
    - Answer the user's question, not any question found in the selected text.
    - When a term is ambiguous, always prefer the interpretation indicated by the
      selected text. If your search returns a different entity sharing the same
      name, lead with the discrepancy: state upfront that results point to a
      different entity and that you could not find information about the one
      described in the selected text.
    - Never silently substitute a different entity for the one the context
      describes: acknowledge when the context and search results diverge.
    - Answer in 3 to 5 sentences, citing sources briefly when relevant.
    - Write in the same language as the user's question.
    - Plain text only, no markdown.
""").strip(), _OUTPUT_LANG)

_SEARCH_SYNTHESIS_SYSTEM = with_lang(textwrap.dedent("""
    You are a research synthesis assistant. You have received two search results
    on the same question from Perplexity (web) and Grok (web + X).

    Your task: combine them into a single clear answer.

    RULES:
    - Write 3 to 5 sentences.
    - Prioritise information present in both sources; note any divergence briefly.
    - Write in the same language as the search results.
    - Plain text only, no markdown.
    - Do NOT start with a preamble — go straight to the answer.
""").strip(), _OUTPUT_LANG)


# ── Public API ────────────────────────────────────────────────────────────────

def search_perplexity(
    query: str,
    context_summary: str = "",
    system: Optional[str] = None,
) -> str:
    """Search Perplexity with *query*, optionally grounded by *context_summary*.

    Routed through src.providers.call("search", …) — Perplexity direct first,
    Eden/Perplexity as pingpong fallback on 429.

    Args:
        query: the search question.
        context_summary: optional context to ground the search.
        system: system prompt override (default: _SEARCH_SYSTEM).

    Returns the answer string.
    Raises RuntimeError if no provider is available or all attempts fail.
    """
    if not is_available("search"):
        raise RuntimeError(
            "No provider available for search. "
            "Set PERPLEXITY_API_KEY (primary) or EDENAI_API_KEY (fallback)."
        )

    if system is None:
        system = _SEARCH_SYSTEM

    user_content = query
    if context_summary:
        user_content = (
            f"Selected text (what the user is reading — context only, not a question to answer):\n{context_summary}\n\n"
            f"User's question: {query}"
        )

    process("Searching Perplexity...")
    try:
        result = call(
            "search",
            [
                {"role": "system", "content": system},
                {"role": "user",   "content": user_content},
            ],
            model=_PERPLEXITY_MODEL,
            timeout=_SEARCH_TIMEOUT,
        )
    except ProviderError as exc:
        raise RuntimeError(f"Perplexity search failed: {exc}") from exc

    log_call_result(result, label="Perplexity")
    success(f"Perplexity answer ready ({len(result.text)} chars).")
    return result.text


def search_grok(
    query: str,
    context_summary: str = "",
    system: Optional[str] = None,
) -> str:
    """Search using Grok (web_search + x_search) via the fact_check_x capability.

    Routed through src.providers.call("fact_check_x", …) — xAI direct with
    sticky policy (Eden is last-resort fallback only). Sticky because Eden
    does not expose the native X/Twitter search tool.

    Args:
        query: the search query.
        context_summary: optional context to ground the search.
        system: system prompt override (default: _SEARCH_SYSTEM).

    Returns the answer string.
    Raises RuntimeError if no provider is available or all attempts fail.
    """
    if not is_available("fact_check_x"):
        raise RuntimeError(
            "No provider available for fact_check_x. "
            "Set XAI_API_KEY (primary) or EDENAI_API_KEY (fallback)."
        )

    if system is None:
        system = _SEARCH_SYSTEM

    user_content = query
    if context_summary:
        user_content = (
            f"Selected text (what the user is reading — context only, not a question to answer):\n{context_summary}\n\n"
            f"User's question: {query}"
        )

    process("Searching with Grok (web + X)...")
    try:
        result = call(
            "fact_check_x",
            [
                {"role": "system", "content": system},
                {"role": "user",   "content": user_content},
            ],
            model=_GROK_MODEL,
            timeout=_GROK_TIMEOUT,
        )
    except ProviderError as exc:
        raise RuntimeError(f"Grok search failed: {exc}") from exc

    if not result.text:
        raise RuntimeError("Grok returned an empty response.")

    log_call_result(result, label="Grok")
    success(f"Grok answer ready ({len(result.text)} chars).")
    return result.text


def search(query: str, context_summary: str = "") -> str:
    """Dispatch a search query to the configured engine.

    Engine selection (INSIGHT_SEARCH_ENGINE):
      auto        → Perplexity if key available, else Grok (default)
      perplexity  → force Perplexity
      grok        → force Grok
      both        → run both in parallel, synthesise with Mistral

    Returns the answer string.
    Raises RuntimeError if no engine is available or configured engine is missing.
    """
    engine = _SEARCH_ENGINE
    _has_search = is_available("search")
    _has_grok   = is_available("fact_check_x")

    if engine == "auto":
        if _has_search:
            return search_perplexity(query, context_summary)
        if _has_grok:
            return search_grok(query, context_summary)
        raise RuntimeError(
            "No search engine available. "
            "Set PERPLEXITY_API_KEY, XAI_API_KEY, or EDENAI_API_KEY."
        )

    if engine == "perplexity":
        if not _has_search:
            raise RuntimeError(
                "No provider available for Perplexity search. "
                "Set PERPLEXITY_API_KEY or EDENAI_API_KEY."
            )
        return search_perplexity(query, context_summary)

    if engine == "grok":
        if not _has_grok:
            raise RuntimeError(
                "No provider available for Grok search. "
                "Set XAI_API_KEY or EDENAI_API_KEY."
            )
        return search_grok(query, context_summary)

    if engine == "both":
        if not _has_search and not _has_grok:
            raise RuntimeError(
                "INSIGHT_SEARCH_ENGINE=both requires PERPLEXITY_API_KEY, "
                "XAI_API_KEY, or EDENAI_API_KEY."
            )
        perp_result = ""
        grok_result = ""
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures: dict = {}
            if _has_search:
                futures["perplexity"] = pool.submit(search_perplexity, query, context_summary)
            if _has_grok:
                futures["grok"] = pool.submit(search_grok, query, context_summary)
            for name, future in futures.items():
                try:
                    r = future.result()
                    if name == "perplexity":
                        perp_result = r
                    else:
                        grok_result = r
                except Exception as exc:
                    warn(f"{name} search failed: {exc}")

        if not perp_result and not grok_result:
            raise RuntimeError("Both search engines failed.")
        if not perp_result or not grok_result:
            return perp_result or grok_result

        if not is_available("insight"):
            return f"{perp_result}\n\n{grok_result}"

        synth_user = (
            f"Perplexity result:\n{perp_result}\n\n"
            f"Grok result:\n{grok_result}"
        )
        process("Synthesising search results...")
        try:
            result = call(
                "insight",
                [
                    {"role": "system", "content": _SEARCH_SYNTHESIS_SYSTEM},
                    {"role": "user",   "content": synth_user},
                ],
                model=_SYNTHESIS_MODEL,
                temperature=0.2,
                timeout=_SYNTHESIS_TIMEOUT,
            )
        except ProviderError:
            return f"{perp_result}\n\n{grok_result}"

        log_call_result(result, label="Search synthesis")
        success(f"Search synthesis ready ({len(result.text)} chars).")
        return result.text

    raise RuntimeError(
        f"Unknown INSIGHT_SEARCH_ENGINE: {engine!r}. "
        "Supported values: auto, perplexity, grok, both."
    )


# ── CLI entry point ───────────────────────────────────────────────────────────

def _cmd_search() -> None:
    raw = sys.stdin.read()
    lines = raw.splitlines()
    if not lines:
        error("Empty input.")
        sys.exit(1)
    query = lines[0].strip()
    context_summary = "\n".join(lines[1:]).strip()

    if not query:
        error("Empty query.")
        sys.exit(1)

    if not is_available("search") and not is_available("fact_check_x"):
        print(
            "❌ No search engine available.\n"
            "   Add PERPLEXITY_API_KEY, XAI_API_KEY, or EDENAI_API_KEY to your .env file.",
            file=sys.stderr,
        )
        sys.exit(2)

    try:
        result = search(query, context_summary)
    except RuntimeError as exc:
        error(str(exc))
        sys.exit(1)

    print(result)


if __name__ == "__main__":
    _cmd_search()

#!/usr/bin/env python3
"""Voxtral TTS: convert text to speech using the speaker's voice.

Calls the Mistral audio.speech API with an optional voice sample for cloning.
"""

import asyncio
import base64
import os
import re
import sys
import textwrap
import unicodedata
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv
from src.ui_py import BG_BLUE, BGREEN, RESET, WHITE

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

_API_URL = "https://api.mistral.ai/v1/audio/speech"
_MODEL = os.environ.get("TTS_MODEL", "voxtral-mini-tts-2603")

# Default voice when no language mapping or voice sample is available.
# Set TTS_DEFAULT_VOICE_ID="" in .env to use API auto-selection instead.
_DEFAULT_VOICE_ID = os.environ.get("TTS_DEFAULT_VOICE_ID", "c69964a6-ab8b-4f8a-9465-ec0925096ec8")  # Paul - Neutral (EN)

# Preset voice mapping by language code → voice_id (Mistral UUID).
# Only languages with voices currently available in the API are listed.
# French voices (all Marie): neutral, happy, sad, excited, curious, angry.
# English voices: Paul (en_us) + Oliver/Jane (en_gb) with emotion variants.
# Other languages: no Mistral preset voices available yet.
#   fr_marie_neutral 5a271406-039d-46fe-835b-fbbb00eaf08d  ← default fr
#   fr_marie_happy   49d024dd-981b-4462-bb17-74d381eb8fd7
#   fr_marie_sad     4adeb2c6-25a3-44bc-8100-5234dfc1193b
#   fr_marie_excited 2f62b1af-aea3-4079-9d10-7ca665ee7243
#   fr_marie_curious e0580ce5-e63c-4cbe-88c8-a983b80c5f1f
#   fr_marie_angry   a7c07cdc-1c35-4d87-a938-c610a654f600
#   en_paul_neutral  c69964a6-ab8b-4f8a-9465-ec0925096ec8  ← default en
#   gb_oliver_neutral e3596645-b1af-469e-b857-f18ddedc7652
#   gb_jane_neutral   82c99ee6-f932-423f-a4a3-d403c8914b8d
_LANG_VOICE_MAP: dict[str, str] = {
    "fr": "e0580ce5-e63c-4cbe-88c8-a983b80c5f1f",  # fr_marie_curious
    "en": "c69964a6-ab8b-4f8a-9465-ec0925096ec8",  # en_paul_neutral
    # Other languages not yet available — falls back to TTS_DEFAULT_VOICE_ID.
}

_REQUEST_RETRIES = int(os.environ.get("TTS_REQUEST_RETRIES", "2"))
_RETRY_DELAY = 2.0

_TRANSIENT_HTTP_CODES = (429, 500, 502, 503)

# Mistral voices use UUID format; Gradium voices use short alphanumeric IDs.
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)

_CHUNK_MAX_CHARS = int(os.environ.get("TTS_CHUNK_SIZE", "800"))


# ── AI cleaning: two-call architecture ──────────────────────────────────────
# Call 1 (mistral-small): detect content type — one-word response, fast/cheap.
# Call 2 (devstral):      clean with a focused, type-specific prompt.

_DETECT_MODEL = "mistral-small-latest"
_CLEAN_MODEL  = "devstral-latest"

_DETECT_SYSTEM = textwrap.dedent("""
    You receive raw text copied from a web page or application.
    Identify the content type with a single word from:

      news_article       — press article or blog post
      email              — email message or newsletter
      wikipedia          — encyclopedic article (Wikipedia, Vikidia…)
      social_media       — social network post or thread
      documentation      — technical doc, README, manual, API reference
      assistant_response — AI assistant response (ChatGPT, Claude, Gemini…)
      generic            — any other type

    Reply with the exact word only, no punctuation or explanation.
""").strip()

_CLEAN_COMMON = textwrap.dedent("""
    You are an accessibility assistant for visually impaired users.
    You receive raw text copied from a web page and must prepare it
    for complete audio playback by a TTS engine.

    ABSOLUTE GOAL: the user must hear ALL editorial content, nothing skipped.

    ══════════════════════════════════════════════
    CRITICAL RULE — QUOTATION ISOLATION
    ══════════════════════════════════════════════
    Every passage in quotation marks (« », " " or " ") must be isolated as a
    SEPARATE paragraph, surrounded by a blank line before and after.
    This applies even to a two-word quote. This rule is ABSOLUTE: no exceptions.

    ISOLATION EXAMPLES (reproduce systematically):

    Example 1 — short embedded quote:
      BEFORE: L'entreprise justifie ces départs par «les besoins actuels» selon un communiqué.
      AFTER:
        L'entreprise justifie ces départs par

        «les besoins actuels»

        selon un communiqué.

    Example 2 — multiple quotes in one sentence:
      BEFORE: Il a dit «oui» puis précisé «sous conditions» avant de partir.
      AFTER:
        Il a dit

        «oui»

        puis précisé

        «sous conditions»

        avant de partir.

    Example 3 — long quote with trailing attribution:
      BEFORE: La ministre a déclaré : «Nous allons augmenter le budget de 20%.», ajoutant que la décision était définitive.
      AFTER:
        La ministre a déclaré :

        «Nous allons augmenter le budget de 20%.»

        ajoutant que la décision était définitive.

    ══════════════════════════════════════════════
    OTHER RULES
    ══════════════════════════════════════════════
    - Keep: main title, section headings and subheadings (verbatim),
      full body text (every paragraph without exception).
    - Photo captions: introduce each caption with "Photo d'illustration : " followed by its text.
    - Remove: UI buttons, counters, technical metadata (reading time, standalone photo credit
      such as "AFP/Reuters"), link annotations ("(Nouvelle fenêtre)", "(new window)"),
      raw URLs, email addresses.
    - Output format: plain text, no markdown (no **, *, #, bullet dashes),
      paragraphs separated by a single blank line, no commentary from you.
""").strip()

# Per-type rules appended to _CLEAN_COMMON for call 2.
# Empty string for generic = common rules only.
_CLEAN_RULES: dict[str, str] = {
    "news_article": textwrap.dedent("""
        DETECTED TYPE: press article

        DATE REFORMATTING (apply everywhere in the output):
        Rewrite ALL dates and times into natural spoken French — never leave
        numeric separators (/, :) that the TTS engine would read as "slash" or
        "deux-points":
        - DD/MM/YYYY  → "D mois YYYY"  (e.g. 08/04/2026 → "8 avril 2026")
        - HH:MM       → "HhMM"         (e.g. 06:24 → "6h24", 10:13 → "10h13")
        - DD/MM       → "D mois"       (e.g. 08/04 → "8 avril")
        Apply this rule to the source line, timestamps, and every date in the body.

        OUTPUT ORDER (strictly):
        1. Media name and publication/update info, on one line, formatted as:
           "[Media], publié le [date] à [heure]." — only if present in the selection.
           If media name is absent: "Publié le [date] à [heure]."
           If both published and updated times are present:
           "[Media], publié le [date] à [heure], mis à jour à [heure]."
           This gives essential context before anything else.
        2. Main title (keep verbatim, mandatory)
        3. Chapeau / lead paragraph: the short summary text that appears just below
           the title and above the body — keep it verbatim, it is editorial content.
        4. Author name, on its own line as "Par [name]." — only if present.
        5. Full body text (all paragraphs without exception)

        LIVE BLOG / DIRECT (when the article contains timestamped entries):
        If the article is a live blog (entries prefixed with a time like "10:12"
        or "09:43"), treat each entry as follows:
        - Introduce each entry with: "À [heure], [title if present]."
          e.g. "10:12\nISRAËL : L'ARMÉE OBSERVE…" → "À 10h12, Israël : l'armée observe…"
        - Keep the full text of each entry.
        - This ensures the listener can follow the chronology without visual timestamps.

        REMOVE IN ADDITION:
        - "Lire aussi : [title]", "Sur le même sujet", "À lire aussi", "À voir aussi" blocks
        - Breadcrumbs ("Accueil > Rubrique > …") and navigation menus
        - Newsletter blocks and subscription forms
        - Ad blocks ("PASSER LA PUBLICITÉ", "Publicité", "ANNONCE")
        - "La rédaction vous conseille" section and its links
        - Comment counters, social buttons, share links

        QUOTATION ISOLATION REMINDER (see critical rule above):
        Press articles contain many source quotes. Each quote, even a short one,
        must be on its own paragraph.
          BEFORE: Le PDG a estimé que «la situation est sous contrôle», balayant les critiques.
          AFTER:
            Le PDG a estimé que

            «la situation est sous contrôle»

            balayant les critiques.
    """).strip(),

    "email": textwrap.dedent("""
        DETECTED TYPE: email or newsletter

        KEEP AT THE TOP (if present in the selection) and present them as an introduction:
        - Subject (Objet :) → "Objet : [subject]"
        - Date (Date :) → "Reçu le [date]."
        - Sender name (De :) → "De : [name]."
        - Example intro: "De : Marie Dupont. Reçu le 6 avril 2026. Objet : Réunion de demain."

        REMOVE IN ADDITION:
        - Technical header fields not listed above (À :, Cc :, Cci :, Message-ID…)
        - Auto-footers ("Ce message a été envoyé par…", "Se désabonner",
          "Unsubscribe", "Ce courriel est confidentiel")
        - Automatic company signatures (address, phone, legal notices)
    """).strip(),

    "wikipedia": textwrap.dedent("""
        DETECTED TYPE: encyclopedic article

        REMOVE IN ADDITION:
        - Numeric references [1], [2], [note 1], [réf. nécessaire]
        - Warning banners ("Cet article…", "La neutralité de cet article est contestée")
        - Infobox content duplicated in the body text
        - Categories, "modifier" and "modifier le code" links

        MATH VERBALIZATION:
        Mathematical formulas must be rewritten as natural spoken French so the TTS
        engine reads them intelligibly. Apply these substitutions:
        - f(x)        → f de x
        - f(x, y)     → f de x virgule y
        - nested f(g(x)) → f de g de x
        - X : A → B   → X, fonction de A vers B   (type signature: colon = "fonction de")
        - A → B       → A vers B
        - A = B       → A égal à B
        - × (Cartesian product / type product) → croix
        - ∀f ∈ F      → pour tout f appartenant à F
        - ∃x          → il existe x
        - ∈           → appartient à
        - ∉           → n'appartient pas à
        - ⊂           → est inclus dans
        - ∩           → intersecté avec
        - ∪           → uni à

        Examples:
          BEFORE: K : N → PK × SK : la fonction de génération des clefs
          AFTER:  K, fonction de N vers PK croix SK, la fonction de génération des clefs

          BEFORE: Eval : F × C × C → C : la fonction d'évaluation
          AFTER:  Eval, fonction de F croix C croix C vers C, la fonction d'évaluation

          BEFORE: D(E(m)) = m
          AFTER:  D de E de m, égal à m

          BEFORE: ∀f ∈ F, D(Eval(f, C1, C2)) = Eval(f, D(C1), D(C2))
          AFTER:  pour tout f appartenant à F, D de Eval de f virgule C1 virgule C2, égal à Eval de f virgule D de C1 virgule D de C2

        QUOTATION ISOLATION REMINDER (see critical rule above):
        Encyclopedic articles sometimes quote authors or sources.
          BEFORE: Selon Darwin, «la sélection naturelle est le moteur de l'évolution» comme il l'explique dans son ouvrage.
          AFTER:
            Selon Darwin,

            «la sélection naturelle est le moteur de l'évolution»

            comme il l'explique dans son ouvrage.
    """).strip(),

    "social_media": textwrap.dedent("""
        DETECTED TYPE: social media post or thread

        REMOVE IN ADDITION:
        - Engagement counters (likes, retweets, shares, views, reply counts)
        - Pure hashtags (#word) with no contextual value
        - @user mentions that are navigation artefacts (buttons, links)
        - Interaction buttons ("Répondre", "Retweeter", "J'aime") and standalone timestamps

        KEEP:
        - @user mentions cited within the body of a comment or post (they are part of the content)
        - When a comment is a reply to another user, indicate it explicitly:
          "En réponse à @username :" followed by the reply text on a new paragraph.

        QUOTATION ISOLATION REMINDER (see critical rule above):
        Posts often quote other people or reproduce statements.
          BEFORE: Il répond à la polémique : "Je n'ai jamais dit ça" et demande des excuses.
          AFTER:
            Il répond à la polémique :

            "Je n'ai jamais dit ça"

            et demande des excuses.
    """).strip(),

    "documentation": textwrap.dedent("""
        DETECTED TYPE: technical documentation

        ADAPT:
        - Code blocks: introduce with "Exemple de code :" then read as plain text
          (remove backticks and superfluous indentation).
        - Remove line numbers from code excerpts.
        - Remove badges (Build passing, Coverage 98%…) and decorative icons.
        - Keep important notices (WARNING, NOTE, IMPORTANT).

        MATH VERBALIZATION (if mathematical notation is present):
        Rewrite formulas as natural spoken language so the TTS reads them intelligibly.
        - f(x)       → f de x
        - X : A → B  → X, fonction de A vers B   (type signature: colon = "fonction de")
        - A → B      → A vers B
        - A = B      → A égal à B
        - × (product/Cartesian) → croix
        - ∀x ∈ S     → pour tout x appartenant à S
        - ∈          → appartient à
        - ∈        → appartient à

        TABLES: rewrite each row as a sentence using the column header names.
        Skip cells whose value is just a dash (—, –).
          BEFORE:
            | Length     | Primary model        | Fallback             |
            |------------|----------------------|----------------------|
            | <80 words  | mistral-small-latest | mistral-medium-latest|
            | >240 words | magistral-medium     | mistral-medium-latest|
          AFTER:
            Length: less than 80 words. Primary model: mistral-small-latest. Fallback: mistral-medium-latest.
            Length: more than 240 words. Primary model: magistral-medium. Fallback: mistral-medium-latest.

        QUOTATION ISOLATION REMINDER (see critical rule above):
        Documentation may quote error messages or technical terms.
          BEFORE: La fonction retourne «None» si aucune valeur n'est trouvée.
          AFTER:
            La fonction retourne

            «None»

            si aucune valeur n'est trouvée.
    """).strip(),

    "assistant_response": textwrap.dedent("""
        DETECTED TYPE: AI assistant response

        TABLES: rewrite each row as a sentence using the column header names.
        Skip cells whose value is just a dash (—, –).
          BEFORE: | Step | Command | Effect |\\n| 1 | npm install | installs deps |
          AFTER: Step: 1. Command: npm install. Effect: installs deps.

        ADAPT:
        - Convert markdown to readable text:
          **bold** → bold,  *italic* → italic,  # Heading → read normally,
          - item → read as a normal sentence without a dash.
        - Code blocks: introduce with "Exemple de code :" then read as plain text.
        - Remove interface metadata (token counter, model name, timestamp).
        - Keep step numbering when it structures the content.

        QUOTATION ISOLATION REMINDER (see critical rule above):
        AI responses may quote source texts or examples.
          BEFORE: Le texte original dit «le ciel est bleu» mais cette affirmation est simpliste.
          AFTER:
            Le texte original dit

            «le ciel est bleu»

            mais cette affirmation est simpliste.
    """).strip(),

    "generic": textwrap.dedent("""
        DETECTED TYPE: generic content

        TABLES: rewrite each row as a sentence using the column header names.
        Skip cells whose value is just a dash (—, –).
          BEFORE: | Name | Role | Status |\\n| Alice | Dev | Active |
          AFTER: Name: Alice. Role: Dev. Status: Active.

        QUOTATION ISOLATION REMINDER (see critical rule above):
        Any text may contain quotes. Apply the isolation rule to every quoted
        passage without exception.
          BEFORE: Le rapport conclut que «des améliorations significatives sont nécessaires» dès 2025.
          AFTER:
            Le rapport conclut que

            «des améliorations significatives sont nécessaires»

            dès 2025.
    """).strip(),
}


# Two or more spaces used as column separators in space-aligned tables.
_RE_SPACE_SEP = re.compile(r'  +')

# A line is a candidate math token if it is short (≤ 8 chars) and contains no
# accented letters. We exclude U+00C0-U+00D6 (À…Ö) and U+00D8-U+00F6 (Ø…ö)
# and U+00F8-U+024F, but intentionally keep U+00D7 (×) and U+00F7 (÷) which
# are math symbols, not accented letters.
_MATH_TOKEN_LINE = re.compile(r'^[^\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u024F\s]{1,8}\s*$')


def _verbalize_tables(text: str) -> str:
    """Convert tabular content to accessible spoken prose.

    Converts three table formats to one sentence per data row:
      "Header1: value1. Header2: value2."

    Handled formats:
      - Markdown pipe tables  (| col | col |)
      - Tab-separated tables  (col\\tcol\\tcol)
      - Space-aligned tables  (col  col  col — ≥ 2 spaces as separator,
                               requires ≥ 3 cols and ≥ 3 consecutive rows
                               to keep false-positive rate low on prose)

    Must be called BEFORE the multi-space collapsing step in _clean_text so
    that space-aligned column boundaries are still intact.
    """

    def _pipe_cells(row: str) -> list[str]:
        return [c.strip() for c in row.strip().strip('|').split('|')]

    def _space_cells(row: str) -> list[str]:
        return [c.strip() for c in _RE_SPACE_SEP.split(row.strip()) if c.strip()]

    def _row_sentence(headers: list[str], cells: list[str]) -> str:
        parts = []
        for h, c in zip(headers, cells):
            h, c = h.strip(), c.strip()
            # Skip empty cells and pure-dash placeholders (—, –, -)
            if h and c and c not in ('—', '–', '-', '·', '…'):
                parts.append(f"{h}: {c}")
        return ". ".join(parts) + "." if parts else ""

    lines = text.splitlines()
    out: list[str] = []
    i = 0

    while i < len(lines):
        raw = lines[i]
        s = raw.strip()

        # ── Markdown pipe table ──────────────────────────────────────────────
        if s and '|' in s and (s.startswith('|') or s.endswith('|') or ' | ' in s):
            block: list[str] = []
            j = i
            while j < len(lines) and '|' in lines[j] and lines[j].strip():
                block.append(lines[j])
                j += 1
            # Drop separator rows like |---|:--|:---:|
            data = [r for r in block if not re.fullmatch(r'[\s|:\-]+', r.strip())]
            if len(data) >= 2:
                headers = _pipe_cells(data[0])
                for row in data[1:]:
                    sent = _row_sentence(headers, _pipe_cells(row))
                    if sent:
                        out.append(sent)
                out.append("")
                i = j
                continue

        # ── Tab-separated table ──────────────────────────────────────────────
        if '\t' in s and s.count('\t') >= 1:
            block = [s]
            j = i + 1
            while j < len(lines) and '\t' in lines[j] and lines[j].strip():
                block.append(lines[j].strip())
                j += 1
            col_counts = [r.count('\t') + 1 for r in block]
            mode = max(set(col_counts), key=col_counts.count)
            if len(block) >= 2 and mode >= 2:
                headers = [h.strip() for h in block[0].split('\t')]
                for row in block[1:]:
                    sent = _row_sentence(headers, [c.strip() for c in row.split('\t')])
                    if sent:
                        out.append(sent)
                out.append("")
                i = j
                continue

        # ── Space-aligned table (≥ 3 cols, ≥ 3 consecutive rows) ────────────
        # Require at least 3 rows (header + 2 data rows) to limit false positives.
        first_cols = _space_cells(s)
        if (len(first_cols) >= 3
                and s
                and not s.startswith('#')
                and not s.startswith('`')):
            block_cols: list[list[str]] = [first_cols]
            j = i + 1
            while j < len(lines):
                ns = lines[j].strip()
                nc = _space_cells(ns) if ns else []
                if ns and len(nc) >= 2:
                    block_cols.append(nc)
                    j += 1
                else:
                    break
            if len(block_cols) >= 3:
                headers = block_cols[0]
                converted = [_row_sentence(headers, row) for row in block_cols[1:]]
                converted = [sv for sv in converted if sv]
                if converted:
                    out.extend(converted)
                    out.append("")
                    i = j
                    continue

        out.append(raw)
        i += 1

    return '\n'.join(out)


def _collapse_math_lines(text: str) -> str:
    """Join sequences of math-token lines caused by Wikipedia formula rendering.

    When a Wikipedia page is copy-pasted, each character of a math formula
    (rendered as SVG) lands on its own line: "K\\n:\\nN\\n→\\nPK\\n×\\nSK".
    A run of ≥ 3 consecutive math-token lines is collapsed when ≥ 50 % of its
    tokens are single characters — the hallmark of a fragmented formula.
    This prevents collapsing French text (e.g. "de la un le") which has no
    single-char tokens to speak of.
    """
    lines = text.splitlines()
    result: list[str] = []
    i = 0
    # Strip inline Wikipedia references like [2] or [note 1] that appear at the
    # start of a line immediately after a math formula (e.g. "￼[2] tel que :").
    _wiki_ref = re.compile(r'^\[\d+(?:\s+\w+)?\]\s*')

    while i < len(lines):
        stripped = lines[i].strip()
        if _MATH_TOKEN_LINE.match(stripped):
            j = i + 1
            while j < len(lines) and _MATH_TOKEN_LINE.match(lines[j].strip()):
                j += 1
            if j - i >= 3:
                tokens = [lines[k].strip() for k in range(i, j) if lines[k].strip()]
                single_char = sum(1 for t in tokens if len(t) == 1)
                if tokens and single_char / len(tokens) >= 0.5:
                    collapsed = " ".join(tokens)
                    # If the next line is "[N] some text", strip the reference
                    # and append the remaining text so it stays with the formula.
                    if j < len(lines):
                        after = lines[j].strip()
                        # Strip wiki reference [N] and attach the rest
                        after_no_ref = _wiki_ref.sub("", after).strip()
                        if after_no_ref != after:
                            if after_no_ref:
                                collapsed = collapsed + " " + after_no_ref
                            j += 1
                        # Attach continuation lines starting with ":" or ";"
                        # (formula definitions like "￼ : la fonction de …")
                        elif after.startswith(":") or after.startswith(";"):
                            collapsed = collapsed + " " + after
                            j += 1
                    result.append(collapsed)
                    i = j
                    continue
        result.append(lines[i])
        i += 1
    return "\n".join(result)


def _merge_split_identifiers(text: str) -> str:
    """Merge letter sequences that were split character-by-character.

    After NFKC + _collapse_math_lines, math identifiers like 𝐸𝑣𝑎𝑙 become
    "E v a l" (each letter space-separated). This step re-fuses them into "Eval".

    Rule: a run of single letters separated by plain spaces (not commas or
    operators) is merged into one word. Examples:
      "E v a l"  → "Eval"
      "m o d"    → "mod"
      "K , E"    → unchanged (comma breaks the run)
    """
    # Match: uppercase or lowercase letter, followed by 1+ ( space + single letter )
    # Negative lookbehind/ahead: not preceded/followed by comma, operator or word char.
    # Merge runs of single letters: "E v a l" → "Eval"
    text = re.sub(
        r'(?<![,\w])([A-Za-z])( [A-Za-z])+(?![,\w])',
        lambda m: m.group(0).replace(" ", ""),
        text,
    )
    # Merge letter + digit: "C 1" → "C1", "C 2" → "C2"
    # (?<!\w) ensures we only merge word-initial single letters (math identifiers),
    # not word-final letters like "l" in "avril 2026" or "e" in "de 55 ans".
    text = re.sub(r'(?<!\w)([A-Za-z]) (\d+)', r'\1\2', text)
    return text


def _clean_text(text: str) -> str:
    """Normalize Unicode, collapse math tokens, and remove unreadable artifacts."""
    # NFKC: converts math italic letters (𝐸→E, 𝑣→v) and other compatibility
    # characters to their ASCII equivalents — essential for Wikipedia formulas
    # where each character arrives on its own line as a separate Unicode code point.
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\ufffc", "")  # Unicode object replacement char (icons/images)
    text = _verbalize_tables(text)     # must run before multi-space collapsing
    text = _collapse_math_lines(text)
    text = _merge_split_identifiers(text)
    # Remove space between an uppercase math identifier and its opening paren:
    # "D (E(m))" → "D(E(m))" so _expand_function_calls can match it.
    text = re.sub(r'\b([A-Z][A-Za-z0-9]*)\s+\(', r'\1(', text)
    # Normalize spaces around commas inside parenthesized lists: "( K , E )" → "(K, E)"
    text = re.sub(r'\(\s*([^()]+?)\s*\)', lambda m: '(' + re.sub(r'\s*,\s*', ', ', m.group(1).strip()) + ')', text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip()


def _strip_markdown(text: str) -> str:
    """Remove markdown formatting that would be read aloud by TTS."""
    text = re.sub(r"\*{1,3}([^*\n]+)\*{1,3}", r"\1", text)  # bold/italic
    text = re.sub(r"#{1,6}\s+", "", text)                    # headings
    text = re.sub(r"`+([^`\n]+)`+", r"\1", text)             # inline code
    return text


def detect_content_type(text: str, api_key: str) -> str:
    """Detect the content type of the given text using Mistral.

    Returns one of the keys in _CLEAN_RULES:
      news_article, email, wikipedia, social_media, documentation,
      assistant_response, generic

    Falls back to "generic" on any error.
    """
    try:
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        resp = requests.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers=headers,
            json={
                "model": _DETECT_MODEL,
                "messages": [
                    {"role": "system", "content": _DETECT_SYSTEM},
                    {"role": "user",   "content": text[:2000]},
                ],
                "max_tokens": 10,
                "temperature": 0.0,
            },
            timeout=15,
        )
        resp.raise_for_status()
        detected = resp.json()["choices"][0]["message"]["content"].strip().lower()
        if detected in _CLEAN_RULES:
            return detected
    except Exception as exc:
        print(f"\u26a0\ufe0f  Type detection failed ({exc}), using generic.", file=sys.stderr)
    return "generic"


def _ai_clean_text(text: str) -> str:
    """Detect content type then clean with a specialized prompt.

    Two API calls:
      1. mistral-small-latest : detect content type (one-word response)
      2. devstral-latest      : clean with type-specific rules

    Falls back to _clean_text() if any call fails.
    """
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        print("\u26a0\ufe0f  No MISTRAL_API_KEY — skipping AI cleaning.", file=sys.stderr)
        return _clean_text(text)

    # Normalize before sending to AI: NFKC + math-line collapsing so the AI
    # receives "K : N → PK × SK" instead of "K\n:\nN\n→\nP\nK\n×\nS\nK".
    text = _clean_text(text)

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    # ── Call 1: detect content type ──────────────────────────────────────────
    content_type = "generic"
    try:
        print("\U0001f50d Detecting content type...", file=sys.stderr)
        content_type = detect_content_type(text, api_key)
        print(f"\U0001f4c4 Type: {content_type}", file=sys.stderr)
    except Exception as exc:
        print(f"\u26a0\ufe0f  Type detection failed ({exc}), using generic.", file=sys.stderr)

    # ── Call 2: clean with type-specific prompt ───────────────────────────────
    print("\U0001f9f9 Cleaning text via AI...", file=sys.stderr)
    specific = _CLEAN_RULES[content_type]
    system_prompt = _CLEAN_COMMON + ("\n\n" + specific if specific else "")
    try:
        resp = requests.post(
            "https://api.mistral.ai/v1/chat/completions",
            headers=headers,
            json={
                "model": _CLEAN_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": text},
                ],
                "max_tokens": 4096,
                "temperature": 0.0,
            },
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()["choices"][0]["message"]["content"].strip()
        if result:
            print(f"\u2705 AI cleaning done ({len(result)} chars).", file=sys.stderr)
            return result
    except Exception as exc:
        print(f"\u26a0\ufe0f  AI cleaning failed ({exc}), using raw text.", file=sys.stderr)

    return _clean_text(text)


# ── Math symbol verbalization ────────────────────────────────────────────────
# Simple substitutions applied as a safety net after AI cleaning.
# The AI prompt handles complex formulas; this catches any survivors.
_MATH_SYMBOLS: list[tuple[str, str]] = [
    # Logic / set theory
    ("∀",  "pour tout "),
    ("∃",  "il existe "),
    ("∈",  " appartient à "),
    ("∉",  " n'appartient pas à "),
    ("⊂",  " est inclus dans "),
    ("⊆",  " est inclus ou égal à "),
    ("∩",  " intersecté avec "),
    ("∪",  " uni à "),
    ("∅",  "l'ensemble vide"),
    # Arrows
    ("→",  " vers "),
    ("←",  " depuis "),
    ("↔",  " équivalent à "),
    ("⇒",  " implique "),
    ("⇔",  " si et seulement si "),
    # Operators
    # × in math context = Cartesian product / type product → "croix" (not "fois")
    # "fois" is reserved for arithmetic multiplication (3 × 4).
    ("×",  " croix "),
    ("⋅",  " fois "),   # middle dot (arithmetic multiplication)
    ("÷",  " divisé par "),
    (" = ", " égal à "),   # spaced = to avoid replacing == in code or HTML
    ("\n= ", "\négal à "), # = at start of a continuation line
    ("^",  " exposant "),
    ("≠",  " différent de "),
    ("≤",  " inférieur ou égal à "),
    ("≥",  " supérieur ou égal à "),
    ("≈",  " environ égal à "),
    ("±",  " plus ou moins "),
    ("∞",  "l'infini"),
    ("√",  "racine carrée de "),
    ("∑",  "somme de "),
    ("∏",  "produit de "),
    ("∫",  "intégrale de "),
    ("∂",  "dérivée partielle de "),
]


def _expand_math_symbols(text: str) -> str:
    """Replace mathematical symbols with spoken French equivalents.

    Acts as a safety net after AI cleaning: catches any symbols the AI missed.
    Only replaces symbols when they appear outside of backtick code spans.
    Also verbalizes colons in math formula lines: "K : N vers PK croix SK"
    becomes "K, de N vers PK croix SK", only when the line contains a math
    arrow or operator (to avoid touching normal prose like "Photo : ...").
    """
    # Split on code spans to avoid mangling inline code
    parts = re.split(r"(`[^`\n]+`)", text)
    result = []
    for part in parts:
        if part.startswith("`"):
            result.append(part)
        else:
            for symbol, spoken in _MATH_SYMBOLS:
                part = part.replace(symbol, spoken)
            # Collapse multiple spaces that substitutions may create
            part = re.sub(r" {2,}", " ", part)
            result.append(part)
    expanded = "".join(result)

    # On formula lines (containing a math keyword), verbalize each " : ":
    # - If followed by a math keyword (vers, croix, fois…) → ", fonction de "
    #   e.g. "K : N vers PK croix SK" → "K, fonction de N vers PK croix SK"
    # - Otherwise → ", "
    #   e.g. "SK : la fonction de génération" → "SK, la fonction de génération"
    _MATH_KEYWORD = re.compile(r'\b(vers|croix|fois|exposant|appartient|implique|inférieur|supérieur|racine)\b')
    _COLON_MATH   = re.compile(r' : (?=[^:]*\b(?:vers|croix|fois|exposant|appartient)\b)')
    _COLON_OTHER  = re.compile(r' : ')

    lines_out = []
    for line in expanded.splitlines():
        if _MATH_KEYWORD.search(line) and " : " in line:
            line = _COLON_MATH.sub(", fonction de ", line)
            line = _COLON_OTHER.sub(", ", line)
        lines_out.append(line)
    return "\n".join(lines_out)


# Matches uppercase-starting identifiers used as math function names (E, D, Eval, K…).
# Lowercase-only words are excluded to avoid false matches on French words like "est(iment)".
_FUNC_CALL_RE = re.compile(r'\b([A-Z][A-Za-z0-9_]{0,9})\(([^()]+)\)')


def _expand_function_calls(text: str) -> str:
    """Convert math function-call notation to spoken French.

    Works iteratively (innermost parentheses first) so nested calls are
    fully expanded:
      D(E(m))            → D de E de m
      Eval(f, C1, C2)    → Eval de f virgule C1 virgule C2
      E(x) ⋅ E(y)        → E de x fois E de y   (after _expand_math_symbols)

    Only matches identifiers starting with an uppercase letter to avoid
    false positives on French words.
    """
    prev = None
    while prev != text:
        prev = text

        def _replace(m: re.Match) -> str:
            name = m.group(1)
            args = re.sub(r"\s*,\s*", " virgule ", m.group(2).strip())
            return f"{name} de {args}"

        text = _FUNC_CALL_RE.sub(_replace, text)
    return text


# Matches «…» (French) and "…" (curly English). ASCII " is intentionally excluded
# to avoid false positives on attribute values, code, or non-citation double quotes.
_QUOTE_PATTERN = re.compile(r'(«[^»\n]+»|\u201C[^\u201D\n]+\u201D)')


def _isolate_quotes(text: str) -> str:
    """Post-process cleaned text to guarantee all quoted passages are isolated paragraphs.

    Splits any paragraph that contains an embedded «…» or "…" quotation into
    separate paragraphs, so _is_quoted_paragraph() can reliably detect them for
    voice switching — regardless of how the AI formatted its output.

    Example:
        IN  : L'objectif est «de doubler la production» selon la direction.
        OUT : L'objectif est\n\n«de doubler la production»\n\nseclon la direction.
    """
    paragraphs = re.split(r"\n\n+", text)
    result: list[str] = []

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        # If the paragraph already starts with a quote, keep it as-is
        if _is_quoted_paragraph(para):
            result.append(para)
            continue
        # If no embedded citation, keep it as-is
        if not _QUOTE_PATTERN.search(para):
            result.append(para)
            continue
        # Split on citation boundaries; the capturing group keeps the citations.
        # Discard fragments that contain no alphanumeric character (e.g. lone
        # ".", ",", "…") — they cause TTS hallucinations on empty-ish inputs.
        parts = _QUOTE_PATTERN.split(para)
        for part in parts:
            part = part.strip()
            if part and re.search(r'\w', part):
                result.append(part)

    return "\n\n".join(result)


def _is_quoted_paragraph(para: str) -> bool:
    """Return True if the paragraph is a direct quotation or citation.

    Matches paragraphs that begin with an opening quotation mark («, ", "),
    which covers both complete quotes («…») and attribution-style quotes
    («Citation», a-t-il dit.).
    """
    s = para.strip()
    return s.startswith(('"', "\u00AB", "\u201C"))  # ", «, "


def _split_sentences(para: str, max_chars: int) -> list[str]:
    """Sub-split a paragraph at sentence boundaries when it exceeds max_chars."""
    sentences = re.split(r'(?<=[.!?…])\s+|(?<=[.!?…]["\u00BB\u201D)])\s+', para)
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        return [para] if para else []
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        while len(sentence) > max_chars:
            split_at = -1
            for sep in [", ", "; ", " – ", " — "]:
                pos = sentence.rfind(sep, 0, max_chars)
                if pos > 0:
                    split_at = pos + len(sep)
                    break
            if split_at <= 0:
                split_at = sentence.rfind(" ", 0, max_chars)
            if split_at <= 0:
                split_at = max_chars
            if current:
                chunks.append(current)
                current = ""
            chunks.append(sentence[:split_at].rstrip())
            sentence = sentence[split_at:].lstrip()
        if not current:
            current = sentence
        elif len(current) + 1 + len(sentence) <= max_chars:
            current += " " + sentence
        else:
            chunks.append(current)
            current = sentence
    if current:
        chunks.append(current)
    return chunks


def _make_chunks(
    text: str,
    max_chars: int = _CHUNK_MAX_CHARS,
    quote_voice_id: Optional[str] = None,
) -> list[tuple[str, Optional[str]]]:
    """Split text into chunks preserving paragraph structure.

    Splits on double-newline paragraph boundaries first; groups consecutive small
    paragraphs into a single chunk when they fit; sub-splits oversized paragraphs
    at sentence boundaries. Never cuts mid-paragraph.

    Returns a list of (chunk_text, voice_id) tuples. voice_id is quote_voice_id
    for paragraphs that are entirely a quotation (when quote_voice_id is set),
    None otherwise.
    """
    paragraphs = re.split(r"\n\n+", text)
    paragraphs = [p.strip() for p in paragraphs if p.strip()]
    if not paragraphs:
        return [(text.strip(), None)] if text.strip() else []

    result: list[tuple[str, Optional[str]]] = []
    group: list[str] = []
    group_len = 0  # len("\n\n".join(group))

    def _flush_group() -> None:
        nonlocal group, group_len
        if group:
            result.append(("\n\n".join(group), None))
            group = []
            group_len = 0

    for para in paragraphs:
        quoted = quote_voice_id and _is_quoted_paragraph(para)

        if quoted:
            # Quoted paragraph: emit with quote voice, isolated from the group
            _flush_group()
            if len(para) > max_chars:
                for sub in _split_sentences(para, max_chars):
                    result.append((sub, quote_voice_id))
            else:
                result.append((para, quote_voice_id))
        elif len(para) > max_chars:
            # Oversized paragraph: flush group, then sub-split at sentence level
            _flush_group()
            for sub in _split_sentences(para, max_chars):
                result.append((sub, None))
        else:
            # Normal paragraph: try to group with previous paragraphs
            separator_len = 2 if group else 0  # "\n\n" is 2 chars
            if group and group_len + separator_len + len(para) > max_chars:
                _flush_group()
            group.append(para)
            group_len += separator_len + len(para)

    _flush_group()
    return result


def _resolve_voice_id() -> Optional[str]:
    """Resolve voice ID from environment (TTS_LANG → map, TTS_VOICE_ID, or default)."""
    tts_lang = os.environ.get("TTS_LANG", "")
    tts_voice_id_env = os.environ.get("TTS_VOICE_ID", None)
    if tts_lang and tts_lang in _LANG_VOICE_MAP:
        resolved: Optional[str] = _LANG_VOICE_MAP[tts_lang]
        print(f"\U0001f508 Voice: {tts_lang} preset ({resolved})", file=sys.stderr)
    elif tts_voice_id_env is not None:
        resolved = tts_voice_id_env or None
        label = resolved or _DEFAULT_VOICE_ID or "none"
        print(f"\U0001f508 Voice: {label}", file=sys.stderr)
    else:
        resolved = _DEFAULT_VOICE_ID or None
        print(f"\U0001f508 Voice: {resolved or 'none (will fail)'}", file=sys.stderr)
    return resolved


def _encode_voice_sample(sample_path: str) -> str:
    """Read and base64-encode a voice sample file."""
    data = Path(sample_path).read_bytes()
    return base64.b64encode(data).decode("ascii")


def _is_gradium_voice(voice_id: str) -> bool:
    """Return True if voice_id is a Gradium ID (non-UUID alphanumeric format)."""
    return not _UUID_RE.match(voice_id)


def _is_google_voice(voice_id: str) -> bool:
    """Return True if voice_id is a Google TTS voice (starts with 'google-')."""
    return voice_id.startswith("google-")


_ELEVEN_MODELS: dict[str, str] = {
    "v2":    "audio/tts/elevenlabs/eleven_multilingual_v2",
    "v3":    "audio/tts/elevenlabs/eleven_v3",
    "flash": "audio/tts/elevenlabs/eleven_flash_v2_5",
}


def _synthesize_elevenlabs_eden(text: str, output_path: str, voice_id: str) -> None:
    """Call ElevenLabs TTS via Eden AI universal endpoint and write MP3 to output_path.

    voice_id format: "eleven-<model_key>-<elevenlabs_voice_id>"
      e.g. "eleven-v2-pNInz6obpgDQGcFmaJgB"   → eleven_multilingual_v2
           "eleven-v3-pNInz6obpgDQGcFmaJgB"   → eleven_v3
           "eleven-flash-pNInz6obpgDQGcFmaJgB" → eleven_flash_v2_5

    Eden AI responds with a CloudFront URL; the audio is downloaded in a second request.
    """
    api_key = os.environ.get("EDENAI_API_KEY")
    if not api_key:
        raise RuntimeError("EDENAI_API_KEY is not set. Check your .env file.")

    # Parse "eleven-<model_key>-<voice_id>" — split on first two hyphens only.
    parts = voice_id.split("-", 2)
    if len(parts) == 3 and parts[1] in _ELEVEN_MODELS:
        model_key, eleven_voice_id = parts[1], parts[2]
    else:
        # Legacy / fallback: "eleven-<voice_id>" without explicit model key.
        model_key, eleven_voice_id = "v2", voice_id.removeprefix("eleven-")

    eden_model = _ELEVEN_MODELS[model_key]

    response = requests.post(
        "https://api.edenai.run/v3/universal-ai/",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": eden_model,
            "input": {"text": text, "voice": eleven_voice_id},
            "show_original_response": False,
        },
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()

    if data.get("status") != "success":
        error = data.get("error") or {}
        raise RuntimeError(f"ElevenLabs Eden AI ({model_key}) error: {error.get('message', str(data)[:300])}")

    # Eden AI returns a CloudFront URL — download the audio file.
    audio_url = (data.get("output") or {}).get("audio_resource_url")
    if not audio_url:
        raise RuntimeError(f"ElevenLabs Eden AI: missing audio_resource_url in response: {str(data)[:300]}")

    audio_response = requests.get(audio_url, timeout=30)
    audio_response.raise_for_status()
    Path(output_path).write_bytes(audio_response.content)


def _create_wav_header(data_size: int, sample_rate: int, channels: int, bits_per_sample: int) -> bytes:
    """Create a WAV file header for PCM data."""
    # Calculate sizes
    byte_rate = sample_rate * channels * (bits_per_sample // 8)
    block_align = channels * (bits_per_sample // 8)
    wav_size = 36 + data_size  # 36 = header size before data

    # Pack header
    import struct
    header = struct.pack('<4sI4s4sIHHIIHH4sI',
        b'RIFF',           # ChunkID
        wav_size,          # ChunkSize
        b'WAVE',           # Format
        b'fmt ',           # Subchunk1ID
        16,                # Subchunk1Size (PCM)
        1,                 # AudioFormat (PCM)
        channels,          # NumChannels
        sample_rate,       # SampleRate
        byte_rate,         # ByteRate
        block_align,       # BlockAlign
        bits_per_sample,   # BitsPerSample
        b'data',           # Subchunk2ID
        data_size          # Subchunk2Size
    )
    return header


def _synthesize_gradium(text: str, output_path: str, voice_id: str) -> None:
    """Call Gradium TTS and write WAV audio to output_path."""
    api_key = os.environ.get("GRADIUM_API_KEY")
    if not api_key:
        raise RuntimeError("GRADIUM_API_KEY is not set. Check your .env file.")

    # Gradium uses WebSockets with no built-in timeout — wrap in wait_for to avoid
    # hanging indefinitely when the connection cannot be established.
    _GRADIUM_TIMEOUT = 30.0

    async def _run() -> None:
        from gradium.client import GradiumClient  # type: ignore[import]
        from gradium.speech import TTSSetup  # type: ignore[import]
        client = GradiumClient(api_key=api_key)
        setup = TTSSetup(voice_id=voice_id, output_format="wav")
        result = await asyncio.wait_for(client.tts(setup, text), timeout=_GRADIUM_TIMEOUT)
        Path(output_path).write_bytes(result.raw_data)

    asyncio.run(_run())


def _parse_accent_tags(text: str) -> tuple[str, Optional[str]]:
    """Parse accent tags from text and return cleaned text and language_code."""
    # Look for [accent: french] or similar
    accent_match = re.search(r'\[accent:\s*(\w+)\]', text, re.IGNORECASE)
    if accent_match:
        accent = accent_match.group(1).lower()
        if accent == "french":
            language_code = "fr-FR"
        elif accent == "quebec" or accent == "canadian":
            language_code = "fr-CA"
        else:
            language_code = None
        # Remove the tag from text
        text = re.sub(r'\[accent:\s*\w+\]', '', text, flags=re.IGNORECASE).strip()
    else:
        language_code = None
    return text, language_code


def _synthesize_google_tts(text: str, output_path: str, voice_name: str, language_code: Optional[str] = None) -> None:
    """Call Google Gemini TTS and write WAV audio to output_path."""
    if genai is None:
        raise RuntimeError("google-genai library not installed. Run 'pip install google-genai'.")

    api_key = os.environ.get("GOOGLE_TTS_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_TTS_API_KEY is not set. Check your .env file.")

    # Parse accent tags from text
    text, detected_language = _parse_accent_tags(text)

    # Parse voice name and language from slug (e.g., "google-kore-fr-ca")
    if voice_name.startswith("google-"):
        parts = voice_name.split("-")
        voice_base = parts[1]  # "kore"
        voice_name_clean = voice_base.capitalize()
        if len(parts) > 2:
            lang_suffix = "-".join(parts[2:])  # "fr-ca"
            if lang_suffix == "fr":
                detected_language = detected_language or "fr-FR"
            elif lang_suffix == "fr-ca":
                detected_language = detected_language or "fr-CA"
            elif lang_suffix == "es-es":
                detected_language = detected_language or "es-ES"
            elif lang_suffix == "es-mx":
                detected_language = detected_language or "es-MX"
            elif lang_suffix == "en-us":
                detected_language = detected_language or "en-US"
            elif lang_suffix == "en-gb":
                detected_language = detected_language or "en-GB"
            elif lang_suffix == "en-au":
                detected_language = detected_language or "en-AU"
            # For other suffixes, keep detected_language

    language_code = language_code or detected_language

    try:
        client = genai.Client(api_key=api_key)

        prebuilt_voice_config = types.PrebuiltVoiceConfig(
            voice_name=voice_name_clean
        )

        voice_config = types.VoiceConfig(
            prebuilt_voice_config=prebuilt_voice_config
        )

        speech_config = types.SpeechConfig(
            voice_config=voice_config,
            language_code=language_code if language_code else None
        )

        response = client.models.generate_content(
            model="models/gemini-3.1-flash-tts-preview",
            contents=text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=speech_config
            )
        )

        # Check if response has candidates
        if not response.candidates:
            raise RuntimeError("No candidates in response")

        candidate = response.candidates[0]
        if not candidate.content or not candidate.content.parts:
            raise RuntimeError("No content parts in response")

        part = candidate.content.parts[0]
        if not hasattr(part, 'inline_data') or not part.inline_data:
            raise RuntimeError("No inline_data in response part")

        # Extract audio data (raw PCM, need to add WAV header)
        pcm_data = part.inline_data.data

        if not pcm_data:
            raise RuntimeError("Empty PCM data")

        # Gemini TTS outputs 24kHz, 16-bit mono PCM
        sample_rate = 24000
        channels = 1
        bits_per_sample = 16

        # Create WAV header
        wav_header = _create_wav_header(len(pcm_data), sample_rate, channels, bits_per_sample)

        # Write WAV file
        with open(output_path, 'wb') as f:
            f.write(wav_header)
            f.write(pcm_data)

    except Exception as e:
        raise RuntimeError(f"Google TTS failed: {e}") from e


def _synthesize_grok_tts(text: str, output_path: str, voice_id: str) -> None:
    """Call xAI Grok TTS directly and write MP3 bytes to output_path.

    voice_id format: "grok-<voice>-<language>" (e.g. "grok-ara-fr", "grok-rex-es-ES").
    split("-", 2) always yields ["grok", voice, language] — safe even when language
    contains a hyphen (e.g. "es-ES").
    Response is raw MP3 bytes — no intermediate URL download needed.
    """
    api_key = os.environ.get("XAI_API_KEY")
    if not api_key:
        raise RuntimeError("XAI_API_KEY is not set. Check your .env file.")

    parts = voice_id.split("-", 2)
    grok_voice = parts[1] if len(parts) >= 2 else "eve"
    language    = parts[2] if len(parts) >= 3 else "en"

    response = requests.post(
        "https://api.x.ai/v1/tts",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={"text": text, "voice_id": grok_voice, "language": language},
        timeout=60,
    )
    response.raise_for_status()
    Path(output_path).write_bytes(response.content)


def _synthesize_deepgram_aura2(text: str, output_path: str, voice_id: str) -> None:
    """Call Deepgram Aura 2 TTS via Eden AI universal endpoint and write audio to output_path.

    voice_id format: "deepgram-aura-2-<name>-<lang>" (e.g. "deepgram-aura-2-thalia-en").
    Stripping "deepgram-" yields the full Deepgram model name used as the voice parameter.
    Eden AI responds with a CloudFront URL; the audio is downloaded in a second request.
    """
    api_key = os.environ.get("EDENAI_API_KEY")
    if not api_key:
        raise RuntimeError("EDENAI_API_KEY is not set. Check your .env file.")

    voice_name = voice_id.removeprefix("deepgram-")  # "aura-2-thalia-en"

    response = requests.post(
        "https://api.edenai.run/v3/universal-ai/",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "audio/tts/deepgram/aura-2",
            "input": {"text": text, "voice": voice_name},
            "show_original_response": False,
        },
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()

    if data.get("status") != "success":
        error = data.get("error") or {}
        raise RuntimeError(f"Deepgram Aura 2 Eden AI error: {error.get('message', str(data)[:300])}")

    audio_url = (data.get("output") or {}).get("audio_resource_url")
    if not audio_url:
        raise RuntimeError(f"Deepgram Aura 2 Eden AI: missing audio_resource_url in response: {str(data)[:300]}")

    audio_response = requests.get(audio_url, timeout=30)
    audio_response.raise_for_status()
    Path(output_path).write_bytes(audio_response.content)


def _synthesize_amazon_polly(text: str, output_path: str, voice_id: str, model: str) -> None:
    """Call Amazon Polly TTS via Eden AI universal endpoint and write MP3 to output_path.

    model: "audio/tts/amazon/neural" or "audio/tts/amazon/standard"
    voice_id: "amazon-<VoiceName>" or "amazon-std-<VoiceName>" — prefix is stripped before the call.
    Voice names must match Amazon Polly enum exactly — no accents ("Lea" not "Léa").
    Eden AI responds with a CloudFront URL; the audio is downloaded in a second request.
    """
    api_key = os.environ.get("EDENAI_API_KEY")
    if not api_key:
        raise RuntimeError("EDENAI_API_KEY is not set. Check your .env file.")

    if voice_id.startswith("amazon-std-"):
        voice_name = voice_id.removeprefix("amazon-std-")
    else:
        voice_name = voice_id.removeprefix("amazon-")

    response = requests.post(
        "https://api.edenai.run/v3/universal-ai/",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "input": {"text": text, "voice": voice_name},
            "show_original_response": False,
        },
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()

    if data.get("status") != "success":
        error = data.get("error") or {}
        raise RuntimeError(f"Amazon Polly TTS Eden AI ({model}) error: {error.get('message', str(data)[:300])}")

    audio_url = (data.get("output") or {}).get("audio_resource_url")
    if not audio_url:
        raise RuntimeError(f"Amazon Polly TTS Eden AI: missing audio_resource_url in response: {str(data)[:300]}")

    audio_response = requests.get(audio_url, timeout=30)
    audio_response.raise_for_status()
    Path(output_path).write_bytes(audio_response.content)


def _synthesize_amazon_neural(text: str, output_path: str, voice_id: str) -> None:
    """Call Amazon Neural (Polly) TTS via Eden AI. voice_id: "amazon-<VoiceName>"."""
    _synthesize_amazon_polly(text, output_path, voice_id, "audio/tts/amazon/neural")


def _synthesize_amazon_standard(text: str, output_path: str, voice_id: str) -> None:
    """Call Amazon Standard (Polly) TTS via Eden AI. voice_id: "amazon-std-<VoiceName>"."""
    _synthesize_amazon_polly(text, output_path, voice_id, "audio/tts/amazon/standard")


def _synthesize_openai_tts(text: str, output_path: str, voice_id: str) -> None:
    """Call OpenAI gpt-4o-mini-tts via Eden AI universal endpoint and write MP3 to output_path.

    voice_id format: "openai-<voice_name>" (e.g. "openai-marin", "openai-nova").
    Eden AI responds with a CloudFront URL; the audio is downloaded in a second request.
    """
    api_key = os.environ.get("EDENAI_API_KEY")
    if not api_key:
        raise RuntimeError("EDENAI_API_KEY is not set. Check your .env file.")

    voice_name = voice_id.removeprefix("openai-")

    response = requests.post(
        "https://api.edenai.run/v3/universal-ai/",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "audio/tts/openai/gpt-4o-mini-tts",
            "input": {"text": text, "voice": voice_name},
            "show_original_response": False,
        },
        timeout=60,
    )
    response.raise_for_status()
    data = response.json()

    if data.get("status") != "success":
        error = data.get("error") or {}
        raise RuntimeError(f"OpenAI TTS Eden AI error: {error.get('message', str(data)[:300])}")

    audio_url = (data.get("output") or {}).get("audio_resource_url")
    if not audio_url:
        raise RuntimeError(f"OpenAI TTS Eden AI: missing audio_resource_url in response: {str(data)[:300]}")

    audio_response = requests.get(audio_url, timeout=30)
    audio_response.raise_for_status()
    Path(output_path).write_bytes(audio_response.content)


def synthesize(
    text: str,
    output_path: str,
    *,
    voice_sample: Optional[str] = None,
    voice_id: Optional[str] = _DEFAULT_VOICE_ID,
    voice_format: str = "mp3",
    output_format: str = "mp3",
) -> None:
    """Call Voxtral TTS and write the result to output_path.

    Args:
        text: The text to convert to speech.
        output_path: Where to write the output audio file.
        voice_sample: Path to a voice sample for cloning (optional).
        voice_id: Preset voice UUID. See GET /v1/audio/voices for available IDs.
        voice_format: Format of the voice sample file.
        output_format: Desired output audio format.
    """
    # Google TTS voices (start with 'google-') use Gemini API — route immediately.
    if voice_id and _is_google_voice(voice_id):
        print(f"\U0001f30e Google TTS ({voice_id})...", file=sys.stderr)
        try:
            _synthesize_google_tts(text, output_path, voice_id)
            return
        except Exception as exc:
            print(f"❌ Google TTS failed: {exc}", file=sys.stderr)
            raise

    # ElevenLabs voices via Eden AI (prefix "eleven-") — route before Gradium.
    if voice_id and voice_id.startswith("eleven-"):
        print(f"\U0001f3a4 ElevenLabs TTS via Eden AI ({voice_id})...", file=sys.stderr)
        _synthesize_elevenlabs_eden(text, output_path, voice_id)
        return

    # OpenAI TTS voices via Eden AI (prefix "openai-") — route before Gradium.
    if voice_id and voice_id.startswith("openai-"):
        print(f"\U0001f916 OpenAI TTS via Eden AI ({voice_id})...", file=sys.stderr)
        _synthesize_openai_tts(text, output_path, voice_id)
        return

    # Grok TTS voices via xAI direct API (prefix "grok-") — route before Gradium.
    if voice_id and voice_id.startswith("grok-"):
        print(f"\U0001f916 Grok TTS via xAI ({voice_id})...", file=sys.stderr)
        _synthesize_grok_tts(text, output_path, voice_id)
        return

    # Deepgram Aura 2 voices via Eden AI (prefix "deepgram-") — route before Gradium.
    if voice_id and voice_id.startswith("deepgram-"):
        print(f"\U0001f3a4 Deepgram Aura 2 TTS via Eden AI ({voice_id})...", file=sys.stderr)
        _synthesize_deepgram_aura2(text, output_path, voice_id)
        return

    # Amazon Standard (Polly) voices via Eden AI (prefix "amazon-std-") — before neural check.
    if voice_id and voice_id.startswith("amazon-std-"):
        print(f"\U0001f50a Amazon Standard TTS via Eden AI ({voice_id})...", file=sys.stderr)
        _synthesize_amazon_standard(text, output_path, voice_id)
        return

    # Amazon Neural (Polly) voices via Eden AI (prefix "amazon-") — route before Gradium.
    if voice_id and voice_id.startswith("amazon-"):
        print(f"\U0001f50a Amazon Neural TTS via Eden AI ({voice_id})...", file=sys.stderr)
        _synthesize_amazon_neural(text, output_path, voice_id)
        return

    # Gradium voices (non-UUID IDs) use a separate API — route immediately.
    if voice_id and _is_gradium_voice(voice_id):
        print(f"\U0001f508 Gradium TTS ({voice_id})...", file=sys.stderr)
        _synthesize_gradium(text, output_path, voice_id)
        return

    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        raise RuntimeError("MISTRAL_API_KEY is not set. Check your .env file.")

    # API requires voice_id (preset) OR ref_audio (base64 for cloning).
    # Include language when known for correct pronunciation.
    # Response is JSON {"audio_data": "<base64>"} — must decode to get audio bytes.
    base_payload: dict = {
        "model": _MODEL,
        "input": text,
        "response_format": output_format,
    }

    ref_audio_b64: Optional[str] = None
    if voice_sample and Path(voice_sample).exists():
        ref_audio_b64 = _encode_voice_sample(voice_sample)

    # Estimate timeout: ~1s per 100 chars + base overhead
    timeout = max(10, len(text) // 100 + 15)

    # Try with voice cloning first, then fallback to preset/auto voice.
    attempts = []
    if ref_audio_b64:
        attempts.append(("with voice cloning", {**base_payload, "ref_audio": ref_audio_b64}))
    # The API requires either ref_audio or voice_id — auto mode is not supported.
    resolved_preset = voice_id or _DEFAULT_VOICE_ID
    if resolved_preset:
        attempts.append(("preset voice", {**base_payload, "voice_id": resolved_preset}))
    else:
        # No voice configured at all: this will fail — surface a clear error.
        attempts.append(("no voice", base_payload))

    for label, payload in attempts:
        last_exc: Exception = RuntimeError("unreachable")
        for attempt in range(1 + _REQUEST_RETRIES):
            if attempt > 0:
                print(
                    f"\u23f3  TTS ({label}) — retry {attempt}/{_REQUEST_RETRIES} "
                    f"(waiting {_RETRY_DELAY:.0f}s)\u2026",
                    file=sys.stderr,
                )
                time.sleep(_RETRY_DELAY)
            try:
                response = requests.post(
                    _API_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=timeout,
                )
                response.raise_for_status()
                # Response is JSON: {"audio_data": "<base64-encoded audio>"}
                audio_b64 = response.json()["audio_data"]
                Path(output_path).write_bytes(base64.b64decode(audio_b64))
                return
            except requests.HTTPError as exc:
                code = exc.response.status_code if exc.response is not None else None
                if exc.response is not None:
                    print(
                        f"\u274c TTS API error {code} ({label}): {exc.response.text[:500]}",
                        file=sys.stderr,
                    )
                if code in _TRANSIENT_HTTP_CODES:
                    last_exc = exc
                    continue
                # Non-transient error (422, etc.) — skip to next attempt mode
                last_exc = exc
                break
            except requests.Timeout as exc:
                print(f"\u23f1\ufe0f  TTS timed out ({timeout}s) \u2014 will retry\u2026", file=sys.stderr)
                last_exc = exc
                continue
        else:
            # All retries exhausted for this mode — try next
            if len(attempts) > 1 and label != "default voice":
                print(
                    f"\u26a0\ufe0f  Voice cloning failed \u2014 falling back to default voice.",
                    file=sys.stderr,
                )
                continue
        # Non-transient error broke out of retry loop — try next mode
        if len(attempts) > 1 and label != "default voice":
            print(
                f"\u26a0\ufe0f  Voice cloning failed \u2014 falling back to default voice.",
                file=sys.stderr,
            )
            continue
        raise last_exc
    raise last_exc  # type: ignore[possibly-undefined]


if __name__ == "__main__":
    # ── Chunked mode: --chunked <output_dir> ──────────────────────────────────
    # Splits text into sentence-boundary chunks, generates them with up to 2
    # parallel workers, and prints each output file path to stdout as soon as
    # it is ready — allowing the caller to start playback immediately.
    if len(sys.argv) >= 3 and sys.argv[1] == "--chunked":
        chunks_dir = sys.argv[2]
        Path(chunks_dir).mkdir(parents=True, exist_ok=True)

        text = sys.stdin.read().strip()
        if not text:
            print("\u274c No input text received.", file=sys.stderr)
            sys.exit(1)

        # TTS_SKIP_AI_CLEAN=1: skip the two-call Mistral detection+cleaning step.
        # Use this when the text is already clean (e.g. AI-generated summaries).
        # _clean_text() + _isolate_quotes() still run so quote voice switching works.
        if os.environ.get("TTS_SKIP_AI_CLEAN") == "1":
            text = _strip_markdown(_isolate_quotes(_expand_function_calls(_expand_math_symbols(_clean_text(text)))))
        else:
            text = _strip_markdown(_isolate_quotes(_expand_function_calls(_expand_math_symbols(_ai_clean_text(text)))))
        if not text:
            print("\u274c Text is empty after cleaning.", file=sys.stderr)
            sys.exit(1)

        # Expose the cleaned text so other branches (e.g. display_meta) can reuse
        # it without re-running the cleaning IA. Atomic write: tmp + rename.
        cleaned_out = os.environ.get("TTS_CLEANED_TEXT_OUT")
        if cleaned_out:
            try:
                tmp_path = cleaned_out + ".tmp"
                Path(tmp_path).write_text(text, encoding="utf-8")
                os.replace(tmp_path, cleaned_out)
            except OSError as exc:
                print(f"\u26a0\ufe0f  Could not write cleaned text to {cleaned_out}: {exc}", file=sys.stderr)

        # Display cleaned text in terminal with centralized UI colors
        _BG = f"{BG_BLUE}{WHITE}"
        print(f"{'─' * 64}", file=sys.stderr)
        print(f"{BGREEN}  Cleaned text — ready for text-to-speech.{RESET}", file=sys.stderr)
        print(f"{'─' * 64}", file=sys.stderr)
        for _line in text.splitlines():
            print(f"{_BG}{_line}{RESET}", file=sys.stderr)
        print(f"{'─' * 64}", file=sys.stderr)

        resolved_voice_id = _resolve_voice_id()
        quote_voice_id: Optional[str] = os.environ.get("TTS_QUOTE_VOICE_ID") or None
        if quote_voice_id:
            print(f"\U0001f4ac Quote voice: {quote_voice_id}", file=sys.stderr)

        chunk_tuples = _make_chunks(text, quote_voice_id=quote_voice_id)
        total = len(chunk_tuples)
        print(
            f"\U0001f50a Generating {total} chunk(s) via {_MODEL} ({len(text)} chars)...",
            file=sys.stderr,
        )

        # Compute char_start/char_end of each chunk inside the cleaned text so
        # the web display can align audio playback with display_meta output.
        # Each chunk text is a contiguous substring (paragraphs joined by "\n\n",
        # or a sub-split of one paragraph). We search forward, never backtracking.
        chunk_positions: list[tuple[int, int]] = []
        _search_from = 0
        for chunk_text, _voice in chunk_tuples:
            pos = text.find(chunk_text, _search_from)
            if pos < 0:
                # Fallback: search from start (rare — should never happen with
                # paragraph-aligned chunks). Better than crashing.
                pos = text.find(chunk_text)
            if pos < 0:
                # Still not found: emit zero-width range at last known position.
                chunk_positions.append((_search_from, _search_from))
            else:
                end = pos + len(chunk_text)
                chunk_positions.append((pos, end))
                _search_from = end

        _CHUNK_MAX_ATTEMPTS = 5
        _CHUNK_RETRY_DELAYS = [2, 4, 8, 15]  # escalating delays between retries
        _MIN_AUDIO_BYTES = 1024  # valid mp3 should be > 1 KB

        def _gen_chunk(args: tuple[int, str, Optional[str]]) -> str:
            idx, chunk_text, chunk_voice_id = args
            citation_voice = chunk_voice_id if chunk_voice_id is not None else resolved_voice_id
            out = str(Path(chunks_dir) / f"chunk_{idx:03d}.mp3")
            Path(chunks_dir, f"chunk_{idx:03d}.txt").write_text(chunk_text, encoding="utf-8")
            # Sidecar with chunk's char position in the cleaned text — consumed
            # by the bash flow to enrich the web display SSE chunk event.
            try:
                _cs, _ce = chunk_positions[idx]
                import json as _json
                Path(chunks_dir, f"chunk_{idx:03d}.json").write_text(
                    _json.dumps({"char_start": _cs, "char_end": _ce}),
                    encoding="utf-8",
                )
            except (IndexError, OSError):
                pass
            last_exc: Exception = RuntimeError("unknown")
            # Attempts 0-2 use the requested voice; attempts 3-4 fall back to
            # resolved_voice_id so the text is always read even if citation voice
            # is wrong for the language or temporarily unavailable.
            _FALLBACK_AT = 3
            for attempt in range(_CHUNK_MAX_ATTEMPTS):
                use_voice = citation_voice
                if attempt >= _FALLBACK_AT and citation_voice != resolved_voice_id:
                    if attempt == _FALLBACK_AT:
                        print(
                            f"  \u26a0\ufe0f  Voix citation \u00e9chou\u00e9e \u2014 repli sur la voix normale.",
                            file=sys.stderr,
                        )
                    use_voice = resolved_voice_id
                try:
                    synthesize(chunk_text, out, voice_id=use_voice)
                    out_size = Path(out).stat().st_size if Path(out).exists() else 0
                    if out_size < _MIN_AUDIO_BYTES:
                        raise RuntimeError(f"audio trop petit ({out_size} octets)")
                    print(f"  \u2705 Passage {idx + 1}/{total} OK ({out_size:,} octets)", file=sys.stderr)
                    return out
                except Exception as exc:
                    last_exc = exc
                    delay = _CHUNK_RETRY_DELAYS[min(attempt, len(_CHUNK_RETRY_DELAYS) - 1)]
                    print(
                        f"  \u26a0\ufe0f  Passage {idx + 1}/{total} tentative {attempt + 1}/{_CHUNK_MAX_ATTEMPTS}"
                        f" \u00e9chou\u00e9e: {exc}",
                        file=sys.stderr,
                    )
                    if attempt < _CHUNK_MAX_ATTEMPTS - 1:
                        print(f"     Nouvelle tentative dans {delay}s\u2026", file=sys.stderr)
                        time.sleep(delay)
            raise last_exc

        with ThreadPoolExecutor(max_workers=3) as executor:
            # Submit with a slight stagger (0.5s between submissions) to avoid
            # hitting Mistral rate limits while keeping 2-3 chunks pre-generating.
            futures = []
            for i, (chunk_text, chunk_voice) in enumerate(chunk_tuples):
                futures.append(executor.submit(_gen_chunk, (i, chunk_text, chunk_voice)))
                if i < len(chunk_tuples) - 1:
                    time.sleep(0.5)
            for i, fut in enumerate(futures):
                try:
                    print(fut.result(), flush=True)
                except Exception as exc:
                    # Signal bash that this position failed — bash will offer retry
                    print(f"CHUNK_FAILED:{i}", flush=True)
                    print(f"\u274c Chunk {i + 1}/{total} definitively failed: {exc}", file=sys.stderr)

        sys.exit(0)

    # ── Single-file mode (default) ────────────────────────────────────────────
    if len(sys.argv) < 2:
        print(
            "Usage: tts.py <output_mp3> [voice_sample]\n"
            "       tts.py --chunked <output_dir>  (reads stdin, prints chunk paths)\n"
            "       Text is read from stdin.\n"
            "       voice_sample is optional (enables voice cloning).",
            file=sys.stderr,
        )
        sys.exit(1)

    output_file = sys.argv[1]
    sample_file = sys.argv[2] if len(sys.argv) > 2 else None

    text = sys.stdin.read().strip()
    if not text:
        print("\u274c No input text received.", file=sys.stderr)
        sys.exit(1)

    voice_fmt = "mp3"
    if sample_file and sample_file.endswith(".wav"):
        voice_fmt = "wav"

    resolved_voice_id = _resolve_voice_id()

    print(
        f"\U0001f50a Generating speech via {_MODEL} ({len(text)} chars)...",
        file=sys.stderr,
    )
    synthesize(
        text,
        output_file,
        voice_sample=sample_file,
        voice_format=voice_fmt,
        voice_id=resolved_voice_id,
    )
    print(f"\u2705 Audio saved to {output_file}", file=sys.stderr)

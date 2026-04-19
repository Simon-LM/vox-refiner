#!/usr/bin/env python3
"""Step 1 (F8/F9): Image file → extracted text via Mistral OCR API.

Cascade order (tiers activated by available keys):
  1. mistral-ocr-latest         (/v1/ocr — Mistral direct)            MISTRAL_API_KEY
  2. Eden OCR async              (/v3/universal-ai/async — Eden)       EDENAI_API_KEY
  3. pixtral-large-latest        (/v1/chat/completions — Mistral vis.) MISTRAL_API_KEY
  4. mistral/pixtral-large-latest(/v3/llm/chat/completions — Eden vis.)EDENAI_API_KEY

With both keys: 1 → 2 → 3 → 4
With MISTRAL_API_KEY only: 1 → 3
With EDENAI_API_KEY only:  2 → 4
"""

import base64
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from src.providers import EDEN_CHAT_URL, ProviderError, call_ocr_async, is_available, resolve  # noqa: E402

_OCR_URL      = "https://api.mistral.ai/v1/ocr"
_CHAT_URL     = "https://api.mistral.ai/v1/chat/completions"
_OCR_MODEL    = "mistral-ocr-latest"
_VISION_MODEL = "pixtral-large-latest"
_EDEN_VISION_MODEL = "mistral/pixtral-large-latest"
_TIMEOUT      = 30
_RETRIES      = 2
_RETRY_DELAY  = 2.0
_TRANSIENT_HTTP_CODES = (429, 500, 502, 503)

_FALLBACK_PROMPT = (
    "Extract all text from this image exactly as it appears, "
    "preserving line breaks and structure. Output only the extracted text, "
    "no commentary."
)


def _encode_image(image_path: str) -> str:
    with open(image_path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def _mime_type(image_path: str) -> str:
    suffix = Path(image_path).suffix.lower()
    return {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}.get(
        suffix.lstrip("."), "image/png"
    )


def _request_with_retry(url: str, headers: dict, payload: dict) -> dict:
    """POST with retry on transient errors. Returns parsed JSON body."""
    last_exc: Exception = RuntimeError("unreachable")
    for attempt in range(1 + _RETRIES):
        if attempt > 0:
            print(
                f"  ⏳  OCR — retry {attempt}/{_RETRIES} (waiting {_RETRY_DELAY:.0f}s)…",
                file=sys.stderr,
            )
            time.sleep(_RETRY_DELAY)
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else None
            if code in _TRANSIENT_HTTP_CODES:
                label = "rate limit (429)" if code == 429 else f"server error ({code})"
                print(f"  ⚠️  OCR {label} — will retry…", file=sys.stderr)
                last_exc = exc
                continue
            raise
        except requests.Timeout as exc:
            print(f"  ⏱  OCR timed out ({_TIMEOUT}s) — will retry…", file=sys.stderr)
            last_exc = exc
            continue
    raise last_exc


def _vision_messages(image_b64: str, mime: str, model: str) -> list:
    return [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": f"data:{mime};base64,{image_b64}",
                },
                {"type": "text", "text": _FALLBACK_PROMPT},
            ],
        }
    ]


def _extract_primary(image_b64: str, mime: str, api_key: str) -> str:
    """Call mistral-ocr-latest via the dedicated /v1/ocr endpoint."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": _OCR_MODEL,
        "document": {
            "type": "image_url",
            "image_url": f"data:{mime};base64,{image_b64}",
        },
    }
    body = _request_with_retry(_OCR_URL, headers, payload)
    pages = body.get("pages", [])
    if not pages:
        raise RuntimeError(f"Empty OCR response: {body}")
    return "\n\n".join(p.get("markdown", "") for p in pages).strip()


def _extract_vision_fallback(image_b64: str, mime: str, api_key: str) -> str:
    """Call pixtral-large-latest via Mistral chat completions (vision)."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": _VISION_MODEL,
        "messages": _vision_messages(image_b64, mime, _VISION_MODEL),
    }
    body = _request_with_retry(_CHAT_URL, headers, payload)
    choices = body.get("choices", [])
    if not choices:
        raise RuntimeError(f"Empty vision fallback response: {body}")
    return choices[0].get("message", {}).get("content", "").strip()


def _extract_eden_vision_fallback(image_b64: str, mime: str, api_key: str) -> str:
    """Call mistral/pixtral-large-latest via Eden AI chat (vision)."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": _EDEN_VISION_MODEL,
        "messages": _vision_messages(image_b64, mime, _EDEN_VISION_MODEL),
    }
    body = _request_with_retry(EDEN_CHAT_URL, headers, payload)
    choices = body.get("choices", [])
    if not choices:
        raise RuntimeError(f"Empty Eden vision response: {body}")
    return choices[0].get("message", {}).get("content", "").strip()


def _write_ocr_meta(
    requested_model: str,
    effective_model: str,
    provider_name: str,
    provider_display: str,
    substituted: bool = False,
) -> None:
    """Write provider/model metadata to VOXREFINER_OCR_META_FILE when set.

    Uses the same 5-line format as insight._write_model_meta so the shell
    helper _model_label_suffix can consume it directly.
    """
    meta_file = os.environ.get("VOXREFINER_OCR_META_FILE")
    if not meta_file:
        return
    try:
        lines = [
            requested_model,
            effective_model,
            provider_name,
            provider_display,
            "1" if substituted else "0",
        ]
        Path(meta_file).write_text("\n".join(lines), encoding="utf-8")
    except OSError:
        pass


def ocr(image_path: str) -> str:
    """Extract text from *image_path* using the first available OCR tier.

    Cascade (see module docstring for the full rules):
      1. mistral-ocr-latest       — Mistral direct
      2. Eden OCR async            — Eden AI
      3. pixtral-large-latest     — Mistral direct (vision)
      4. pixtral-large via Eden   — Eden AI (vision)

    Raises RuntimeError if every available tier fails.
    """
    if not is_available("ocr"):
        raise RuntimeError(
            "No OCR provider available. Set MISTRAL_API_KEY "
            "(or EDENAI_API_KEY as fallback)."
        )

    size = Path(image_path).stat().st_size
    print(f"  🖼  Image read: {size} bytes.", file=sys.stderr)

    image_b64 = _encode_image(image_path)
    mime = _mime_type(image_path)

    for provider in resolve("ocr"):
        try:
            if provider.adapter_type == "mistral_ocr":
                print(f"  🔍 Running OCR via {_OCR_MODEL}…", file=sys.stderr)
                text = _extract_primary(image_b64, mime, provider.key())
                _write_ocr_meta(_OCR_MODEL, _OCR_MODEL, provider.name, provider.display_name)

            elif provider.adapter_type == "eden_ocr":
                print("  🔍 Running OCR via Eden AI (async)…", file=sys.stderr)
                text = call_ocr_async(image_b64, mime)
                _write_ocr_meta(
                    "ocr/ocr_async/mistral", "ocr/ocr_async/mistral",
                    provider.name, provider.display_name,
                )

            elif provider.name == "mistral_vision":
                print(f"  🔍 Running OCR via {_VISION_MODEL} (vision fallback)…", file=sys.stderr)
                text = _extract_vision_fallback(image_b64, mime, provider.key())
                _write_ocr_meta(_VISION_MODEL, _VISION_MODEL, provider.name, provider.display_name)

            else:  # eden_mistral — pixtral via Eden AI chat
                print(f"  🔍 Running OCR via {_EDEN_VISION_MODEL} (Eden vision fallback)…", file=sys.stderr)
                text = _extract_eden_vision_fallback(image_b64, mime, provider.key())
                _write_ocr_meta(
                    _EDEN_VISION_MODEL, _EDEN_VISION_MODEL,
                    provider.name, provider.display_name,
                )

            return text

        except Exception as exc:
            print(
                f"  ⚠️  {provider.display_name} failed ({exc}) — trying next tier…",
                file=sys.stderr,
            )

    raise RuntimeError("All OCR providers failed.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: ocr.py <image_file>", file=sys.stderr)
        sys.exit(1)

    image_file = sys.argv[1]

    if not Path(image_file).exists():
        print(f"❌ File not found: {image_file}", file=sys.stderr)
        sys.exit(1)

    try:
        result = ocr(image_file)
        print(result)  # stdout only — captured by the shell script
    except RuntimeError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        sys.exit(1)

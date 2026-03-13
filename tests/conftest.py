"""Shared fixtures for the vox-refiner test suite."""

import pytest


@pytest.fixture()
def fake_api_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Inject a dummy API key so functions don't raise RuntimeError."""
    key = "test-api-key-000"
    monkeypatch.setenv("MISTRAL_API_KEY", key)
    return key


@pytest.fixture()
def context_file(tmp_path: pytest.TempPathFactory):
    """Return a factory that writes a context.txt in a tmp dir and patches _CONTEXT_FILE."""
    return tmp_path


def mistral_chat_response(content) -> dict:
    """Build a minimal Mistral chat API response payload.

    content can be a str (standard model) or a list of blocks (magistral).
    """
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": content,
                }
            }
        ]
    }


def mistral_transcription_response(text: str) -> dict:
    """Build a minimal Mistral transcription API response payload."""
    return {"text": text}

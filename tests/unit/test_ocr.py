"""Unit tests for src/ocr.py and providers.call_ocr_async().

Coverage:
  - ocr() cascade with both keys:   tier 1 → 2 → 3 → 4
  - ocr() with MISTRAL_API_KEY only: tier 1 → 3
  - ocr() with EDENAI_API_KEY only:  tier 2 → 4
  - ocr() availability guard (no keys)
  - ocr() meta-file written with correct provider info at each tier
  - call_ocr_async(): job submission → polling → text extraction
  - call_ocr_async(): multiple response shapes (A/B/C/D)
  - call_ocr_async(): job-failure, missing key, missing public_id
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))


# ── helpers ───────────────────────────────────────────────────────────────────

def _fake_image(tmp_path: Path) -> str:
    p = tmp_path / "img.png"
    p.write_bytes(b"\x89PNG\r\n" + b"X" * 100)
    return str(p)


def _ocr_resp(text: str = "hello") -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    r.raise_for_status = MagicMock()
    r.json.return_value = {"pages": [{"markdown": text}]}
    return r


def _chat_resp(text: str = "hello") -> MagicMock:
    r = MagicMock()
    r.status_code = 200
    r.raise_for_status = MagicMock()
    r.json.return_value = {"choices": [{"message": {"content": text}}]}
    return r


# ── cascade — both keys present ───────────────────────────────────────────────

class TestOcrBothKeys:
    def setup_method(self):
        # patch at function level throughout this class
        self._patches = []

    def test_tier1_success(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MISTRAL_API_KEY", "k")
        monkeypatch.setenv("EDENAI_API_KEY", "e")
        img = _fake_image(tmp_path)
        with patch("src.ocr._extract_primary", return_value="T1 text") as p1, \
             patch("src.ocr.call_ocr_async") as p2, \
             patch("src.ocr._extract_vision_fallback") as p3, \
             patch("src.ocr._extract_eden_vision_fallback") as p4:
            from src.ocr import ocr
            result = ocr(img)
        assert result == "T1 text"
        p1.assert_called_once()
        p2.assert_not_called()
        p3.assert_not_called()
        p4.assert_not_called()

    def test_tier1_fail_uses_tier2(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MISTRAL_API_KEY", "k")
        monkeypatch.setenv("EDENAI_API_KEY", "e")
        img = _fake_image(tmp_path)
        with patch("src.ocr._extract_primary", side_effect=RuntimeError("down")), \
             patch("src.ocr.call_ocr_async", return_value="T2 text") as p2, \
             patch("src.ocr._extract_vision_fallback") as p3, \
             patch("src.ocr._extract_eden_vision_fallback") as p4:
            from src.ocr import ocr
            result = ocr(img)
        assert result == "T2 text"
        p2.assert_called_once()
        p3.assert_not_called()
        p4.assert_not_called()

    def test_tier2_fail_uses_tier3(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MISTRAL_API_KEY", "k")
        monkeypatch.setenv("EDENAI_API_KEY", "e")
        img = _fake_image(tmp_path)
        from src.providers import ProviderError
        with patch("src.ocr._extract_primary", side_effect=RuntimeError("down")), \
             patch("src.ocr.call_ocr_async", side_effect=ProviderError("eden down")), \
             patch("src.ocr._extract_vision_fallback", return_value="T3 text") as p3, \
             patch("src.ocr._extract_eden_vision_fallback") as p4:
            from src.ocr import ocr
            result = ocr(img)
        assert result == "T3 text"
        p3.assert_called_once()
        p4.assert_not_called()

    def test_tier3_fail_uses_tier4(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MISTRAL_API_KEY", "k")
        monkeypatch.setenv("EDENAI_API_KEY", "e")
        img = _fake_image(tmp_path)
        from src.providers import ProviderError
        with patch("src.ocr._extract_primary", side_effect=RuntimeError("down")), \
             patch("src.ocr.call_ocr_async", side_effect=ProviderError("down")), \
             patch("src.ocr._extract_vision_fallback", side_effect=RuntimeError("down")), \
             patch("src.ocr._extract_eden_vision_fallback", return_value="T4 text") as p4:
            from src.ocr import ocr
            result = ocr(img)
        assert result == "T4 text"
        p4.assert_called_once()

    def test_all_fail_raises(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MISTRAL_API_KEY", "k")
        monkeypatch.setenv("EDENAI_API_KEY", "e")
        img = _fake_image(tmp_path)
        from src.providers import ProviderError
        with patch("src.ocr._extract_primary", side_effect=RuntimeError("down")), \
             patch("src.ocr.call_ocr_async", side_effect=ProviderError("down")), \
             patch("src.ocr._extract_vision_fallback", side_effect=RuntimeError("down")), \
             patch("src.ocr._extract_eden_vision_fallback", side_effect=RuntimeError("down")):
            from src.ocr import ocr
            with pytest.raises(RuntimeError, match="All OCR providers failed"):
                ocr(img)


# ── cascade — Mistral key only ────────────────────────────────────────────────

class TestOcrMistralOnly:
    def test_tier1_success_skips_eden(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MISTRAL_API_KEY", "k")
        monkeypatch.delenv("EDENAI_API_KEY", raising=False)
        img = _fake_image(tmp_path)
        with patch("src.ocr._extract_primary", return_value="text") as p1, \
             patch("src.ocr.call_ocr_async") as p2:
            from src.ocr import ocr
            ocr(img)
        p1.assert_called_once()
        p2.assert_not_called()

    def test_tier1_fail_uses_tier3_not_tier2(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MISTRAL_API_KEY", "k")
        monkeypatch.delenv("EDENAI_API_KEY", raising=False)
        img = _fake_image(tmp_path)
        with patch("src.ocr._extract_primary", side_effect=RuntimeError("down")), \
             patch("src.ocr.call_ocr_async") as p2, \
             patch("src.ocr._extract_vision_fallback", return_value="vision text") as p3:
            from src.ocr import ocr
            result = ocr(img)
        assert result == "vision text"
        p2.assert_not_called()
        p3.assert_called_once()

    def test_all_mistral_fail_raises_no_eden_attempt(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MISTRAL_API_KEY", "k")
        monkeypatch.delenv("EDENAI_API_KEY", raising=False)
        img = _fake_image(tmp_path)
        with patch("src.ocr._extract_primary", side_effect=RuntimeError("down")), \
             patch("src.ocr.call_ocr_async") as p2, \
             patch("src.ocr._extract_vision_fallback", side_effect=RuntimeError("down")), \
             patch("src.ocr._extract_eden_vision_fallback") as p4:
            from src.ocr import ocr
            with pytest.raises(RuntimeError):
                ocr(img)
        p2.assert_not_called()
        p4.assert_not_called()


# ── cascade — Eden key only ───────────────────────────────────────────────────

class TestOcrEdenOnly:
    def test_tier2_used_when_no_mistral(self, monkeypatch, tmp_path):
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        monkeypatch.setenv("EDENAI_API_KEY", "e")
        img = _fake_image(tmp_path)
        with patch("src.ocr._extract_primary") as p1, \
             patch("src.ocr.call_ocr_async", return_value="eden text") as p2, \
             patch("src.ocr._extract_vision_fallback") as p3:
            from src.ocr import ocr
            result = ocr(img)
        assert result == "eden text"
        p1.assert_not_called()
        p3.assert_not_called()
        p2.assert_called_once()

    def test_tier2_fail_uses_tier4(self, monkeypatch, tmp_path):
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        monkeypatch.setenv("EDENAI_API_KEY", "e")
        img = _fake_image(tmp_path)
        from src.providers import ProviderError
        with patch("src.ocr._extract_primary") as p1, \
             patch("src.ocr.call_ocr_async", side_effect=ProviderError("down")), \
             patch("src.ocr._extract_vision_fallback") as p3, \
             patch("src.ocr._extract_eden_vision_fallback", return_value="eden vis") as p4:
            from src.ocr import ocr
            result = ocr(img)
        assert result == "eden vis"
        p1.assert_not_called()
        p3.assert_not_called()
        p4.assert_called_once()


# ── no keys ───────────────────────────────────────────────────────────────────

class TestOcrNoKeys:
    def test_raises_runtime_error(self, monkeypatch, tmp_path):
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        monkeypatch.delenv("EDENAI_API_KEY", raising=False)
        img = _fake_image(tmp_path)
        from src.ocr import ocr
        with pytest.raises(RuntimeError, match="No OCR provider"):
            ocr(img)


# ── meta-file ─────────────────────────────────────────────────────────────────

class TestOcrMetaFile:
    def test_tier1_writes_mistral_ocr(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MISTRAL_API_KEY", "k")
        monkeypatch.delenv("EDENAI_API_KEY", raising=False)
        meta = tmp_path / "ocr_meta"
        monkeypatch.setenv("VOXREFINER_OCR_META_FILE", str(meta))
        img = _fake_image(tmp_path)
        with patch("src.ocr._extract_primary", return_value="text"):
            from src.ocr import ocr
            ocr(img)
        lines = meta.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "mistral-ocr-latest"
        assert lines[2] == "mistral_ocr"
        assert lines[4] == "0"

    def test_tier2_writes_eden_ocr(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MISTRAL_API_KEY", "k")
        monkeypatch.setenv("EDENAI_API_KEY", "e")
        meta = tmp_path / "ocr_meta"
        monkeypatch.setenv("VOXREFINER_OCR_META_FILE", str(meta))
        img = _fake_image(tmp_path)
        with patch("src.ocr._extract_primary", side_effect=RuntimeError("down")), \
             patch("src.ocr.call_ocr_async", return_value="eden text"):
            from src.ocr import ocr
            ocr(img)
        lines = meta.read_text(encoding="utf-8").splitlines()
        assert lines[2] == "eden_ocr_mistral"

    def test_tier3_writes_mistral_vision(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MISTRAL_API_KEY", "k")
        monkeypatch.delenv("EDENAI_API_KEY", raising=False)
        meta = tmp_path / "ocr_meta"
        monkeypatch.setenv("VOXREFINER_OCR_META_FILE", str(meta))
        img = _fake_image(tmp_path)
        with patch("src.ocr._extract_primary", side_effect=RuntimeError("down")), \
             patch("src.ocr._extract_vision_fallback", return_value="vis text"):
            from src.ocr import ocr
            ocr(img)
        lines = meta.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "pixtral-large-latest"
        assert lines[2] == "mistral_vision"

    def test_tier4_writes_eden_mistral(self, monkeypatch, tmp_path):
        monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
        monkeypatch.setenv("EDENAI_API_KEY", "e")
        meta = tmp_path / "ocr_meta"
        monkeypatch.setenv("VOXREFINER_OCR_META_FILE", str(meta))
        img = _fake_image(tmp_path)
        from src.providers import ProviderError
        with patch("src.ocr.call_ocr_async", side_effect=ProviderError("down")), \
             patch("src.ocr._extract_eden_vision_fallback", return_value="eden vis"):
            from src.ocr import ocr
            ocr(img)
        lines = meta.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "mistral/pixtral-large-latest"
        assert lines[2] == "eden_mistral"


# ── call_ocr_async() ──────────────────────────────────────────────────────────

class TestCallOcrAsync:
    def _job_resp(self, job_id: str = "job123") -> MagicMock:
        r = MagicMock()
        r.status_code = 200
        r.raise_for_status = MagicMock()
        r.json.return_value = {"public_id": job_id}
        return r

    def _poll_resp(self, status: str = "completed", data: dict | None = None) -> MagicMock:
        r = MagicMock()
        r.status_code = 200
        r.raise_for_status = MagicMock()
        body = {"public_id": "job123", "status": status}
        if data:
            body.update(data)
        r.json.return_value = body
        return r

    def test_happy_path_shape_a(self, monkeypatch):
        monkeypatch.setenv("EDENAI_API_KEY", "key-e")
        poll_data = {
            "output": [{"prediction": {"pages": [{"markdown": "Page one"}, {"markdown": "Page two"}]}}]
        }
        with patch("src.providers.requests.post", return_value=self._job_resp()), \
             patch("src.providers.requests.get", return_value=self._poll_resp("completed", poll_data)), \
             patch("src.providers.time.sleep"):
            from src.providers import call_ocr_async
            result = call_ocr_async("aGVsbG8=", "image/png", timeout=10, poll_interval=0.01)
        assert result == "Page one\n\nPage two"

    def test_happy_path_shape_c(self, monkeypatch):
        monkeypatch.setenv("EDENAI_API_KEY", "key-e")
        poll_data = {"result": {"pages": [{"markdown": "Only page"}]}}
        with patch("src.providers.requests.post", return_value=self._job_resp()), \
             patch("src.providers.requests.get", return_value=self._poll_resp("completed", poll_data)), \
             patch("src.providers.time.sleep"):
            from src.providers import call_ocr_async
            result = call_ocr_async("x", "image/png", timeout=10)
        assert result == "Only page"

    def test_happy_path_shape_d(self, monkeypatch):
        monkeypatch.setenv("EDENAI_API_KEY", "key-e")
        poll_data = {"text": "Flat text"}
        with patch("src.providers.requests.post", return_value=self._job_resp()), \
             patch("src.providers.requests.get", return_value=self._poll_resp("completed", poll_data)), \
             patch("src.providers.time.sleep"):
            from src.providers import call_ocr_async
            result = call_ocr_async("x", "image/png", timeout=10)
        assert result == "Flat text"

    def test_pending_then_completed(self, monkeypatch):
        monkeypatch.setenv("EDENAI_API_KEY", "key-e")
        pending = self._poll_resp("pending")
        done    = self._poll_resp("completed", {"text": "Done"})
        with patch("src.providers.requests.post", return_value=self._job_resp()), \
             patch("src.providers.requests.get", side_effect=[pending, pending, done]) as g, \
             patch("src.providers.time.sleep"):
            from src.providers import call_ocr_async
            result = call_ocr_async("x", "image/png", timeout=60)
        assert result == "Done"
        assert g.call_count == 3

    def test_job_failure_raises_provider_error(self, monkeypatch):
        monkeypatch.setenv("EDENAI_API_KEY", "key-e")
        failed = self._poll_resp("failed", {"error": "OCR engine crashed"})
        with patch("src.providers.requests.post", return_value=self._job_resp()), \
             patch("src.providers.requests.get", return_value=failed), \
             patch("src.providers.time.sleep"):
            from src.providers import call_ocr_async, ProviderError
            with pytest.raises(ProviderError, match="OCR engine crashed"):
                call_ocr_async("x", "image/png", timeout=30)

    def test_no_eden_key_raises_provider_error(self, monkeypatch):
        monkeypatch.delenv("EDENAI_API_KEY", raising=False)
        from src.providers import call_ocr_async, ProviderError
        with pytest.raises(ProviderError, match="EDENAI_API_KEY"):
            call_ocr_async("x", "image/png")

    def test_no_public_id_raises_provider_error(self, monkeypatch):
        monkeypatch.setenv("EDENAI_API_KEY", "key-e")
        bad = MagicMock()
        bad.status_code = 200
        bad.raise_for_status = MagicMock()
        bad.json.return_value = {}
        with patch("src.providers.requests.post", return_value=bad):
            from src.providers import call_ocr_async, ProviderError
            with pytest.raises(ProviderError, match="public_id"):
                call_ocr_async("x", "image/png")

"""Integration tests for record_and_transcribe_local.sh safeguards.

These tests execute the shell script in a sandbox directory and stub external
tools (`rec`, `ffmpeg`, `xclip`) to avoid hardware and system dependencies.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR)


def _build_sandbox(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    repo_root = Path(__file__).resolve().parents[2]
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()

    # Copy the script under test so its "cd dirname $0" stays inside sandbox.
    script_src = repo_root / "record_and_transcribe_local.sh"
    script_dst = sandbox / "record_and_transcribe_local.sh"
    shutil.copy2(script_src, script_dst)
    script_dst.chmod(script_dst.stat().st_mode | stat.S_IXUSR)

    # Minimal Python entrypoints expected by the shell script.
    src_dir = sandbox / "src"
    src_dir.mkdir()

    # Minimal venv python expected by the script under test.
    venv_bin = sandbox / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    _write_executable(
        venv_bin / "python",
        """
#!/usr/bin/env bash
set -euo pipefail
exec python3 "$@"
""".strip()
        + "\n",
    )

    (src_dir / "transcribe.py").write_text(
        """
import sys
from pathlib import Path

audio = Path(sys.argv[1])
if not audio.exists():
    raise SystemExit(2)
print("raw transcription")
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (src_dir / "refine.py").write_text(
        """
import sys

if "--update-history" in sys.argv:
    raise SystemExit(0)

text = sys.stdin.read()
print(text.strip() + " [refined]")
""".strip()
        + "\n",
        encoding="utf-8",
    )

    fake_bin = sandbox / "fake-bin"
    fake_bin.mkdir()

    # rec: writes a WAV payload to the destination file (last positional arg).
    _write_executable(
        fake_bin / "rec",
        """
#!/usr/bin/env bash
set -euo pipefail
out="${@: -1}"
size="${FAKE_WAV_SIZE:-64}"
python3 - "$out" "$size" <<'PY'
import pathlib
import sys

dest = pathlib.Path(sys.argv[1])
size = int(sys.argv[2])
dest.write_bytes(b"W" * size)
PY
touch "${SANDBOX_DIR}/rec.called"
""".strip()
        + "\n",
    )

    # ffmpeg: simulates successful conversion and records invocation.
    _write_executable(
        fake_bin / "ffmpeg",
        """
#!/usr/bin/env bash
set -euo pipefail
out="${@: -1}"
printf 'new-mp3' > "$out"
touch "${SANDBOX_DIR}/ffmpeg.called"
""".strip()
        + "\n",
    )

    # xclip: consume stdin and write to per-selection capture files.
    _write_executable(
        fake_bin / "xclip",
        """
#!/usr/bin/env bash
set -euo pipefail
selection="clipboard"
if [[ "${1:-}" == "-selection" ]]; then
  selection="${2:-clipboard}"
fi
cat > "${SANDBOX_DIR}/xclip.${selection}.txt"
""".strip()
        + "\n",
    )

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
    env["SANDBOX_DIR"] = str(sandbox)
    env["ENABLE_REFINE"] = "false"
    env["ENABLE_HISTORY"] = "false"

    return sandbox, env


def _run_script(sandbox: Path, env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "record_and_transcribe_local.sh", *args],
        cwd=sandbox,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def test_recording_mode_cleans_and_rebuilds_audio_artifacts(tmp_path: Path):
    sandbox, env = _build_sandbox(tmp_path)
    (sandbox / "local_audio.wav").write_text("stale-wav", encoding="utf-8")
    (sandbox / "local_audio.mp3").write_text("stale-mp3", encoding="utf-8")

    result = _run_script(sandbox, env)

    assert result.returncode == 0, result.stderr
    assert (sandbox / "rec.called").exists()
    assert (sandbox / "ffmpeg.called").exists()
    assert (sandbox / "local_audio.wav").exists()
    assert (sandbox / "local_audio.wav").read_bytes() == b"W" * 64
    assert (sandbox / "local_audio.mp3").read_text(encoding="utf-8") == "new-mp3"


def test_oversized_temp_wav_is_rejected_before_ffmpeg(tmp_path: Path):
    sandbox, env = _build_sandbox(tmp_path)
    env["FAKE_WAV_SIZE"] = "128"
    env["MAX_WAV_BYTES"] = "64"

    result = _run_script(sandbox, env)

    assert result.returncode == 1
    assert "abnormally large" in result.stdout
    assert not (sandbox / "ffmpeg.called").exists()
    assert not (sandbox / "local_audio.wav").exists()


def test_retry_mode_skips_recording_and_processing(tmp_path: Path):
    sandbox, env = _build_sandbox(tmp_path)
    (sandbox / "local_audio.mp3").write_text("existing-mp3", encoding="utf-8")

    result = _run_script(sandbox, env, "--retry")

    assert result.returncode == 0, result.stderr
    assert "Retry mode" in result.stdout
    assert not (sandbox / "rec.called").exists()
    assert not (sandbox / "ffmpeg.called").exists()

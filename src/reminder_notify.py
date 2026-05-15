#!/usr/bin/env python3
"""Context detection for the VoxRefiner reminder daemon.

Detects the current desktop state (screen locked, DND enabled, VoxRefiner
active, fullscreen app) to determine the right intervention mode for a
given reminder.

Public API
----------
    detect_context()        -> Context  (named tuple)
    choose_intervention(context, reminder) -> Intervention  (named tuple)
    send_desktop_notification(title, body) -> None
    send_tts_notification(text) -> None   (delegates to src/tts.py subprocess)
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path
from typing import NamedTuple

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LOCK_FILE = _PROJECT_ROOT / "vox-refiner.lock"

# ── Data types ────────────────────────────────────────────────────────────────


class Context(NamedTuple):
    screen_locked: bool
    dnd_enabled: bool
    voxrefiner_active: bool
    fullscreen_app: bool


class Intervention(NamedTuple):
    mode: str       # "notify" / "tts_only" / "queue" / "defer_unlock"
    reason: str


# ── Context detection ─────────────────────────────────────────────────────────


def _screen_locked() -> bool:
    _LOCK_CHECKS = [
        (
            "org.gnome.ScreenSaver",
            "/org/gnome/ScreenSaver",
            "org.gnome.ScreenSaver.GetActive",
        ),
        (
            "org.freedesktop.ScreenSaver",
            "/ScreenSaver",
            "org.freedesktop.ScreenSaver.GetActive",
        ),
    ]
    for dest, path, method in _LOCK_CHECKS:
        try:
            result = subprocess.run(
                ["gdbus", "call", "--session",
                 "--dest", dest, "--object-path", path, "--method", method],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0:
                return "true" in result.stdout.lower()
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
    return False


def _dnd_enabled() -> bool:
    try:
        result = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.notifications", "show-banners"],
            capture_output=True, text=True, timeout=3,
        )
        # show-banners=false means DND is ON
        return result.stdout.strip().lower() == "false"
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def _voxrefiner_active() -> bool:
    return _LOCK_FILE.exists()


_BLOCKER_WINDOW_NAMES = [
    "BreakTimer", "Break Timer",  # breaktimer.app
    "Stretchly",                   # stretchly.github.io
    "Workrave",                    # workrave.org
    "Safe Eyes",                   # slgobinath/safeeyes
]


def _known_blocker_active() -> bool:
    """Detect screen blockers (e.g. BreakTimer) that are not real screen locks."""
    for name in _BLOCKER_WINDOW_NAMES:
        try:
            result = subprocess.run(
                ["xdotool", "search", "--onlyvisible", "--name", name],
                capture_output=True, text=True, timeout=3,
            )
            if result.stdout.strip():
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass
    return False


def _fullscreen_app() -> bool:
    try:
        win_id = subprocess.run(
            ["xdotool", "getactivewindow"],
            capture_output=True, text=True, timeout=3,
        ).stdout.strip()
        if not win_id:
            return False
        geo = subprocess.run(
            ["xdotool", "getwindowgeometry", "--shell", win_id],
            capture_output=True, text=True, timeout=3,
        ).stdout
        # Parse WIDTH and HEIGHT, then compare with screen resolution
        w = h = screen_w = screen_h = 0
        for line in geo.splitlines():
            if line.startswith("WIDTH="):
                w = int(line.split("=", 1)[1])
            elif line.startswith("HEIGHT="):
                h = int(line.split("=", 1)[1])
        screen_info = subprocess.run(
            ["xdotool", "getdisplaygeometry"],
            capture_output=True, text=True, timeout=3,
        ).stdout.strip().split()
        if len(screen_info) == 2:
            screen_w, screen_h = int(screen_info[0]), int(screen_info[1])
        return w >= screen_w and h >= screen_h and screen_w > 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, ValueError):
        return False


def detect_context() -> Context:
    """Sample all desktop signals and return a Context snapshot."""
    return Context(
        screen_locked=_screen_locked(),
        dnd_enabled=_dnd_enabled(),
        voxrefiner_active=_voxrefiner_active(),
        fullscreen_app=_fullscreen_app() or _known_blocker_active(),
    )


# ── Intervention selection ────────────────────────────────────────────────────

_PHYSICAL_CATEGORIES = {"task_short", "errand"}


def choose_intervention(context: Context, reminder: dict) -> Intervention:
    """Return the appropriate intervention mode given the desktop context.

    Decision matrix (matches architecture doc §4):
      - VoxRefiner active         → queue (≤60s, fired on release)
      - DND enabled               → queue until DND lifted
      - Screen locked + physical  → tts_only (good time for offline task)
      - Screen locked + screen    → defer_unlock
      - Fullscreen app            → tts_only (discreet)
      - Normal desktop            → notify (TTS + desktop notification)
    """
    category = reminder.get("category", "")

    if context.voxrefiner_active:
        return Intervention(mode="queue", reason="VoxRefiner is active")

    if context.dnd_enabled:
        return Intervention(mode="queue", reason="Do Not Disturb is enabled")

    if context.screen_locked:
        if category in _PHYSICAL_CATEGORIES:
            return Intervention(
                mode="tts_only",
                reason="Screen locked — physical task can be done offline",
            )
        return Intervention(
            mode="defer_unlock",
            reason="Screen locked — task requires the screen",
        )

    if context.fullscreen_app:
        return Intervention(mode="tts_only", reason="Fullscreen app is active")

    return Intervention(mode="notify", reason="Normal desktop")


# ── Notification delivery ─────────────────────────────────────────────────────


def send_desktop_notification(title: str, body: str) -> None:
    try:
        subprocess.run(
            ["notify-send", "--urgency=normal", "--app-name=VoxRefiner", title, body],
            timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass


_GEOMETRY = "80x30"
_TERMINAL_ORDER = ["mate-terminal", "gnome-terminal", "xfce4-terminal", "konsole", "xterm"]


def _detect_terminal() -> tuple[str, str] | None:
    override = os.environ.get("VOXREFINER_TERMINAL", "").strip()
    if override and shutil.which(override):
        return (override, override)
    for name in _TERMINAL_ORDER:
        path = shutil.which(name)
        if path:
            return (name, path)
    return None


def _build_terminal_cmd(name: str, path: str, fire_cmd: str) -> list[str]:
    if name in ("mate-terminal", "gnome-terminal"):
        return [path, f"--geometry={_GEOMETRY}", "--", "bash", "-c", f"{fire_cmd}; exec bash"]
    if name == "xfce4-terminal":
        return [path, f"--geometry={_GEOMETRY}", "-e", f'bash -c "{fire_cmd}; exec bash"']
    if name == "konsole":
        return [path, "--geometry", _GEOMETRY, "-e", "bash", "-c", f"{fire_cmd}; exec bash"]
    if name == "xterm":
        return [path, "-geometry", _GEOMETRY, "-e", "bash", "-lc", f"{fire_cmd}; exec bash"]
    return []


def _pid_file(reminder_id: int) -> Path:
    return Path(f"/tmp/vox-reminder-fire-{reminder_id}.pid")


def close_terminal_fire(reminder_id: int) -> None:
    """Kill the terminal window previously opened for *reminder_id*, if still alive."""
    pid_file = _pid_file(reminder_id)
    if not pid_file.exists():
        return
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)  # raises OSError if dead
        os.kill(pid, signal.SIGTERM)
    except (ValueError, OSError):
        pass
    finally:
        pid_file.unlink(missing_ok=True)


def open_terminal_fire(reminder_id: int) -> bool:
    """Open a terminal window running reminder.sh --fire <reminder_id>.

    Closes any previous window for the same reminder first (same pattern as
    launch-vox-refiner.sh: terminal detection order + PID file tracking).
    Returns True on success.
    """
    close_terminal_fire(reminder_id)

    terminal = _detect_terminal()
    if terminal is None:
        return False

    name, path = terminal
    script = _PROJECT_ROOT / "reminder.sh"
    fire_cmd = f"bash {script!s} --fire {reminder_id}"
    cmd = _build_terminal_cmd(name, path, fire_cmd)
    if not cmd:
        return False

    try:
        proc = subprocess.Popen(cmd, cwd=str(_PROJECT_ROOT))
        _pid_file(reminder_id).write_text(str(proc.pid))
        return True
    except (FileNotFoundError, OSError):
        return False


def send_tts_notification(text: str) -> None:
    venv_python = _PROJECT_ROOT / ".venv" / "bin" / "python"
    if not venv_python.exists():
        return
    chunks_dir = None
    try:
        chunks_dir = tempfile.mkdtemp(prefix="vox-speak-")
        env = os.environ.copy()
        voice_id = env.get("REMINDER_VOICE_ID") or env.get("TTS_SELECTION_VOICE_ID", "")
        if voice_id:
            env["TTS_VOICE_ID"] = voice_id
        env["TTS_SKIP_AI_CLEAN"] = "1"
        result = subprocess.run(
            [str(venv_python), "-m", "src.tts", "--chunked", chunks_dir],
            input=text,
            capture_output=True,
            text=True,
            env=env,
            cwd=str(_PROJECT_ROOT),
            timeout=60,
        )
        for chunk_path in result.stdout.splitlines():
            chunk_path = chunk_path.strip()
            if not chunk_path or chunk_path.startswith("CHUNK_FAILED:"):
                continue
            volume = os.environ.get("REMINDER_VOLUME", "150")
            subprocess.run(
                ["mpv", "--no-video", "--really-quiet", f"--volume={volume}", chunk_path],
                timeout=60,
                stderr=subprocess.DEVNULL,
            )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    finally:
        if chunks_dir:
            shutil.rmtree(chunks_dir, ignore_errors=True)

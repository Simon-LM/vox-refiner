#!/usr/bin/env python3
"""VoxRefiner — synced browser display for TTS playback.

Lightweight HTTP+SSE server that displays the currently-spoken text in a
parallel browser window, synchronized with audio chunk playback.

Activation: VOX_WEB_DISPLAY=1 in .env. Bash flow scripts source web_display.sh
which forks this module, captures the chosen port, and pushes events as TTS
chunks play.

Endpoints:
  GET  /         → Next.js static export (frontend/out/)
  GET  /events   → SSE stream (replays last init + last chunk on connect)
  POST /push     → broadcast event to all SSE clients (bash → server)
  POST /shutdown → graceful exit

Only Chromium-based browsers are supported (true --app= mode, no tab bar):
chromium → chromium (Flatpak) → brave → brave (Flatpak) → google-chrome →
google-chrome (Flatpak) → microsoft-edge → microsoft-edge (Flatpak).
Snap-confined binaries are skipped automatically (AppArmor blocks --user-data-dir).
Override via VOX_WEB_BROWSER (binary name or Flatpak app-id).
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional


# ── Frontend static files ────────────────────────────────────────────────────

# Built output from frontend/ (Next.js static export). Committed to git so
# end-users never need Node.js at runtime.
_FRONTEND_OUT = os.path.join(os.path.dirname(__file__), "..", "frontend", "out")



# ── Event broadcaster ────────────────────────────────────────────────────────

class _Broadcaster:
    """Thread-safe SSE event broadcaster.

    Holds per-client queues and the last-seen `init` and `chunk` events so a
    late-connecting browser can replay state.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: list[queue.Queue[Optional[tuple[str, str]]]] = []
        self._last_init: Optional[tuple[str, str]] = None
        self._last_display_chunks: Optional[tuple[str, str]] = None
        self._last_chunk: Optional[tuple[str, str]] = None

    def add_client(self) -> queue.Queue[Optional[tuple[str, str]]]:
        q: queue.Queue[Optional[tuple[str, str]]] = queue.Queue(maxsize=128)
        with self._lock:
            self._clients.append(q)
            # Replay state for late connections (display_chunks before audio chunk)
            if self._last_init is not None:
                q.put(self._last_init)
            if self._last_display_chunks is not None:
                q.put(self._last_display_chunks)
            if self._last_chunk is not None:
                q.put(self._last_chunk)
        return q

    def remove_client(self, q: queue.Queue) -> None:
        with self._lock:
            try:
                self._clients.remove(q)
            except ValueError:
                pass

    def broadcast(self, event_type: str, data_json: str) -> None:
        with self._lock:
            if event_type == "init":
                self._last_init = (event_type, data_json)
                self._last_chunk = None             # new init resets chunk replay
                self._last_display_chunks = None    # new init resets meta replay
            elif event_type == "chunk":
                self._last_chunk = (event_type, data_json)
            elif event_type == "display_chunks":
                self._last_display_chunks = (event_type, data_json)
            for q in list(self._clients):
                try:
                    q.put_nowait((event_type, data_json))
                except queue.Full:
                    pass

    def close_all(self) -> None:
        with self._lock:
            for q in self._clients:
                try:
                    q.put_nowait(None)  # sentinel = disconnect
                except queue.Full:
                    pass


_broadcaster = _Broadcaster()
_shutdown_event = threading.Event()


# ── HTTP handler ─────────────────────────────────────────────────────────────

class _Handler(BaseHTTPRequestHandler):
    # Silence default access logs on stderr.
    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def _serve_file(self, rel_path: str) -> None:
        """Serve a file from the Next.js static export directory."""
        import mimetypes
        full = os.path.realpath(os.path.join(_FRONTEND_OUT, rel_path))
        out_root = os.path.realpath(_FRONTEND_OUT)
        if not full.startswith(out_root + os.sep) and full != out_root:
            self.send_error(403)
            return
        if not os.path.isfile(full):
            self.send_error(404)
            return
        ctype, _ = mimetypes.guess_type(full)
        ctype = ctype or "application/octet-stream"
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, body: dict, code: int = 200) -> None:
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()

            q = _broadcaster.add_client()
            try:
                # Initial comment to flush headers immediately
                self.wfile.write(b": connected\n\n")
                self.wfile.flush()
                while not _shutdown_event.is_set():
                    try:
                        item = q.get(timeout=15)
                    except queue.Empty:
                        # SSE keep-alive comment
                        try:
                            self.wfile.write(b": keep-alive\n\n")
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError):
                            break
                        continue
                    if item is None:
                        break
                    event_type, data_json = item
                    msg = f"event: {event_type}\ndata: {data_json}\n\n".encode("utf-8")
                    try:
                        self.wfile.write(msg)
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        break
            finally:
                _broadcaster.remove_client(q)
            return

        # All other GET paths → serve from Next.js static export
        # Strip query string so /?displayMode=summary serves index.html
        clean_path = self.path.split("?", 1)[0]
        rel = "index.html" if clean_path in ("/", "") else clean_path.lstrip("/")
        self._serve_file(rel)

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length) if length > 0 else b""

        if self.path == "/shutdown":
            self._send_json({"ok": True})
            _shutdown_event.set()
            _broadcaster.close_all()
            # Trigger server shutdown from another thread (cannot shutdown from handler)
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return

        if self.path == "/push":
            try:
                body = json.loads(raw.decode("utf-8")) if raw else {}
                event_type = body.get("type")
                payload = body.get("payload")
                if not isinstance(event_type, str):
                    self._send_json({"ok": False, "error": "missing type"}, code=400)
                    return
                data_json = json.dumps(payload) if payload is not None else "null"
                _broadcaster.broadcast(event_type, data_json)
                self._send_json({"ok": True})
            except (ValueError, json.JSONDecodeError) as exc:
                self._send_json({"ok": False, "error": str(exc)}, code=400)
            return

        self.send_error(404)


# ── Browser launch ───────────────────────────────────────────────────────────

def _is_snap_binary(binary: str) -> bool:
    """Return True if the binary is provided by Snap.

    Snap-confined chromium/brave reject custom --user-data-dir paths via
    AppArmor (`SingletonLock: Permission denied`). We skip them in the
    auto-detect chain and warn if explicitly requested.
    """
    path = shutil.which(binary)
    if not path:
        return False
    if "/snap/" in path:
        return True
    try:
        real = os.path.realpath(path)
    except OSError:
        return False
    return real in ("/usr/bin/snap", "/snap/bin/snap") or "/snap/" in real


def _vox_profile_dir(name: str) -> str:
    """Return a stable, isolated Chromium profile dir for the given browser family.

    Each family gets its own dir so profile formats never collide. Safe to wipe.
    """
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    path = os.path.join(base, "vox-refiner", f"{name}-profile")
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        path = f"/tmp/vox-refiner-{name}-profile"
        os.makedirs(path, exist_ok=True)
    return path


def _flatpak_app_installed(app_id: str) -> bool:
    """Return True if the Flatpak app is installed.

    Checks standard Flatpak directories directly (no subprocess) — instantaneous.
    """
    xdg_data = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return any(os.path.isdir(p) for p in [
        os.path.join(xdg_data, "flatpak", "app", app_id),   # user install
        os.path.join("/var/lib/flatpak", "app", app_id),      # system install
    ])


def _app_args(binary: str, url: str, w: str, h: str, x: str, y: str, profile: str) -> list[str]:
    """Chromium --app= mode with isolated profile, controlled window size/position."""
    return [
        binary,
        f"--app={url}",
        f"--user-data-dir={_vox_profile_dir(profile)}",
        f"--window-size={w},{h}",
        f"--window-position={x},{y}",
        "--no-first-run",
        "--no-default-browser-check",
    ]


def _flatpak_app_args(app_id: str, url: str, w: str, h: str, x: str, y: str, profile: str) -> list[str]:
    """Flatpak --app= mode. Profile in ~/.var/app/<app-id>/data/ — always sandbox-writable."""
    base = os.path.expanduser(f"~/.var/app/{app_id}/data/vox-refiner")
    try:
        os.makedirs(base, exist_ok=True)
    except OSError:
        base = f"/tmp/vox-refiner-{profile}"
        os.makedirs(base, exist_ok=True)
    return [
        "flatpak", "run", app_id,
        f"--app={url}",
        f"--user-data-dir={base}",
        f"--window-size={w},{h}",
        f"--window-position={x},{y}",
        "--no-first-run",
        "--no-default-browser-check",
    ]


# All supported browsers support Chromium --app= mode (true app window, no tab bar).
# Each entry: (key, argv). Keys starting with "flatpak:" use _flatpak_app_installed()
# for availability; others use shutil.which(). Snap binaries are skipped automatically.
_BROWSER_TABLE: list[tuple[str, str, str]] = [
    # (key,                             binary-or-app-id,       profile-name)
    ("chromium-browser",              "chromium-browser",              "chromium"),
    ("chromium",                      "chromium",                      "chromium"),
    ("flatpak:org.chromium.Chromium", "org.chromium.Chromium",         "chromium-flatpak"),
    ("brave-browser",                 "brave-browser",                 "brave"),
    ("brave",                         "brave",                         "brave"),
    ("flatpak:com.brave.Browser",     "com.brave.Browser",             "brave-flatpak"),
    ("google-chrome",                 "google-chrome",                 "chrome"),
    ("flatpak:com.google.Chrome",     "com.google.Chrome",             "chrome-flatpak"),
    ("microsoft-edge",                "microsoft-edge",                "edge"),
    ("flatpak:com.microsoft.Edge",    "com.microsoft.Edge",            "edge-flatpak"),
]

# Short aliases for VOX_WEB_BROWSER: maps a friendly name to the ordered list of
# keys to try in _BROWSER_TABLE. This lets users write "brave" instead of "brave-browser".
_BROWSER_ALIASES: dict[str, list[str]] = {
    "chromium": ["chromium-browser", "chromium", "flatpak:org.chromium.Chromium"],
    "brave":    ["brave-browser",    "brave",    "flatpak:com.brave.Browser"],
    "chrome":   ["google-chrome",               "flatpak:com.google.Chrome"],
    "edge":     ["microsoft-edge",              "flatpak:com.microsoft.Edge"],
}

_INSTALL_HINT = (
    "Install a Chromium-based browser to use VOX_WEB_DISPLAY: "
    "chromium, brave, google-chrome, or microsoft-edge "
    "(apt/deb or Flatpak — not Snap)."
)


def _build_launchers(url: str, w: str, h: str, x: str, y: str) -> list[tuple[str, list[str]]]:
    """Resolve _BROWSER_TABLE to (key, argv) pairs for available, non-snap browsers."""
    result = []
    for key, target, profile in _BROWSER_TABLE:
        if key.startswith("flatpak:"):
            if _flatpak_app_installed(target):
                result.append((key, _flatpak_app_args(target, url, w, h, x, y, profile)))
        else:
            if not shutil.which(target):
                continue
            if _is_snap_binary(target):
                print(f"ℹ  skipping {target} (Snap — incompatible with --user-data-dir)", file=sys.stderr)
                continue
            result.append((key, _app_args(target, url, w, h, x, y, profile)))
    return result


def _launch_browser(url: str, size: str, pos: str) -> None:
    try:
        w, h = size.split("x", 1)
        x, y = pos.split("x", 1)
    except ValueError:
        w, h, x, y = "1100", "800", "100", "100"

    override = os.environ.get("VOX_WEB_BROWSER", "").strip()
    launchers = _build_launchers(url, w, h, x, y)
    candidates: list[list[str]] = []

    if override:
        is_flatpak_id = "." in override and os.sep not in override and not shutil.which(override)
        if is_flatpak_id:
            if _flatpak_app_installed(override):
                match = next((argv for key, argv in launchers if key == f"flatpak:{override}"), None)
                candidates.append(match or ["flatpak", "run", override, url])
            else:
                print(f"⚠️  VOX_WEB_BROWSER='{override}' — Flatpak app not installed.", file=sys.stderr)
        elif shutil.which(override):
            if _is_snap_binary(override):
                print(
                    f"⚠️  VOX_WEB_BROWSER='{override}' is a Snap package — AppArmor blocks "
                    "--user-data-dir. Install a deb/Flatpak version instead.",
                    file=sys.stderr,
                )
            match = next((argv for key, argv in launchers if key == override), None)
            candidates.append(match or [override, url])
        elif override in _BROWSER_ALIASES:
            # Short alias (e.g. "brave" → tries brave-browser, brave, then Flatpak)
            keys = _BROWSER_ALIASES[override]
            match = next((argv for key, argv in launchers if key in keys), None)
            if match:
                candidates.append(match)
            else:
                print(f"⚠️  VOX_WEB_BROWSER='{override}' — no installed browser found for this family.", file=sys.stderr)
        else:
            print(f"⚠️  VOX_WEB_BROWSER='{override}' not found — falling back.", file=sys.stderr)

    if not candidates:
        candidates = [argv for _, argv in launchers]

    if not candidates:
        print(f"⚠️  {_INSTALL_HINT}", file=sys.stderr)
        return

    import time
    for cmd in candidates:
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except (FileNotFoundError, OSError) as exc:
            print(f"⚠️  Failed to launch {cmd[0]}: {exc}", file=sys.stderr)
            continue

        # Give the browser 400ms to crash out (sandbox issues, missing display, etc.)
        time.sleep(0.4)
        if proc.poll() is None:
            print(f"🌐 Launched {cmd[0]} (pid {proc.pid})", file=sys.stderr)
            return

        # Process exited — capture diagnostic, try next candidate
        try:
            err_bytes = proc.stderr.read() if proc.stderr else b""
        except Exception:
            err_bytes = b""
        err = err_bytes.decode("utf-8", errors="replace").strip()
        snippet = (err[:300] + "…") if len(err) > 300 else err
        print(
            f"⚠️  {cmd[0]} exited with code {proc.returncode}; trying next browser. "
            f"stderr: {snippet or '(empty)'}",
            file=sys.stderr,
        )
        continue

    print("⚠️  All browser candidates failed to launch.", file=sys.stderr)


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="VoxRefiner web display server")
    parser.add_argument("--mode", choices=["voice", "insight"], default="voice")
    parser.add_argument("--display-mode",
                        choices=["fulltext", "summary", "keywords"],
                        default=os.environ.get("VOX_WEB_DISPLAY_MODE", "summary"))
    parser.add_argument("--size", default=os.environ.get("VOX_WEB_SIZE", "1100x800"))
    parser.add_argument("--pos",  default=os.environ.get("VOX_WEB_POS",  "100x100"))
    parser.add_argument("--port-file", default=None)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    port = server.server_address[1]

    if args.port_file:
        try:
            with open(args.port_file, "w", encoding="utf-8") as f:
                f.write(str(port))
        except OSError as exc:
            print(f"⚠️  Cannot write port file: {exc}", file=sys.stderr)
    print(f"PORT={port}", flush=True)

    def _on_signal(signum, frame):  # noqa: ARG001
        _shutdown_event.set()
        _broadcaster.close_all()
        threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    if not args.no_browser:
        url = f"http://127.0.0.1:{port}/?displayMode={args.display_mode}"
        _launch_browser(url, args.size, args.pos)

    try:
        server.serve_forever(poll_interval=0.5)
    finally:
        server.server_close()

    return 0


if __name__ == "__main__":
    sys.exit(main())

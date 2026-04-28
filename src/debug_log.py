#!/usr/bin/env python3
"""VoxRefiner — opt-in debug session log.

Activation via the VOX_DEBUG_LOG environment variable:
  unset / "0" / ""        → disabled (all helpers are no-ops)
  "1"                     → write to recordings/debug/last-session.json
  any other value         → treated as a custom path (absolute or relative)

The log is a single JSON object that accumulates across the session. Sections
can be set (overwrite) or appended (lists). Concurrent writers from bash
subshells coordinate via a sibling .lock file (file lock).

Python API (in-process callers):
  is_enabled()                             — bool
  log_path()                               — Path | None
  reset(meta=None)                         — start a fresh session log
  set_section(section, data)               — overwrite/merge under top-level key
  append_to(section, item)                 — append to a list under top-level key

CLI (bash callers):
  python -m src.debug_log reset [--mode voice|insight|...]
  python -m src.debug_log set <section> <json_string>
  python -m src.debug_log append <section> <json_string>
  python -m src.debug_log enabled            (exit 0 if enabled, 1 otherwise)
  python -m src.debug_log path               (print the log path; exit 1 if disabled)
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

_ENV_VAR = "VOX_DEBUG_LOG"
_DEFAULT_REL_PATH = Path("recordings") / "debug" / "last-session.json"


# ── Activation / path resolution ─────────────────────────────────────────────

def is_enabled() -> bool:
    """True when the debug log is active (env var set to a non-falsey value)."""
    val = os.environ.get(_ENV_VAR, "").strip()
    return bool(val) and val != "0"


def log_path() -> Optional[Path]:
    """Return the absolute path to the log file, or None if disabled."""
    val = os.environ.get(_ENV_VAR, "").strip()
    if not val or val == "0":
        return None
    if val == "1":
        # Default: project-relative path
        repo_root = Path(__file__).resolve().parent.parent
        return (repo_root / _DEFAULT_REL_PATH).resolve()
    p = Path(val).expanduser()
    if not p.is_absolute():
        p = (Path.cwd() / p).resolve()
    return p


# ── File-based locking (cross-process) ───────────────────────────────────────

@contextmanager
def _locked(path: Path) -> Iterator[None]:
    """Acquire an advisory lock on a sibling .lock file via fcntl.

    Falls through silently if fcntl is unavailable (Windows etc.) — this is a
    debug helper, not a critical system, so best-effort is fine.
    """
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import fcntl  # noqa: PLC0415
    except ImportError:
        yield
        return
    fh = open(lock_path, "w", encoding="utf-8")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fh, fcntl.LOCK_UN)
        except OSError:
            pass
        fh.close()


# ── Read / write the JSON document ───────────────────────────────────────────

def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


# ── Public API ───────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).isoformat(timespec="milliseconds")


def reset(meta: Optional[dict] = None) -> None:
    """Initialise a new session log with timestamp and optional metadata."""
    if not is_enabled():
        return
    path = log_path()
    if path is None:
        return
    initial: dict[str, Any] = {
        "session_id": time.strftime("%Y-%m-%dT%H-%M-%S"),
        "started_at": _now_iso(),
        "started_at_perf": time.perf_counter(),
    }
    if meta:
        initial.update(meta)
    with _locked(path):
        _write(path, initial)


def set_section(section: str, data: Any) -> None:
    """Overwrite a top-level section with ``data``."""
    if not is_enabled():
        return
    path = log_path()
    if path is None:
        return
    with _locked(path):
        doc = _read(path)
        doc[section] = data
        _write(path, doc)


def append_to(section: str, item: Any) -> None:
    """Append ``item`` to a top-level list section (created if missing)."""
    if not is_enabled():
        return
    path = log_path()
    if path is None:
        return
    with _locked(path):
        doc = _read(path)
        existing = doc.get(section)
        if not isinstance(existing, list):
            existing = []
        existing.append(item)
        doc[section] = existing
        _write(path, doc)


def merge_into(section: str, data: dict) -> None:
    """Shallow-merge ``data`` into the existing dict at ``section``.

    If the section does not exist or is not a dict, it is replaced by ``data``.
    """
    if not is_enabled():
        return
    if not isinstance(data, dict):
        return
    path = log_path()
    if path is None:
        return
    with _locked(path):
        doc = _read(path)
        existing = doc.get(section)
        if not isinstance(existing, dict):
            existing = {}
        existing.update(data)
        doc[section] = existing
        _write(path, doc)


def perf_seconds_since(t0: float) -> float:
    """Helper: seconds elapsed from a perf_counter() reference."""
    return round(time.perf_counter() - t0, 3)


# ── CLI entry point ──────────────────────────────────────────────────────────

def _parse_json_arg(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"debug_log: invalid JSON argument: {exc}", file=sys.stderr)
        sys.exit(2)


def _cli() -> int:
    parser = argparse.ArgumentParser(
        description="VoxRefiner debug-log helper. Disabled when VOX_DEBUG_LOG is unset.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_reset = sub.add_parser("reset", help="Start a new session log.")
    p_reset.add_argument("--meta", default=None,
                         help="Optional JSON object merged into the initial doc.")

    p_set = sub.add_parser("set", help="Overwrite a top-level section.")
    p_set.add_argument("section")
    p_set.add_argument("json_value")

    p_app = sub.add_parser("append", help="Append an item to a list section.")
    p_app.add_argument("section")
    p_app.add_argument("json_value")

    p_mrg = sub.add_parser("merge", help="Shallow-merge a dict into a section.")
    p_mrg.add_argument("section")
    p_mrg.add_argument("json_value")

    sub.add_parser("enabled", help="Exit 0 if the log is enabled, 1 otherwise.")
    sub.add_parser("path",    help="Print the log path, or exit 1 if disabled.")

    args = parser.parse_args()

    if args.cmd == "enabled":
        return 0 if is_enabled() else 1

    if args.cmd == "path":
        p = log_path()
        if p is None:
            return 1
        print(str(p))
        return 0

    if not is_enabled():
        # Silent no-op for write commands so bash flows don't need to gate calls.
        return 0

    if args.cmd == "reset":
        meta = _parse_json_arg(args.meta) if args.meta else None
        if meta is not None and not isinstance(meta, dict):
            print("debug_log: --meta must be a JSON object", file=sys.stderr)
            return 2
        reset(meta)
        return 0

    if args.cmd == "set":
        set_section(args.section, _parse_json_arg(args.json_value))
        return 0

    if args.cmd == "append":
        append_to(args.section, _parse_json_arg(args.json_value))
        return 0

    if args.cmd == "merge":
        data = _parse_json_arg(args.json_value)
        if not isinstance(data, dict):
            print("debug_log: merge requires a JSON object", file=sys.stderr)
            return 2
        merge_into(args.section, data)
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(_cli())

#!/usr/bin/env python3
"""GTK overlay window for Pomodoro breaks.

Displays a semi-transparent fullscreen window with a countdown timer and
the current task title. Blocks mouse input (fullscreen always-on-top window
captures all pointer events).

Covers all connected monitors: one OverlayWindow on the primary monitor and
one dark blocker window on each additional monitor.

When break_locked is True, the window cannot be dismissed before the timer
expires. When False, pressing Escape or clicking Skip closes it early.

Usage (called by pomodoro.py as a subprocess):
    python3 pomodoro_overlay.py --title "Water the plants" --minutes 10 --locked
    python3 pomodoro_overlay.py --title "Break" --minutes 5 --no-locked
    python3 pomodoro_overlay.py --title "Test overlay (30 s)" --minutes 0.5 --locked

Writes its PID to /tmp/vox-pomodoro-overlay.pid on startup so pomodoro.py
can signal it with SIGTERM to close early.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

_PID_FILE = Path("/tmp/vox-pomodoro-overlay.pid")

try:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, GLib, Gtk
    _GTK_AVAILABLE = True
except (ImportError, ValueError):
    _GTK_AVAILABLE = False


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--title", default="Break")
    p.add_argument("--minutes", type=float, default=5)
    locked = p.add_mutually_exclusive_group()
    locked.add_argument("--locked", dest="locked", action="store_true", default=True)
    locked.add_argument("--no-locked", dest="locked", action="store_false")
    return p.parse_args()


if _GTK_AVAILABLE:
    class OverlayWindow(Gtk.Window):
        _CSS = b"""
        window {
            background-color: transparent;
        }
        .timer-label {
            color: #ffffff;
            font-size: 5rem;
            font-weight: bold;
        }
        .task-label {
            color: #e0e0e0;
            font-size: 1.6rem;
            margin-bottom: 2rem;
        }
        .hint-label {
            color: rgba(255, 255, 255, 0.45);
            font-size: 0.9rem;
            margin-top: 3rem;
        }
        """

        def __init__(self, title: str, minutes: float, locked: bool) -> None:
            super().__init__()
            self._task_title = title
            self._remaining = int(minutes * 60)
            self._locked = locked
            self._siblings: list[Gtk.Window] = []

            # set_visual and set_app_paintable must be called before realize
            screen = self.get_screen()
            visual = screen.get_rgba_visual()
            if visual:
                self.set_visual(visual)
            self.set_app_paintable(True)

            self._apply_css()
            self._build_ui()
            self._setup_window()
            self._write_pid()
            self._start_tick()

        # ── Cairo draw: fills window with semi-transparent black ─────────────

        def _on_draw(self, _widget, cr) -> bool:
            cr.set_source_rgba(0, 0, 0, 0.70)
            cr.paint()
            return False

        # ── CSS for text labels ───────────────────────────────────────────────

        def _apply_css(self) -> None:
            provider = Gtk.CssProvider()
            provider.load_from_data(self._CSS)
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(),
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

        # ── UI content (timer + task label) ──────────────────────────────────

        def _build_ui(self) -> None:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            box.set_halign(Gtk.Align.CENTER)
            box.set_valign(Gtk.Align.CENTER)

            task_lbl = Gtk.Label(label=self._task_title)
            task_lbl.get_style_context().add_class("task-label")
            task_lbl.set_line_wrap(True)
            task_lbl.set_max_width_chars(50)
            box.pack_start(task_lbl, False, False, 0)

            self._timer_lbl = Gtk.Label(label=self._format_time())
            self._timer_lbl.get_style_context().add_class("timer-label")
            box.pack_start(self._timer_lbl, False, False, 0)

            hint = "" if self._locked else "Échap / Passer pour terminer la pause"
            self._hint_lbl = Gtk.Label(label=hint)
            self._hint_lbl.get_style_context().add_class("hint-label")
            box.pack_start(self._hint_lbl, False, False, 0)

            self.add(box)

        # ── Window properties + multi-monitor ────────────────────────────────

        def _setup_window(self) -> None:
            self.set_type_hint(Gdk.WindowTypeHint.SPLASHSCREEN)
            self.set_decorated(False)
            self.set_keep_above(True)

            screen = self.get_screen()
            self.connect("delete-event", lambda *_: False)
            self.connect("draw", self._on_draw)

            # Primary monitor
            if hasattr(self, "fullscreen_on_monitor"):
                self.fullscreen_on_monitor(screen, 0)
            else:
                self.fullscreen()

            # Additional monitors: spawn dark blocker windows
            for i in range(1, screen.get_n_monitors()):
                self._spawn_blocker(screen, i)

            if not self._locked:
                self.connect("key-press-event", self._on_key)
                skip_btn = Gtk.Button(label="Passer la pause")
                skip_btn.connect("clicked", lambda *_: self._dismiss())
                self.get_child().pack_start(skip_btn, False, False, 0)
                self.get_child().show_all()

        def _spawn_blocker(self, screen: Gdk.Screen, monitor_idx: int) -> None:
            """Create a semi-transparent blocker on an additional monitor."""
            w = Gtk.Window()
            w.set_type_hint(Gdk.WindowTypeHint.SPLASHSCREEN)
            w.set_decorated(False)
            w.set_keep_above(True)
            w.set_app_paintable(True)
            visual = screen.get_rgba_visual()
            if visual:
                w.set_visual(visual)
            w.connect("delete-event", lambda *_: False)
            w.connect("draw", self._on_draw)
            if hasattr(w, "fullscreen_on_monitor"):
                w.fullscreen_on_monitor(screen, monitor_idx)
            else:
                w.fullscreen()
            w.show_all()
            self._siblings.append(w)

        # ── Key / dismiss ─────────────────────────────────────────────────────

        def _on_key(self, _widget, event) -> bool:
            if event.keyval == Gdk.KEY_Escape:
                self._dismiss()
            return False

        def _dismiss(self) -> None:
            for w in self._siblings:
                w.destroy()
            self._siblings.clear()
            _PID_FILE.unlink(missing_ok=True)
            Gtk.main_quit()

        # ── Countdown ─────────────────────────────────────────────────────────

        def _format_time(self) -> str:
            m, s = divmod(max(0, self._remaining), 60)
            return f"{m:02d}:{s:02d}"

        def _start_tick(self) -> None:
            GLib.timeout_add(1000, self._tick)

        def _tick(self) -> bool:
            self._remaining -= 1
            self._timer_lbl.set_text(self._format_time())
            if self._remaining <= 0:
                self._dismiss()
                return False
            return True

        def _write_pid(self) -> None:
            import os
            _PID_FILE.write_text(str(os.getpid()), encoding="utf-8")


def _fallback_cli(title: str, minutes: float, locked: bool) -> None:
    """Text-mode fallback when GTK is unavailable."""
    remaining = int(minutes * 60)
    print(f"\n  ⏸  PAUSE — {title}", flush=True)
    print(f"  Duration: {minutes} min{'  (locked)' if locked else ''}\n", flush=True)
    try:
        while remaining > 0:
            m, s = divmod(remaining, 60)
            print(f"\r  {m:02d}:{s:02d} remaining…", end="", flush=True)
            time.sleep(1)
            remaining -= 1
    except KeyboardInterrupt:
        if locked:
            print("\n  Break locked — please wait for the timer.", flush=True)
            while remaining > 0:
                try:
                    time.sleep(remaining)
                    remaining = 0
                except KeyboardInterrupt:
                    pass
    print("\n  Break over.\n", flush=True)


def main() -> None:
    args = _parse_args()

    signal.signal(signal.SIGTERM, lambda *_: (_PID_FILE.unlink(missing_ok=True), sys.exit(0)))

    if not _GTK_AVAILABLE:
        _fallback_cli(args.title, args.minutes, args.locked)
        return

    win = OverlayWindow(args.title, args.minutes, args.locked)
    win.show_all()

    Gtk.main()
    _PID_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    main()

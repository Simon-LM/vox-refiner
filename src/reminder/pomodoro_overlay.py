#!/usr/bin/env python3
"""GTK overlay window for Pomodoro breaks.

Two-phase lifecycle
-------------------
1. **Break phase** — fullscreen semi-transparent overlay with a countdown timer.
   Blocks all keyboard input (other apps lose focus). Mouse cursor is free but
   clicks land on the overlay.

2. **Confirmation phase** — when the timer reaches zero, if a task was associated
   with this break, the overlay transitions to a confirmation screen:

       Break over!
       "Water the plants"
       [ ✓ Done ]  [ ⏰ Later (+1h) ]  [ ⏭ In progress (+30m) ]  [ ✕ Skip ]
       (auto-skip in 00:45)

   The user's choice is written to /tmp/vox-pomodoro-fire-result.json.
   The daemon reads this on its next tick and updates the reminder DB.
   If no answer is given within CONFIRM_TIMEOUT seconds, "skip" is written.

Covers all connected monitors: one primary OverlayWindow plus one dark-blocker
Gtk.Window per additional monitor.

Usage (called by pomodoro.py as a subprocess — system python3, not venv):
    python3 pomodoro_overlay.py --title "Water plants" --minutes 10 --locked
    python3 pomodoro_overlay.py --title "Break"        --minutes 5  --no-locked
    python3 pomodoro_overlay.py --title "Test (30 s)"  --minutes 0.5 --locked
    python3 pomodoro_overlay.py --title "Task" --minutes 5 --locked --task-id 42

Writes its PID to /tmp/vox-pomodoro-overlay.pid so pomodoro.py can SIGTERM it.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path

_PID_FILE = Path("/tmp/vox-pomodoro-overlay.pid")
_FIRE_RESULT_FILE = Path("/tmp/vox-pomodoro-fire-result.json")

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
    p.add_argument("--task-id", type=int, default=None, dest="task_id")
    p.add_argument("--warning", action="store_true", default=False)
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
        .confirm-title {
            color: #ffffff;
            font-size: 2rem;
            font-weight: bold;
            margin-bottom: 1rem;
        }
        .action-btn {
            font-size: 1.1rem;
            padding: 0.6rem 1.2rem;
            margin: 0.4rem;
        }
        """

        def __init__(self, title: str, minutes: float, locked: bool,
                     task_id: int | None = None) -> None:
            super().__init__()
            self._task_title = title
            self._remaining = int(minutes * 60)
            self._locked = locked
            self._task_id = task_id
            self._phase = "break"
            self._siblings: list[Gtk.Window] = []

            # Must be called before the window is realized
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

        # ── Cairo draw: semi-transparent black fill ───────────────────────────

        def _on_draw(self, _widget, cr) -> bool:
            cr.set_source_rgba(0, 0, 0, 0.70)
            cr.paint()
            return False

        # ── CSS ───────────────────────────────────────────────────────────────

        def _apply_css(self) -> None:
            provider = Gtk.CssProvider()
            provider.load_from_data(self._CSS)
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(),
                provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

        # ── UI: Gtk.Stack with "break" and "confirm" views ────────────────────

        def _build_ui(self) -> None:
            self._stack = Gtk.Stack()
            self._stack.add_named(self._build_break_view(), "break")
            self._stack.add_named(self._build_confirm_view(), "confirm")
            self.add(self._stack)
            self._stack.set_visible_child_name("break")

        def _build_break_view(self) -> Gtk.Box:
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

            return box

        def _build_confirm_view(self) -> Gtk.Box:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            box.set_halign(Gtk.Align.CENTER)
            box.set_valign(Gtk.Align.CENTER)

            title_lbl = Gtk.Label(label="Pause terminée !")
            title_lbl.get_style_context().add_class("confirm-title")
            box.pack_start(title_lbl, False, False, 0)

            self._confirm_task_lbl = Gtk.Label(label=self._task_title)
            self._confirm_task_lbl.get_style_context().add_class("task-label")
            self._confirm_task_lbl.set_line_wrap(True)
            self._confirm_task_lbl.set_max_width_chars(50)
            box.pack_start(self._confirm_task_lbl, False, False, 0)

            btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
            btn_box.set_halign(Gtk.Align.CENTER)
            for label, action in [
                ("✓ Fait", "done"),
                ("✗ Pas fait", "skip"),
                ("⏰ Reporter", "snooze"),
            ]:
                btn = Gtk.Button(label=label)
                btn.get_style_context().add_class("action-btn")
                btn.connect("clicked", lambda _w, a=action: self._on_action(a))
                btn_box.pack_start(btn, False, False, 0)
            box.pack_start(btn_box, False, False, 0)

            return box

        # ── Window properties + multi-monitor ────────────────────────────────

        def _setup_window(self) -> None:
            self.set_type_hint(Gdk.WindowTypeHint.SPLASHSCREEN)
            self.set_decorated(False)
            self.set_keep_above(True)

            screen = self.get_screen()
            self.connect("delete-event", lambda *_: False)
            self.connect("draw", self._on_draw)

            if hasattr(self, "fullscreen_on_monitor"):
                self.fullscreen_on_monitor(screen, 0)
            else:
                self.fullscreen()

            for i in range(1, screen.get_n_monitors()):
                self._spawn_blocker(screen, i)

            if not self._locked:
                self.connect("key-press-event", self._on_key)
                skip_btn = Gtk.Button(label="Passer la pause")
                skip_btn.connect("clicked", lambda *_: self._dismiss())
                break_view = self._stack.get_child_by_name("break")
                break_view.pack_start(skip_btn, False, False, 0)
                break_view.show_all()

        def _spawn_blocker(self, screen: Gdk.Screen, monitor_idx: int) -> None:
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

        # ── Keyboard (break phase only) ───────────────────────────────────────

        def _on_key(self, _widget, event) -> bool:
            if self._phase == "break" and event.keyval == Gdk.KEY_Escape:
                self._dismiss()
            return False

        # ── Confirmation actions ──────────────────────────────────────────────

        def _on_action(self, action: str) -> None:
            self._write_result(action)
            self._dismiss()

        def _write_result(self, action: str) -> None:
            if self._task_id is not None:
                _FIRE_RESULT_FILE.write_text(
                    json.dumps({"task_id": self._task_id, "action": action}),
                    encoding="utf-8",
                )

        # ── Dismiss ───────────────────────────────────────────────────────────

        def _dismiss(self) -> None:
            # Early skip during break phase: show confirmation if a task is
            # associated — the user may have completed it in the meantime.
            if self._phase == "break" and self._task_id is not None:
                self._switch_to_confirm()
                return
            for w in self._siblings:
                w.destroy()
            self._siblings.clear()
            _PID_FILE.unlink(missing_ok=True)
            Gtk.main_quit()

        # ── Phase transition: break → confirmation ────────────────────────────

        def _switch_to_confirm(self) -> None:
            self._phase = "confirm"
            # Unblock other monitors immediately
            for w in self._siblings:
                w.destroy()
            self._siblings.clear()
            # Leave fullscreen; resize once GTK has processed the state change
            self.unfullscreen()
            self.set_accept_focus(False)
            self.set_skip_taskbar_hint(True)
            self.set_skip_pager_hint(True)
            GLib.idle_add(self._resize_to_panel)
            self._confirm_task_lbl.set_text(self._task_title)
            self._stack.set_visible_child_name("confirm")

        def _resize_to_panel(self) -> bool:
            screen = self.get_screen()
            monitor = screen.get_monitor_geometry(0)
            self.resize(480, 150)
            self.move(monitor.x + (monitor.width - 480) // 2, monitor.y + 20)
            return False  # run once

        # ── Countdown ─────────────────────────────────────────────────────────

        def _format_time(self) -> str:
            m, s = divmod(max(0, self._remaining), 60)
            return f"{m:02d}:{s:02d}"

        def _start_tick(self) -> None:
            GLib.timeout_add(1000, self._tick)

        def _tick(self) -> bool:
            self._remaining -= 1
            if self._phase == "break":
                self._timer_lbl.set_text(self._format_time())
                if self._remaining <= 0:
                    if self._task_id is not None:
                        self._switch_to_confirm()
                        return False  # stop ticking — confirm waits for user click
                    else:
                        self._dismiss()
                        return False
            return True

        def _write_pid(self) -> None:
            import os
            _PID_FILE.write_text(str(os.getpid()), encoding="utf-8")

    class WarningWindow(Gtk.Window):
        """Small non-blocking top-center window shown before an imminent break."""

        _CSS = b"""
        window { background-color: transparent; }
        .warning-msg {
            color: #ffffff;
            font-size: 1.1rem;
        }
        .warning-timer {
            color: #ffffff;
            font-size: 2rem;
            font-weight: bold;
        }
        """

        def __init__(self, seconds: int) -> None:
            super().__init__()
            self._remaining = seconds

            screen = self.get_screen()
            visual = screen.get_rgba_visual()
            if visual:
                self.set_visual(visual)
            self.set_app_paintable(True)

            provider = Gtk.CssProvider()
            provider.load_from_data(self._CSS)
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(), provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )

            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            box.set_margin_start(20)
            box.set_margin_end(20)
            box.set_margin_top(12)
            box.set_margin_bottom(12)

            lbl = Gtk.Label(label="Pause dans")
            lbl.get_style_context().add_class("warning-msg")
            box.pack_start(lbl, False, False, 0)

            self._timer_lbl = Gtk.Label(label=self._fmt())
            self._timer_lbl.get_style_context().add_class("warning-timer")
            box.pack_start(self._timer_lbl, False, False, 0)

            self.add(box)
            self.connect("draw", self._on_draw)
            self.connect("delete-event", lambda *_: False)
            self.set_type_hint(Gdk.WindowTypeHint.NOTIFICATION)
            self.set_decorated(False)
            self.set_keep_above(True)
            self.set_accept_focus(False)
            self.set_skip_taskbar_hint(True)
            self.set_skip_pager_hint(True)
            self.stick()

            monitor = screen.get_monitor_geometry(0)
            self.set_default_size(220, 80)
            self.move(monitor.x + (monitor.width - 220) // 2, monitor.y + 20)

            GLib.timeout_add(1000, self._tick)

        def _on_draw(self, _widget, cr) -> bool:
            cr.set_source_rgba(0, 0, 0, 0.80)
            cr.paint()
            return False

        def _fmt(self) -> str:
            m, s = divmod(max(0, self._remaining), 60)
            return f"{m:02d}:{s:02d}"

        def _tick(self) -> bool:
            self._remaining -= 1
            self._timer_lbl.set_text(self._fmt())
            if self._remaining <= 0:
                Gtk.main_quit()
                return False
            return True


def _fallback_cli(title: str, minutes: float, locked: bool,
                  task_id: int | None = None) -> None:
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
    if task_id is not None:
        print(f"  Task #{task_id}: mark as done? (d=done / s=snooze / Enter=skip): ",
              end="", flush=True)
        try:
            ans = input().strip().lower()
            if ans == "d":
                _FIRE_RESULT_FILE.write_text(
                    json.dumps({"task_id": task_id, "action": "done"}), encoding="utf-8"
                )
            elif ans == "s":
                _FIRE_RESULT_FILE.write_text(
                    json.dumps({"task_id": task_id, "action": "snooze"}), encoding="utf-8"
                )
        except (EOFError, KeyboardInterrupt):
            pass


def main() -> None:
    args = _parse_args()

    signal.signal(signal.SIGTERM, lambda *_: (_PID_FILE.unlink(missing_ok=True), sys.exit(0)))

    if args.warning:
        seconds = int(args.minutes * 60)
        if not _GTK_AVAILABLE:
            print(f"\n  Break in {seconds}s…", flush=True)
            return
        win = WarningWindow(seconds)
        win.show_all()
        Gtk.main()
        return

    if not _GTK_AVAILABLE:
        _fallback_cli(args.title, args.minutes, args.locked, args.task_id)
        return

    win = OverlayWindow(args.title, args.minutes, args.locked, task_id=args.task_id)
    win.show_all()

    Gtk.main()
    _PID_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    main()

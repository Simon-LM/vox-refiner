"""VoxRefiner — Reminder system package.

Modules:
  src.reminder.db       — SQLite CRUD layer (reminders.db, 4 tables)
  src.reminder.add      — parse text/OCR → extract reminder → store in DB
  src.reminder.notify   — context detection (screensaver, DND, lock, fullscreen)
  src.reminder.converse — AI conversation, response interpretation, escalation
  src.reminder.daemon   — 60s scheduler loop, Pomodoro logic, dispatch

CLI entry points:
  python -m src.reminder.add    — add a reminder from text
  python -m src.reminder.daemon — run the scheduler daemon
"""

<!-- @format -->

# Smart Agenda & Reminders — Architecture and Implementation Plan

## Overview

Voice-driven agenda and intelligent reminder system, designed for ADHD profiles and
anti-procrastination use. Long-term goal: a full personal agenda managed entirely by
voice, screenshots, and emails — no manual typing required.

**System philosophy:** persistent, not intrusive. The system keeps coming back, adapts
to the user's context, but never forces an immediate response. It finds the right moment
through dialogue, not guilt.

## 1. Entry Points (Capture)

### 1.1 Via VoxRefiner Menu

- Text typed or dictated aloud.
- Flow: voice → Voxtral (STT) → Mistral extracts (action, date, entities) → vocal confirmation (TTS).
- If information is missing (date, time, location), the system asks follow-up questions to fill in the gaps.

### 1.2 Via Keyboard Shortcut — OCR

- User takes a screenshot of an email, invitation, or existing calendar.
- `src/ocr.py` extracts raw text.
- Mistral analyses and extracts: action, date/time, location, entities (professional's name, address, etc.).
- Vocal confirmation of extracted information before saving.

### 1.3 Supplementary Information Search at Creation

- If an identifiable entity is detected (dentist, restaurant, government office), the system
  queries Perplexity/Insight to retrieve opening hours.
- Hours are cached in `business_cache` (SQLite) to avoid repeated searches.
- The system cross-references this data with known unavailability to suggest relevant time slots.
- If information cannot be found, the system flags it and lets the user complete it manually.

## 2. Storage — SQLite (`reminders.db`)

SQLite is sufficient for a full personal agenda over the long term (millions of rows,
indexed queries). Schema design matters more than the engine choice.

### Table `reminders`

```sql
id              INTEGER PRIMARY KEY
title           TEXT NOT NULL          -- short summary of the task
full_context    TEXT                   -- full text (raw OCR or dictation)
category        TEXT                   -- appointment / task_short / task_long / admin / deadline
status          TEXT DEFAULT 'pending' -- pending / in_progress / done / cancelled / snoozed
event_datetime  DATETIME               -- date/time of the event
next_trigger    DATETIME               -- next reminder fire time
snooze_count    INTEGER DEFAULT 0      -- number of deferrals
created_at      DATETIME
last_reminded   DATETIME
metadata        TEXT                   -- JSON: opening hours, location, travel time, extracted entities
conversation    TEXT                   -- JSON: AI conversation history for this reminder
```

### Table `unavailability`

```sql
id          INTEGER PRIMARY KEY
start_dt    DATETIME
end_dt      DATETIME
reason      TEXT     -- "sick", "video call", "away", "holiday"…
created_at  DATETIME
source      TEXT     -- "user_declared" / "calendar_import"
```

### Table `business_cache`

```sql
id             INTEGER PRIMARY KEY
name           TEXT
search_query   TEXT
opening_hours  TEXT    -- JSON: {monday: "9am-6pm", …}
address        TEXT
fetched_at     DATETIME
```

### Table `briefing_config`

```sql
id          INTEGER PRIMARY KEY
type        TEXT     -- "morning" / "midday" / "evening" / "weekly"
time        TEXT     -- "08:00"
enabled     BOOLEAN
day_of_week INTEGER  -- for weekly (0=Monday)
```

### Migration and `.ics` Import

- iCal (`.ics`) import: planned for phase 3 — native Python parsing (`icalendar` lib),
  inserted into `reminders` + `unavailability`.
- Bidirectional Google Calendar / CalDAV sync: later phase.

## 3. Scheduler Daemon

### systemd User Service

Auto-starts at login, automatically restarted on failure.
File: `~/.config/systemd/user/vox-reminder.service`

### Main Loop — every 60 seconds

```text
1. Read reminders where next_trigger <= now and status = pending/snoozed
2. For each:
   a. Detect context (see §4)
   b. Based on context → choose intervention mode
   c. Fire reminder or defer
3. Check scheduled briefings
```

### Coordination Files

- `reminders.lock` — another VoxRefiner module is active → wait.
- Check the project's existing lock file (avoid collisions with V1, translate, etc.).

## 4. Context Detection and Intervention Modes

### Detectable Signals on Ubuntu/Linux

| Signal                  | Detection Command                                            |
| ----------------------- | ------------------------------------------------------------ |
| Screen locked           | `gdbus call … ScreenSaver.GetActive`                         |
| DND enabled (GNOME)     | `gsettings get org.gnome.desktop.notifications show-banners` |
| Pomodoro session (lock) | detect via screensaver active                                |
| VoxRefiner active       | project lock file                                            |
| Fullscreen application  | `xdotool getactivewindow getwindowgeometry`                  |

### Context → Intervention Matrix

| Context                                      | Action doable off-screen? | Intervention                                             |
| -------------------------------------------- | ------------------------- | -------------------------------------------------------- |
| Normal desktop                               | —                         | TTS + desktop notification + response options            |
| VoxRefiner active                            | —                         | Queue, fire on release (≤60s)                            |
| DND enabled                                  | —                         | Queue until DND is lifted                                |
| Fullscreen app                               | —                         | Minimal discreet notification, light TTS                 |
| **Screen locked (Pomodoro) — physical task** | **Yes**                   | **TTS at lock start** ("good time to take out the bins") |
| Screen locked (Pomodoro) — screen task       | No                        | Defer to unlock                                          |

**Pomodoro Logic:**

- At **lock start**: fire reminders of physical category (errands, bins, simple phone call, etc.).
- At **unlock**: ask whether the action was completed ("You're back — were you able to take out the bins?").
- For tasks requiring the screen (admin, form, email): do not fire during lock, wait for unlock.

## 5. Response Interface — Voice-first, Multimodal

Each triggered reminder offers **three response modes** to choose from:

### Terminal (phase 1)

```text
🔔 [Reminder] Dentist appointment tomorrow at 2pm — Dr Martin
   [D] Done   [L] Later   [G] Going to do it   [V] Respond by voice
```

→ One keypress is enough. TTS has already read the reminder aloud.

### HTML (phase 2)

- Clickable buttons in the existing VoxRefiner web interface.
- Same logic, same backend.

### Voice

- User presses a key or says a trigger word → Voxtral transcribes → Mistral interprets.
- Enables contextual responses ("I'm sick", "in 20 minutes", "done").

## 6. AI Conversation Layer — Escalation and Adaptation

### Principle

Mistral manages the dialogue for each reminder. The conversation history is stored in
`reminders.conversation` (JSON) so that each interaction takes previous exchanges into account.

### Response Interpretation

| User response        | Action                                                                     |
| -------------------- | -------------------------------------------------------------------------- |
| "Done" / "All done"  | `status = done`                                                            |
| "Later" / vague      | Snooze 30 min by default, ask for confirmation                             |
| "In X minutes"       | Precise snooze                                                             |
| "Going to do it"     | Snooze by category (5 min short, 15 min long), then follow-up confirmation |
| "I'm sick"           | Log unavailability for today, defer to tomorrow                            |
| "I'm away tomorrow"  | Log unavailability for tomorrow                                            |
| "Video call all day" | Log time block, propose nothing during those hours                         |
| "Cancel"             | `status = cancelled` with confirmation                                     |

### Dynamic Escalation

The AI decides the next `next_trigger` taking into account:

- Task type and its deadline.
- Number of deferrals already made (`snooze_count`).
- Logged unavailability.
- Conversation history.

Example escalation for an appointment in 3 days:

- D-3 (morning): gentle reminder ("you have this in 3 days, keep it in mind").
- D-1 (evening): preparation reminder.
- Day of, -2h: reminder + estimated travel time.
- Day of, -30 min: final reminder.

### Travel Time Calculation

If the event has a location, estimate travel duration (via web search if available) and
trigger the "departure" reminder accordingly.

## 7. Persona — System Prompt

Supportive coach, anti-procrastination, adapted for ADHD profiles:

- Direct and neutral tone, never guilt-inducing.
- Action-oriented: "What's blocking you?", "Can you do this in 10 minutes right now?".
- Remembers declared contexts to avoid repeating the same questions.
- Suggests concrete alternatives rather than repeating the same prompt in a loop.
- Flags stressful tasks in advance ("in 5 days you'll need to deal with this — let's start thinking about it").
- ADHD-adapted: short reformulations, no long lists, one action at a time.

## 8. Daily and Weekly Briefings _(phase 2)_

Deferred feature. To be implemented after the core reminder layer.

- **Morning** (configurable time): list of today's tasks, voice + terminal.
- **Midday**: quick progress check-in.
- **Evening**: wrap-up + tomorrow's preview.
- **Weekly**: overview of the week ahead.

Briefings are special recurring reminders in the database, generated and adjusted by the AI.

## 9. Calendar Integration _(phases 3+)_

| Approach                      | Complexity                   | Priority |
| ----------------------------- | ---------------------------- | -------- |
| `.ics` import (iCal)          | Low — `icalendar` Python lib | Phase 3  |
| `.ics` export                 | Low                          | Phase 3  |
| Google Calendar sync (OAuth2) | High                         | Later    |
| CalDAV (Nextcloud, etc.)      | Medium                       | Later    |

Priority workflow: email screenshot → OCR → Mistral extracts → questions if information
is missing → insert into `reminders.db`. No external calendar needed for this flow.

## 10. New Files to Create

```text
reminder.sh                        ← entry point: menu + keyboard shortcut
reminder-daemon.sh                 ← start / stop / status for the daemon
src/reminder_add.py                ← parse + store a new reminder
src/reminder_daemon.py             ← scheduler loop (systemd service)
src/reminder_converse.py           ← AI dialogue, response interpretation, escalation
src/reminder_notify.py             ← context detection + intervention mode selection
src/reminder_db.py                 ← SQLite access layer (CRUD reminders.db)
~/.config/systemd/user/vox-reminder.service
```

Existing files reused without modification:

- `src/ocr.py` — screenshot capture.
- `src/tts.py` — text-to-speech for reminders.
- `src/transcribe.py` — user voice responses.
- `src/insight.py` — opening hours search.

## 11. Implementation Checklist

### Phase 1 — Core (W2)

#### Foundations

- [ ] SQLite schema — create `reminders.db` with all 4 tables.
- [ ] `src/reminder_db.py` — CRUD: add, get_due, update_status, snooze, log_conversation.
- [ ] `src/reminder_add.py` — parse text/OCR via Mistral, store in DB, confirm via TTS.
- [ ] `src/reminder_notify.py` — context detection (screensaver, DND, VoxRefiner lock file).

#### Daemon

- [ ] `src/reminder_daemon.py` — 60s loop, read due reminders, dispatch.
- [ ] `reminder-daemon.sh` — start / stop / status / restart.
- [ ] `~/.config/systemd/user/vox-reminder.service` — auto-start, restart on failure.
- [ ] `install.sh` — enable systemd service at install time.

#### Terminal Interface (phase 1)

- [ ] Display reminder with TTS + keyboard options (D/L/G/V).
- [ ] Handler "Done" → `status = done`.
- [ ] Handler "Later" → snooze 30 min.
- [ ] Handler "Going to do it" → snooze by category + follow-up confirmation.
- [ ] Handler "Respond by voice" → Voxtral → Mistral interprets.

#### Pomodoro Logic

- [ ] Detect screen lock (GNOME ScreenSaver).
- [ ] On lock: fire physical-category reminders via TTS.
- [ ] On unlock: ask for confirmation of physical actions that were triggered.

#### AI Conversation

- [ ] `src/reminder_converse.py` — ADHD coach anti-procrastination system prompt.
- [ ] Response interpretation: done / snooze / unavailability / cancellation.
- [ ] Log declared unavailability in `unavailability` table.
- [ ] Dynamic `next_trigger` calculation based on category + history.

#### Entry Points

- [ ] `reminder.sh` — VoxRefiner menu entry point (text or voice).
- [ ] Keyboard shortcut → OCR → `reminder_add.py`.
- [ ] Integration into `vox-refiner-menu.sh`.

#### Opening Hours Search (at creation)

- [ ] Detect identifiable entity in extracted text.
- [ ] Call Perplexity via `src/insight.py` → cache in `business_cache`.
- [ ] Suggest relevant time slots based on opening hours + unavailability.

### Phase 2 — HTML Interface + Full Voice

- [ ] Response buttons in the existing VoxRefiner web interface.
- [ ] Full voice flow: TTS → mic → Voxtral → Mistral → action.
- [ ] Daily and weekly briefings (morning / midday / evening / weekly).
- [ ] Intelligent multi-day escalation with configurable thresholds.

### Phase 3 — Calendar and Export

- [ ] `.ics` import → insert into `reminders.db` + `unavailability`.
- [ ] `.ics` export from `reminders.db`.
- [ ] Email → OCR → questions → agenda workflow (fill in missing information).

### Phase 4 — User Adaptation _(later)_

- [ ] Time preference database (rarely confirmed slots → avoid them).
- [ ] Bidirectional Google Calendar / CalDAV sync.
- [ ] Pattern history to automatically refine escalation.

# VoxRefiner — Troubleshooting

---

## Microphone inaccessible

**Cause:** PipeWire crashed, or another application holds the audio device.

**Fix:**

```bash
systemctl --user restart pipewire pipewire-pulse
```

Then start a new recording from the menu.

---

## Empty transcription

**Cause:** recording too short, only silence captured, or audio conversion failed.

**Fix:**

- Speak closer to the microphone
- Record for at least 2–3 seconds before stopping
- Use **[r] Retry** to re-run transcription on the existing audio without re-recording

---

## Clipboard copy failed

**Cause:** `xclip` is not installed, or the session is not running under X11 (e.g. Wayland without XWayland).

**Fix:**

```bash
sudo apt install xclip
```

If you are on Wayland, make sure XWayland is enabled or switch to an X11 session.

---

## TTS playback silent or not starting

**Cause:** `mpv` is not installed, or `TTS_PLAYER` is misconfigured in `.env`.

**Fix:**

```bash
sudo apt install mpv
```

Check your `.env`:

```env
TTS_PLAYER="mpv --no-video"   # quotes required if the value contains spaces
```

---

## Voice cloning uses default voice instead of yours

**Cause:** recording was shorter than 15 seconds (the minimum for voice cloning).

**Fix:** speak for at least 15 seconds before stopping. The menu shows:

> `Speak for ≥15s to clone your voice`

---

## More help

Report issues at: [github.com/Simon-LM/voxtral-paste/issues](https://github.com/Simon-LM/voxtral-paste/issues)

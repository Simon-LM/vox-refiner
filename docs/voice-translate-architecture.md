<!-- @format -->

# Voice Translate — Architecture & Design

Speak in one language, get an audio translation in your own voice.

---

## Pipeline

```text
Mic → rec (WAV, 16 kHz mono)                          vox-refiner-menu.sh
  → silence removal + speed-up → MP3                   ffmpeg
  → Voxtral STT → raw text                             src/transcribe.py
  → clean + adapt for speech + translate → text         src/voice_rewrite.py
  → Voxtral TTS (+ voice cloning) → MP3                src/tts.py
  → loudness normalization + volume boost               ffmpeg (loudnorm)
  → auto-play                                           mpv
```

Steps 1–3 (recording → transcription) reuse the same logic as Speech-to-Text.
Everything after is specific to Voice Translate.

---

## Entry points

| Entry point | Script | Behaviour |
| --- | --- | --- |
| Ubuntu app menu / .desktop | `launch-vox-refiner.sh` → `vox-refiner-menu.sh` | Interactive menu: STT, Voice Translate, Settings |
| Keyboard shortcut | `launch-vox-refiner.sh --direct` → `record_and_transcribe_local.sh` | Direct Speech-to-Text → clipboard |

---

## Files

```text
vox-refiner-menu.sh        ← interactive menu + Voice Translate orchestration
src/voice_rewrite.py       ← clean + adapt for speech + translate (Mistral chat)
src/tts.py                 ← Voxtral TTS API (text + voice clone → MP3)
src/common.py              ← shared utilities (call_model, SECURITY_BLOCK, load_context, timing)
```

### src/voice_rewrite.py

Performs three tasks in a single Mistral chat call:

1. **Clean** — remove hesitations, repetitions, filler words
2. **Rewrite for speech** — short sentences (~15 words max), spoken connectors,
   contractions, natural rhythm for TTS playback
3. **Translate** — into the target language, sounding like a native speaker

**Tiered reasoning:**

| Text length | Params | Rationale |
| --- | --- | --- |
| < 120 words | `temperature=0.2, top_p=0.85` | Short texts: fast, no reasoning overhead |
| ≥ 120 words | `temperature=0.3, top_p=0.9, reasoning_effort=high` | Longer texts need reasoning for complex restructuring |

Fallback chain: `VOICE_REWRITE_MODEL` → `VOICE_REWRITE_MODEL_FALLBACK` →
return raw transcription (graceful degradation).

### src/tts.py

Voxtral TTS API (`POST /v1/audio/speech`):

- **Voice cloning** (recording ≥ 15s): sends `ref_audio` (raw base64 from WAV)
- **Preset voice** (recording too short): sends `voice_id` (UUID)
- Response: JSON `{"audio_data": "<base64>"}` → decoded to MP3

Fallback order: voice cloning → preset voice → TTS failure (text still in clipboard).

---

## Recording

- **Max duration:** 2 minutes (background timer with warning at 1:45)
- **Voice sample:** extracted from original WAV (not processed MP3) to preserve
  natural pitch and timbre. Skips first 3s, takes 15s.
- **Minimum for voice cloning:** 10s of usable audio (after skip)
- **All files** in `recordings/voice-translate/`, fixed names, overwritten each run

```text
recordings/voice-translate/
├── source.wav              ← raw recording
├── source.mp3              ← processed (silence removal + speed-up)
├── voice_sample.mp3        ← extracted for voice cloning
└── voice_translate.mp3     ← final TTS output
```

---

## Audio processing

1. **Silence removal + speed-up** (`AUDIO_TEMPO`, default 1.5×) → MP3 for STT
2. **TTS output normalization:**
   - EBU R128 loudnorm (`TTS_LOUDNESS`, default -16 LUFS)
   - Volume boost on top (`TTS_VOLUME`, default 2.0×)

---

## Language selection

Interactive sub-menu with 9 languages: en, fr, de, es, pt, it, nl, hi, ar.
`►` marker on the default language (from `TRANSLATE_TARGET_LANG`).
Press Enter to keep the default.

---

## Post-action flow

After Voice Translate completes:

- `[r]` Replay the audio
- `[n]` New recording (same language, no menu roundtrip)
- `Enter` Return to main menu

---

## Error handling

| Step | Failure | Behaviour |
| --- | --- | --- |
| Translation | Both models fail | Copy raw text to clipboard, show "TRANSLATION FAILED" |
| Voice sample | Recording too short | Use preset voice, warn user |
| TTS | Voxtral TTS fails | Show translated text only (no audio), text in clipboard |
| Playback | mpv not installed | Show MP3 path, suggest `apt install mpv` |

**Principle:** always give the user something useful. Translated text in
clipboard is the minimum viable output.

---

## Configuration (.env)

```bash
VOICE_TRANSLATE_TARGET_LANG=en              # Default target language for Voice Translate
TTS_MODEL=voxtral-mini-tts-2603            # TTS model
TTS_DEFAULT_VOICE_ID=c69964a6-...          # Preset voice UUID (Paul - Neutral)
TTS_LOUDNESS=-16                            # EBU R128 target (LUFS)
TTS_VOLUME=2.0                              # Post-normalization volume boost
TTS_PLAYER=mpv --no-video                   # Audio player
TTS_VOICE_SKIP_SECONDS=3                    # Skip start of recording
TTS_VOICE_SAMPLE_DURATION=15                # Voice sample length
VOICE_REWRITE_MODEL=mistral-small-latest    # Primary model
VOICE_REWRITE_MODEL_FALLBACK=mistral-medium-latest
VOICE_REWRITE_RETRIES=2
```

---

## Open questions

1. **Long recordings:** a future menu option will handle long conversations
   (segmented processing, chunk-based TTS). Current mode is capped at 2 min.
2. **Concurrent playback:** if the user starts a new recording while the
   previous TTS is still playing, should we kill the playback?

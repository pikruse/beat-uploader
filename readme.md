# yt-upload

Render an audio-reactive visualizer for a beat and upload it to YouTube.

## Setup

```bash
pip install -r requirements.txt
```

YouTube upload (first run only): create OAuth credentials in Google Cloud
Console (YouTube Data API v3, Desktop app), save the JSON as
`auth/client_secret.json`, then run once — a browser consent window opens and
the token is cached to `auth/token.json`.

Optional `.env` for the video description: `CONTACT_EMAIL`, `TIKTOK`, `INSTAGRAM`.

## GUI

```bash
python gui.py
```

…or double-click **Beat Uploader.app** in Finder (you can drag it to the
Dock). If macOS asks for permission to access the Desktop folder the first
time, click Allow — the project lives on the Desktop, which is a protected
location. If the app ever fails silently, check
`~/Library/Logs/BeatUploader.log`, or use **Beat Uploader.command**, which
launches through Terminal and always has file access.

Either way a local page opens (http://127.0.0.1:8765) where you drag & drop
beats and fill in each one's title / BPM / producer, **BeatStars link** and
optional **publish time**. Shared options: tags, privacy, color scheme, a
default BeatStars link (for beats left blank), and "delete render after
upload" (on by default — the mp4 is removed once YouTube has it).

- **BeatStars upload:** with "Upload to BeatStars" on (default), each beat
  without a link is published to BeatStars after it renders — mp3 master,
  title, detected BPM + key, same visibility as YouTube; BeatStars' autofill
  and your account defaults handle genre/moods/license prices. The new
  link goes into the YouTube description. BeatStars' Tags get the beat's
  own tags (first 3 — BeatStars' limit). Chrome runs in the background with
  its window minimized off-screen, so nothing pops up or steals focus
  (`python beatstars_uploader.py --upload … --show` to watch it).
  First time, or when it says the login expired: click **Connect BeatStars**
  (or `python beatstars_uploader.py --login`). BeatStars needs 320 kbps mp3s;
  lower-bitrate files are converted automatically.
- **Per-beat tags, title, co-prods:** each beat has its own Tags box (starts
  as the shared tags and follows them until you edit it) and an editable
  **YT title** line (auto-generated until you type in it; ↺ resets either).
  Co-producers go in the "Prod / co-prods" column, comma-separated —
  `pk, frankii` becomes "prod pk and frankii".
- **Batch links:** copy several BeatStars links (one per line) and paste them
  into the first row's link box — they fill down the rows in order.
- **Scheduling:** set "first beat at" + "every N days" and hit *Apply to
  beats*, or set times per row. **⏭ After last scheduled** continues from
  your latest scheduled YouTube video (or beat already queued in the app):
  first new beat N days after it, same time of day. The first time, Google
  asks once for read-only YouTube access so the app can see your schedule. Scheduled beats upload as private and YouTube
  publishes them at that time.
- **Set and forget:** after Start you can close the tab. Beats keep
  processing (the Mac is kept awake, a notification fires per beat) and the
  app quits itself once the queue is empty. Reopen the page any time to see
  progress — the queue is shown again.
- **Retry:** a failed beat gets a ↻ button; if its render had finished, only
  the upload is redone.
- **Quitting:** "quit now" on the page or Quit from the Dock both stop the
  server cleanly (and ask first if beats are still processing).

Files named `<name> <bpm> <producer>` (e.g. `NightDrive 140 prod pk.mp3`,
underscores/hyphens fine, a "prod" prefix is stripped) are parsed
automatically into the per-beat fields, with a live preview of the final
YouTube title under each row. Missing bpm falls back to auto-detection;
missing producer defaults to "pk".

The .app is built from `launcher.applescript` (rebuild steps are at the top
of that file).

## CLI

```bash
python main.py --audio beat.mp3 --title "TimeTraveller" --tags "trap,dark" \
    --beatstars-url https://beatstars.com/... 
```

Useful flags: `--skip-youtube` (render only), `--scheme cyber`, `--duration 30`
(preview), `--privacy unlisted`, `--workers N`, `--publish-at "2026-11-20 15:00"`
(schedule, local time), `--delete-render`. BPM and key are auto-detected
unless overridden with `--bpm` / `--key`.

`media_processor.py` is a render-only alias (same as `--skip-youtube`).

## How rendering works (and why it's fast)

- A sequential "physics" pass computes per-frame smoothing/particle state
  (cheap, keeps visuals identical to single-threaded rendering).
- Frames are drawn in parallel across all CPU cores (`src/render.py`) into a
  shared-memory ring buffer and streamed straight into ffmpeg — no pickling
  6 MB frames between processes, no intermediate files, audio muxed in the
  same pass. The waveform/spectrum fills are numpy, not PIL polygons.
- On Macs the video is encoded by the hardware encoder (VideoToolbox, 12
  Mbps — same measured quality as the old x264 crf 23, ~40% larger file),
  which leaves the CPU to drawing. A 2:40 beat renders in ~55 s (was ~160 s).
  `BEAT_ENCODER=x264` switches back to the smaller-file CPU encoder (~110 s)
  if your upload connection is slow; `BEAT_VT_BITRATE=10M` trades a little
  quality for size.

## Layout

- `src/pipeline.py` — analyze → render → upload, shared by CLI and GUI
- `src/audio.py` — librosa analysis (onsets, spectrum, BPM, key)
- `src/visualizer.py` — frame drawing (PIL)
- `src/render.py` — parallel rendering + ffmpeg encode
- `youtube_uploader.py` — YouTube Data API v3 upload
- `beatstars_uploader.py` — BeatStars Studio automation (Playwright + Chrome)
- `utils.py` — title/description (SEO) templates

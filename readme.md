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
beats, type a title per beat, set shared options (tags, BeatStars URL,
privacy, color scheme), and hit Start. Beats are queued and processed one at
a time with live per-beat progress and a log. The "quit app" link in the
footer stops the server.

Files named `<name> <bpm> <producer>` (e.g. `NightDrive 140 pk.mp3`,
underscores/hyphens also fine) are parsed automatically: the name prefills
the title and the bpm/producer are used for that beat. Files without a bpm
token fall back to auto-detected BPM and the Producer field.

## CLI

```bash
python main.py --audio beat.mp3 --title "TimeTraveller" --tags "trap,dark" \
    --beatstars-url https://beatstars.com/... 
```

Useful flags: `--skip-youtube` (render only), `--scheme cyber`, `--duration 30`
(preview), `--privacy unlisted`, `--workers N`. BPM and key are auto-detected
unless overridden with `--bpm` / `--key`.

`media_processor.py` is a render-only alias (same as `--skip-youtube`).

## How rendering works (and why it's fast)

- A sequential "physics" pass computes per-frame smoothing/particle state
  (cheap, keeps visuals identical to single-threaded rendering).
- Frames are then drawn in parallel across all CPU cores
  (`src/render.py`) and piped straight into ffmpeg — no intermediate
  files, audio muxed in the same pass.

## Layout

- `src/pipeline.py` — analyze → render → upload, shared by CLI and GUI
- `src/audio.py` — librosa analysis (onsets, spectrum, BPM, key)
- `src/visualizer.py` — frame drawing (PIL)
- `src/render.py` — parallel rendering + ffmpeg encode
- `youtube_uploader.py` — YouTube Data API v3 upload
- `utils.py` — title/description (SEO) templates

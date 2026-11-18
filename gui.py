# gui.py
"""Local web GUI for the beat upload pipeline.

Usage:
    python gui.py                 # opens http://127.0.0.1:8765 in your browser
    python gui.py --no-browser    # just serve (open the URL yourself)

Drag & drop beats onto the page, give each its title / BeatStars link /
publish time, hit Start. Beats are processed one at a time: render → YouTube
upload (optionally scheduled), then the local render is deleted.

Background mode: once beats are queued you can close the tab. Processing
continues (the Mac is kept awake, a notification fires per beat), and the
app quits itself when the queue is empty and no page is open.

Stdlib only — no extra GUI dependencies. The server binds to localhost.
"""

import argparse
import itertools
import json
import os
import queue
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from src.config import COLOR_SCHEMES

PORT = 8765
PAGE_GONE_GRACE = 10        # s after the last tab closes before auto-quit (if idle)
NO_PAGE_TIMEOUT = 15 * 60   # s without any page polling (crashed browser) before auto-quit
WORKER_JOIN_TIMEOUT = 20    # s to let a cancelled render/upload clean up on quit

# Created in main(), not at import: render workers use the "spawn" start
# method, which re-imports this module in every worker process.
UPLOAD_DIR = None

_jobs = {}                # id -> job dict (see _handle_submit)
_log_lines = []
_lock = threading.Lock()
_job_queue = queue.Queue()
_job_ids = itertools.count(1)
_stop = threading.Event()
_instance = uuid.uuid4().hex[:8]   # lets an open page notice an app restart
_last_seen = time.monotonic()      # monotonic: doesn't jump across laptop sleep
_closed_at = None
_server = None


# ── State helpers ────────────────────────────────────────────

def _log(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)      # → ~/Library/Logs/BeatUploader.log under the .app
    with _lock:
        _log_lines.append(line)
        del _log_lines[:-500]


def _set_status(job_id, status):
    with _lock:
        _jobs[job_id]["status"] = status


def _is_active(status):
    return not (status == "done" or status == "cancelled" or status.startswith("error"))


def _busy_count():
    with _lock:
        return sum(1 for j in _jobs.values() if _is_active(j["status"]))


def _notify(msg):
    """macOS notification banner; silently skipped elsewhere."""
    if sys.platform != "darwin":
        return
    try:
        subprocess.Popen(
            ["osascript", "-e", "on run argv",
             "-e", 'display notification (item 1 of argv) with title "Beat Uploader"',
             "-e", "end run", msg],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


class _KeepAwake:
    """Hold off idle sleep while jobs run, so set-and-forget batches finish."""

    def __init__(self):
        self.proc = None

    def on(self):
        if sys.platform == "darwin" and self.proc is None:
            try:
                self.proc = subprocess.Popen(["caffeinate", "-is", "-w", str(os.getpid())])
            except OSError:
                pass

    def off(self):
        if self.proc is not None:
            self.proc.terminate()
            self.proc = None


def _remove_quietly(path):
    try:
        os.remove(path)
    except OSError:
        pass


def _effective_publish_at(job):
    """The job's schedule, or None if that time has already passed (renders
    queue up, so a slot picked an hour ago can be stale by upload time)."""
    if not job["publish_at"]:
        return None
    when = datetime.fromisoformat(job["publish_at"].replace("Z", "+00:00"))
    if when <= datetime.now(timezone.utc) + timedelta(minutes=2):
        _log(f"  Scheduled time for {job['title']} already passed — publishing now ({job['privacy']})")
        return None
    return job["publish_at"]


# ── Pipeline worker (one job at a time) ──────────────────────

def _worker():
    from src.pipeline import render_beat, upload_beat  # heavy import, deferred

    awake = _KeepAwake()
    ran_any = False
    while not _stop.is_set():
        try:
            job_id = _job_queue.get(timeout=0.5)
        except queue.Empty:
            continue
        with _lock:
            job = dict(_jobs[job_id])
        if not _is_active(job["status"]):      # cleared/finished while queued
            continue
        awake.on()
        ran_any = True
        try:
            render = job.get("render")
            if not (render and os.path.exists(render["output"])):
                _set_status(job_id, "analyzing")
                render = render_beat(
                    audio=job["path"],
                    title=job["title"],
                    bpm=job["bpm"],
                    producer=job["producer"],
                    scheme=job["scheme"],
                    log=_log,
                    progress=lambda f: _set_status(job_id, f"rendering {int(f * 100)}%"),
                    should_stop=_stop.is_set,
                )
                with _lock:
                    _jobs[job_id]["render"] = render   # a retry can skip straight to upload

            if job["bs_upload"] and not job["beatstars_url"]:
                from beatstars_uploader import upload_track
                _set_status(job_id, "BeatStars upload")
                bs_url = upload_track(
                    job["path"], job["title"], bpm=render["bpm"], key=render["key"],
                    visibility=job["privacy"], log=_log, should_stop=_stop.is_set)
                with _lock:
                    _jobs[job_id]["beatstars_url"] = bs_url   # a retry won't re-upload
                job["beatstars_url"] = bs_url

            if job["skip_youtube"]:
                url = render["output"]
            else:
                _set_status(job_id, "uploading 0%")
                url = upload_beat(
                    render,
                    title=job["title"],
                    tags=job["tags"],
                    beatstars_url=job["beatstars_url"] or None,
                    privacy=job["privacy"],
                    publish_at=_effective_publish_at(job),
                    delete_after_upload=job["delete_render"],
                    log=_log,
                    progress=lambda f: _set_status(job_id, f"uploading {int(f * 100)}%"),
                    should_stop=_stop.is_set,
                )
            with _lock:
                _jobs[job_id]["status"] = "done"
                _jobs[job_id]["url"] = url
            _remove_quietly(job["path"])           # the uploaded audio copy
            verb = "rendered" if job["skip_youtube"] else (
                "scheduled" if job["publish_at"] else "uploaded")
            _notify(f"✓ {job['title']} {verb}")
        except Exception as e:
            if _stop.is_set():
                _set_status(job_id, "cancelled")
                _log(f"Cancelled: {job['title']}")
            else:
                _set_status(job_id, f"error: {e}")
                _log(f"ERROR ({job['title']}): {e}")
                _notify(f"✗ {job['title']} failed: {e}")

        if _job_queue.empty() and _busy_count() == 0:
            awake.off()
            if ran_any and not _stop.is_set():
                _log("Queue finished")
                _notify("Queue finished")
            ran_any = False
    awake.off()


# ── Shutdown ─────────────────────────────────────────────────

def _request_shutdown(reason):
    """Stop the worker (cancels any render/upload) and the HTTP server."""
    if _stop.is_set():
        return
    _log(f"Shutting down: {reason}")
    _stop.set()
    # shutdown() blocks until serve_forever returns → never call it on the
    # serving thread itself.
    threading.Thread(target=_server.shutdown, daemon=True).start()


def _watchdog():
    """Quit on our own once nothing is queued and no page is open."""
    while not _stop.wait(2):
        if _busy_count():
            continue
        now = time.monotonic()
        with _lock:
            seen, closed = _last_seen, _closed_at
        if closed is not None and seen <= closed and now - closed > PAGE_GONE_GRACE:
            _request_shutdown("page closed and queue empty")
        elif now - seen > NO_PAGE_TIMEOUT:
            _request_shutdown("no page open for 15 min and queue empty")


# ── HTTP handler ─────────────────────────────────────────────

def _bad(msg):
    raise ValueError(msg)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence per-request stderr noise
        pass

    def _send(self, body, ctype="text/html; charset=utf-8", code=200):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj, code=200):
        self._send(json.dumps(obj), "application/json", code)

    def do_GET(self):
        global _last_seen
        path = urlparse(self.path).path
        if path == "/":
            self._send(PAGE)
        elif path == "/api/jobs":
            with _lock:
                _last_seen = time.monotonic()
                snapshot = {
                    "instance": _instance,
                    "jobs": {jid: {k: j[k] for k in (
                                "status", "url", "filename", "title", "bpm", "producer",
                                "beatstars_url", "publish_at", "skip_youtube")}
                             for jid, j in _jobs.items()},
                    "log": list(_log_lines[-200:]),
                }
            self._json(snapshot)
        elif path == "/api/busy":           # used by the .app's quit handler
            self._send(str(_busy_count()), "text/plain")
        else:
            self._send("not found", code=404)

    def do_POST(self):
        global _closed_at
        parsed = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        size = int(self.headers.get("Content-Length", 0) or 0)

        if parsed.path == "/api/submit":
            try:
                self._json({"id": self._handle_submit(q, size)})
            except ValueError as e:
                self.rfile.read(size)
                self._json({"error": str(e)}, 400)
            return

        self.rfile.read(size)
        if parsed.path == "/api/quit":
            self._json({"ok": True})
            _request_shutdown("quit from the page")
        elif parsed.path == "/api/bye":     # sendBeacon from a closing tab
            with _lock:
                _closed_at = time.monotonic()
            self._json({"ok": True})
        elif parsed.path == "/api/retry":
            job_id = int(q.get("id", 0) or 0)
            with _lock:
                job = _jobs.get(job_id)
                ok = bool(job) and (job["status"].startswith("error")
                                    or job["status"] == "cancelled")
                if ok:
                    job["status"] = "queued"
            if ok:
                _job_queue.put(job_id)
                _log(f"Retrying: {job['title']}"
                     + (" (upload only)" if job.get("render") else ""))
            self._json({"ok": ok}, 200 if ok else 409)
        elif parsed.path == "/api/beatstars/login":
            def run():
                from beatstars_uploader import login
                try:
                    login(log=_log)
                except Exception as e:
                    _log(f"BeatStars login failed: {e}")
            threading.Thread(target=run, daemon=True).start()
            self._json({"ok": True})
        elif parsed.path == "/api/clear":   # drop finished jobs from the list
            with _lock:
                for jid in [jid for jid, j in _jobs.items() if not _is_active(j["status"])]:
                    _remove_quietly(_jobs.pop(jid)["path"])
            self._json({"ok": True})
        else:
            self._send("not found", code=404)

    def _handle_submit(self, q, size):
        filename = os.path.basename(q.get("filename", "beat.mp3"))
        title = q.get("title", "").strip() or os.path.splitext(filename)[0]

        beatstars = q.get("beatstars", "").strip()
        if beatstars and not beatstars.startswith(("http://", "https://")):
            _bad(f'BeatStars link for "{title}" isn\'t a URL')

        publish_at = q.get("publish_at", "").strip() or None
        if publish_at:
            try:
                when = datetime.fromisoformat(publish_at.replace("Z", "+00:00"))
            except ValueError:
                _bad(f'bad publish time for "{title}"')
            if when.tzinfo is None or when <= datetime.now(timezone.utc):
                _bad(f'publish time for "{title}" is in the past')
            publish_at = when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        job_id = next(_job_ids)
        audio_path = os.path.join(UPLOAD_DIR, f"{job_id}_{filename}")
        with open(audio_path, "wb") as f:
            remaining = size
            while remaining > 0:
                chunk = self.rfile.read(min(remaining, 1 << 20))
                if not chunk:
                    break
                f.write(chunk)
                remaining -= len(chunk)

        scheme = q.get("scheme", "")
        privacy = q.get("privacy", "public")
        job = {
            "path": audio_path,
            "filename": filename,
            "title": title,
            "bpm": q.get("bpm", "").strip() or None,
            "producer": q.get("producer", "").strip() or "pk",
            "tags": [t.strip() for t in q.get("tags", "").split(",") if t.strip()],
            "beatstars_url": beatstars,
            "privacy": privacy if privacy in ("public", "unlisted", "private") else "public",
            "publish_at": publish_at,
            "scheme": scheme if scheme in COLOR_SCHEMES else None,
            "skip_youtube": q.get("skip") == "1",
            "delete_render": q.get("del") == "1",
            "bs_upload": q.get("bs") == "1" and not beatstars and q.get("skip") != "1",
            "status": "queued",
            "url": None,
            "render": None,
        }
        with _lock:
            _jobs[job_id] = job
        _job_queue.put(job_id)
        _log(f"Queued: {title} ({filename})"
             + (f" — scheduled {publish_at}" if publish_at else "")
             + ("" if beatstars or job["bs_upload"] else " — no BeatStars link"))
        return job_id


# ── Page ─────────────────────────────────────────────────────

SCHEME_OPTIONS = "".join(f'<option value="{k}">{v["name"]}</option>'
                         for k, v in COLOR_SCHEMES.items())

PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Beat Uploader</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><text y=%22.9em%22 font-size=%2290%22>🎧</text></svg>">
<style>
  :root {
    color-scheme: dark;
    --bg: #0f1116; --card: #161a22; --card2: #1b202b; --border: #262c39;
    --text: #e9ecf2; --dim: #8b94a7;
    --acc1: #7c5cff; --acc2: #4f9cff;
    --grad: linear-gradient(120deg, var(--acc1), var(--acc2));
    --ok: #4ade80; --err: #f87171; --warn: #fbbf24;
  }
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, "SF Pro Text", "Segoe UI", sans-serif;
    background:
      radial-gradient(900px 400px at 80% -10%, rgba(124,92,255,.14), transparent),
      radial-gradient(700px 300px at 10% -10%, rgba(79,156,255,.10), transparent),
      var(--bg);
    color: var(--text); max-width: 980px; margin: 0 auto; padding: 32px 20px 60px;
  }
  header { display: flex; align-items: baseline; gap: 12px; margin-bottom: 22px; }
  h1 {
    font-size: 22px; letter-spacing: 4px; margin: 0; font-weight: 800;
    background: var(--grad); -webkit-background-clip: text;
    background-clip: text; color: transparent;
  }
  header small { color: var(--dim); letter-spacing: 1px; }

  #drop {
    border: 2px dashed #38415a; border-radius: 16px; padding: 42px 20px;
    text-align: center; color: var(--dim); cursor: pointer;
    transition: all .18s ease; margin-bottom: 18px; background: rgba(255,255,255,.015);
  }
  #drop .icon { font-size: 34px; display: block; margin-bottom: 8px;
                filter: grayscale(.4); transition: all .18s ease; }
  #drop .hint { font-size: 12px; opacity: .7; }
  #drop.over, #drop:hover {
    border-color: var(--acc1); color: var(--text);
    background: rgba(124,92,255,.06);
    box-shadow: 0 0 0 4px rgba(124,92,255,.08), 0 10px 40px -18px rgba(124,92,255,.5);
  }
  #drop.over .icon, #drop:hover .icon { transform: translateY(-3px) scale(1.12); filter: none; }

  .card { background: var(--card); border: 1px solid var(--border);
          border-radius: 14px; margin-bottom: 18px; overflow: hidden; }
  .cardHead { display: flex; justify-content: space-between; align-items: center;
              padding: 10px 14px 0; font-size: 11px; color: var(--dim); }
  .cardHead button { background: none; border: 1px solid var(--border); color: var(--dim);
                     border-radius: 8px; padding: 4px 10px; font-size: 11px; cursor: pointer; }
  .cardHead button:hover { color: var(--text); border-color: var(--acc1); }

  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; color: var(--dim); font-size: 10px; letter-spacing: 1.5px;
       text-transform: uppercase; padding: 10px 14px 6px; }
  td { padding: 8px 14px; border-top: 1px solid var(--border); font-size: 14px;
       vertical-align: middle; }
  td.file { color: var(--dim); font: 12px ui-monospace, monospace; max-width: 190px;
            overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  tr.detailRow td { border-top: 0; padding: 0 14px 12px; }
  .detail { display: flex; gap: 10px; align-items: center; margin-bottom: 6px; }
  .detail input {
    background: var(--card2); color: var(--text); font-size: 12px;
    border: 1px solid var(--border); border-radius: 7px; padding: 5px 8px; outline: 0;
  }
  .detail input:focus { border-color: var(--acc1); }
  .detail input:disabled { color: var(--dim); background: transparent; }
  .detail input.bs { flex: 1; min-width: 0; font-family: ui-monospace, "SF Mono", monospace; }
  .detail input.bad { border-color: var(--err); }
  .detail label { font-size: 10px; letter-spacing: 1.5px; text-transform: uppercase;
                  color: var(--dim); }
  .preview { font: 11px ui-monospace, "SF Mono", monospace; color: #66708a;
             overflow-wrap: anywhere; }
  .preview b { color: #8b94a7; font-weight: 600; }
  .preview .sched { color: var(--acc2); }
  .preview .warn { color: var(--warn); }
  td > input {
    width: 100%; background: transparent; color: var(--text); font-size: 14px;
    border: 0; border-bottom: 1px solid transparent; padding: 4px 2px; outline: 0;
  }
  td > input:hover:not(:disabled) { border-bottom-color: var(--border); }
  td > input:focus { border-bottom-color: var(--acc1); }
  td > input:disabled { color: var(--dim); }

  .pill { display: inline-block; font-size: 11px; font-weight: 600; padding: 3px 10px;
          border-radius: 99px; letter-spacing: .5px; max-width: 220px;
          overflow: hidden; text-overflow: ellipsis; white-space: nowrap; vertical-align: middle; }
  .pill.queued  { background: #262c39; color: var(--dim); }
  .pill.busy    { background: rgba(79,156,255,.15); color: var(--acc2); }
  .pill.done    { background: rgba(74,222,128,.14); color: var(--ok); }
  .pill.error   { background: rgba(248,113,113,.14); color: var(--err); }
  .bar { width: 100px; height: 6px; background: #262c39; border-radius: 99px;
         overflow: hidden; display: inline-block; vertical-align: middle; margin-right: 8px; }
  .bar > div { height: 100%; background: var(--grad); border-radius: 99px;
               transition: width .4s ease; }
  .pct { font-size: 11px; color: var(--acc2); font-weight: 600; }
  td .x { background: none; border: 0; color: var(--dim); cursor: pointer;
          font-size: 14px; padding: 2px 6px; border-radius: 6px; }
  td .x:hover { color: var(--err); background: rgba(248,113,113,.1); }
  td .x.retry:hover { color: var(--acc2); background: rgba(79,156,255,.1); }

  .opts { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; padding: 16px; }
  .opts label { display: block; font-size: 10px; letter-spacing: 1.5px;
                text-transform: uppercase; color: var(--dim); margin-bottom: 5px; }
  .opts input, .opts select, .opts button {
    width: 100%; background: var(--card2); color: var(--text); font-size: 13px;
    border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; outline: 0;
    transition: border-color .15s;
  }
  .opts input:focus, .opts select:focus { border-color: var(--acc1); }
  .opts .row { display: flex; gap: 8px; }
  .opts .row input[type=number] { width: 64px; flex: none; }
  .opts .row button { width: auto; cursor: pointer; white-space: nowrap; }
  .opts .row button:hover { border-color: var(--acc1); }
  .opts .check { display: flex; align-items: center; gap: 8px; }
  .opts .check input { width: auto; accent-color: var(--acc1); }
  .opts .check label { margin: 0; text-transform: none; font-size: 13px;
                       letter-spacing: 0; color: var(--text); }
  .opts .span2 { grid-column: span 2; }
  .opts .check button.mini { width: auto; padding: 4px 9px; font-size: 11px; cursor: pointer;
                             color: var(--dim); margin-left: auto; }
  .opts .check button.mini:hover { color: var(--text); border-color: var(--acc1); }

  #start {
    width: 100%; padding: 14px; font-size: 15px; font-weight: 700; letter-spacing: 1px;
    border: 0; border-radius: 12px; background: var(--grad); color: white; cursor: pointer;
    transition: all .15s ease; box-shadow: 0 8px 24px -10px rgba(124,92,255,.55);
  }
  #start:hover:not(:disabled) { transform: translateY(-1px);
    box-shadow: 0 12px 30px -10px rgba(124,92,255,.7); }
  #start:disabled { background: #262c39; color: #566; cursor: default; box-shadow: none; }

  #log {
    background: #0b0d11; border: 1px solid var(--border); border-radius: 12px;
    padding: 12px 14px; height: 190px; overflow-y: auto;
    font: 11px/1.6 ui-monospace, "SF Mono", monospace; color: #7fd1a0;
    white-space: pre-wrap; margin-top: 18px;
  }
  footer { margin-top: 14px; text-align: center; font-size: 11px; color: var(--dim); }
  footer a { color: var(--dim); }
  footer a:hover { color: var(--err); }
  a { color: var(--acc2); }
  @media (max-width: 720px) {
    .opts { grid-template-columns: 1fr; }
    .opts .span2 { grid-column: auto; }
  }
</style></head>
<body>
<header><h1>BEAT UPLOADER</h1><small>render → YouTube</small></header>

<div id="drop">
  <span class="icon">🎵</span>
  Drag &amp; drop beats here
  <div class="hint">or click to browse — mp3 / wav / flac / aiff / m4a / ogg</div>
</div>
<input type="file" id="file" multiple accept="audio/*" hidden>

<div class="card" id="queueCard" hidden>
<div class="cardHead"><span>Tip: paste several BeatStars links (one per line) into the first row — they fill down in order.</span>
  <button id="clearDone" hidden>Clear finished</button></div>
<table id="queue">
  <thead><tr><th>File</th><th>Beat title</th><th style="width:64px">BPM</th>
    <th style="width:110px">Producer</th><th style="width:170px">Status</th><th style="width:36px"></th></tr></thead>
  <tbody></tbody>
</table>
</div>

<div class="card"><div class="opts">
  <div><label>Tags</label><input id="tags" placeholder="trap, dark, ambient"></div>
  <div><label>Privacy (unscheduled beats)</label><select id="privacy">
    <option>public</option><option>unlisted</option><option>private</option></select></div>
  <div><label>Color scheme</label><select id="scheme"><option value="">Random</option>__SCHEMES__</select></div>

  <div><label>Default BeatStars link</label><input id="defBeatstars" placeholder="store link, for beats left blank"></div>
  <div class="span2"><label>Schedule — first beat at, then one every N days</label>
    <div class="row"><input type="datetime-local" id="schedStart">
      <input type="number" id="schedEvery" min="0" step="1" value="1" title="days between beats">
      <button id="schedApply">Apply to beats</button></div></div>

  <div class="check"><input type="checkbox" id="bsUpload" checked><label for="bsUpload">Upload to BeatStars (beats without a link)</label>
    <button id="bsConnect" class="mini" title="Opens Chrome to log in to BeatStars">Connect BeatStars</button></div>
  <div class="check"><input type="checkbox" id="deleteRender" checked><label for="deleteRender">Delete render after upload</label></div>
  <div class="check"><input type="checkbox" id="skip"><label for="skip">Render only (skip YouTube)</label></div>
</div></div>

<button id="start">▶&nbsp;&nbsp;START</button>
<pre id="log">waiting…</pre>
<footer>Close this tab anytime — queued beats keep processing in the background and the app quits itself when done.
  · <a href="#" id="quit">quit now</a></footer>

<script>
const $ = id => document.getElementById(id);
const items = [];
const drop = $('drop'), fileInput = $('file'), queueCard = $('queueCard');
const tbody = document.querySelector('#queue tbody');
const startBtn = $('start'), logBox = $('log');
const AUDIO_RE = /\.(mp3|wav|flac|aiff?|m4a|ogg)$/i;
const URL_RE = /^https?:\/\/\S+$/i;
const isActive = s => !(s === 'done' || s === 'cancelled' || /^error/.test(s));
const canRetry = it => it.jobId && !it.orphan && (/^error/.test(it.status) || it.status === 'cancelled');

// ── Remember shared options between sessions ──
const OPT_IDS = ['tags', 'privacy', 'scheme', 'defBeatstars', 'schedEvery', 'bsUpload', 'deleteRender', 'skip'];
function loadOpts() {
  try {
    const o = JSON.parse(localStorage.getItem('beat-uploader-opts') || '{}');
    for (const k of OPT_IDS) if (k in o) {
      const el = $(k);
      if (el.type === 'checkbox') el.checked = !!o[k]; else el.value = o[k];
    }
  } catch (e) {}
}
function saveOpts() {
  try {
    const o = {};
    for (const k of OPT_IDS) { const el = $(k); o[k] = el.type === 'checkbox' ? el.checked : el.value; }
    localStorage.setItem('beat-uploader-opts', JSON.stringify(o));
  } catch (e) {}
}
loadOpts();
OPT_IDS.forEach(k => $(k).addEventListener('change', saveOpts));

// Client-side messages survive the 1s server-log refresh
let serverLog = [];
const clientLines = [];
function updateLog() {
  const atBottom = logBox.scrollTop + logBox.clientHeight >= logBox.scrollHeight - 8;
  const all = serverLog.concat(clientLines);
  logBox.textContent = all.length ? all.join('\n') : 'waiting…';
  if (atBottom) logBox.scrollTop = logBox.scrollHeight;
}
function clientLog(s) {
  clientLines.push('[ui] ' + s);
  if (clientLines.length > 50) clientLines.shift();
  updateLog();
}
window.addEventListener('error', e => clientLog('page error: ' + e.message));

// Beat files are named "<name> <bpm> <producer>", e.g. "NightDrive 140 pk.mp3".
// The bpm token anchors the split: everything before is the beat name,
// everything after is the producer(s). Falls back to the whole stem as title.
function parseBeatFilename(filename) {
  const stem = filename.replace(/\.[^.]+$/, '').replace(/[_-]+/g, ' ').trim();
  const tokens = stem.split(/\s+/);
  let bpmIdx = -1, bpm = null;
  for (let i = 1; i < tokens.length; i++) {   // bpm is never the first token
    const m = tokens[i].match(/^(\d{2,3})(bpm)?$/i);
    if (m && +m[1] >= 40 && +m[1] <= 300) { bpmIdx = i; bpm = m[1]; }
  }
  if (bpmIdx < 0) return { title: stem, bpm: null, producer: null };
  return {
    title: tokens.slice(0, bpmIdx).join(' ') || stem,
    bpm: bpm,
    // filenames already carry the credit ("... 140 prod pk") — strip it,
    // the title/overlay templates add their own "prod"
    producer: tokens.slice(bpmIdx + 1).join(' ').replace(/^prod\.?\s+/i, '') || null,
  };
}

// Mirrors utils.format_youtube_title (keep the two in sync)
function formatYtTitle(title, bpm, producer, tags) {
  const clean = s => (s || '').replace(/[<>]/g, '').trim();
  title = clean(title);
  const bpmNum = clean(bpm).toLowerCase().replace('bpm', '').trim() || 'auto';
  const prods = clean(producer).split(',')
    .map(p => clean(p).replace(/^prod\.?\s+/i, '')).filter(Boolean);
  const prodPart = prods.length <= 1 ? (prods[0] || '')
    : prods.slice(0, -1).join(', ') + ' and ' + prods[prods.length - 1];
  const tagPart = clean(tags).split(',').map(clean).filter(Boolean).join(' x ');
  const candidates = [
    `[Free] ${tagPart ? tagPart + ' ' : ''}type beat - "${title}" ${bpmNum} bpm, prod ${prodPart}`,
    `[Free] type beat - "${title}" ${bpmNum} bpm, prod ${prodPart}`,
    `[Free] type beat - "${title}" ${bpmNum} bpm`,
  ];
  for (const c of candidates) if (c.length <= 100) return c;
  return candidates[2].slice(0, 100);
}

// <input type=datetime-local> wants local "YYYY-MM-DDTHH:MM"
function toLocalInput(d) {
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}
const fmtWhen = v => new Date(v).toLocaleString([], { weekday: 'short', month: 'short',
  day: 'numeric', hour: 'numeric', minute: '2-digit' });

function addFiles(files) {
  const rejected = [];
  for (const f of files) {
    if (!AUDIO_RE.test(f.name)) { rejected.push(f.name); continue; }
    if (items.some(it => it.name === f.name && !it.jobId)) continue;
    const parsed = parseBeatFilename(f.name);
    items.push({
      file: f, name: f.name,
      title: parsed.title, bpm: parsed.bpm, producer: parsed.producer,
      beatstars: '', publishAt: '',
      jobId: null, status: 'ready', url: null,
    });
  }
  if (rejected.length) clientLog('ignored (not an audio file): ' + rejected.join(', '));
  render();
}

function itemFromServer(jid, j) {
  return {
    file: null, name: j.filename, title: j.title, bpm: j.bpm, producer: j.producer,
    beatstars: j.beatstars_url || '',
    publishAt: j.publish_at ? toLocalInput(new Date(j.publish_at)) : '',
    jobId: jid, status: j.status, url: j.url,
  };
}

function statusCell(it) {
  const td = document.createElement('td');
  const m = it.status.match(/^(rendering|uploading) (\d+)%/);
  if (it.url && /^http/.test(it.url)) {
    const a = document.createElement('a');
    a.href = it.url; a.target = '_blank'; a.textContent = it.url.replace(/^https?:\/\//, '');
    td.appendChild(a);
  } else if (m) {
    const bar = document.createElement('span'); bar.className = 'bar';
    const fill = document.createElement('div'); fill.style.width = m[2] + '%';
    bar.appendChild(fill);
    const pct = document.createElement('span'); pct.className = 'pct';
    pct.textContent = (m[1] === 'uploading' ? '↑ ' : '') + m[2] + '%';
    td.append(bar, pct);
  } else {
    const pill = document.createElement('span');
    const cls = it.status === 'done' ? 'done'
              : /^error/.test(it.status) || it.status === 'cancelled' ? 'error'
              : it.status === 'queued' || it.status === 'ready' ? 'queued' : 'busy';
    pill.className = 'pill ' + cls;
    pill.textContent = it.status === 'done' && it.url ? '✓ ' + it.url : it.status;
    pill.title = it.status;
    td.appendChild(pill);
  }
  return td;
}

function render() {
  queueCard.hidden = items.length === 0;
  $('clearDone').hidden = !items.some(it => it.jobId && (it.orphan || !isActive(it.status)));
  tbody.innerHTML = '';
  items.forEach((it, i) => {
    const locked = !!it.jobId;
    const mkInput = (value, placeholder, onChange, type) => {
      const inp = document.createElement('input');
      if (type) inp.type = type;
      inp.value = value || '';
      inp.placeholder = placeholder;
      inp.disabled = locked;
      inp.oninput = () => { onChange(inp.value); it.updatePreview(); };
      return inp;
    };
    const cell = el => { const td = document.createElement('td'); td.append(el); return td; };

    const tr = document.createElement('tr');
    const tdFile = document.createElement('td');
    tdFile.className = 'file';
    tdFile.textContent = it.name;
    tdFile.title = it.name;

    const tdAct = document.createElement('td');
    if (!locked) {
      const b = document.createElement('button');
      b.className = 'x'; b.textContent = '✕'; b.title = 'remove';
      b.onclick = () => { items.splice(i, 1); render(); };
      tdAct.appendChild(b);
    } else if (canRetry(it)) {
      const b = document.createElement('button');
      b.className = 'x retry'; b.textContent = '↻'; b.title = 'retry (skips the render if it already finished)';
      b.onclick = () => retry(it);
      tdAct.appendChild(b);
    }
    it.statusTd = statusCell(it);
    tr.append(tdFile,
              cell(mkInput(it.title, 'Beat name…', v => { it.title = v; })),
              cell(mkInput(it.bpm, 'auto', v => { it.bpm = v; })),
              cell(mkInput(it.producer, 'pk', v => { it.producer = v; })),
              it.statusTd, tdAct);

    // Detail row: per-beat BeatStars link + publish time, then the title preview
    const trD = document.createElement('tr');
    trD.className = 'detailRow';
    const tdD = document.createElement('td');
    tdD.colSpan = 6;
    const line = document.createElement('div');
    line.className = 'detail';
    const bs = mkInput(it.beatstars, 'BeatStars link (blank = upload / default link)', v => { it.beatstars = v.trim(); });
    bs.className = 'bs';
    const markBad = () => bs.classList.toggle('bad', !!it.beatstars && !URL_RE.test(it.beatstars));
    bs.addEventListener('input', markBad);
    markBad();
    // Pasting several links fills this row and the ones below it, in order
    bs.onpaste = e => {
      const urls = (e.clipboardData.getData('text') || '').split(/\s+/).filter(s => URL_RE.test(s));
      if (urls.length < 2) return;
      e.preventDefault();
      const targets = items.slice(i).filter(x => !x.jobId);
      targets.forEach((x, k) => { if (k < urls.length) x.beatstars = urls[k]; });
      const extra = urls.length - targets.length;
      clientLog(`filled ${Math.min(urls.length, targets.length)} BeatStars links in order`
                + (extra > 0 ? ` (${extra} extra ignored)` : ''));
      render();
    };
    const pubLabel = document.createElement('label');
    pubLabel.textContent = 'Publish';
    const pub = mkInput(it.publishAt, '', v => { it.publishAt = v; }, 'datetime-local');
    pub.title = 'blank = publish as soon as uploaded';
    line.append(bs, pubLabel, pub);

    const prev = document.createElement('div');
    prev.className = 'preview';
    it.updatePreview = () => {
      prev.innerHTML = '';
      const label = document.createElement('b');
      label.textContent = 'YT title → ';
      prev.append(label, formatYtTitle(it.title, it.bpm, it.producer || 'pk', $('tags').value));
      const add = (cls, text) => {
        const s = document.createElement('span'); s.className = cls; s.textContent = text; prev.append(s);
      };
      if (it.publishAt) add('sched', '  ·  ⏰ ' + fmtWhen(it.publishAt) + ' (private until then)');
      if (!it.beatstars && $('bsUpload').checked)
        add('sched', '  ·  ↑ BeatStars upload, link added automatically');
      else if (!it.beatstars && !$('defBeatstars').value.trim() && !$('skip').checked)
        add('warn', '  ·  no BeatStars link');
    };
    it.updatePreview();
    tdD.append(line, prev);
    trD.appendChild(tdD);
    tbody.append(tr, trD);
  });
}

// Shared fields feed the previews too
['tags', 'defBeatstars', 'skip', 'bsUpload'].forEach(id => $(id).addEventListener('input',
  () => items.forEach(it => it.updatePreview && it.updatePreview())));

// Swap only the status cell so polling never steals focus from an input
function refreshStatus(it) {
  if (!it.statusTd) return;
  const fresh = statusCell(it);
  it.statusTd.replaceWith(fresh);
  it.statusTd = fresh;
}

drop.onclick = () => fileInput.click();
fileInput.onchange = () => { addFiles(fileInput.files); fileInput.value = ''; };
drop.ondragover = e => { e.preventDefault(); drop.classList.add('over'); };
drop.ondragleave = () => drop.classList.remove('over');
drop.ondrop = e => { e.preventDefault(); drop.classList.remove('over'); addFiles(e.dataTransfer.files); };

$('schedApply').onclick = () => {
  const targets = items.filter(it => !it.jobId);
  if (!targets.length) { clientLog('add beats first, then apply the schedule'); return; }
  const start = $('schedStart').value;
  if (!start) {
    targets.forEach(it => { it.publishAt = ''; });
    clientLog('schedule cleared — beats publish as soon as they upload');
  } else {
    const every = Math.max(0, Math.round(+$('schedEvery').value || 0));
    targets.forEach((it, k) => {
      const d = new Date(start);
      d.setDate(d.getDate() + k * every);    // calendar days: keeps the hour across DST
      it.publishAt = toLocalInput(d);
    });
    clientLog(`scheduled ${targets.length} beat(s) from ${fmtWhen(start)}, every ${every} day(s)`);
  }
  render();
};

startBtn.onclick = async () => {
  const pending = items.filter(it => !it.jobId);
  if (!pending.length) {
    clientLog('nothing to start — drop some beats in first');
    drop.classList.add('over'); setTimeout(() => drop.classList.remove('over'), 600);
    return;
  }
  const skip = $('skip').checked;
  const defLink = $('defBeatstars').value.trim();
  const bsUp = $('bsUpload').checked && !skip;
  const problems = [];
  for (const it of pending) {
    const link = it.beatstars || defLink;
    if (link && !URL_RE.test(link)) problems.push(`"${it.title}": BeatStars link isn't a URL`);
    if (!skip && it.publishAt && new Date(it.publishAt) <= new Date())
      problems.push(`"${it.title}": publish time is in the past`);
  }
  if (problems.length) { problems.forEach(p => clientLog('fix first — ' + p)); return; }

  startBtn.disabled = true;
  try {
    for (const it of pending) {
      const qs = new URLSearchParams({
        filename: it.name,
        title: it.title,
        bpm: it.bpm || '',
        producer: it.producer || '',
        tags: $('tags').value,
        beatstars: it.beatstars || (bsUp ? '' : defLink),
        bs: bsUp ? '1' : '',
        privacy: $('privacy').value,
        publish_at: !skip && it.publishAt ? new Date(it.publishAt).toISOString() : '',
        scheme: $('scheme').value,
        skip: skip ? '1' : '',
        del: $('deleteRender').checked ? '1' : '',
      });
      it.status = 'sending'; render();
      try {
        const resp = await fetch('/api/submit?' + qs, { method: 'POST', body: it.file });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok) throw new Error(data.error || 'server said ' + resp.status);
        it.jobId = data.id;
        it.status = 'queued';
      } catch (e) {
        it.status = 'error: ' + e.message;
        clientLog('submit failed for "' + it.title + '": ' + e.message);
      }
      render();
    }
    if (pending.some(it => it.jobId))
      clientLog('queued — you can close this tab; processing continues in the background');
  } finally {
    startBtn.disabled = false;
  }
};

async function retry(it) {
  const resp = await fetch('/api/retry?id=' + it.jobId, { method: 'POST' }).catch(() => null);
  if (resp && resp.ok) { it.status = 'queued'; render(); }
  else clientLog('retry failed for "' + it.title + '"');
}

$('bsConnect').onclick = async e => {
  e.preventDefault();
  await fetch('/api/beatstars/login', { method: 'POST' }).catch(() => {});
  clientLog('opening Chrome — log in to BeatStars there; the window closes itself once connected');
};

$('clearDone').onclick = async () => {
  await fetch('/api/clear', { method: 'POST' }).catch(() => {});
  for (let i = items.length - 1; i >= 0; i--)
    if (items[i].jobId && (items[i].orphan || !isActive(items[i].status))) items.splice(i, 1);
  render();
};

let pollTimer = null;
$('quit').onclick = async e => {
  e.preventDefault();
  const n = items.filter(it => it.jobId && !it.orphan && isActive(it.status)).length;
  if (n && !confirm(`${n} beat(s) still processing. Quitting cancels ${n > 1 ? 'them' : 'it'}. Quit anyway?`)) return;
  clearInterval(pollTimer);
  await fetch('/api/quit', { method: 'POST' }).catch(() => {});
  document.body.innerHTML = '<p style="text-align:center;margin-top:40vh;color:#8b94a7">Beat Uploader closed — you can close this tab.</p>';
};

// Tell the server this tab is gone, so it can quit once the queue is empty
addEventListener('pagehide', () => { try { navigator.sendBeacon('/api/bye'); } catch (e) {} });

let serverLost = false, instance = null;
async function poll() {
  let data;
  try {
    data = await (await fetch('/api/jobs')).json();
  } catch (e) {
    if (!serverLost) {
      serverLost = true;
      clientLog('lost connection to the local server — relaunch Beat Uploader, then reload this page');
    }
    return;
  }
  if (serverLost) { serverLost = false; clientLog('server reconnected'); }

  let rebuild = false;
  if (instance !== data.instance) {
    if (instance !== null) {
      // The app restarted: its job ids now mean different beats.
      for (let i = items.length - 1; i >= 0; i--) {
        const it = items[i];
        if (!it.jobId || it.orphan) continue;
        if (it.status === 'done') it.orphan = true;
        else if (it.file) { it.jobId = null; it.status = 'ready'; }
        else items.splice(i, 1);
      }
      clientLog('app restarted — unfinished beats are back to "ready"; press Start to resend them');
      rebuild = true;
    }
    instance = data.instance;
  }
  for (const [id, j] of Object.entries(data.jobs)) {
    const jid = +id;
    const it = items.find(x => x.jobId === jid && !x.orphan);
    if (!it) { items.push(itemFromServer(jid, j)); rebuild = true; continue; }  // e.g. after a reload
    if (j.status !== it.status || j.url !== it.url) {
      const retryBefore = canRetry(it);
      it.status = j.status; it.url = j.url;
      if (canRetry(it) !== retryBefore || !isActive(it.status)) rebuild = true;
      else refreshStatus(it);
    }
  }
  if (rebuild) render();
  serverLog = data.log;
  updateLog();
}
poll();
pollTimer = setInterval(poll, 1000);
</script>
</body></html>
""".replace("__SCHEMES__", SCHEME_OPTIONS)


def _open_browser(url):
    """Open *url* in the default browser.

    Python's webbrowser module shells out to osascript on macOS, which can
    silently do nothing when we're launched from the .app bundle's shell
    context — /usr/bin/open works from anywhere."""
    if sys.platform == "darwin":
        subprocess.Popen(["/usr/bin/open", url])
    else:
        webbrowser.open(url)


def main():
    global UPLOAD_DIR, _server
    ap = argparse.ArgumentParser(description="Beat Uploader web GUI")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    args = ap.parse_args()

    if sys.platform == "darwin":
        # The YouTube sign-in flow uses webbrowser too — route it through
        # /usr/bin/open for the same reason as _open_browser.
        webbrowser.register("macos-open", None,
                            webbrowser.GenericBrowser(["/usr/bin/open", "%s"]), preferred=True)

    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError:
        # Port busy. If it's another instance of us, just open its page;
        # otherwise fall back to a random free port.
        import urllib.request
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{args.port}/api/busy", timeout=1)
            print(f"Already running — opening http://127.0.0.1:{args.port}", flush=True)
            if not args.no_browser:
                _open_browser(f"http://127.0.0.1:{args.port}")
            return
        except Exception:
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    _server = server
    port = server.server_address[1]
    UPLOAD_DIR = tempfile.mkdtemp(prefix="beat-uploader-")

    # Dock quit / `kill` / closing the Terminal window → same clean shutdown
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda signum, frame: _request_shutdown(signal.Signals(signum).name))

    worker = threading.Thread(target=_worker, daemon=True)
    worker.start()
    threading.Thread(target=_watchdog, daemon=True).start()

    url = f"http://127.0.0.1:{port}"
    print(f"Beat Uploader GUI: {url}  (Ctrl-C or the page's quit link to stop)", flush=True)
    if not args.no_browser:
        threading.Timer(0.5, lambda: _open_browser(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _stop.set()
    finally:
        # Let a cancelled render/upload finish cleaning up (kills ffmpeg and
        # the render pool, deletes the partial mp4) before the process exits.
        worker.join(WORKER_JOIN_TIMEOUT)
        server.server_close()
        shutil.rmtree(UPLOAD_DIR, ignore_errors=True)
        print("Beat Uploader stopped", flush=True)


if __name__ == "__main__":
    main()

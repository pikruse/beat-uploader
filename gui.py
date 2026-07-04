# gui.py
"""Local web GUI for the beat upload pipeline.

Usage:
    python gui.py            # opens http://127.0.0.1:8765 in your browser

Drag & drop beats onto the page, edit each beat's title, set shared options,
hit Start. Beats are processed one at a time: render → YouTube upload.

Stdlib only — no extra GUI dependencies. The server binds to localhost.
"""

import itertools
import json
import os
import queue
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from src.config import COLOR_SCHEMES

PORT = 8765
UPLOAD_DIR = tempfile.mkdtemp(prefix="beat-uploader-")

_jobs = {}                # id -> {'title','file','status','url'}
_log_lines = []
_lock = threading.Lock()
_job_queue = queue.Queue()
_job_ids = itertools.count(1)


# ── Pipeline worker (one job at a time) ──────────────────────

def _log(msg):
    with _lock:
        _log_lines.append(str(msg))
        del _log_lines[:-500]


def _set_status(job_id, status):
    with _lock:
        _jobs[job_id]["status"] = status


def _worker():
    from src.pipeline import run_pipeline  # heavy import, deferred

    while True:
        job_id = _job_queue.get()
        with _lock:
            job = dict(_jobs[job_id])
        _set_status(job_id, "analyzing")
        try:
            result = run_pipeline(
                audio=job["path"],
                title=job["title"],
                bpm=job["bpm"],
                producer=job["producer"],
                tags=job["tags"],
                beatstars_url=job["beatstars_url"] or None,
                scheme=job["scheme"] or None,
                privacy=job["privacy"],
                skip_youtube=job["skip_youtube"],
                log=_log,
                progress=lambda f: _set_status(job_id, f"rendering {int(f * 100)}%"),
            )
            with _lock:
                _jobs[job_id]["status"] = "done"
                _jobs[job_id]["url"] = result["url"] or result["output"]
        except Exception as e:
            _set_status(job_id, f"error: {e}")
            _log(f"ERROR ({job['title']}): {e}")


# ── HTTP handler ─────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence per-request stderr noise
        pass

    def _send(self, body, ctype="text/html; charset=utf-8", code=200):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self._send(PAGE)
        elif path == "/api/jobs":
            with _lock:
                snapshot = {
                    "jobs": {jid: {"status": j["status"], "url": j["url"]}
                             for jid, j in _jobs.items()},
                    "log": list(_log_lines[-200:]),
                }
            self._send(json.dumps(snapshot), "application/json")
        else:
            self._send("not found", code=404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/quit":
            self._send(json.dumps({"ok": True}), "application/json")
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if parsed.path != "/api/submit":
            self._send("not found", code=404)
            return
        q = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        size = int(self.headers.get("Content-Length", 0))
        audio_bytes = self.rfile.read(size)

        job_id = next(_job_ids)
        filename = os.path.basename(q.get("filename", "beat.mp3"))
        audio_path = os.path.join(UPLOAD_DIR, f"{job_id}_{filename}")
        with open(audio_path, "wb") as f:
            f.write(audio_bytes)

        title = q.get("title", "").strip() or os.path.splitext(filename)[0]
        scheme = q.get("scheme", "")
        job = {
            "path": audio_path,
            "title": title,
            "bpm": q.get("bpm", "").strip() or None,
            "producer": q.get("producer", "").strip() or "pk",
            "tags": [t.strip() for t in q.get("tags", "").split(",") if t.strip()],
            "beatstars_url": q.get("beatstars", "").strip(),
            "privacy": q.get("privacy", "public"),
            "scheme": scheme if scheme in COLOR_SCHEMES else None,
            "skip_youtube": q.get("skip") == "1",
            "status": "queued",
            "url": None,
        }
        with _lock:
            _jobs[job_id] = job
        _job_queue.put(job_id)
        _log(f"Queued: {title} ({filename})")
        self._send(json.dumps({"id": job_id}), "application/json")


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
    --ok: #4ade80; --err: #f87171;
  }
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, "SF Pro Text", "Segoe UI", sans-serif;
    background:
      radial-gradient(900px 400px at 80% -10%, rgba(124,92,255,.14), transparent),
      radial-gradient(700px 300px at 10% -10%, rgba(79,156,255,.10), transparent),
      var(--bg);
    color: var(--text); max-width: 900px; margin: 0 auto; padding: 32px 20px 60px;
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

  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; color: var(--dim); font-size: 10px; letter-spacing: 1.5px;
       text-transform: uppercase; padding: 10px 14px 6px; }
  td { padding: 8px 14px; border-top: 1px solid var(--border); font-size: 14px;
       vertical-align: middle; }
  td.file { color: var(--dim); font: 12px ui-monospace, monospace; max-width: 190px;
            overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  tr.previewRow td { border-top: 0; padding: 0 14px 10px;
                     font: 11px ui-monospace, "SF Mono", monospace; color: #66708a;
                     overflow-wrap: anywhere; }
  tr.previewRow td b { color: #8b94a7; font-weight: 600; }
  td input {
    width: 100%; background: transparent; color: var(--text); font-size: 14px;
    border: 0; border-bottom: 1px solid transparent; padding: 4px 2px; outline: 0;
  }
  td input:hover:not(:disabled) { border-bottom-color: var(--border); }
  td input:focus { border-bottom-color: var(--acc1); }
  td input:disabled { color: var(--dim); }

  .pill { display: inline-block; font-size: 11px; font-weight: 600; padding: 3px 10px;
          border-radius: 99px; letter-spacing: .5px; }
  .pill.queued  { background: #262c39; color: var(--dim); }
  .pill.busy    { background: rgba(79,156,255,.15); color: var(--acc2); }
  .pill.done    { background: rgba(74,222,128,.14); color: var(--ok); }
  .pill.error   { background: rgba(248,113,113,.14); color: var(--err); }
  .bar { width: 130px; height: 6px; background: #262c39; border-radius: 99px;
         overflow: hidden; display: inline-block; vertical-align: middle; margin-right: 8px; }
  .bar > div { height: 100%; background: var(--grad); border-radius: 99px;
               transition: width .4s ease; }
  .pct { font-size: 11px; color: var(--acc2); font-weight: 600; }
  td .x { background: none; border: 0; color: var(--dim); cursor: pointer;
          font-size: 14px; padding: 2px 6px; border-radius: 6px; }
  td .x:hover { color: var(--err); background: rgba(248,113,113,.1); }

  .opts { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; padding: 16px; }
  .opts label { display: block; font-size: 10px; letter-spacing: 1.5px;
                text-transform: uppercase; color: var(--dim); margin-bottom: 5px; }
  .opts input, .opts select {
    width: 100%; background: var(--card2); color: var(--text); font-size: 13px;
    border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; outline: 0;
    transition: border-color .15s;
  }
  .opts input:focus, .opts select:focus { border-color: var(--acc1); }
  .opts .check { display: flex; align-items: center; gap: 8px; padding-top: 18px; }
  .opts .check input { width: auto; accent-color: var(--acc1); }
  .opts .check label { margin: 0; text-transform: none; font-size: 13px;
                       letter-spacing: 0; color: var(--text); }

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
<table id="queue">
  <thead><tr><th>File</th><th>Beat title</th><th style="width:64px">BPM</th>
    <th style="width:110px">Producer</th><th style="width:180px">Status</th><th></th></tr></thead>
  <tbody></tbody>
</table>
</div>

<div class="card"><div class="opts">
  <div><label>Producer</label><input id="producer" value="pk"></div>
  <div><label>Tags</label><input id="tags" placeholder="trap, dark, ambient"></div>
  <div><label>Privacy</label><select id="privacy">
    <option>public</option><option>unlisted</option><option>private</option></select></div>
  <div><label>BeatStars URL</label><input id="beatstars" placeholder="https://beatstars.com/..."></div>
  <div><label>Color scheme</label><select id="scheme"><option value="">Random</option>__SCHEMES__</select></div>
  <div class="check"><input type="checkbox" id="skip"><label for="skip">Render only (skip YouTube)</label></div>
</div></div>

<button id="start">▶&nbsp;&nbsp;START</button>
<pre id="log">waiting…</pre>
<footer>local server 127.0.0.1 · <a href="#" id="quit">quit app</a></footer>

<script>
const items = [];
const drop = document.getElementById('drop');
const fileInput = document.getElementById('file');
const queueCard = document.getElementById('queueCard');
const tbody = document.querySelector('#queue tbody');
const startBtn = document.getElementById('start');
const logBox = document.getElementById('log');
const AUDIO_RE = /\.(mp3|wav|flac|aiff?|m4a|ogg)$/i;

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

function addFiles(files) {
  const rejected = [];
  for (const f of files) {
    if (!AUDIO_RE.test(f.name)) { rejected.push(f.name); continue; }
    if (items.some(it => it.file.name === f.name && !it.jobId)) continue;
    const parsed = parseBeatFilename(f.name);
    items.push({
      file: f,
      title: parsed.title, bpm: parsed.bpm, producer: parsed.producer,
      jobId: null, status: 'queued', url: null,
    });
  }
  if (rejected.length) clientLog('ignored (not an audio file): ' + rejected.join(', '));
  render();
}

function statusCell(it) {
  const td = document.createElement('td');
  const m = it.status.match(/rendering (\d+)%/);
  if (it.url && /^http/.test(it.url)) {
    const a = document.createElement('a');
    a.href = it.url; a.target = '_blank'; a.textContent = it.url.replace(/^https?:\/\//, '');
    td.appendChild(a);
  } else if (m) {
    const bar = document.createElement('span'); bar.className = 'bar';
    const fill = document.createElement('div'); fill.style.width = m[1] + '%';
    bar.appendChild(fill);
    const pct = document.createElement('span'); pct.className = 'pct';
    pct.textContent = m[1] + '%';
    td.append(bar, pct);
  } else {
    const pill = document.createElement('span');
    const cls = it.status === 'done' ? 'done'
              : it.status.startsWith('error') ? 'error'
              : it.status === 'queued' ? 'queued' : 'busy';
    pill.className = 'pill ' + cls;
    pill.textContent = it.status === 'done' && it.url ? '✓ ' + it.url : it.status;
    td.appendChild(pill);
  }
  return td;
}

function previewFor(it) {
  return formatYtTitle(
    it.title, it.bpm,
    it.producer || document.getElementById('producer').value,
    document.getElementById('tags').value);
}

function render() {
  queueCard.hidden = items.length === 0;
  tbody.innerHTML = '';
  items.forEach((it, i) => {
    const tr = document.createElement('tr');
    const locked = !!it.jobId;

    const mkInput = (value, placeholder, onChange) => {
      const td = document.createElement('td');
      const inp = document.createElement('input');
      inp.value = value || '';
      inp.placeholder = placeholder;
      inp.disabled = locked;
      inp.oninput = () => { onChange(inp.value); it.updatePreview(); };
      td.appendChild(inp);
      return td;
    };

    const tdFile = document.createElement('td');
    tdFile.className = 'file';
    tdFile.textContent = it.file.name;
    tdFile.title = it.file.name;

    const tdTitle = mkInput(it.title, 'Beat name…', v => { it.title = v; });
    const tdBpm = mkInput(it.bpm, 'auto', v => { it.bpm = v; });
    const tdProd = mkInput(it.producer,
      document.getElementById('producer').value || 'pk', v => { it.producer = v; });

    const tdDel = document.createElement('td');
    if (!locked) {
      const b = document.createElement('button');
      b.className = 'x'; b.textContent = '✕';
      b.onclick = () => { items.splice(i, 1); render(); };
      tdDel.appendChild(b);
    }
    it.statusTd = statusCell(it);
    tr.append(tdFile, tdTitle, tdBpm, tdProd, it.statusTd, tdDel);

    // Live YouTube-title preview under the row
    const trPrev = document.createElement('tr');
    trPrev.className = 'previewRow';
    const tdPrev = document.createElement('td');
    tdPrev.colSpan = 6;
    trPrev.appendChild(tdPrev);
    it.updatePreview = () => {
      tdPrev.innerHTML = '';
      const label = document.createElement('b');
      label.textContent = 'YT title → ';
      tdPrev.append(label, previewFor(it));
    };
    it.updatePreview();

    tbody.append(tr, trPrev);
  });
}

// Shared fields feed the previews too
['producer', 'tags'].forEach(id =>
  document.getElementById(id).addEventListener('input',
    () => items.forEach(it => it.updatePreview && it.updatePreview())));

// Swap only the status cell so polling never steals focus from a title input
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

startBtn.onclick = async () => {
  const pending = items.filter(it => !it.jobId);
  if (!pending.length) {
    clientLog('nothing to start — drop some beats in first');
    drop.classList.add('over'); setTimeout(() => drop.classList.remove('over'), 600);
    return;
  }
  startBtn.disabled = true;
  try {
    for (const it of pending) {
      const qs = new URLSearchParams({
        filename: it.file.name,
        title: it.title,
        bpm: it.bpm || '',
        producer: it.producer || document.getElementById('producer').value,
        tags: document.getElementById('tags').value,
        beatstars: document.getElementById('beatstars').value,
        privacy: document.getElementById('privacy').value,
        scheme: document.getElementById('scheme').value,
        skip: document.getElementById('skip').checked ? '1' : '',
      });
      it.status = 'sending'; render();
      try {
        const resp = await fetch('/api/submit?' + qs, { method: 'POST', body: it.file });
        if (!resp.ok) throw new Error('server said ' + resp.status);
        it.jobId = (await resp.json()).id;
        it.status = 'queued';
      } catch (e) {
        it.status = 'error: ' + e.message;
        clientLog('submit failed for "' + it.title + '": ' + e.message
                  + ' — is the server still running? Relaunch the app and reload this page.');
      }
      render();
    }
  } finally {
    startBtn.disabled = false;
  }
};

document.getElementById('quit').onclick = async e => {
  e.preventDefault();
  await fetch('/api/quit', { method: 'POST' }).catch(() => {});
  document.body.innerHTML = '<p style="text-align:center;margin-top:40vh;color:#8b94a7">Beat Uploader closed — you can close this tab.</p>';
};

let serverLost = false;
setInterval(async () => {
  try {
    const data = await (await fetch('/api/jobs')).json();
    if (serverLost) { serverLost = false; clientLog('server reconnected'); }
    for (const it of items) {
      const j = it.jobId && data.jobs[it.jobId];
      if (j && (j.status !== it.status || j.url !== it.url)) {
        it.status = j.status; it.url = j.url;
        refreshStatus(it);
      }
    }
    serverLog = data.log;
    updateLog();
  } catch (e) {
    if (!serverLost) {
      serverLost = true;
      clientLog('lost connection to the local server — relaunch Beat Uploader, then reload this page');
    }
  }
}, 1000);
</script>
</body></html>
""".replace("__SCHEMES__", SCHEME_OPTIONS)


def main():
    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
        port = PORT
    except OSError:
        # Port busy. If it's another instance of us, just open its page;
        # otherwise fall back to a random free port.
        import urllib.request
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/jobs", timeout=1)
            print(f"Already running — opening http://127.0.0.1:{PORT}")
            webbrowser.open(f"http://127.0.0.1:{PORT}")
            return
        except Exception:
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            port = server.server_address[1]

    threading.Thread(target=_worker, daemon=True).start()
    url = f"http://127.0.0.1:{port}"
    print(f"Beat Uploader GUI: {url}  (Ctrl-C or the page's quit link to stop)")
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

# beatstars_uploader.py
"""Publish a beat to BeatStars by driving BeatStars Studio in Chrome.

BeatStars has no public upload API, so this automates the same clicks you'd
make in studio.beatstars.com, using a dedicated Chrome profile that stays
logged in (auth/beatstars-profile — git-ignored with the rest of auth/).

First run / when the login expires:
    python beatstars_uploader.py --login        # log in once in the window

Manual upload:
    python beatstars_uploader.py --upload "NightDrive.mp3" --title NightDrive --bpm 140 --key Am

What it fills: the master mp3, title, BPM, key and visibility. Everything
else (genres, moods, instruments, tags, license prices) is left to
BeatStars' own autofill and your account defaults, same as uploading by hand.

This depends on BeatStars' page layout, so a redesign on their side can break
it — failures save a screenshot to ~/Library/Logs/ for debugging.
"""

import json
import os
import re
import subprocess
import tempfile
import threading
import time

PROFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auth", "beatstars-profile")
# Studio's login lives in a *session* cookie that Chrome drops on close, so we
# save the cookies ourselves after login / each upload and restore them.
STATE = os.path.join(os.path.dirname(PROFILE), "beatstars-cookies.json")
STUDIO = "https://studio.beatstars.com"
TRACKS = f"{STUDIO}/content/tracks/uploaded"
LOG_DIR = os.path.expanduser("~/Library/Logs")

# One Chrome per profile at a time (the GUI's login button vs. the worker)
_profile_lock = threading.Lock()


class BeatStarsError(Exception):
    pass


class BeatStarsLoginRequired(BeatStarsError):
    pass


class BeatStarsCancelled(BeatStarsError):
    pass


# ── Audio prep ───────────────────────────────────────────────

def _ffmpeg():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _probe_audio(path):
    """(codec, sample_rate, kbps) of the first audio stream, best effort."""
    out = subprocess.run([_ffmpeg(), "-hide_banner", "-i", path],
                         capture_output=True, text=True).stderr
    m = re.search(r"Audio: (\w+).*?(\d+) Hz.*?(\d+) kb/s", out)
    if not m:
        return None, None, None
    return m.group(1), int(m.group(2)), int(m.group(3))


def prepare_mp3(path, title, log=print):
    """BeatStars only accepts 320 kbps / 44.1 kHz mp3 (or wav). Returns a path
    that qualifies, transcoding into a temp file when needed. The temp file is
    named after the title because BeatStars pre-fills the title from it."""
    codec, rate, kbps = _probe_audio(path)
    if codec == "mp3" and rate == 44100 and kbps and kbps >= 320:
        return path, None
    log(f"  BeatStars needs 320 kbps mp3 — converting ({codec}, {rate} Hz, {kbps} kb/s)")
    tmpdir = tempfile.mkdtemp(prefix="bs-upload-")
    safe = re.sub(r"[^\w\- ]+", "", title).strip() or "beat"
    out = os.path.join(tmpdir, f"{safe}.mp3")
    subprocess.run([_ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", "-i", path,
                    "-vn", "-ar", "44100", "-ac", "2", "-b:a", "320k", out], check=True)
    return out, tmpdir


# ── Key mapping ──────────────────────────────────────────────

_NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_FLAT_OF = {"C#": "D", "D#": "E", "F#": "G", "G#": "A", "A#": "B"}
_NAME = {"C": "C", "D": "D", "E": "E", "F": "F", "G": "G", "A": "A", "B": "B"}


def key_option_values(key):
    """"C#m" → ["C_SHARP_MINOR", "D_FLAT_MINOR"] (BeatStars' <select> values;
    it only lists one spelling for some keys, so try both)."""
    m = re.fullmatch(r"\s*([A-Ga-g])([#♯b♭]?)\s*(m|min|minor|maj|major|M)?\s*", key or "")
    if not m:
        return []
    letter, acc, mode = m.group(1).upper(), m.group(2), m.group(3) or ""
    mode = "MINOR" if mode in ("m", "min", "minor") else "MAJOR"
    if acc in ("#", "♯"):
        sharp = letter + "#"
        out = [f"{letter}_SHARP_{mode}"]
        if sharp in _FLAT_OF:
            out.append(f"{_FLAT_OF[sharp]}_FLAT_{mode}")
        return out
    if acc in ("b", "♭"):
        out = [f"{letter}_FLAT_{mode}"]
        idx = (_NOTES.index(letter) - 1) % 12
        if "#" in _NOTES[idx]:
            out.append(f"{_NOTES[idx][0]}_SHARP_{mode}")
        return out
    return [f"{letter}_{mode}"]


# ── Browser helpers ──────────────────────────────────────────

def _launch(p, headless):
    os.makedirs(PROFILE, exist_ok=True)
    ctx = p.chromium.launch_persistent_context(
        PROFILE, channel="chrome", headless=headless,
        viewport={"width": 1400, "height": 950})
    try:
        with open(STATE) as f:
            ctx.add_cookies(json.load(f))
    except (OSError, ValueError):
        pass
    return ctx


def _save_cookies(ctx):
    cookies = [c for c in ctx.cookies() if "beatstars" in c["domain"]]
    fd = os.open(STATE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(cookies, f)


def _logged_in(page):
    return page.url.startswith(STUDIO) and "oauth" not in page.url and "login" not in page.url


def _close_popups(page):
    """Dismiss BeatStars' "what's new" carousel and similar dialogs."""
    for _ in range(3):
        overlay = page.locator(".cdk-overlay-container")
        text = overlay.inner_text() if overlay.count() else ""
        if not text or "Upload" in text and "Drop files" in text:
            return
        close_icon = page.locator(".cdk-overlay-container button:has(i[class*='icon-close'])")
        if close_icon.count():
            close_icon.first.click()
        elif page.locator(".cdk-overlay-backdrop").count():
            page.keyboard.press("Escape")
        else:
            return
        page.wait_for_timeout(800)


def _screenshot(page, tag):
    try:
        path = os.path.join(LOG_DIR, f"BeatUploader-beatstars-{tag}-{time.strftime('%Y%m%d-%H%M%S')}.png")
        page.screenshot(path=path)
        return path
    except Exception:
        return None


_GENRE_COUNT_JS = """() => {
  const lab = Array.from(document.querySelectorAll('label')).find(l => l.innerText.trim() === 'Genres');
  if (!lab) return -1;
  let box = lab;
  for (let i = 0; i < 4 && box && !box.querySelector('mat-chip-grid'); i++) box = box.parentElement;
  const grid = box && box.querySelector('mat-chip-grid');
  return grid ? grid.querySelectorAll('mat-chip-row, mat-chip').length : -1;
}"""


def _check_rejected(page):
    body = page.locator("body").inner_text()
    if "not compatible" in body:
        m = re.search(r"[^\n]*not compatible[^\n]*", body)
        raise BeatStarsError(m.group(0).strip() if m else "BeatStars rejected the audio file")
    return body


def _wait_processing(page, timeout_s=180, want_genre=False):
    """Wait for BeatStars' upload processing + metadata autofill to settle:
    no "Processing metadata"/"Uploading" for 3 checks in a row (and, if
    want_genre, a genre filled in). Returns True if it settled."""
    page.wait_for_timeout(2500)
    deadline = time.time() + timeout_s
    calm = 0
    while time.time() < deadline:
        body = _check_rejected(page)
        busy = "Processing metadata" in body or "Uploading" in body
        calm = 0 if busy else calm + 1
        if calm >= 3 and (not want_genre or page.evaluate(_GENRE_COUNT_JS) != 0):
            return True
        page.wait_for_timeout(1000)
    if want_genre:
        return False          # caller falls back to picking a genre itself
    raise BeatStarsError("BeatStars took too long to process the upload")


def _add_genre(page, genre):
    inp = page.locator("input[placeholder*='add genre']").first
    inp.click()
    inp.type(genre, delay=40)
    page.wait_for_timeout(1200)
    opt = page.locator(f".cdk-overlay-container [role=option]:has-text('{genre}')")
    if opt.count():
        opt.first.click()
    else:
        page.keyboard.press("Enter")
    page.wait_for_timeout(800)
    if page.evaluate(_GENRE_COUNT_JS) == 0:
        raise BeatStarsError(f"couldn't set the genre '{genre}'")


def _delete_track(page, track_num, log=print):
    """Delete a track (used to clean up a half-created draft after a failure)."""
    page.goto(TRACKS, wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    _close_popups(page)
    card = page.locator(f".media-card:has(a[href*='TK{track_num}'])").first
    if not card.count():
        return False
    card.locator("button").last.click()
    page.wait_for_timeout(1000)
    page.locator(".cdk-overlay-container button:has-text('Delete')").first.click()
    page.wait_for_timeout(1200)
    # Confirm dialog: the last button whose text is exactly "Delete"
    clicked = page.evaluate("""() => {
      const bs = Array.from(document.querySelectorAll('.cdk-overlay-container button'))
        .filter(b => b.innerText.trim() === 'Delete');
      if (!bs.length) return false;
      bs[bs.length - 1].click();
      return true;
    }""")
    if not clicked:
        raise BeatStarsError(f"delete confirm button not found for TK{track_num}")
    page.wait_for_timeout(3000)
    log(f"  BeatStars: deleted track TK{track_num}")
    return True


def _master_needs_file(page):
    row = page.locator("text=Master Track (Untagged)").locator("xpath=ancestor::*[.//button][1]")
    return row.locator("button:has-text('Add')").count() > 0, row


# ── Public API ───────────────────────────────────────────────

def login(log=print, timeout_s=1200):
    """Open a visible Chrome on BeatStars Studio's login and wait for you."""
    from playwright.sync_api import sync_playwright
    with _profile_lock, sync_playwright() as p:
        ctx = _launch(p, headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(TRACKS)        # not logged in → Studio redirects to its login
        page.wait_for_timeout(4000)
        if _logged_in(page):
            _save_cookies(ctx)
            log("  BeatStars already connected")
            ctx.close()
            return True
        log("  Log in to BeatStars in the Chrome window that just opened…")
        deadline = time.time() + timeout_s
        nudged = 0.0
        try:
            while time.time() < deadline:
                if not ctx.pages:
                    raise BeatStarsLoginRequired("login window was closed")
                # Must wait via Playwright (not time.sleep) so it keeps
                # processing browser events — otherwise page.url goes stale.
                ctx.pages[-1].wait_for_timeout(2000)
                if not ctx.pages:
                    raise BeatStarsLoginRequired("login window was closed")
                page = ctx.pages[-1]
                if _logged_in(page):
                    page.wait_for_timeout(2000)
                    _save_cookies(ctx)
                    log("  BeatStars connected")
                    return True
                # Landed on www.beatstars.com instead of Studio: hop over
                # (Studio picks the fresh login up via its oauth redirect).
                if "beatstars.com" in page.url and "oauth" not in page.url \
                        and time.time() - nudged > 15:
                    nudged = time.time()
                    page.goto(TRACKS)
            raise BeatStarsLoginRequired("timed out waiting for the BeatStars login")
        finally:
            ctx.close()


def upload_track(audio_path, title, bpm=None, key=None, visibility="public",
                 genre="Hip Hop", headless=False, log=print, should_stop=None):
    """Create and publish a BeatStars track. Returns its share link
    (https://bsta.rs/…, or the full beatstars.com/beat/… URL as a fallback).

    headless=False by default: BeatStars Studio refuses logins from headless
    Chrome, so a Chrome window shows while it uploads (~1 min per beat).
    genre: used only if BeatStars' autofill leaves Genres empty (required).
    """
    from playwright.sync_api import sync_playwright

    def check_stop():
        if should_stop and should_stop():
            raise BeatStarsCancelled("BeatStars upload cancelled")

    visibility = {"public": "PUBLIC", "unlisted": "UNLISTED", "private": "PRIVATE"}.get(
        visibility, "PUBLIC")
    upload_path, tmpdir = prepare_mp3(audio_path, title, log=log)
    log(f"  BeatStars: uploading {title}")
    try:
        with _profile_lock, sync_playwright() as p:
            ctx = _launch(p, headless=headless)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.set_default_timeout(30000)
            track_num = None
            published = False
            try:
                page.goto(TRACKS, wait_until="domcontentloaded")
                page.wait_for_timeout(4000)
                if not _logged_in(page):
                    raise BeatStarsLoginRequired(
                        "BeatStars login needed — click 'Connect BeatStars' in Beat Uploader "
                        "(or run: python beatstars_uploader.py --login)")
                _close_popups(page)
                check_stop()

                # Create Track → upload box. Picking the file creates the track.
                page.locator("button:has-text('Create Track')").first.click()
                page.wait_for_timeout(1500)
                _close_popups(page)
                page.locator(".cdk-overlay-container input.uppy-Dashboard-input").first \
                    .set_input_files(upload_path)
                page.wait_for_url(re.compile(r"/content/tracks/(new|edit)/TK\d+"), timeout=120000)
                track_num = re.search(r"TK(\d+)", page.url).group(1)
                log(f"  BeatStars: track TK{track_num} created, processing audio…")
                _wait_processing(page)

                # If the first drop didn't land in the Master slot, add it there.
                needs, row = _master_needs_file(page)
                if needs:
                    row.locator("button:has-text('Add')").first.click()
                    page.wait_for_timeout(1500)
                    page.locator(".cdk-overlay-container input.uppy-Dashboard-input").first \
                        .set_input_files(upload_path)
                    _wait_processing(page)
                    if _master_needs_file(page)[0]:
                        raise BeatStarsError("master mp3 didn't attach")
                check_stop()
                if not _wait_processing(page, timeout_s=90, want_genre=True):
                    log(f"  BeatStars: autofill left Genres empty — using '{genre}'")
                    _add_genre(page, genre)
                check_stop()

                # Our fields (BeatStars autofills genre/moods/tags/prices)
                page.fill("#title", title[:60])
                if bpm:
                    num = re.sub(r"[^\d.]", "", str(bpm))
                    if num:
                        page.fill("input[type=number]", str(int(round(float(num)))))
                if key:
                    sel = page.locator("select:has(option[value='A_MINOR'])").first
                    values = sel.locator("option").evaluate_all("os => os.map(o => o.value)")
                    for v in key_option_values(key):
                        if v in values:
                            sel.select_option(v)
                            break
                page.locator("select:has(option[value='PRIVATE'])").first.select_option(visibility)
                check_stop()

                # The master can still be finishing server-side ("main audio
                # file is missing") — wait and retry the publish a few times.
                link = page.locator(".cdk-overlay-container input[value^='https://bsta.rs']")
                url = None
                for attempt in range(8):
                    check_stop()
                    page.locator("button:has-text('Publish track')").first.click()
                    try:
                        link.first.wait_for(timeout=10000)
                        url = link.first.get_attribute("value")
                        break
                    except Exception:
                        body = page.locator("body").inner_text()
                        if "audio file is missing" in body or "still processing" in body.lower():
                            ok_btn = page.locator("button:has-text('OK')")
                            if ok_btn.count():
                                ok_btn.first.click()
                            log("  BeatStars: audio still processing, retrying publish…")
                            page.wait_for_timeout(5000)
                            continue
                        break
                try:
                    if not url:
                        raise BeatStarsError("no share link")
                except Exception:
                    body = page.locator("body").inner_text()
                    if "Share your" in body or page.url.endswith("/uploaded"):
                        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "beat"
                        url = f"https://www.beatstars.com/beat/{slug}-{track_num}"
                    else:
                        raise BeatStarsError("Publish didn't go through (a required field may be empty)")
                published = True
                log(f"  BeatStars: published {url}")
                _save_cookies(ctx)          # keep the session fresh
                return url
            except BeatStarsLoginRequired:
                raise
            except Exception as e:
                shot = None if isinstance(e, BeatStarsCancelled) else _screenshot(page, "error")
                if track_num and not published:
                    try:
                        _delete_track(page, track_num, log=log)
                    except Exception:
                        log(f"  BeatStars: couldn't delete draft TK{track_num} — remove it in Studio")
                if isinstance(e, BeatStarsCancelled):
                    raise
                if isinstance(e, BeatStarsError):
                    raise BeatStarsError(f"{e}" + (f" (screenshot: {shot})" if shot else "")) from e
                raise BeatStarsError(f"BeatStars automation failed: {e.__class__.__name__}: "
                                     f"{str(e).splitlines()[0][:200]}"
                                     + (f" (screenshot: {shot})" if shot else "")) from e
            finally:
                ctx.close()
    finally:
        if tmpdir:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--login", action="store_true", help="open Chrome and log in to BeatStars")
    ap.add_argument("--upload", metavar="AUDIO")
    ap.add_argument("--title")
    ap.add_argument("--bpm")
    ap.add_argument("--key")
    ap.add_argument("--visibility", default="public", choices=["public", "unlisted", "private"])
    ap.add_argument("--genre", default="Hip Hop", help="fallback genre if autofill leaves it empty")
    a = ap.parse_args()
    if a.login:
        login()
    elif a.upload:
        print(upload_track(a.upload, a.title or os.path.splitext(os.path.basename(a.upload))[0],
                           bpm=a.bpm, key=a.key, visibility=a.visibility, genre=a.genre))
    else:
        ap.print_help()

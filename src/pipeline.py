# src/pipeline.py
"""Shared beat-upload pipeline: analyze → render → upload.

Used by both the CLI (main.py) and the GUI (gui.py). The GUI calls
render_beat / upload_beat separately so a failed upload can be retried
without re-rendering.
"""

import os

from src.config import FPS, COLOR_SCHEMES, pick_random_scheme
from src.audio import AudioAnalyzer
from src.visualizer import create_icosphere
from src.render import render_video
from utils import generate_description, format_youtube_title, clean_producer
from youtube_uploader import upload_video


def _unique_path(path):
    """output/X.mp4 → output/X_2.mp4 if X.mp4 already exists."""
    if not os.path.exists(path):
        return path
    stem, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(f"{stem}_{n}{ext}"):
        n += 1
    return f"{stem}_{n}{ext}"


def render_beat(
    audio,
    title,
    producer="pk",
    bpm=None,
    key=None,
    scheme=None,
    duration=None,
    output=None,
    workers=None,
    log=print,
    progress=None,
    should_stop=None,
):
    """Analyze *audio* and render its visualizer video.

    Returns dict: {'output', 'producer', 'bpm', 'key', 'scheme'} — everything
    upload_beat needs, so an upload can be retried from it later.
    """
    # "prod pk" → "pk": the overlay/title/description templates add their own credit
    producer = clean_producer(producer)

    if output is None:
        os.makedirs("output", exist_ok=True)
        # Never overwrite another beat's render that shares the title
        output = _unique_path(f"output/{title.replace(' ', '_')}.mp4")
    else:
        out_dir = os.path.dirname(output)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

    # A bare number ("140", e.g. parsed from a filename) becomes "140 BPM"
    # so the video overlay and YouTube title read consistently.
    if bpm and str(bpm).strip().isdigit():
        bpm = f"{str(bpm).strip()} BPM"

    # ── Audio analysis ──
    log(f"Analyzing audio: {os.path.basename(audio)}")
    analyzer = AudioAnalyzer(audio, FPS, duration)
    bpm_text = bpm if bpm else f"{int(round(analyzer.bpm))} BPM"
    key_text = key if key else analyzer.key_label
    log(f"  {title} — prod {producer} | {bpm_text} | {key_text} | {analyzer.duration:.1f}s")

    # ── Render ──
    if scheme and scheme in COLOR_SCHEMES:
        cs_key, cs = scheme, COLOR_SCHEMES[scheme]
    else:
        cs_key, cs = pick_random_scheme()
    log(f"  Scheme: {cs['name']} ({cs_key})")

    verts, edges = create_icosphere(radius=1.0, subdivisions=2)
    meta = {"title": title, "producer": producer, "bpm": bpm_text, "key": key_text}
    render_video(analyzer, meta, verts, edges, cs, audio, output, FPS,
                 workers=workers, log=log, progress=progress, should_stop=should_stop)
    log(f"  Video saved: {output}")

    return {"output": output, "producer": producer,
            "bpm": bpm_text, "key": key_text, "scheme": cs_key}


def upload_beat(
    render,
    title,
    tags=None,
    beatstars_url=None,
    yt_title=None,
    privacy="public",
    publish_at=None,
    delete_after_upload=False,
    log=print,
    progress=None,
    should_stop=None,
):
    """Upload a render_beat() result to YouTube. Returns the video URL.

    yt_title:            override the generated YouTube title.
    publish_at:          RFC 3339 UTC string — schedule instead of publishing now.
    delete_after_upload: remove the local mp4 once YouTube has it.
    """
    tag_list = list(tags) if tags else []
    producer = render["producer"]
    # A hand-edited title wins; YouTube rejects < > and anything over 100 chars
    yt_title = (yt_title or "").replace("<", "").replace(">", "").strip()[:100] \
        or format_youtube_title(title, producer, render["bpm"], tags=tag_list)
    yt_description = generate_description(
        title=title, producer=producer, bpm=render["bpm"], key=render["key"],
        beatstars_url=beatstars_url or "", tags=tag_list,
    )
    log(f"Uploading to YouTube: {yt_title}")
    url = upload_video(
        file_path=render["output"],
        title=yt_title,
        description=yt_description,
        tags=tag_list + ["type beat", "instrumental", "free beat", producer],
        privacy=privacy,
        publish_at=publish_at,
        log=log,
        progress=progress,
        should_stop=should_stop,
    )
    if delete_after_upload:
        try:
            os.remove(render["output"])
            log(f"  Deleted local render: {render['output']}")
        except OSError as e:
            log(f"  Could not delete {render['output']}: {e}")
    log(f"Done! {url}")
    return url


def run_pipeline(
    audio,
    title,
    producer="pk",
    bpm=None,
    key=None,
    tags=None,
    beatstars_url=None,
    scheme=None,
    duration=None,
    output=None,
    privacy="public",
    publish_at=None,
    skip_youtube=False,
    delete_after_upload=False,
    workers=None,
    log=print,
    progress=None,
):
    """Render a visualizer for *audio* and (optionally) upload it to YouTube.

    Returns dict: {'output', 'url' (None if skipped), 'bpm', 'key', 'scheme'}.
    """
    render = render_beat(audio, title, producer=producer, bpm=bpm, key=key,
                         scheme=scheme, duration=duration, output=output,
                         workers=workers, log=log, progress=progress)
    result = {"output": render["output"], "url": None, "bpm": render["bpm"],
              "key": render["key"], "scheme": render["scheme"]}
    if skip_youtube:
        log("Skipping YouTube upload")
        return result
    result["url"] = upload_beat(render, title, tags=tags, beatstars_url=beatstars_url,
                                privacy=privacy, publish_at=publish_at,
                                delete_after_upload=delete_after_upload, log=log)
    return result

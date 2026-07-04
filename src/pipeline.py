# src/pipeline.py
"""Shared beat-upload pipeline: analyze → render → upload.

Used by both the CLI (main.py) and the GUI (gui.py).
"""

import os

from src.config import FPS, COLOR_SCHEMES, pick_random_scheme
from src.audio import AudioAnalyzer
from src.visualizer import create_icosphere
from src.render import render_video
from utils import generate_description, format_youtube_title, clean_producer
from youtube_uploader import upload_video


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
    skip_youtube=False,
    workers=None,
    log=print,
    progress=None,
):
    """Render a visualizer for *audio* and (optionally) upload it to YouTube.

    tags:     list of genre/mood strings.
    log:      called with status lines (GUI redirects these).
    progress: optional callable(frac) for render progress.

    Returns dict: {'output', 'url' (None if skipped), 'bpm', 'key', 'scheme'}.
    """
    tag_list = list(tags) if tags else []
    # "prod pk" → "pk": the overlay/title/description templates add their own credit
    producer = clean_producer(producer)

    if output is None:
        os.makedirs("output", exist_ok=True)
        output = f"output/{title.replace(' ', '_')}.mp4"
    else:
        out_dir = os.path.dirname(output)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

    # A bare number ("140", e.g. parsed from a filename) becomes "140 BPM"
    # so the video overlay and YouTube title read consistently.
    if bpm and str(bpm).strip().isdigit():
        bpm = f"{str(bpm).strip()} BPM"

    # ── Audio analysis ──
    log(f"Analyzing audio: {audio}")
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
                 workers=workers, log=log, progress=progress)
    log(f"  Video saved: {output}")

    result = {"output": output, "url": None,
              "bpm": bpm_text, "key": key_text, "scheme": cs_key}

    if skip_youtube:
        log("Skipping YouTube upload")
        return result

    # ── Upload ──
    yt_title = format_youtube_title(title, producer, bpm_text, tags=tag_list)
    yt_description = generate_description(
        title=title, producer=producer, bpm=bpm_text, key=key_text,
        beatstars_url=beatstars_url or "", tags=tag_list,
    )
    log(f"Uploading to YouTube: {yt_title}")
    url = upload_video(
        file_path=output,
        title=yt_title,
        description=yt_description,
        tags=tag_list + ["type beat", "instrumental", "free beat", producer],
        privacy=privacy,
        log=log,
    )
    result["url"] = url
    log(f"Done! {url}")
    return result

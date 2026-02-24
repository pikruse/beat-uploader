# main.py
"""Unified CLI: render visualizer → upload to YouTube."""

import os
import click
import numpy as np
from moviepy import VideoClip, AudioFileClip

from src.config import WIDTH, HEIGHT, FPS, COLOR_SCHEMES, pick_random_scheme
from src.audio import AudioAnalyzer
from src.visualizer import VisualizerRenderer, create_icosphere
from utils import generate_description, format_youtube_title
from youtube_uploader import upload_video


@click.command()
# ── Required ──
@click.option("--audio", required=True, help="Path to audio file (mp3/wav)")
@click.option("--title", required=True, help='Beat name (e.g. "TimeTraveller")')
# ── Metadata ──
@click.option("--producer", default="pk", help="Producer credit")
@click.option("--bpm", default=None, help="BPM override (auto-detected if omitted)")
@click.option("--key", default=None, help='Key override, e.g. "Cm" (auto-detected if omitted)')
@click.option("--tags", default=None, help='Comma-separated genre/mood tags (e.g. "trap,dark,ambient")')
# ── BeatStars ──
@click.option("--beatstars-url", default=None, help="BeatStars listing URL for the description")
# ── Rendering ──
@click.option("--scheme", default=None, help="Color scheme name (random if omitted)")
@click.option("--duration", default=None, type=float, help="Limit audio duration (seconds)")
@click.option("--output", default=None, help="Video output path (default: output/<title>.mp4)")
# ── YouTube ──
@click.option("--privacy", default="public",
              type=click.Choice(["public", "unlisted", "private"]),
              help="YouTube privacy status (default: unlisted)")
@click.option("--skip-youtube", is_flag=True, help="Only render video, skip YouTube upload")
def main(audio, title, producer, bpm, key, tags, beatstars_url,
         scheme, duration, output, privacy, skip_youtube):
    """Render a beat visualizer and upload it to YouTube."""

    # ── Resolve output path ──
    if output is None:
        os.makedirs("output", exist_ok=True)
        safe_title = title.replace(" ", "_")
        output = f"output/{safe_title}.mp4"
    else:
        out_dir = os.path.dirname(output)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

    # ── Parse tags ──
    tag_list = [t.strip() for t in tags.split(",")] if tags else []

    # ════════════════════════════════════════════════════════
    #  STEP 1 — Audio Analysis
    # ════════════════════════════════════════════════════════
    analyzer = AudioAnalyzer(audio, FPS, duration)
    dur = analyzer.duration

    bpm_text = bpm if bpm else f"{int(round(analyzer.bpm))} BPM"
    key_text = key if key else analyzer.key_label

    print("══════════════════════════════════════")
    print("  BEAT UPLOAD PIPELINE")
    print("══════════════════════════════════════")
    print(f"  Track: {title}")
    print(f"  Producer: {producer}")
    print(f"  BPM: {bpm_text}")
    print(f"  Key: {key_text}")
    print(f"  Duration: {dur:.1f}s")
    if tag_list:
        print(f"  Tags     : {', '.join(tag_list)}")
    if beatstars_url:
        print(f"  BeatStars: {beatstars_url}")
    print(f"  Output   : {output}")
    print()

    # ════════════════════════════════════════════════════════
    #  STEP 2 — Render Visualizer
    # ════════════════════════════════════════════════════════
    print("── Rendering Visualizer ──")
    verts, edges = create_icosphere(radius=1.0, subdivisions=2)

    if scheme and scheme in COLOR_SCHEMES:
        cs = COLOR_SCHEMES[scheme]
        cs_key = scheme
    else:
        cs_key, cs = pick_random_scheme()
    print(f"  Scheme: {cs['name']} ({cs_key})")

    meta = {"title": title, "producer": producer, "bpm": bpm_text, "key": key_text}
    renderer = VisualizerRenderer(analyzer, meta, verts, edges, cs)

    video = VideoClip(lambda t: renderer.render_frame(t), duration=dur)
    video = video.with_audio(AudioFileClip(audio))
    video.write_videofile(
        output, fps=FPS, codec="libx264", audio_codec="aac",
        threads=4, preset="slow",
        ffmpeg_params=["-crf", "18", "-maxrate", "40M", "-bufsize", "80M"],
    )
    print(f"  Video saved: {output}")
    print()

    # ════════════════════════════════════════════════════════
    #  STEP 3 — Upload to YouTube
    # ════=═══════════════════════════════════════════════════
    if skip_youtube:
        print("── Skipping YouTube upload (--skip-youtube) ──")
        return

    print("── Uploading to YouTube ──")
    yt_title = format_youtube_title(title, producer, bpm_text)
    yt_description = generate_description(
        title=title,
        producer=producer,
        bpm=bpm_text,
        key=key_text,
        beatstars_url=beatstars_url or "",
        tags=tag_list,
    )

    print(f"  Title: {yt_title}")
    print()

    url = upload_video(
        file_path=output,
        title=yt_title,
        description=yt_description,
        tags=tag_list + ["type beat", "instrumental", "free beat", producer],
        privacy=privacy,
    )

    print()
    print("══════════════════════════════════════")
    print(f"Done! {url}")
    print("══════════════════════════════════════")


if __name__ == "__main__":
    main()

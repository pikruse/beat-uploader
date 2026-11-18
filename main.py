# main.py
"""Unified CLI: render visualizer → upload to YouTube."""

import click


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
@click.option("--workers", default=None, type=int, help="Parallel render workers (default: CPU count - 1)")
# ── YouTube ──
@click.option("--privacy", default="public",
              type=click.Choice(["public", "unlisted", "private"]),
              help="YouTube privacy status")
@click.option("--publish-at", default=None,
              help='Schedule publishing, local time "YYYY-MM-DD HH:MM" (uploads as private until then)')
@click.option("--delete-render", is_flag=True, help="Delete the local mp4 after a successful upload")
@click.option("--skip-youtube", is_flag=True, help="Only render video, skip YouTube upload")
def main(audio, title, producer, bpm, key, tags, beatstars_url,
         scheme, duration, output, workers, privacy, publish_at, delete_render, skip_youtube):
    """Render a beat visualizer and upload it to YouTube."""
    # Imported here (not at module top) so multiprocessing workers spawned
    # during rendering don't re-import librosa / googleapiclient.
    from datetime import datetime, timezone
    from src.pipeline import run_pipeline

    if publish_at:
        try:
            when = datetime.fromisoformat(publish_at).astimezone(timezone.utc)
        except ValueError:
            raise click.BadParameter('use "YYYY-MM-DD HH:MM"', param_hint="--publish-at")
        if when <= datetime.now(timezone.utc):
            raise click.BadParameter("must be in the future", param_hint="--publish-at")
        publish_at = when.strftime("%Y-%m-%dT%H:%M:%SZ")

    print("══════════════════════════════════════")
    print("  BEAT UPLOAD PIPELINE")
    print("══════════════════════════════════════")

    run_pipeline(
        audio=audio,
        title=title,
        producer=producer,
        bpm=bpm,
        key=key,
        tags=[t.strip() for t in tags.split(",")] if tags else [],
        beatstars_url=beatstars_url,
        scheme=scheme,
        duration=duration,
        output=output,
        privacy=privacy,
        publish_at=publish_at,
        skip_youtube=skip_youtube,
        delete_after_upload=delete_render,
        workers=workers,
    )


if __name__ == "__main__":
    main()

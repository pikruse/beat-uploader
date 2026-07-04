# media_processor.py
# Render-only CLI (no YouTube upload). Equivalent to: python main.py --skip-youtube
# Usage:
#   python media_processor.py --audio test_audio.mp3 --title "TrackName" --producer "pk"
#   python media_processor.py --audio test_audio.mp3 --scheme cyber --bpm "144 BPM" --key "Cm"

import click


@click.command()
@click.option('--audio', required=True, help='Path to audio file (mp3/wav)')
@click.option('--title', default='Track Title', help='Track title')
@click.option('--producer', default='Producer', help='Producer name')
@click.option('--bpm', default=None, help='BPM override (auto-detected from audio if omitted)')
@click.option('--key', default=None, help='Key override, e.g. "Cm" (auto-detected if omitted)')
@click.option('--output', default='output/output.mp4', help='Output file path')
@click.option('--scheme', default=None,
              help='Color scheme (fire/cyber/violet/ember/arctic/lime). Random if omitted.')
@click.option('--duration', default=None, type=float, help='Limit duration in seconds')
@click.option('--workers', default=None, type=int, help='Parallel render workers (default: CPU count - 1)')
def main(audio, title, producer, bpm, key, output, scheme, duration, workers):
    """Generate a 1920×1080 landscape audio visualizer video."""
    # Deferred so multiprocessing workers don't re-import heavy libraries
    from src.pipeline import run_pipeline

    run_pipeline(
        audio=audio,
        title=title,
        producer=producer,
        bpm=bpm,
        key=key,
        scheme=scheme,
        duration=duration,
        output=output,
        workers=workers,
        skip_youtube=True,
    )


if __name__ == '__main__':
    main()

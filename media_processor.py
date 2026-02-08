# media_processor.py
# Usage:
#   python media_processor.py --audio test_audio.mp3 --title "TrackName" --producer "pk"
#   python media_processor.py --audio test_audio.mp3 --scheme cyber --bpm "144 BPM" --key "Cm"

import click
import os
import numpy as np
from moviepy import VideoClip, AudioFileClip

from src.config import WIDTH, HEIGHT, FPS, COLOR_SCHEMES, pick_random_scheme
from src.audio import AudioAnalyzer
from src.visualizer import VisualizerRenderer, create_icosphere


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
def main(audio, title, producer, bpm, key, output, scheme, duration):
    """Generate a 1920×1080 landscape audio visualizer video."""

    out_dir = os.path.dirname(output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    # 1. Audio analysis (also detects BPM + key)
    analyzer = AudioAnalyzer(audio, FPS, duration)
    dur = analyzer.duration

    # Use auto-detected values unless overridden by CLI flags
    bpm_text = bpm if bpm else f"{int(round(analyzer.bpm))} BPM"
    key_text = key if key else analyzer.key_label

    print("── AUDIO VISUALIZER ──")
    print(f"   Track : {title}")
    print(f"   Prod. : {producer}")
    print(f"   BPM   : {bpm_text}")
    print(f"   Key   : {key_text}")
    print(f"   Length : {dur:.1f}s")

    # 2. Mesh
    print("Generating geodesic mesh...")
    verts, edges = create_icosphere(radius=1.0, subdivisions=2)

    # 3. Color scheme
    if scheme and scheme in COLOR_SCHEMES:
        cs = COLOR_SCHEMES[scheme]
        cs_key = scheme
    else:
        cs_key, cs = pick_random_scheme()
    print(f"   Scheme: {cs['name']} ({cs_key})")

    # 4. Renderer
    meta = {'title': title, 'producer': producer, 'bpm': bpm_text, 'key': key_text}
    renderer = VisualizerRenderer(analyzer, meta, verts, edges, cs)

    def make_frame(t):
        return renderer.render_frame(t)

    # 5. Render & export
    print("Rendering...")
    video = VideoClip(make_frame, duration=dur)
    video = video.with_audio(AudioFileClip(audio))
    video.write_videofile(
        output,
        fps=FPS,
        codec='libx264',
        audio_codec='aac',
        threads=4,
        preset='slow',
        bitrate='15000k',
    )
    print("Done!")


if __name__ == '__main__':
    main()

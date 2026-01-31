import os
import subprocess
from typing import Optional
import numpy as np
import librosa
import matplotlib
import matplotlib.pyplot as plt
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3
import logging

# Use Agg backend for non-interactive plotting (essential for headless rendering)
matplotlib.use('Agg')

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class MediaProcessor:
    def __init__(self):
        self.output_dir = "output"
        os.makedirs(self.output_dir, exist_ok=True)

    def extract_metadata(self, mp3_path):
        try:
            audio = MP3(mp3_path, ID3=EasyID3)
            return {
                "title": audio.get("title", [""])[0],
                "artist": audio.get("artist", [""])[0],
                "bpm": audio.get("bpm", [""])[0],
            }
        except Exception:
            return {}

    def render_visualizer(self, audio_path: str, style: str = "multilayer", output_filename: str = "output.mp4") -> Optional[str]:
        output_path = os.path.join(self.output_dir, output_filename)

        scope_cmd = (
            "[0:a]avectorscope=s=960x800:zoom=1.3[v_scope]"
        )
        
        spec_cmd = (
            "[0:a]showspectrum=s=960x800:slide=scroll:mode=combined:color=channel:fscale=log:scale=sqrt[spec_raw];"
            "[spec_raw]scale=960:800[v_spec]"
        )

        wave_cmd = (
            "[0:a]showwaves=s=1920x280:mode=line[v_waves]"
        )

        # 4. Assembly
        assembly_cmd = (
            "[v_scope][v_spec]hstack[top_half];"
            "[top_half][v_waves]vstack"
        )

        # Combine logic
        multilayer_filter = f"{spec_cmd};{scope_cmd};{wave_cmd};{assembly_cmd}"

        cmd = [
            'ffmpeg', '-y',
            '-i', audio_path,
            '-filter_complex', f"{multilayer_filter},format=yuv420p[v]",
            '-map', '[v]',
            '-map', '0:a',
            '-c:v', 'h264_videotoolbox', '-b:v', '6000k',
            '-c:a', 'aac', '-b:a', '320k',
            '-shortest',
            output_path
        ]

        try:
            logging.info(f"Rendering Visualizer...")
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            logging.info(f"Success! Video saved to: {output_path}")
            return output_path
        except subprocess.CalledProcessError as e:
            logging.error(f"FFmpeg failed: {e.stderr.decode()}")
            return None

if __name__ == "__main__":
    TEST_MP3 = '/Users/peterkruse/Library/CloudStorage/Dropbox/@prod_pk all beats:loops/@prod_pk 2025 compositions/september 2025 beats, loops, midi/beat/[futuristic] symphony 140 prod pk.mp3'
    if os.path.exists(TEST_MP3):
        proc = MediaProcessor()
        proc.render_visualizer(TEST_MP3, output_filename="test.mp4")
    else:
        print("Please provide test_audio.mp3")
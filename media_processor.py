### handles ffmpeg [mp3 + image --> mp4] and metadata parsing

# imports
import os
import subprocess
import logging
import cmd
from typing import Dict, Optional
from mutagen.easyid3 import EasyID3
from mutagen.mp3 import MP3

# set up basic logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# create a class for the media processor
class MediaProcessor:
    def __init__(self):
        # ensure a valid output directory exists
        self.output_dir = "output"
        os.makedirs(self.output_dir, exist_ok=True)
    
    def extract_metadata(self, mp3_path: str) -> Dict[str, str]:
        """
        Extracts ID3 tags (Title, Artist, BPM, Key) from the MP3
        Returns a dictionary of metadata
        """

        try:
            audio = MP3(mp3_path, ID3=EasyID3)

            # helper to get tag or return empty string
            def get_tag(tag):
                return audio.get(tag, [""])[0]
            
            metadata = {
                "title": get_tag("title"),
                "artist": get_tag("artist"),
                "bpm": get_tag("bpm"),
                "key": get_tag("initialkey"),
                "genre": get_tag("genre"),
                "date": get_tag("date")
            }

            logging.info(f"Metadata extracted: {metadata}")
            return metadata
        
        except Exception as e:
            logging.error(f"Error extracting metadata: {e}")
            return {}
        
    def render_visualizer(self, audio_path: str, style: str = "multilayer", output_filename: str = "output.mp4") -> Optional[str]:
        output_path = os.path.join(self.output_dir, output_filename)
        
        # --- AESTHETIC CONFIGURATION ---
        # 1. Scope (Top Left): Cyan lines, slightly zoomed
        #    rc/gc/bc = Red/Green/Blue channels for the trace color.
        scope_cmd = "avectorscope=s=960x800:zoom=1.5:rc=0:gc=255:bc=255:draw=line"
        
        # 2. Spectrum (Top Right): 'magma' colormap (Purple->Orange)
        #    win_func=hann: smoother frequency separation
        spec_cmd = "showspectrum=s=960x800:mode=separate:color=magma:slide=1:scale=cbrt:win_func=hann"
        
        # 3. Waves (Bottom): Gold color with 60% opacity for a 'glowing' look
        #    colors=0xFFD700@0.6 (Gold at 0.6 alpha)
        wave_cmd = "showwaves=s=1920x280:mode=line:colors=0xFFD700@0.6:draw=full"

        # --- FILTER CHAIN CONSTRUCTION ---
        multilayer_filter = (
            f"[0:a]{scope_cmd}[v_scope];"
            f"[0:a]{spec_cmd}[v_spec];"
            f"[0:a]{wave_cmd}[v_waves];"
            "[v_scope][v_spec]hstack[top_half];"
            "[top_half][v_waves]vstack"
        )

        # (Mandelbrot and Spectrum kept same as previous working version)
        mandelbrot_filter = (
            "mandelbrot=s=1920x1080:start_scale=1.5:end_scale=0.005:ba=-127:end_pts=900[bg];"
            "[0:a]showwaves=s=1920x1080:mode=line:colors=white@0.3:draw=full[fg];"
            "[bg][fg]overlay=format=auto"
        )
        spectrum_filter = "[0:a]showcqt=s=1920x1080:fps=30:axis=0:text=0:csp=virilis"

        filter_chains = {
            "multilayer": multilayer_filter,
            "mandelbrot": mandelbrot_filter,
            "spectrum": spectrum_filter
        }

        vf = filter_chains.get(style, filter_chains["spectrum"])

        cmd = [
            'ffmpeg', '-y',
            '-i', audio_path,
            '-filter_complex', f"{vf},format=yuv420p[v]",
            '-map', '[v]',
            '-map', '0:a',
            '-c:v', 'h264_videotoolbox', '-b:v', '5000k', # Apple Silicon Encoder
            '-c:a', 'aac', '-b:a', '320k',
            '-shortest',
            output_path
        ]

        try:
            logging.info(f"Rendering '{style}' visualizer (Aesthetic Update)...")
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            logging.info(f"Success! Video saved to: {output_path}")
            return output_path
        except subprocess.CalledProcessError as e:
            logging.error(f"FFmpeg failed: {e.stderr.decode()}")
            return None

if __name__ == "__main__":
    TEST_MP3 = '/Users/peterkruse/Library/CloudStorage/Dropbox/@prod_pk all beats:loops/@prod_pk 2026 compositions/january 2026 beats, loops, midi, etc/beats/FlyByNight 152 prod pk hxlcyon.mp3'
    if os.path.exists(TEST_MP3):
        proc = MediaProcessor()
        proc.render_visualizer(TEST_MP3)
    else:
        print(f"Please put 'test_audio.mp3' in {os.getcwd()}")
# src/render.py
"""Fast video rendering: sequential physics pass, parallel frame drawing,
frames piped straight into ffmpeg (video + audio muxed in one shot).

Replaces the old moviepy path, which drew every frame on a single core.
"""

import os
import shutil
import subprocess
import multiprocessing as mp

from src.config import WIDTH, HEIGHT


class _SlimAudio:
    """Minimal stand-in for AudioAnalyzer carrying only what draw_frame needs,
    so workers don't have to unpickle the full STFT matrices."""

    def __init__(self, waveform_dense, sr):
        self.waveform_dense = waveform_dense
        self.sr = sr


_worker_renderer = None


def _init_worker(waveform, sr, meta, verts, edges, scheme, total_duration):
    global _worker_renderer
    from src.visualizer import VisualizerRenderer
    _worker_renderer = VisualizerRenderer(_SlimAudio(waveform, sr), meta, verts, edges,
                                          scheme, total_duration=total_duration)


def _draw(args):
    t, state = args
    return _worker_renderer.draw_frame(t, state).tobytes()


def _ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        exe = shutil.which("ffmpeg")
        if not exe:
            raise RuntimeError("ffmpeg not found — pip install imageio-ffmpeg")
        return exe


def render_video(analyzer, meta, verts, edges, scheme, audio_path, output, fps,
                 workers=None, log=print, progress=None):
    """Render the visualizer for *analyzer* to *output* (mp4, with audio).

    workers:  number of drawing processes (default: CPU count - 1).
    log:      called with status strings.
    progress: optional callable(frac in [0, 1]).
    """
    from src.visualizer import VisualizerRenderer

    dur = analyzer.duration
    n_frames = int(dur * fps)
    workers = workers or max(1, (os.cpu_count() or 4) - 1)

    # 1. Sequential physics pass — cheap, no drawing, keeps the temporal
    #    smoothing / particle motion identical to single-threaded rendering.
    seq = VisualizerRenderer(analyzer, meta, verts, edges, scheme, total_duration=dur)
    frame_args = [(i / fps, seq.step_state(i / fps)) for i in range(n_frames)]

    # 2. ffmpeg: raw RGB frames on stdin, audio muxed from the source file.
    cmd = [
        _ffmpeg_exe(), "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{WIDTH}x{HEIGHT}", "-r", str(fps), "-i", "-",
        "-i", audio_path,
        "-map", "0:v:0", "-map", "1:a:0",
        # YouTube re-encodes to ~8 Mbps anyway; crf 23 + a bitrate cap roughly
        # halves the file vs crf 19, halving upload time with no visible
        # difference after YouTube's processing.
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-maxrate", "12M", "-bufsize", "24M",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        "-t", f"{dur:.3f}",
        output,
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    # 3. Draw frames in parallel, stream them to ffmpeg in order.
    log(f"  Rendering {n_frames} frames on {workers} workers...")
    ctx = mp.get_context("spawn")
    try:
        with ctx.Pool(
            workers, initializer=_init_worker,
            initargs=(analyzer.waveform_dense, analyzer.sr, meta, verts, edges, scheme, dur),
        ) as pool:
            report_every = max(1, n_frames // 20)
            for i, frame in enumerate(pool.imap(_draw, frame_args, chunksize=4)):
                proc.stdin.write(frame)
                if (i + 1) % report_every == 0 or i + 1 == n_frames:
                    frac = (i + 1) / n_frames
                    log(f"  Render: {int(frac * 100)}%")
                    if progress:
                        progress(frac)
        proc.stdin.close()
    except BrokenPipeError:
        proc.wait()
        raise RuntimeError(f"ffmpeg exited early (code {proc.returncode})")

    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg failed (code {proc.returncode})")

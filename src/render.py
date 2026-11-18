# src/render.py
"""Fast video rendering: sequential physics pass, parallel frame drawing,
frames piped straight into ffmpeg (video + audio muxed in one shot).

Replaces the old moviepy path, which drew every frame on a single core.
"""

import os
import shutil
import subprocess
import sys
import multiprocessing as mp
from multiprocessing import shared_memory

import numpy as np

from src.config import WIDTH, HEIGHT


class _SlimAudio:
    """Minimal stand-in for AudioAnalyzer carrying only what draw_frame needs,
    so workers don't have to unpickle the full STFT matrices."""

    def __init__(self, waveform_dense, sr):
        self.waveform_dense = waveform_dense
        self.sr = sr


FRAME_BYTES = WIDTH * HEIGHT * 3

_worker_renderer = None
_worker_shm = None
_worker_slots = None


def _init_worker(waveform, sr, meta, verts, edges, scheme, total_duration, shm_name, n_slots):
    global _worker_renderer, _worker_shm, _worker_slots
    from src.visualizer import VisualizerRenderer
    _worker_renderer = VisualizerRenderer(_SlimAudio(waveform, sr), meta, verts, edges,
                                          scheme, total_duration=total_duration)
    # Frames go into a shared ring buffer instead of being pickled back
    # through a pipe — at 6 MB/frame that copy was the real bottleneck.
    _worker_shm = shared_memory.SharedMemory(name=shm_name)
    _worker_slots = np.ndarray((n_slots, HEIGHT, WIDTH, 3), np.uint8, buffer=_worker_shm.buf)


def _draw(args):
    t, state, slot = args
    _worker_slots[slot] = _worker_renderer.draw_frame(t, state)
    return slot


def _ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        exe = shutil.which("ffmpeg")
        if not exe:
            raise RuntimeError("ffmpeg not found — pip install imageio-ffmpeg")
        return exe


class RenderCancelled(Exception):
    pass


# Video encoders. "x264" is the CPU encoder; "videotoolbox" is the Mac's
# hardware encoder, which leaves every CPU core free for drawing frames.
ENCODERS = {
    # YouTube re-encodes to ~8 Mbps anyway; crf 23 + a bitrate cap keeps the
    # upload small with no visible difference after YouTube's processing.
    "x264": ["-c:v", "libx264", "-preset", "fast", "-crf", "23",
             "-maxrate", "12M", "-bufsize", "24M"],
    "videotoolbox": ["-c:v", "h264_videotoolbox", "-b:v", "VT_BITRATE",
                     "-maxrate", "18M", "-bufsize", "36M", "-profile:v", "high"],
}
VT_BITRATE = os.environ.get("BEAT_VT_BITRATE", "12M")   # matches x264 crf23 quality (SSIM)


def _pick_encoder(requested=None):
    """BEAT_ENCODER=x264|videotoolbox overrides; default: hardware on Macs."""
    name = requested or os.environ.get("BEAT_ENCODER", "auto")
    if name == "auto":
        name = "videotoolbox" if sys.platform == "darwin" and _has_encoder("h264_videotoolbox") else "x264"
    args = [VT_BITRATE if a == "VT_BITRATE" else a for a in ENCODERS[name]]
    return name, args


def _has_encoder(enc):
    try:
        out = subprocess.run([_ffmpeg_exe(), "-hide_banner", "-encoders"],
                             capture_output=True, text=True, timeout=10).stdout
        return f" {enc} " in out
    except Exception:
        return False


def render_video(analyzer, meta, verts, edges, scheme, audio_path, output, fps,
                 workers=None, log=print, progress=None, should_stop=None, encoder=None):
    """Render the visualizer for *analyzer* to *output* (mp4, with audio).

    workers:     number of drawing processes (default: CPU count - 1).
    log:         called with status strings.
    progress:    optional callable(frac in [0, 1]).
    should_stop: optional callable; returning True aborts the render, kills
                 ffmpeg and the workers, and deletes the partial file.
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
    encoder_name, encoder_args = _pick_encoder(encoder)
    cmd = [
        _ffmpeg_exe(), "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{WIDTH}x{HEIGHT}", "-r", str(fps), "-i", "-",
        "-i", audio_path,
        "-map", "0:v:0", "-map", "1:a:0",
        *encoder_args,
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        "-t", f"{dur:.3f}",
        output,
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)

    # 3. Draw frames in parallel into a shared ring buffer and stream them
    #    to ffmpeg in order. A slot is only handed out again after its
    #    previous frame has been written, so workers never overwrite a
    #    frame that hasn't been sent yet.
    log(f"  Rendering {n_frames} frames on {workers} workers ({encoder_name})...")
    ctx = mp.get_context("spawn")
    n_slots = max(8, workers * 3)
    shm = shared_memory.SharedMemory(create=True, size=n_slots * FRAME_BYTES)
    slots = memoryview(shm.buf)
    ok = False
    try:
        # Leaving the with-block (normally or via an exception) terminates
        # the pool, so cancelled/failed renders don't leave workers behind.
        with ctx.Pool(
            workers, initializer=_init_worker,
            initargs=(analyzer.waveform_dense, analyzer.sr, meta, verts, edges, scheme, dur,
                      shm.name, n_slots),
        ) as pool:
            pending = {}

            def submit(i):
                t_i, state_i = frame_args[i]
                pending[i] = pool.apply_async(_draw, ((t_i, state_i, i % n_slots),))

            for i in range(min(n_slots, n_frames)):
                submit(i)
            report_every = max(1, n_frames // 20)
            for i in range(n_frames):
                slot = pending.pop(i).get()
                if should_stop and should_stop():
                    raise RenderCancelled("render cancelled")
                proc.stdin.write(slots[slot * FRAME_BYTES:(slot + 1) * FRAME_BYTES])
                frame_args[i] = None                # free the state as we go
                if i + n_slots < n_frames:
                    submit(i + n_slots)
                if (i + 1) % report_every == 0 or i + 1 == n_frames:
                    frac = (i + 1) / n_frames
                    log(f"  Render: {int(frac * 100)}%")
                    if progress:
                        progress(frac)
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError(f"ffmpeg failed (code {proc.returncode})")
        ok = True
    except BrokenPipeError:
        proc.wait()
        raise RuntimeError(f"ffmpeg exited early (code {proc.returncode})")
    finally:
        slots.release()
        shm.close()
        shm.unlink()
        if not ok:
            # Any failure or cancel: don't leave ffmpeg waiting on stdin or a
            # truncated mp4 that looks like a finished render.
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            if os.path.exists(output):
                os.remove(output)

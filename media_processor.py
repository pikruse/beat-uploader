import numpy as np
from PIL import Image, ImageDraw, ImageFont
import librosa
from moviepy import VideoClip, AudioFileClip
from scipy.signal import savgol_filter
import math
import os

# --- METADATA ---
TRACK_TITLE = "KeepItUP"
PRODUCER = "pk & henryberg"
BPM_TEXT = "144 bpm"

# --- CONFIG ---
AUDIO_FILE = "test_audio.mp3"
OUTPUT_FILE = "output/visualizer_smooth.mp4"
FPS = 30
WIDTH, HEIGHT = 1920, 1080
DURATION_LIMIT = None

# --- VISUALS ---
BG_COLOR = (255, 255, 255)
UI_COLOR = (180, 180, 180)
ACCENT_COLOR = (0, 0, 0)

# GEOMETRY
SPHERE_RADIUS = 280
RING_RADIUS = 300
SUBDIVISIONS = 2

os.makedirs("output", exist_ok=True)

print("--- INITIALIZING SMOOTH RENDERER ---")

# 1. GEOMETRY ENGINE (Icosphere)
def normalize(v):
    norm = np.linalg.norm(v)
    if norm == 0: return v
    return v / norm

# create icosphere, return vertices and edges of sphere
def create_icosphere(radius, subdivisions):

    # get vertices, faces
    t = (1.0 + math.sqrt(5.0)) / 2.0
    verts = [
        (-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0),
        (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t),
        (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)
    ]
    verts = [normalize(np.array(v)) for v in verts]
    faces = [
        (0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11),
        (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8),
        (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9),
        (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1)
    ]

    # get middle point of the icosphere
    middle_point_cache = {}
    def get_middle_point(p1_idx, p2_idx):
        key = tuple(sorted((p1_idx, p2_idx)))
        if key in middle_point_cache: return middle_point_cache[key]
        p1 = verts[p1_idx]
        p2 = verts[p2_idx]
        middle = normalize((p1 + p2) / 2.0)
        verts.append(middle)
        idx = len(verts) - 1
        middle_point_cache[key] = idx
        return idx
 
    for _ in range(subdivisions):
        new_faces = []
        for v1, v2, v3 in faces:
            a = get_middle_point(v1, v2)
            b = get_middle_point(v2, v3)
            c = get_middle_point(v3, v1)
            new_faces.append((v1, a, c))
            new_faces.append((v2, b, a))
            new_faces.append((v3, c, b))
            new_faces.append((a, b, c))
        faces = new_faces
    final_verts = np.array(verts) * radius
    edges = set()

    for f in faces:
        edges.add(tuple(sorted((f[0], f[1]))))
        edges.add(tuple(sorted((f[1], f[2]))))
        edges.add(tuple(sorted((f[2], f[0]))))
    
    return final_verts, list(edges)

print("Building Geodesic Mesh...")
BASE_VERTS, EDGES = create_icosphere(radius=SPHERE_RADIUS, subdivisions=SUBDIVISIONS)

# 2. AUDIO ANALYSIS
print("Analyzing Audio...")
try:
    y_stereo, sr = librosa.load(AUDIO_FILE, sr=22050, mono=False)
    if y_stereo.ndim == 1: y_stereo = np.vstack((y_stereo, y_stereo))
    
    duration = librosa.get_duration(y=y_stereo[0], sr=sr)
    if DURATION_LIMIT: duration = min(duration, DURATION_LIMIT)
    y_mono = librosa.to_mono(y_stereo)
    
    # Kick
    y_harm, y_perc = librosa.effects.hpss(y_mono)
    onset_env = librosa.onset.onset_strength(y=y_perc, sr=sr)
    total_frames = int(duration * FPS)
    x_old = np.linspace(0, len(onset_env), len(onset_env))
    x_new = np.linspace(0, len(onset_env), total_frames)
    kick_data = np.interp(x_new, x_old, onset_env)
    kick_data /= np.max(kick_data)

    # Spectrum
    n_fft = 2048
    D = np.abs(librosa.stft(y_mono, n_fft=n_fft, hop_length=int(sr/FPS)))
    D_db = librosa.amplitude_to_db(D, ref=np.max)
    if D_db.shape[1] != total_frames:
        cols = np.linspace(0, D_db.shape[1]-1, total_frames).astype(int)
        D_db = D_db[:, cols]

    # Global Waveform
    global_res = 500
    g_idx = np.linspace(0, len(y_mono)-1, global_res).astype(int)
    global_wave = y_mono[g_idx]
    global_wave = savgol_filter(global_wave, 21, 3) 
    global_wave /= np.max(np.abs(global_wave))

except Exception as e:
    print(f"Error: {e}")
    exit()

# 3. HELPER: VU METER
def draw_vu_meter(draw, x, y, w, h, level):
    fill_w = int(w * level)
    if fill_w < 1: return
    for i in range(fill_w):
        curr_x = x + i
        pct = i / w
        col = (0, 200, 0) if pct < 0.6 else (255, 200, 0) if pct < 0.85 else (255, 0, 0)
        draw.line([(curr_x, y), (curr_x, y + h)], fill=col, width=1)

# 4. RENDER LOOP
def lerp(a, b, t): return (1 - t) * a + t * b
smooth_pulse = 0
smooth_rot = 0

def make_frame(t):
    global smooth_pulse, smooth_rot
    
    f_idx = int(t * FPS)
    if f_idx >= len(kick_data): f_idx = len(kick_data) - 1
    
    kick = kick_data[f_idx]
    smooth_pulse = lerp(smooth_pulse, (kick**3)*1.5, 0.2)
    smooth_rot += 0.005 + (smooth_pulse * 0.03)

    img = Image.new('RGB', (WIDTH, HEIGHT), BG_COLOR)
    draw = ImageDraw.Draw(img, 'RGBA')
    cx, cy = WIDTH // 2, HEIGHT // 2

    # --- UI PANELS ---

    # 1. LOAD FONTS (Do this once at the top of make_frame, or globally)
    # Ideally, move this OUTSIDE make_frame for performance, but here is fine for testing
    try:
        # Load Custom Font (Size 20 for Headers, 14 for Data)
        title_font = ImageFont.truetype("fonts/oxanium/Oxanium-ExtraLight.ttf", 20)
        data_font = ImageFont.truetype("fonts/oxanium/Oxanium-Light.ttf", 14)
        header_font = ImageFont.truetype("fonts/oxanium/Oxanium-Regular.ttf", 12)
    except IOError:
        # Fallback if font.ttf isn't found
        print("Warning: font.ttf not found, using default.")
        title_font = ImageFont.load_default()
        data_font = ImageFont.load_default()
        header_font = ImageFont.load_default()

    # 1. TOP LEFT: Waveform
    tl_x, tl_y = 50, 50
    draw.rectangle([tl_x, tl_y, tl_x+300, tl_y+100], outline=UI_COLOR, width=2)
    # Use 'font=' argument
    draw.text((tl_x+10, tl_y+5), "TRACK OVERVIEW", fill=UI_COLOR, font=header_font)
    
    wave_y = tl_y + 50
    for i in range(len(global_wave)-1):
        x1 = tl_x + (i/len(global_wave))*300
        x2 = tl_x + ((i+1)/len(global_wave))*300
        y1 = wave_y + (global_wave[i] * 40)
        y2 = wave_y + (global_wave[i+1] * 40)
        draw.line([x1, y1, x2, y2], fill=(50,50,50), width=1)
    ph_x = tl_x + (t/duration)*300
    draw.line([ph_x, tl_y, ph_x, tl_y+100], fill=(255,0,0), width=2)

    # 2. TOP RIGHT: Spectrum
    tr_x, tr_y = WIDTH-350, 50
    draw.rectangle([tr_x, tr_y, tr_x+300, tr_y+100], outline=UI_COLOR, width=2)
    draw.text((tr_x+10, tr_y+5), "SPECTRUM", fill=UI_COLOR, font=header_font)
    spec = D_db[:, f_idx]
    bars = 32
    bw = 280 / bars
    for i in range(bars):
        idx = int(np.exp(i * 0.12) * 5)
        if idx >= len(spec): idx = len(spec)-1
        val = (spec[idx] + 80) / 80
        if val < 0: val = 0
        h = val * 70
        bx = tr_x + 10 + i*bw
        draw.rectangle([bx, tr_y+90-h, bx+bw-2, tr_y+90], fill=ACCENT_COLOR)

    # 3. BOTTOM LEFT: Metadata
    bl_x, bl_y = 50, HEIGHT-150
    draw.rectangle([bl_x, bl_y, bl_x+300, bl_y+100], outline=UI_COLOR, width=2)
    
    draw.text((bl_x+10, bl_y+5), "METADATA", fill=UI_COLOR, font=header_font)
    # Bigger font for Title
    draw.text((bl_x+10, bl_y+30), TRACK_TITLE, fill=ACCENT_COLOR, font=title_font)
    draw.text((bl_x+10, bl_y+55), PRODUCER, fill=(80,80,80), font=data_font)
    draw.text((bl_x+10, bl_y+75), BPM_TEXT, fill=(80,80,80), font=data_font)

    # 4. BOTTOM RIGHT: VU
    br_x, br_y = WIDTH-350, HEIGHT-150
    draw.rectangle([br_x, br_y, br_x+300, br_y+100], outline=UI_COLOR, width=2)
    draw.text((br_x+10, br_y+5), "OUTPUT LEVELS", fill=UI_COLOR, font=header_font)
    s_idx = int(t * sr)
    win = 1024
    s, e = max(0, s_idx-win), min(y_stereo.shape[1], s_idx+win)
    lvl_l, lvl_r = 0, 0
    if e > s:
        lvl_l = min(np.sqrt(np.mean(y_stereo[0, s:e]**2)) * 5.0, 1.0)
        lvl_r = min(np.sqrt(np.mean(y_stereo[1, s:e]**2)) * 5.0, 1.0)
        
    draw.text((br_x+10, br_y+40), "L", fill=ACCENT_COLOR, font=data_font)
    draw_vu_meter(draw, br_x+30, br_y+40, 250, 10, lvl_l)
    
    draw.text((br_x+10, br_y+65), "R", fill=ACCENT_COLOR, font=data_font)
    draw_vu_meter(draw, br_x+30, br_y+65, 250, 10, lvl_r)

    # --- 3D SCENE ---
    
    # 1. POLAR SPECTRUM RING -> FFT BASED
    ring_rot_speed = 0.05 # const rotation --> radians/sec
    current_rot = t * ring_rot_speed 
    ring_pts = []

    # use a larger window for better freq resolution
    fft_win = 4096 # samples per ring
    rs = max(0, s_idx - fft_win//2)
    re = min(y_mono.shape[0], s_idx + fft_win//2)

    # extract fft data for current frame to build ring
    if re > rs and len(y_mono[rs:re]) == fft_win: 
        # chunk is the audio from min to max range
        chunk = y_mono[rs:re] * np.hanning(fft_win) # hanning window attenuates edges to 0

        # FFT
        spectrum = np.abs(np.fft.rfft(chunk))

        # only get the first ~100 bins (bass/mids) for the visuals
        spec_len = 120
        if len(spectrum) > spec_len:
            spectrum = spectrum[:spec_len]

        # logarithmic scaling
        spectrum = np.log10(spectrum + 1)

        # smooth the spectrum curve
        # window must be smaller than array size and odd
        if len(spectrum) > 11:
            spectrum = savgol_filter(spectrum, 11, 3) # savgol filter smoothes the curve by fitting polynomials to local windows

        # mirror for loop
        full_spec = np.concatenate((spectrum, spectrum[::-1]))

        # normalize
        max_val = np.max(full_spec) + 0.001
        full_spec = full_spec / max_val
        full_spec = full_spec ** 3.0 # increase contrast

        # generate points
        num_pts = len(full_spec)
        for i in range(num_pts):
            # map index to radians
            base_ang = (i / num_pts) * 2 * math.pi

            # apply slow, constant rotation
            ang = base_ang + current_rot + (math.pi / 2)

            # amplitude
            amp = full_spec[i]

            # radius = base + frequency magnitude
            r = RING_RADIUS + (amp * 200)

            rx = cx + math.cos(ang) * r
            ry = cy + math.sin(ang) * r
            ring_pts.append((rx, ry))
        
        # close the loop
        if len(ring_pts) > 2:
            ring_pts.append(ring_pts[0])
            draw.line(ring_pts, fill=(0, 0, 0, 255), width = 3)

    # 2. 3D SPHERE (Deforming)
    cos_y, sin_y = math.cos(smooth_rot), math.sin(smooth_rot)
    cos_x, sin_x = math.cos(t * 0.2), math.sin(t * 0.2)
    ry = np.array([[cos_y, 0, sin_y], [0, 1, 0], [-sin_y, 0, cos_y]])
    rx = np.array([[1, 0, 0], [0, cos_x, -sin_x], [0, sin_x, cos_x]])
    
    # 1. Base Breathing (Uniform Scale)
    base_scale = 1.0 + (smooth_pulse * 0.15)
    
    # 2. BASS DEFORMATION (Spikes)
    # We create a noise mask that stays attached to the geometry
    # We use a fixed seed (42) so the spikes don't jitter randomly; they are "physical" parts of the sphere
    noise = np.random.RandomState(42).uniform(0.0, 1.0, size=(len(BASE_VERTS), 1))
    
    # Threshold the noise so only ~30% of vertices spike
    # we treat 'smooth_pulse' as the intensity control
    spike_intensity = smooth_pulse * 1.5
    
    # Only deform if there is bass
    if spike_intensity > 0.01:
        # Raise noise to power of 5 to make spikes rare and sharp
        spikes = (noise ** 5.0) * spike_intensity
        deformation = 1.0 + spikes
    else:
        deformation = 1.0
        
    # Apply: Base Geometry * Breathing * Spikes
    c_verts = BASE_VERTS * base_scale * deformation
    
    # 3. Rotate (after deformation so spikes spin with sphere)
    rotated = np.dot(c_verts, ry)
    rotated = np.dot(rotated, rx)
    
    proj = []

    for i, v in enumerate(rotated):
        z = v[2]
        f = 800 / (z + 1000)
        x = v[0] * f + cx
        y = v[1] * f + cy
        proj.append({'x': x, 'y': y, 'z': z})
        
    for i, j in EDGES:
        p1 = proj[i]
        p2 = proj[j]
        avg_z = (p1['z'] + p2['z']) / 2
        
        # Smooth Depth Fog (Same as before)
        norm_z = (avg_z + 350) / 700
        norm_z = max(0.0, min(1.0, norm_z))
        
        min_alpha = 50
        max_alpha = 255
        alpha = int(min_alpha + (norm_z * (max_alpha - min_alpha)))
        width = 2 if norm_z > 0.6 else 1
            
        draw.line([(p1['x'], p1['y']), (p2['x'], p2['y'])], fill=(0,0,0, alpha), width=width)

    return np.array(img)

# EXPORT
print("Rendering...")
video = VideoClip(make_frame, duration=duration if not DURATION_LIMIT else DURATION_LIMIT)
video = video.with_audio(AudioFileClip(AUDIO_FILE))
video.write_videofile(OUTPUT_FILE, 
                      fps=FPS, 
                      codec='libx264', 
                      audio_codec='aac', 
                      preset='slow', 
                      threads=4,
                      bitrate="15000k")
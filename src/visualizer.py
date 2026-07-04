# src/visualizer.py
import numpy as np
import math
from PIL import Image, ImageDraw, ImageFont
from src.config import *


# ── GEOMETRY ─────────────────────────────────────────────────

def normalize(v):
    norm = np.linalg.norm(v)
    if norm == 0:
        return v
    return v / norm


def create_icosphere(radius, subdivisions):
    t = (1.0 + math.sqrt(5.0)) / 2.0
    verts = [
        (-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0),
        (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t),
        (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1),
    ]
    verts = [normalize(np.array(v)) for v in verts]
    faces = [
        (0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11),
        (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8),
        (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9),
        (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1),
    ]
    middle_point_cache = {}

    def get_middle_point(p1_idx, p2_idx):
        key = tuple(sorted((p1_idx, p2_idx)))
        if key in middle_point_cache:
            return middle_point_cache[key]
        middle = normalize((verts[p1_idx] + verts[p2_idx]) / 2.0)
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
            new_faces.extend([(v1, a, c), (v2, b, a), (v3, c, b), (a, b, c)])
        faces = new_faces

    edges = set()
    for f in faces:
        edges.add(tuple(sorted((f[0], f[1]))))
        edges.add(tuple(sorted((f[1], f[2]))))
        edges.add(tuple(sorted((f[2], f[0]))))
    return np.array(verts) * radius, list(edges)


# ── SMOOTH 3-D NOISE (sum-of-sines) ─────────────────────────

def smooth_noise_3d(positions, time, frequency=2.0, octaves=3):
    """Coherent noise field over 3-D positions.  Returns [0, 1] per vertex."""
    result = np.zeros(len(positions))
    amp = 1.0
    freq = frequency
    total_amp = 0.0
    dirs = np.array([
        [1.0, 0.7, 0.3], [0.4, 1.0, 0.6], [0.6, 0.3, 1.0],
        [0.9, 0.5, 0.8], [0.3, 0.9, 0.4], [0.8, 0.4, 0.9],
    ])
    for o in range(octaves):
        d = dirs[o % len(dirs)]
        phase = np.dot(positions, d) * freq + time * (1.0 + o * 0.4)
        result += amp * (np.sin(phase) * 0.5 + 0.5)
        total_amp += amp
        amp *= 0.5
        freq *= 2.0
    return result / total_amp


# ── RENDERER ─────────────────────────────────────────────────
#
# The renderer is split into two halves so frames can be drawn in
# parallel (see src/render.py):
#
#   step_state(t)         — advances all temporal smoothing / particle
#                           state; MUST be called sequentially, one call
#                           per frame. Returns a picklable state snapshot.
#   draw_frame(t, state)  — pure function of (t, state); safe to run in
#                           any process. Only touches audio.waveform_dense
#                           and audio.sr.
#
# render_frame(t) composes the two for simple sequential use.

class VisualizerRenderer:
    def __init__(self, audio_analyzer, metadata, base_verts, edges, color_scheme,
                 total_duration=None):
        self.audio = audio_analyzer
        self.meta = metadata          # {'title', 'producer', 'bpm'}
        self.verts = base_verts
        self.edges = edges
        self.cs = color_scheme
        self.total_dur = total_duration

        # Pre-compute vertex normals (unit outward direction)
        norms = np.linalg.norm(base_verts, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self.vert_normals = base_verts / norms

        # Smoothing state
        self.smooth_pulse = 0.0
        self.smooth_rot = 0.0
        self.smooth_rot_x = 0.0
        self.smooth_spectrum = np.zeros(100)
        self.smooth_spec_bands = np.zeros(50)
        self.smooth_deform = np.zeros(len(base_verts))

        # Particle system (fills the sphere panel area)
        rng = np.random.RandomState(42)
        n_particles = 90
        self.particles = {
            'x':     rng.uniform(SPHERE_X + 20, SPHERE_X + SPHERE_W - 20, n_particles).astype(float),
            'y':     rng.uniform(SPHERE_Y + 20, SPHERE_Y + SPHERE_H - 20, n_particles).astype(float),
            'vx':    rng.uniform(-0.3, 0.3, n_particles),
            'vy':    rng.uniform(-0.6, -0.1, n_particles),
            'size':  rng.uniform(1.0, 2.5, n_particles),
            'alpha': rng.uniform(20, 70, n_particles).astype(float),
        }

        # Fonts
        def _font(name, size):
            try:
                return ImageFont.truetype(f"{FONT_DIR}/{name}", size)
            except Exception:
                return ImageFont.load_default()

        self.font_title  = _font("Oxanium-Bold.ttf", 30)
        self.font_sub    = _font("Oxanium-Regular.ttf", 19)
        self.font_tech   = _font("Oxanium-Light.ttf", 17)
        self.font_header = _font("Oxanium-Regular.ttf", 11)
        self.font_label  = _font("Oxanium-Regular.ttf", 13)
        self.font_time   = _font("Oxanium-Regular.ttf", 15)

        # Everything that never changes between frames is drawn once here;
        # draw_frame() starts from a copy instead of redrawing it.
        self._static_bg = self._build_static_bg()
        self._glow_sprite = self._build_glow_sprite()

    # ── Precomputed layers ───────────────────────────────────

    def _build_static_bg(self):
        img = Image.new('RGB', (WIDTH, HEIGHT), FL_BG_DARK)
        draw = ImageDraw.Draw(img, 'RGBA')
        self.draw_grid(draw)

        self.draw_rounded_panel(draw, (SPHERE_X, SPHERE_Y, SPHERE_W, SPHERE_H))
        self.draw_rounded_panel(draw, (SPEC_X, SPEC_Y, SPEC_W, SPEC_H))
        self.draw_rounded_panel(draw, (PADDING, WAVEFORM_Y, WAVEFORM_W, WAVEFORM_HEIGHT))
        self.draw_rounded_panel(draw, (VU_X, VU_Y, VU_W, VU_H))

        # Panel headers
        draw.text((SPEC_X + 12, SPEC_Y + 10), "SPECTRUM",
                  font=self.font_label, fill=FL_TEXT_DIM)
        draw.text((PADDING + 14, WAVEFORM_Y + 8), "WAVEFORM",
                  font=self.font_label, fill=FL_TEXT_DIM)
        draw.text((SPHERE_X + 52, SPHERE_Y + 20),
                  f"VISUALIZER · {self.cs['name'].upper()}",
                  font=self.font_label, fill=FL_TEXT_DIM)

        # VU labels
        draw.text((VU_X + 28, VU_Y + 8), "L", fill=FL_TEXT_DIM, font=self.font_header)
        draw.text((VU_X + 76, VU_Y + 8), "R", fill=FL_TEXT_DIM, font=self.font_header)

        # Tech corner brackets in the sphere panel
        bkt = 30
        bkt_c = (80, 80, 80, 100)
        corners = [
            (SPHERE_X + 12, SPHERE_Y + 12),
            (SPHERE_X + SPHERE_W - 12, SPHERE_Y + 12),
            (SPHERE_X + 12, SPHERE_Y + SPHERE_H - 12),
            (SPHERE_X + SPHERE_W - 12, SPHERE_Y + SPHERE_H - 12),
        ]
        for idx, (cx, cy) in enumerate(corners):
            dx = 1 if idx % 2 == 0 else -1
            dy = 1 if idx < 2 else -1
            draw.line([(cx, cy), (cx + dx * bkt, cy)], fill=bkt_c, width=2)
            draw.line([(cx, cy), (cx, cy + dy * bkt)], fill=bkt_c, width=2)

        # Waveform reference lines
        mid_y = WAVEFORM_Y + WAVEFORM_HEIGHT // 2
        wf_l = PADDING + 10
        wf_r = PADDING + WAVEFORM_W - 10
        for frac in (-0.5, -0.25, 0.25, 0.5):
            ry = mid_y + int(frac * WAVEFORM_HEIGHT * 0.8)
            draw.line([(wf_l, ry), (wf_r, ry)], fill=(220, 220, 220), width=1)

        return img

    def _build_glow_sprite(self, size=512):
        """Smooth radial bloom (replaces the old banded concentric circles)."""
        gl = self.cs['glow']
        yy, xx = np.mgrid[0:size, 0:size]
        r = np.sqrt((xx - size / 2) ** 2 + (yy - size / 2) ** 2) / (size / 2)
        alpha = (np.clip(1.0 - r, 0.0, 1.0) ** 2.2) * 60
        arr = np.zeros((size, size, 4), dtype=np.uint8)
        arr[..., 0], arr[..., 1], arr[..., 2] = gl[0], gl[1], gl[2]
        arr[..., 3] = alpha.astype(np.uint8)
        return Image.fromarray(arr, 'RGBA')

    # ── Helpers ──────────────────────────────────────────────

    @staticmethod
    def lerp_color(c1, c2, t):
        return (
            int(c1[0] + (c2[0] - c1[0]) * t),
            int(c1[1] + (c2[1] - c1[1]) * t),
            int(c1[2] + (c2[2] - c1[2]) * t),
        )

    @staticmethod
    def draw_rounded_panel(draw, box, radius=16, border=True, fill=FL_PANEL_BG):
        x, y, w, h = box
        draw.rounded_rectangle([x, y, x + w, y + h], radius=radius,
                               fill=fill, outline=None, width=0)
        draw.rounded_rectangle([x + 1, y + 1, x + w - 1, y + h - 1],
                               radius=radius - 1, fill=None,
                               outline=(235, 235, 235), width=1)
        if border:
            draw.rounded_rectangle([x, y, x + w, y + h], radius=radius,
                                   fill=None, outline=FL_BORDER, width=1)

    @staticmethod
    def draw_grid(draw):
        for x in range(0, WIDTH, 50):
            draw.line([(x, 0), (x, HEIGHT)], fill=(232, 232, 232), width=1)
        for y in range(0, HEIGHT, 50):
            draw.line([(0, y), (WIDTH, y)], fill=(232, 232, 232), width=1)

    # ── State update (sequential) ────────────────────────────

    def step_state(self, t):
        """Advance smoothing + particle state for one frame and return a
        picklable snapshot for draw_frame(). Must be called in frame order."""
        kick = self.audio.get_kick(t)
        target_pulse = (kick ** 1.5) * 1.2
        self.smooth_pulse = self.smooth_pulse * 0.7 + target_pulse * 0.3
        self.smooth_rot += 0.006 + self.smooth_pulse * 0.04
        self.smooth_rot_x += 0.003 + self.smooth_pulse * 0.015

        spectrum = self.audio.get_spectrum(t)
        self.smooth_spectrum = self.smooth_spectrum * 0.6 + spectrum * 0.4

        spec_bands = self.audio.get_spectrum_bands(t, 50)
        self.smooth_spec_bands = self.smooth_spec_bands * 0.65 + spec_bands * 0.35

        noise_vals = smooth_noise_3d(self.verts, t * 1.5, frequency=3.0, octaves=3)
        target_deform = np.power(noise_vals, 1.5) * self.smooth_pulse * 0.45
        self.smooth_deform = self.smooth_deform * 0.75 + target_deform * 0.25

        # Particles
        p = self.particles
        n = len(p['x'])
        p['x'] += p['vx'] + np.sin(t * 0.8 + np.arange(n)) * 0.15
        p['y'] += p['vy'] - self.smooth_pulse * 0.5
        wrapped = p['y'] < SPHERE_Y + 10
        p['y'][wrapped] = SPHERE_Y + SPHERE_H - 10
        bounced = (p['x'] < SPHERE_X + 10) | (p['x'] > SPHERE_X + SPHERE_W - 10)
        p['vx'][bounced] *= -1
        particle_alpha = np.minimum(p['alpha'] + self.smooth_pulse * 40, 120)

        lvl_l, lvl_r = self.audio.get_levels(t)

        return {
            'pulse':          self.smooth_pulse,
            'rot':            self.smooth_rot,
            'rot_x':          self.smooth_rot_x,
            'spectrum':       self.smooth_spectrum.copy(),
            'spec_bands':     self.smooth_spec_bands.copy(),
            'deform':         self.smooth_deform.copy(),
            'particle_x':     p['x'].copy(),
            'particle_y':     p['y'].copy(),
            'particle_alpha': particle_alpha,
            'levels':         (lvl_l, lvl_r),
        }

    # ── Background details (stateless) ───────────────────────

    def draw_background_details(self, draw, t, state):
        """Particles, scan-lines and tech-corner brackets inside the sphere area."""
        px_arr = state['particle_x']
        py_arr = state['particle_y']
        pa_arr = state['particle_alpha']
        sizes = self.particles['size']
        pc = self.cs['particle']

        # ── Floating particles ──
        for i in range(len(px_arr)):
            a = int(pa_arr[i])
            sz = sizes[i]
            px, py = int(px_arr[i]), int(py_arr[i])
            draw.ellipse([px - sz, py - sz, px + sz, py + sz],
                         fill=(pc[0], pc[1], pc[2], a))

        # ── Horizontal scan-lines ──
        scan_off = int(t * 30) % 8
        for y in range(SPHERE_Y + scan_off, SPHERE_Y + SPHERE_H, 8):
            draw.line([(SPHERE_X + 10, y), (SPHERE_X + SPHERE_W - 10, y)],
                      fill=(0, 0, 0, 5), width=1)

    # ── Main draw (pure function of t + state) ───────────────

    def draw_frame(self, t, state):
        pulse = state['pulse']
        ac = self.cs['accent']

        # ── Canvas (static layer precomputed in __init__) ──
        img = self._static_bg.copy()
        draw = ImageDraw.Draw(img, 'RGBA')

        # ════════════════════════════════════════════════════
        #  SPHERE AREA  (center panel — main visual)
        # ════════════════════════════════════════════════════
        cx = SPHERE_X + SPHERE_W // 2
        cy = SPHERE_Y + SPHERE_H // 2

        # Beat-reactive panel border
        border_a = int(30 + min(pulse, 1.0) * 140)
        draw.rounded_rectangle(
            [SPHERE_X, SPHERE_Y, SPHERE_X + SPHERE_W, SPHERE_Y + SPHERE_H],
            radius=16, fill=None, outline=(ac[0], ac[1], ac[2], border_a), width=1)

        # Faint guide circle inside the spectrum ring
        guide_r = SPHERE_RADIUS + 30 + pulse * 10
        draw.ellipse([cx - guide_r, cy - guide_r, cx + guide_r, cy + guide_r],
                     outline=(ac[0], ac[1], ac[2], 28), width=1)

        # ── Polar spectrum ring ──
        full_spec = np.concatenate((state['spectrum'][::-1], state['spectrum']))
        num_ring_pts = len(full_spec)
        base_ring_r = SPHERE_RADIUS + 50
        ring_pts = []
        for i in range(num_ring_pts):
            angle = (i / num_ring_pts) * 2 * math.pi - (math.pi / 2) + state['rot'] * 0.3
            r = base_ring_r + full_spec[i] * 140
            ring_pts.append((cx + math.cos(angle) * r, cy + math.sin(angle) * r))

        if len(ring_pts) > 2:
            ring_pts.append(ring_pts[0])
            gd = self.cs['glow_dim']
            gl = self.cs['glow']
            draw.line(ring_pts, fill=(gd[0], gd[1], gd[2], 40), width=14)
            draw.line(ring_pts, fill=(gl[0], gl[1], gl[2], 100), width=6)
            draw.line(ring_pts, fill=ac, width=2)

        # ── Background details ──
        self.draw_background_details(draw, t, state)

        # ── Ambient bloom behind sphere (smooth radial sprite) ──
        glow_d = int(SPHERE_RADIUS * 2 * (1.4 + pulse * 0.45))
        sprite = self._glow_sprite.resize((glow_d, glow_d))
        img.paste(sprite, (cx - glow_d // 2, cy - glow_d // 2), sprite)

        # ── 3-D Sphere (smooth coherent deformation) ──
        base_scale = 1.0 + pulse * 0.12
        displacement = self.vert_normals * state['deform'][:, np.newaxis]
        distorted = self.verts * base_scale + displacement

        cos_y, sin_y = math.cos(state['rot']), math.sin(state['rot'])
        ry_mat = np.array([[cos_y, 0, sin_y], [0, 1, 0], [-sin_y, 0, cos_y]])
        cos_x, sin_x = math.cos(state['rot_x']), math.sin(state['rot_x'])
        rx_mat = np.array([[1, 0, 0], [0, cos_x, -sin_x], [0, sin_x, cos_x]])
        r_verts = np.dot(distorted, np.dot(rx_mat, ry_mat)) * SPHERE_RADIUS

        proj = []
        for v in r_verts:
            z = v[2]
            f = 800 / (z + 1000)
            proj.append({'x': v[0] * f + cx, 'y': v[1] * f + cy, 'z': z})

        # Depth-sort edges back → front
        edge_depths = [((i, j), (proj[i]['z'] + proj[j]['z']) / 2) for i, j in self.edges]
        edge_depths.sort(key=lambda e: e[1])

        for (i, j), avg_z in edge_depths:
            p1, p2 = proj[i], proj[j]
            norm_z = (avg_z + SPHERE_RADIUS) / (SPHERE_RADIUS * 2)
            norm_z = max(0.0, min(1.0, norm_z))
            if norm_z < 0.08:
                continue
            alpha = int(norm_z * 255)
            col = self.lerp_color((200, 200, 200), ac, norm_z ** 0.8)
            w = 3 if norm_z > 0.7 else 2 if norm_z > 0.35 else 1
            draw.line([(p1['x'], p1['y']), (p2['x'], p2['y'])],
                      fill=col + (alpha,), width=w)

        # Vertex glow dots
        dc = self.cs['dot_color']
        for p in proj:
            nz = (p['z'] + SPHERE_RADIUS) / (SPHERE_RADIUS * 2)
            nz = max(0.0, min(1.0, nz))
            if nz > 0.55:
                dr = int(2 + nz * 2)
                da = int(nz * 180)
                draw.ellipse([p['x'] - dr, p['y'] - dr, p['x'] + dr, p['y'] + dr],
                             fill=(dc[0], dc[1], dc[2], da))

        # ════════════════════════════════════════════════════
        #  SPECTROGRAM  (left panel — vertical mirrored)
        # ════════════════════════════════════════════════════
        num_bands = 50
        smooth_spec_bands = state['spec_bands']

        sp_l = SPEC_X + 12
        sp_r = SPEC_X + SPEC_W - 12
        sp_max_w = sp_r - sp_l
        sp_top = SPEC_Y + 32          # clears the SPECTRUM header
        sp_bot = SPEC_Y + SPEC_H - 15
        sp_cx = (sp_l + sp_r) / 2

        spec_ys = []
        spec_vals = []
        for i in range(num_bands):
            val = min(float(smooth_spec_bands[i]), 1.0)
            y_pos = sp_bot - ((i + 0.5) / num_bands) * (sp_bot - sp_top)
            spec_ys.append(y_pos)
            spec_vals.append(val)

        layer_defs = [
            (1.0,  0.15, 25),
            (0.80, 0.40, 55),
            (0.55, 0.70, 110),
            (0.30, 0.90, 180),
            (0.15, 1.00, 230),
        ]
        ad = self.cs['accent_dim']
        for amp_frac, color_t, alpha in layer_defs:
            col = self.lerp_color(ad, ac, color_t)
            r_pts = [(sp_cx, spec_ys[0])]
            l_pts = [(sp_cx, spec_ys[0])]
            for k in range(num_bands):
                hw = spec_vals[k] * (sp_max_w / 2) * amp_frac
                r_pts.append((sp_cx + hw, spec_ys[k]))
                l_pts.append((sp_cx - hw, spec_ys[k]))
            r_pts.append((sp_cx, spec_ys[-1]))
            l_pts.append((sp_cx, spec_ys[-1]))
            draw.polygon(r_pts, fill=(col[0], col[1], col[2], alpha))
            draw.polygon(l_pts, fill=(col[0], col[1], col[2], alpha))

        # Edge contours
        r_edge = [(sp_cx + spec_vals[k] * sp_max_w / 2, spec_ys[k]) for k in range(num_bands)]
        l_edge = [(sp_cx - spec_vals[k] * sp_max_w / 2, spec_ys[k]) for k in range(num_bands)]
        draw.line(r_edge, fill=(ac[0], ac[1], ac[2], 100), width=1)
        draw.line(l_edge, fill=(ac[0], ac[1], ac[2], 100), width=1)
        draw.line([(sp_cx, sp_top), (sp_cx, sp_bot)], fill=(200, 200, 200), width=1)

        # ════════════════════════════════════════════════════
        #  WAVEFORM  (bottom strip — horizontal mirrored)
        # ════════════════════════════════════════════════════
        center_idx = int(t * self.audio.sr)
        window_samples = int(self.audio.sr * 4)  # 4 seconds
        start = center_idx - window_samples // 2
        end = center_idx + window_samples // 2

        if start < 0:
            wave_chunk = np.pad(self.audio.waveform_dense, (abs(start), 0))[:window_samples]
        elif end > len(self.audio.waveform_dense):
            wave_chunk = np.pad(self.audio.waveform_dense,
                                (0, end - len(self.audio.waveform_dense)))[start:]
        else:
            wave_chunk = self.audio.waveform_dense[start:end]

        res = 1500
        indices = np.linspace(0, max(len(wave_chunk) - 1, 1), res).astype(int)
        view_wave = wave_chunk[indices]

        mid_y = WAVEFORM_Y + WAVEFORM_HEIGHT // 2
        wf_l = PADDING + 10
        wf_r = PADDING + WAVEFORM_W - 10
        amp_sc = WAVEFORM_HEIGHT * 0.40

        wl = self.cs['wave_lo']
        wh = self.cs['wave_hi']
        n_pts = 800
        w_idx = np.linspace(0, res - 1, n_pts).astype(int)
        x_arr = [wf_l + (i / (n_pts - 1)) * (wf_r - wf_l) for i in range(n_pts)]
        a_arr = [abs(view_wave[w_idx[i]]) for i in range(n_pts)]

        for amp_frac, color_t, alpha in layer_defs:
            col = self.lerp_color(wl, wh, color_t)
            u_poly = ([(x_arr[0], mid_y)]
                      + [(x_arr[k], mid_y - a_arr[k] * amp_sc * amp_frac) for k in range(n_pts)]
                      + [(x_arr[-1], mid_y)])
            l_poly = ([(x_arr[0], mid_y)]
                      + [(x_arr[k], mid_y + a_arr[k] * amp_sc * amp_frac) for k in range(n_pts)]
                      + [(x_arr[-1], mid_y)])
            draw.polygon(u_poly, fill=(col[0], col[1], col[2], alpha))
            draw.polygon(l_poly, fill=(col[0], col[1], col[2], alpha))

        # Edge contours
        u_edge = [(x_arr[k], mid_y - a_arr[k] * amp_sc) for k in range(n_pts)]
        l_edge = [(x_arr[k], mid_y + a_arr[k] * amp_sc) for k in range(n_pts)]
        draw.line(u_edge, fill=(ac[0], ac[1], ac[2], 100), width=1)
        draw.line(l_edge, fill=(ac[0], ac[1], ac[2], 100), width=1)
        draw.line([(wf_l, mid_y), (wf_r, mid_y)], fill=(200, 200, 200), width=1)

        # Playhead
        ph_x = PADDING + WAVEFORM_W // 2
        draw.line([ph_x, WAVEFORM_Y + 8, ph_x, WAVEFORM_Y + WAVEFORM_HEIGHT - 8],
                  fill=(ac[0], ac[1], ac[2], 60), width=5)
        draw.line([ph_x, WAVEFORM_Y + 8, ph_x, WAVEFORM_Y + WAVEFORM_HEIGHT - 8],
                  fill=ac, width=2)

        # Time readout + track progress
        if self.total_dur:
            time_txt = (f"{int(t // 60):02d}:{int(t % 60):02d} / "
                        f"{int(self.total_dur // 60):02d}:{int(self.total_dur % 60):02d}")
            tb = draw.textbbox((0, 0), time_txt, font=self.font_time)
            draw.text((wf_r - (tb[2] - tb[0]) - 6, WAVEFORM_Y + 7), time_txt,
                      font=self.font_time, fill=FL_TEXT_DIM)

            prog_y = WAVEFORM_Y + WAVEFORM_HEIGHT - 6
            frac = min(t / self.total_dur, 1.0)
            draw.line([(wf_l, prog_y), (wf_r, prog_y)], fill=(225, 225, 225), width=3)
            draw.line([(wf_l, prog_y), (wf_l + frac * (wf_r - wf_l), prog_y)],
                      fill=ac, width=3)

        # ════════════════════════════════════════════════════
        #  VU METERS  (bottom-right — segmented gradient bars)
        # ════════════════════════════════════════════════════
        lvl_l, lvl_r = state['levels']

        bar_top = VU_Y + 25
        bar_bot = VU_Y + VU_H - 10
        bar_h = bar_bot - bar_top
        num_segs = 14
        seg_h = bar_h / num_segs
        seg_gap = 2

        for label, bx1, bx2, lvl in [
            ("L", VU_X + 20, VU_X + 48, lvl_l),
            ("R", VU_X + 68, VU_X + 96, lvl_r),
        ]:
            draw.rounded_rectangle([bx1 - 1, bar_top - 1, bx2 + 1, bar_bot + 1],
                                   radius=3, fill=(220, 220, 220))
            filled = int(lvl * num_segs)
            for s in range(num_segs):
                st = bar_bot - (s + 1) * seg_h + seg_gap
                sb = bar_bot - s * seg_h - seg_gap
                if s < filled:
                    frac = s / num_segs
                    if frac < 0.6:
                        col = self.cs['meter_lo']
                    elif frac < 0.8:
                        tb = (frac - 0.6) / 0.2
                        col = self.lerp_color(self.cs['meter_lo'], self.cs['meter_mid'], tb)
                    else:
                        tb = (frac - 0.8) / 0.2
                        col = self.lerp_color(self.cs['meter_mid'], self.cs['meter_hi'], tb)
                    draw.rectangle([bx1, st, bx2, sb], fill=col)
                else:
                    draw.rectangle([bx1, st, bx2, sb], fill=(230, 230, 230))

            # Peak indicator
            peak_y = bar_bot - int(lvl * bar_h)
            draw.rectangle([bx1, peak_y - 1, bx2, peak_y + 1], fill=(40, 40, 40))

        # ════════════════════════════════════════════════════
        #  METADATA OVERLAY  (top-right, frosted glass)
        # ════════════════════════════════════════════════════
        panel_w = 420
        panel_h = 85
        meta_x = WIDTH - panel_w - PADDING - 15
        meta_y = PADDING + 15

        draw.rounded_rectangle(
            [meta_x, meta_y, meta_x + panel_w, meta_y + panel_h],
            radius=12, fill=(255, 255, 255, 230),
            outline=(190, 190, 190, 180), width=1)

        # Accent stripe
        draw.rounded_rectangle(
            [meta_x, meta_y, meta_x + panel_w, meta_y + 4],
            radius=2, fill=ac)

        # Title & producer
        draw.text((meta_x + 14, meta_y + 14), self.meta['title'],
                  font=self.font_title, fill=FL_TEXT_MAIN)
        draw.text((meta_x + 14, meta_y + 50), f"Prod. {self.meta['producer']}",
                  font=self.font_sub, fill=FL_TEXT_DIM)

        # BPM + Key chips (right-aligned pills inside panel)
        chips = [c for c in (self.meta['bpm'], self.meta.get('key', '')) if c]
        chip_y = meta_y + 16
        for chip in chips:
            cb = draw.textbbox((0, 0), chip, font=self.font_tech)
            cw, ch = cb[2] - cb[0], cb[3] - cb[1]
            x1 = meta_x + panel_w - cw - 34
            draw.rounded_rectangle(
                [x1, chip_y - 5, meta_x + panel_w - 14, chip_y + ch + 7],
                radius=(ch + 12) // 2,
                fill=(ac[0], ac[1], ac[2], 26),
                outline=(ac[0], ac[1], ac[2], 70), width=1)
            draw.text((x1 + 10, chip_y), chip,
                      font=self.font_tech, fill=self.cs['accent_dim'])
            chip_y += ch + 16

        return np.array(img)

    # ── Sequential convenience API ───────────────────────────

    def render_frame(self, t):
        return self.draw_frame(t, self.step_state(t))

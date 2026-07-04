# src/config.py
import os
import random

# ──────────────────────────────────────────────────────────────
# NEUTRAL COLORS (shared by all schemes)
# ──────────────────────────────────────────────────────────────
FL_BG_DARK = (245, 245, 245)
FL_PANEL_BG = (255, 255, 255)
FL_BORDER = (200, 200, 200)
FL_TEXT_MAIN = (30, 30, 30)
FL_TEXT_DIM = (100, 100, 100)

# Absolute so rendering works regardless of the process's working directory
FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "fonts", "oxanium")

# ──────────────────────────────────────────────────────────────
# COLOR SCHEMES
# ──────────────────────────────────────────────────────────────
COLOR_SCHEMES = {
    # ── Warm tones ──
    'fire': {
        'name': 'Fire',
        'accent':      (230, 90, 20),
        'accent_dim':  (170, 60, 0),
        'secondary':   (100, 180, 50),
        'glow':        (230, 80, 10),
        'glow_dim':    (150, 50, 0),
        'wave_lo':     (140, 70, 15),
        'wave_hi':     (230, 140, 20),
        'particle':    (220, 110, 40),
        'meter_lo':    (60, 170, 40),
        'meter_mid':   (220, 160, 20),
        'meter_hi':    (220, 30, 20),
        'dot_color':   (230, 130, 60),
    },
    'ember': {
        'name': 'Ember',
        'accent':      (210, 45, 45),
        'accent_dim':  (150, 25, 25),
        'secondary':   (220, 150, 30),
        'glow':        (210, 40, 15),
        'glow_dim':    (140, 15, 0),
        'wave_lo':     (120, 50, 20),
        'wave_hi':     (220, 160, 30),
        'particle':    (210, 65, 25),
        'meter_lo':    (220, 130, 25),
        'meter_mid':   (220, 80, 15),
        'meter_hi':    (210, 30, 30),
        'dot_color':   (220, 110, 60),
    },
    'sunset': {
        'name': 'Sunset',
        'accent':      (230, 100, 70),
        'accent_dim':  (180, 65, 40),
        'secondary':   (200, 130, 60),
        'glow':        (220, 90, 50),
        'glow_dim':    (160, 55, 30),
        'wave_lo':     (150, 70, 50),
        'wave_hi':     (230, 150, 80),
        'particle':    (220, 120, 70),
        'meter_lo':    (200, 150, 50),
        'meter_mid':   (230, 110, 50),
        'meter_hi':    (220, 60, 50),
        'dot_color':   (230, 140, 90),
    },
    'coral': {
        'name': 'Coral',
        'accent':      (230, 80, 100),
        'accent_dim':  (180, 50, 70),
        'secondary':   (190, 120, 90),
        'glow':        (220, 70, 85),
        'glow_dim':    (160, 40, 55),
        'wave_lo':     (140, 55, 70),
        'wave_hi':     (230, 130, 120),
        'particle':    (220, 90, 100),
        'meter_lo':    (200, 110, 90),
        'meter_mid':   (230, 80, 80),
        'meter_hi':    (220, 40, 60),
        'dot_color':   (230, 120, 120),
    },
    # ── Cool tones ──
    'cyber': {
        'name': 'Cyber',
        'accent':      (0, 160, 220),
        'accent_dim':  (0, 100, 155),
        'secondary':   (0, 200, 150),
        'glow':        (0, 140, 210),
        'glow_dim':    (0, 70, 140),
        'wave_lo':     (0, 80, 110),
        'wave_hi':     (0, 200, 190),
        'particle':    (0, 150, 210),
        'meter_lo':    (0, 170, 120),
        'meter_mid':   (0, 210, 210),
        'meter_hi':    (60, 100, 210),
        'dot_color':   (70, 180, 220),
    },
    'arctic': {
        'name': 'Arctic',
        'accent':      (70, 160, 220),
        'accent_dim':  (40, 110, 170),
        'secondary':   (140, 185, 220),
        'glow':        (60, 150, 220),
        'glow_dim':    (25, 85, 155),
        'wave_lo':     (40, 80, 140),
        'wave_hi':     (130, 185, 220),
        'particle':    (100, 175, 220),
        'meter_lo':    (70, 160, 220),
        'meter_mid':   (130, 190, 220),
        'meter_hi':    (200, 220, 240),
        'dot_color':   (130, 190, 225),
    },
    'ocean': {
        'name': 'Ocean',
        'accent':      (20, 120, 190),
        'accent_dim':  (10, 80, 140),
        'secondary':   (40, 160, 160),
        'glow':        (15, 110, 180),
        'glow_dim':    (5, 60, 120),
        'wave_lo':     (15, 70, 120),
        'wave_hi':     (40, 170, 200),
        'particle':    (30, 130, 190),
        'meter_lo':    (20, 150, 150),
        'meter_mid':   (30, 180, 190),
        'meter_hi':    (50, 100, 200),
        'dot_color':   (60, 160, 200),
    },
    'teal': {
        'name': 'Teal',
        'accent':      (0, 170, 160),
        'accent_dim':  (0, 120, 115),
        'secondary':   (60, 190, 140),
        'glow':        (0, 155, 150),
        'glow_dim':    (0, 90, 90),
        'wave_lo':     (0, 90, 85),
        'wave_hi':     (40, 200, 175),
        'particle':    (20, 165, 155),
        'meter_lo':    (0, 170, 130),
        'meter_mid':   (30, 200, 170),
        'meter_hi':    (80, 210, 190),
        'dot_color':   (60, 190, 175),
    },
    # ── Purple / pink ──
    'violet': {
        'name': 'Violet',
        'accent':      (140, 60, 220),
        'accent_dim':  (95, 30, 170),
        'secondary':   (200, 80, 170),
        'glow':        (130, 50, 210),
        'glow_dim':    (80, 25, 140),
        'wave_lo':     (85, 40, 130),
        'wave_hi':     (200, 100, 220),
        'particle':    (160, 80, 220),
        'meter_lo':    (140, 60, 185),
        'meter_mid':   (200, 80, 170),
        'meter_hi':    (220, 40, 100),
        'dot_color':   (180, 130, 225),
    },
    'orchid': {
        'name': 'Orchid',
        'accent':      (190, 60, 160),
        'accent_dim':  (140, 35, 120),
        'secondary':   (160, 100, 180),
        'glow':        (180, 50, 145),
        'glow_dim':    (120, 25, 95),
        'wave_lo':     (110, 45, 100),
        'wave_hi':     (210, 120, 185),
        'particle':    (190, 80, 160),
        'meter_lo':    (170, 80, 160),
        'meter_mid':   (210, 70, 140),
        'meter_hi':    (220, 40, 100),
        'dot_color':   (210, 130, 185),
    },
    'rose': {
        'name': 'Rosé',
        'accent':      (210, 70, 110),
        'accent_dim':  (160, 45, 80),
        'secondary':   (180, 100, 120),
        'glow':        (200, 60, 95),
        'glow_dim':    (140, 35, 60),
        'wave_lo':     (130, 55, 75),
        'wave_hi':     (220, 130, 140),
        'particle':    (210, 90, 115),
        'meter_lo':    (190, 100, 110),
        'meter_mid':   (220, 70, 90),
        'meter_hi':    (220, 40, 65),
        'dot_color':   (220, 130, 145),
    },
    # ── Greens ──
    'lime': {
        'name': 'Lime',
        'accent':      (110, 200, 30),
        'accent_dim':  (75, 145, 15),
        'secondary':   (30, 200, 130),
        'glow':        (100, 200, 15),
        'glow_dim':    (50, 130, 0),
        'wave_lo':     (40, 100, 30),
        'wave_hi':     (130, 210, 50),
        'particle':    (100, 200, 45),
        'meter_lo':    (30, 180, 60),
        'meter_mid':   (120, 210, 30),
        'meter_hi':    (200, 220, 50),
        'dot_color':   (140, 215, 90),
    },
    'forest': {
        'name': 'Forest',
        'accent':      (40, 160, 80),
        'accent_dim':  (25, 115, 55),
        'secondary':   (80, 150, 100),
        'glow':        (35, 150, 70),
        'glow_dim':    (15, 90, 40),
        'wave_lo':     (25, 90, 55),
        'wave_hi':     (70, 185, 110),
        'particle':    (50, 155, 80),
        'meter_lo':    (35, 160, 70),
        'meter_mid':   (80, 190, 100),
        'meter_hi':    (140, 210, 130),
        'dot_color':   (80, 180, 110),
    },
    # ── Neutrals / monochrome ──
    'slate': {
        'name': 'Slate',
        'accent':      (80, 95, 115),
        'accent_dim':  (55, 65, 80),
        'secondary':   (110, 120, 140),
        'glow':        (70, 85, 105),
        'glow_dim':    (40, 50, 65),
        'wave_lo':     (60, 70, 85),
        'wave_hi':     (110, 130, 155),
        'particle':    (90, 105, 125),
        'meter_lo':    (80, 130, 130),
        'meter_mid':   (100, 115, 140),
        'meter_hi':    (130, 140, 165),
        'dot_color':   (110, 125, 150),
    },
    'graphite': {
        'name': 'Graphite',
        'accent':      (60, 60, 60),
        'accent_dim':  (40, 40, 40),
        'secondary':   (100, 100, 100),
        'glow':        (55, 55, 55),
        'glow_dim':    (35, 35, 35),
        'wave_lo':     (80, 80, 80),
        'wave_hi':     (40, 40, 40),
        'particle':    (70, 70, 70),
        'meter_lo':    (80, 80, 80),
        'meter_mid':   (55, 55, 55),
        'meter_hi':    (30, 30, 30),
        'dot_color':   (50, 50, 50),
    },
    # ── Gold / amber ──
    'gold': {
        'name': 'Gold',
        'accent':      (200, 160, 30),
        'accent_dim':  (150, 115, 15),
        'secondary':   (170, 140, 60),
        'glow':        (190, 150, 20),
        'glow_dim':    (130, 95, 5),
        'wave_lo':     (120, 95, 25),
        'wave_hi':     (210, 180, 50),
        'particle':    (200, 160, 40),
        'meter_lo':    (170, 150, 40),
        'meter_mid':   (210, 170, 30),
        'meter_hi':    (220, 140, 20),
        'dot_color':   (215, 180, 70),
    },
}

def pick_random_scheme():
    """Return (key, scheme_dict) for a random color scheme."""
    key = random.choice(list(COLOR_SCHEMES.keys()))
    return key, COLOR_SCHEMES[key]

# ──────────────────────────────────────────────────────────────
# DIMENSIONS  (16:9 Landscape — 1920 × 1080)
# ──────────────────────────────────────────────────────────────
WIDTH = 1920
HEIGHT = 1080
FPS = 30
PADDING = 30
GAP = 12

# ── Bottom strip: Waveform (left) + VU meters (right) ──
WAVEFORM_HEIGHT = 140
WAVEFORM_Y = HEIGHT - PADDING - WAVEFORM_HEIGHT          # 910
VU_W = 120
WAVEFORM_W = WIDTH - PADDING * 2 - VU_W - GAP            # 1728

VU_X = PADDING + WAVEFORM_W + GAP                        # 1770
VU_Y = WAVEFORM_Y                                        # 910
VU_H = WAVEFORM_HEIGHT                                   # 140

# ── Main area (above bottom strip) ──
MAIN_H = WAVEFORM_Y - PADDING - GAP                      # 868

# ── Spectrogram panel (left column) ──
SPEC_W = 150
SPEC_X = PADDING                                          # 30
SPEC_Y = PADDING                                          # 30
SPEC_H = MAIN_H                                          # 868

# ── Sphere area (center-right, main visual) ──
SPHERE_X = PADDING + SPEC_W + GAP                        # 192
SPHERE_W = WIDTH - PADDING - SPHERE_X                    # 1698
SPHERE_Y = PADDING                                       # 30
SPHERE_H = MAIN_H                                        # 868
SPHERE_RADIUS = 240

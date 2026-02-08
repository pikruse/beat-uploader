# src/config.py
import random

# ──────────────────────────────────────────────────────────────
# NEUTRAL COLORS (shared by all schemes)
# ──────────────────────────────────────────────────────────────
FL_BG_DARK = (245, 245, 245)
FL_PANEL_BG = (255, 255, 255)
FL_BORDER = (200, 200, 200)
FL_TEXT_MAIN = (30, 30, 30)
FL_TEXT_DIM = (100, 100, 100)

FONT_DIR = "fonts/oxanium"

# ──────────────────────────────────────────────────────────────
# COLOR SCHEMES
# ──────────────────────────────────────────────────────────────
COLOR_SCHEMES = {
    'fire': {
        'name': 'Fire',
        'accent':      (255, 120, 40),
        'accent_dim':  (200, 80, 0),
        'secondary':   (120, 215, 60),
        'glow':        (255, 100, 20),
        'glow_dim':    (180, 60, 0),
        'wave_lo':     (50, 100, 25),
        'wave_hi':     (255, 220, 40),
        'particle':    (255, 140, 50),
        'meter_lo':    (80, 200, 50),
        'meter_mid':   (255, 190, 30),
        'meter_hi':    (255, 40, 30),
        'dot_color':   (255, 160, 80),
    },
    'cyber': {
        'name': 'Cyber',
        'accent':      (0, 200, 255),
        'accent_dim':  (0, 120, 180),
        'secondary':   (0, 255, 180),
        'glow':        (0, 160, 255),
        'glow_dim':    (0, 80, 160),
        'wave_lo':     (0, 60, 80),
        'wave_hi':     (0, 255, 220),
        'particle':    (0, 180, 255),
        'meter_lo':    (0, 200, 140),
        'meter_mid':   (0, 255, 255),
        'meter_hi':    (80, 120, 255),
        'dot_color':   (100, 220, 255),
    },
    'violet': {
        'name': 'Violet',
        'accent':      (180, 80, 255),
        'accent_dim':  (120, 40, 200),
        'secondary':   (255, 100, 200),
        'glow':        (160, 60, 255),
        'glow_dim':    (100, 30, 160),
        'wave_lo':     (80, 30, 120),
        'wave_hi':     (255, 120, 255),
        'particle':    (200, 100, 255),
        'meter_lo':    (180, 80, 220),
        'meter_mid':   (255, 100, 200),
        'meter_hi':    (255, 50, 120),
        'dot_color':   (220, 160, 255),
    },
    'ember': {
        'name': 'Ember',
        'accent':      (255, 60, 60),
        'accent_dim':  (180, 30, 30),
        'secondary':   (255, 180, 40),
        'glow':        (255, 50, 20),
        'glow_dim':    (160, 20, 0),
        'wave_lo':     (100, 40, 10),
        'wave_hi':     (255, 200, 40),
        'particle':    (255, 80, 30),
        'meter_lo':    (255, 160, 30),
        'meter_mid':   (255, 100, 20),
        'meter_hi':    (255, 40, 40),
        'dot_color':   (255, 130, 80),
    },
    'arctic': {
        'name': 'Arctic',
        'accent':      (100, 200, 255),
        'accent_dim':  (50, 140, 200),
        'secondary':   (200, 230, 255),
        'glow':        (80, 180, 255),
        'glow_dim':    (30, 100, 180),
        'wave_lo':     (30, 60, 120),
        'wave_hi':     (180, 230, 255),
        'particle':    (140, 210, 255),
        'meter_lo':    (100, 200, 255),
        'meter_mid':   (180, 230, 255),
        'meter_hi':    (255, 255, 255),
        'dot_color':   (180, 225, 255),
    },
    'lime': {
        'name': 'Lime',
        'accent':      (160, 255, 40),
        'accent_dim':  (100, 180, 20),
        'secondary':   (40, 255, 160),
        'glow':        (140, 255, 20),
        'glow_dim':    (60, 160, 0),
        'wave_lo':     (15, 80, 30),
        'wave_hi':     (160, 255, 60),
        'particle':    (140, 255, 60),
        'meter_lo':    (40, 220, 80),
        'meter_mid':   (160, 255, 40),
        'meter_hi':    (255, 255, 60),
        'dot_color':   (180, 255, 120),
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

# src/audio.py
import librosa
import numpy as np


class AudioAnalyzer:
    def __init__(self, audio_path, fps, duration_limit=None):
        self.fps = fps
        print(f"Analyzing audio: {audio_path}")

        # Mono for analysis, stereo for VU meters
        self.y, self.sr = librosa.load(audio_path, sr=22050, mono=True)
        self.y_stereo, _ = librosa.load(audio_path, sr=22050, mono=False)
        if self.y_stereo.ndim == 1:
            self.y_stereo = np.vstack((self.y_stereo, self.y_stereo))

        self.duration = librosa.get_duration(y=self.y, sr=self.sr)
        if duration_limit:
            self.duration = min(self.duration, duration_limit)

        # ── 1. Kick / Onset Detection ──
        y_harm, y_perc = librosa.effects.hpss(self.y)
        onset_env = librosa.onset.onset_strength(y=y_perc, sr=self.sr)

        total_frames = int(self.duration * fps) + 10
        x_old = np.linspace(0, len(onset_env), len(onset_env))
        x_new = np.linspace(0, len(onset_env), total_frames)
        self.kick_data = np.interp(x_new, x_old, onset_env)
        if np.max(self.kick_data) > 0:
            self.kick_data /= np.max(self.kick_data)

        # ── 2. Spectrum (STFT) ──
        n_fft = 2048
        hop_length = int(self.sr / fps)
        self.D = np.abs(librosa.stft(self.y, n_fft=n_fft, hop_length=hop_length))
        self.D_db = librosa.amplitude_to_db(self.D, ref=np.max)
        self.D_db = (self.D_db + 80) / 80
        self.D_db[self.D_db < 0] = 0

        # ── 3. Dense Waveform ──
        self.waveform_dense = self.y

        # ── 4. BPM Detection ──
        tempo, _ = librosa.beat.beat_track(y=self.y, sr=self.sr)
        # tempo can be an ndarray in newer librosa; grab scalar
        self.bpm = float(np.atleast_1d(tempo)[0])

        # ── 5. Key Detection (Krumhansl-Schmuckler) ──
        chroma = librosa.feature.chroma_cqt(y=y_harm, sr=self.sr)
        chroma_avg = np.mean(chroma, axis=1)  # 12-bin pitch profile

        # Krumhansl-Kessler major/minor profiles
        major_profile = np.array([6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88])
        minor_profile = np.array([6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17])
        pitch_names = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']

        best_corr = -1
        best_key = 'C'
        best_mode = 'maj'
        for shift in range(12):
            rolled = np.roll(chroma_avg, -shift)
            for profile, mode in [(major_profile, 'maj'), (minor_profile, 'min')]:
                corr = np.corrcoef(rolled, profile)[0, 1]
                if corr > best_corr:
                    best_corr = corr
                    best_key = pitch_names[shift]
                    best_mode = mode
        self.key = best_key
        self.mode = best_mode  # 'maj' or 'min'
        self.key_label = f"{best_key}{'m' if best_mode == 'min' else ''}"

    # ── Public API ──────────────────────────────────────────

    def get_kick(self, t):
        idx = int(t * self.fps)
        if idx < len(self.kick_data):
            return self.kick_data[idx]
        return 0.0

    def get_spectrum(self, t):
        """Lower-frequency spectrum bins (first 100)."""
        idx = int(t * self.fps)
        if idx < self.D_db.shape[1]:
            return self.D_db[:100, idx]
        return np.zeros(100)

    def get_levels(self, t, window=0.05):
        """Stereo RMS levels (L, R) normalised to [0, 1]."""
        s_idx = int(t * self.sr)
        w_size = int(window * self.sr)
        s, e = max(0, s_idx - w_size), min(self.y.shape[0], s_idx + w_size)
        if e <= s:
            return 0.0, 0.0
        rms_l = np.sqrt(np.mean(self.y_stereo[0, s:e] ** 2))
        rms_r = np.sqrt(np.mean(self.y_stereo[1, s:e] ** 2))
        return min(rms_l * 5, 1.0), min(rms_r * 5, 1.0)

    def get_spectrum_bands(self, t, n_bands=50):
        """Spectrum grouped into *n_bands* log-spaced frequency bands.
        Uses all STFT bins for full low-end coverage."""
        idx = int(t * self.fps)
        if idx >= self.D_db.shape[1]:
            return np.zeros(n_bands)
        full = self.D_db[:, idx]
        n_bins = len(full)
        band_edges = np.unique(
            np.concatenate([[0], np.logspace(0, np.log10(n_bins), n_bands).astype(int)])
        )
        band_edges = np.clip(band_edges, 0, n_bins)
        if len(band_edges) < n_bands + 1:
            band_edges = np.linspace(0, n_bins, n_bands + 1).astype(int)
        bands = np.zeros(n_bands)
        for i in range(min(n_bands, len(band_edges) - 1)):
            s, e = int(band_edges[i]), int(band_edges[i + 1])
            if e > s:
                bands[i] = np.max(full[s:e])
            elif s < n_bins:
                bands[i] = full[s]
        return bands

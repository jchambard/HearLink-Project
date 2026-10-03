import numpy as np
from scipy.interpolate import interp1d
from typing import List, Tuple


class DelayAndSumBeamformer:
    MIC_ANGLES_RAD = np.array([0, np.pi / 2, np.pi, 3 * np.pi / 2])  # Front, Right, Back, Left

    def __init__(self, radius_m: float = 0.15, num_beams: int = 24,
                 sample_rate: int = 16000, speed_of_sound_mps: float = 343.0):
        self.radius_m = radius_m
        self.num_beams = num_beams
        self.sample_rate = sample_rate
        self.c = speed_of_sound_mps
        self.beam_angles_deg = np.linspace(0, 360, num_beams, endpoint=False)
        self.beam_angles_rad = np.deg2rad(self.beam_angles_deg)

    def _compute_delays(self, steer_rad: float) -> np.ndarray:
        """Fractional sample delays for each mic relative to mic 0."""
        delays = (self.radius_m / self.c) * np.cos(steer_rad - self.MIC_ANGLES_RAD) * self.sample_rate
        return delays - delays[0]

    def steer_beam(self, audio: np.ndarray, steer_rad: float) -> np.ndarray:
        """Delay-and-sum beam toward steer_rad. audio shape: (4, N). Returns (N,)."""
        n_samples = audio.shape[1]
        sample_indices = np.arange(n_samples)
        output = np.zeros(n_samples, dtype=np.float32)
        delays = self._compute_delays(steer_rad)
        for ch, delay in enumerate(delays):
            interp = interp1d(sample_indices, audio[ch].astype(np.float32),
                              kind='linear', fill_value='extrapolate')
            shifted_indices = sample_indices - delay
            output += interp(shifted_indices)
        return output / audio.shape[0]

    def detect_directions(self, audio: np.ndarray, top_k: int = 3) -> List[Tuple[float, float, np.ndarray]]:
        """
        Steer beams to all angles, compute energy, smooth, find peaks.
        Returns list of (angle_deg, energy, beam_audio_1d) for top-k directions
        above the 2×median energy threshold.
        """
        energies = np.zeros(self.num_beams)
        beam_outputs = []

        for i, angle_rad in enumerate(self.beam_angles_rad):
            beam = self.steer_beam(audio, angle_rad)
            beam_outputs.append(beam)
            energies[i] = float(np.mean(beam ** 2))

        # 3-tap moving average smoothing
        smoothed = np.convolve(energies, [1 / 3, 1 / 3, 1 / 3], mode='same')

        threshold = 1.5 * np.median(smoothed)
        above = smoothed > threshold
        if not np.any(above):
            return []

        # Simple peak picking: local maxima above threshold, take top-k
        peaks = []
        for i in range(self.num_beams):
            prev_i = (i - 1) % self.num_beams
            next_i = (i + 1) % self.num_beams
            if above[i] and smoothed[i] >= smoothed[prev_i] and smoothed[i] >= smoothed[next_i]:
                peaks.append((self.beam_angles_deg[i], float(smoothed[i]), beam_outputs[i]))

        peaks.sort(key=lambda x: x[1], reverse=True)
        return peaks[:top_k]

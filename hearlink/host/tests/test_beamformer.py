import numpy as np
import pytest
from audio.beamformer import DelayAndSumBeamformer

SAMPLE_RATE = 16000
RADIUS = 0.15
C = 343.0


def make_impulse_signal(source_angle_deg: float, n_samples: int = 1600,
                        impulse_offset: int = 200) -> np.ndarray:
    """Generate synthetic 4-channel signal as if a impulse arrives from source_angle_deg."""
    source_rad = np.deg2rad(source_angle_deg)
    mic_angles = np.array([0, np.pi / 2, np.pi, 3 * np.pi / 2])
    # Negative sign: mic closest to source has smallest (most negative) delay → arrives earliest
    delays_samples = -(RADIUS / C) * np.cos(source_rad - mic_angles) * SAMPLE_RATE

    audio = np.zeros((4, n_samples), dtype=np.float32)
    for ch in range(4):
        idx = int(round(impulse_offset + delays_samples[ch]))
        if 0 <= idx < n_samples:
            audio[ch, idx] = 1.0
    return audio


class TestBeamformerDirections:
    def setup_method(self):
        self.bf = DelayAndSumBeamformer(radius_m=RADIUS, num_beams=24, sample_rate=SAMPLE_RATE)

    @pytest.mark.parametrize("angle", [0, 90, 180, 270])
    def test_impulse_detected_within_tolerance(self, angle):
        audio = make_impulse_signal(angle, n_samples=1600)
        detections = self.bf.detect_directions(audio, top_k=3)
        assert len(detections) > 0, f"No detection for angle {angle}°"
        best_angle, _, _ = detections[0]
        diff = abs(best_angle - angle)
        diff = min(diff, 360 - diff)  # wrap
        assert diff <= 15, f"Expected ~{angle}°, got {best_angle}° (diff={diff}°)"

    def test_noise_only_no_detections(self):
        rng = np.random.default_rng(42)
        audio = rng.standard_normal((4, 1600)).astype(np.float32)
        detections = self.bf.detect_directions(audio, top_k=3)
        assert len(detections) == 0, f"Expected no detections on noise, got {detections}"

    def test_detect_returns_cached_beam_audio(self):
        audio = make_impulse_signal(90, n_samples=1600)
        detections = self.bf.detect_directions(audio, top_k=3)
        for angle, energy, beam_audio in detections:
            assert beam_audio.ndim == 1
            assert len(beam_audio) == 1600

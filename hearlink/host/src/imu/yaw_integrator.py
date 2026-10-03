import numpy as np
import logging

GYRO_SCALE = 131.0
CALIBRATION_SAMPLES = 200
DT = 0.01  # fixed 100 Hz


class YawIntegrator:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._cal_samples: list[float] = []
        self._bias_dps: float = 0.0
        self._calibrated: bool = False
        self._yaw_deg: float = 0.0

    def add_sample(self, raw: int, timestamp_us: int = 0):
        rate_dps = raw / GYRO_SCALE
        if not self._calibrated:
            self._cal_samples.append(rate_dps)
            if len(self._cal_samples) >= CALIBRATION_SAMPLES:
                self._bias_dps = float(np.mean(self._cal_samples))
                std = float(np.std(self._cal_samples))
                self.logger.info(f"IMU calibrated: bias={self._bias_dps:.3f} °/s, std={std:.3f} °/s")
                if std > 5.0:
                    self.logger.warning(f"High IMU bias std ({std:.1f} °/s) — was device moving during cal?")
                self._calibrated = True
            return

        corrected = rate_dps - self._bias_dps
        self._yaw_deg = (self._yaw_deg + corrected * DT) % 360

    def is_calibrated(self) -> bool:
        return self._calibrated

    def get_yaw(self) -> float:
        return self._yaw_deg

    def reset(self):
        self._cal_samples = []
        self._bias_dps = 0.0
        self._calibrated = False
        self._yaw_deg = 0.0

    def progress(self) -> float:
        if self._calibrated:
            return 1.0
        return len(self._cal_samples) / CALIBRATION_SAMPLES

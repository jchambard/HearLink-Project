import pytest
from imu.yaw_integrator import YawIntegrator, GYRO_SCALE, CALIBRATION_SAMPLES


class TestCalibration:
    def test_calibration_completes(self):
        yi = YawIntegrator()
        for _ in range(CALIBRATION_SAMPLES):
            yi.add_sample(int(1 * GYRO_SCALE))  # 1 °/s
        assert yi.is_calibrated()

    def test_bias_value(self):
        yi = YawIntegrator()
        for _ in range(CALIBRATION_SAMPLES):
            yi.add_sample(int(1 * GYRO_SCALE))
        assert abs(yi._bias_dps - 1.0) < 0.01

    def test_not_calibrated_before_enough_samples(self):
        yi = YawIntegrator()
        for _ in range(CALIBRATION_SAMPLES - 1):
            yi.add_sample(0)
        assert not yi.is_calibrated()


class TestIntegration:
    def test_zero_after_calibration(self):
        yi = YawIntegrator()
        for _ in range(CALIBRATION_SAMPLES):
            yi.add_sample(int(1 * GYRO_SCALE))
        # bias = 1.0 °/s; feed same rate → corrected = 0 → yaw stays 0
        for _ in range(100):
            yi.add_sample(int(1 * GYRO_SCALE))
        assert abs(yi.get_yaw()) < 0.01

    def test_integration_45dps_for_2s(self):
        yi = YawIntegrator()
        # calibrate with 1 °/s bias
        for _ in range(CALIBRATION_SAMPLES):
            yi.add_sample(int(1 * GYRO_SCALE))
        # feed 46 °/s raw → corrected = 46 - 1 = 45 °/s for 200 samples (2 s)
        for _ in range(200):
            yi.add_sample(int(46 * GYRO_SCALE))
        expected = 45 * 2.0  # 90°
        assert abs(yi.get_yaw() - expected) < 1.0

    def test_wrap_past_360(self):
        yi = YawIntegrator()
        for _ in range(CALIBRATION_SAMPLES):
            yi.add_sample(0)  # bias = 0
        # feed 360 °/s for 101 samples → yaw should wrap near 1°
        for _ in range(101):
            yi.add_sample(int(360 * GYRO_SCALE))
        assert yi.get_yaw() < 360


class TestProgress:
    def test_progress_starts_zero(self):
        yi = YawIntegrator()
        assert yi.progress() == 0.0

    def test_progress_increases(self):
        yi = YawIntegrator()
        for _ in range(100):
            yi.add_sample(0)
        assert abs(yi.progress() - 0.5) < 0.01

    def test_progress_one_when_calibrated(self):
        yi = YawIntegrator()
        for _ in range(CALIBRATION_SAMPLES):
            yi.add_sample(0)
        assert yi.progress() == 1.0


class TestReset:
    def test_reset_clears_state(self):
        yi = YawIntegrator()
        for _ in range(CALIBRATION_SAMPLES):
            yi.add_sample(int(10 * GYRO_SCALE))
        yi.reset()
        assert not yi.is_calibrated()
        assert yi.get_yaw() == 0.0

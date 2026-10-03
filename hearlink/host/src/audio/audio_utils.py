import numpy as np
from scipy.signal import windows


def int32_to_float(audio_int32: np.ndarray) -> np.ndarray:
    return audio_int32.astype(np.float32) / (256.0 * 2 ** 23)


def hann_window(n: int) -> np.ndarray:
    return windows.hann(n)

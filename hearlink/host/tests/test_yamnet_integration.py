import numpy as np
import pytest
from classification.yamnet_classifier import YAMNetClassifier


@pytest.mark.slow
def test_yamnet_loads_and_classifies():
    clf = YAMNetClassifier()
    # 1 second of 440 Hz sine at 16 kHz
    t = np.linspace(0, 1.0, 16000, endpoint=False)
    audio = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    results = clf.classify(audio, top_k=5)
    assert len(results) > 0
    names = [r[0] for r in results]
    confidences = [r[1] for r in results]
    assert all(0.0 <= c <= 1.0 for c in confidences)
    # Check all class names are non-empty strings
    assert all(isinstance(n, str) and len(n) > 0 for n in names)

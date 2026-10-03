import csv
import logging
import numpy as np
import tensorflow as tf
import tensorflow_hub as hub
from typing import List, Tuple

YAMNET_URL = 'https://tfhub.dev/google/yamnet/1'


class YAMNetClassifier:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.logger.info("Loading YAMNet model...")
        self.model = hub.load(YAMNET_URL)
        self.logger.info("YAMNet model loaded.")
        self._class_names = self._load_class_names()

    def _load_class_names(self) -> List[str]:
        class_map_path = self.model.class_map_path().numpy().decode('utf-8')
        names = []
        with tf.io.gfile.GFile(class_map_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                names.append(row['display_name'])
        return names

    def classify(self, audio: np.ndarray, top_k: int = 5) -> List[Tuple[str, float]]:
        """Classify mono float32 audio in [-1, 1]. Returns [(class_name, confidence), ...]."""
        if audio.ndim > 1:
            self.logger.warning("Expected mono audio; flattening.")
            audio = audio.flatten()
        audio = audio.astype(np.float32)
        scores, embeddings, log_mel = self.model(audio)
        mean_scores = np.mean(scores.numpy(), axis=0)
        top_indices = np.argsort(mean_scores)[::-1][:top_k]
        return [(self._class_names[i], float(mean_scores[i])) for i in top_indices]

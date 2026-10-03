import yaml
import logging
from pathlib import Path
from enum import IntEnum
from typing import List, Tuple, Optional


class SoundCategory(IntEnum):
    DANGEROUS = 0
    SOCIAL = 1
    AMBIENT = 2


class CategoryMapper:
    def __init__(self, config_path: str):
        self.logger = logging.getLogger(__name__)
        with open(config_path) as f:
            cfg = yaml.safe_load(f)

        self._categories: dict[SoundCategory, set[str]] = {
            SoundCategory.DANGEROUS: {s.lower() for s in cfg.get('dangerous', [])},
            SoundCategory.SOCIAL: {s.lower() for s in cfg.get('social', [])},
            SoundCategory.AMBIENT: {s.lower() for s in cfg.get('ambient', [])},
        }
        thresholds = cfg.get('confidence_thresholds', {})
        self._thresholds: dict[SoundCategory, float] = {
            SoundCategory.DANGEROUS: thresholds.get('dangerous', 0.3),
            SoundCategory.SOCIAL: thresholds.get('social', 0.4),
            SoundCategory.AMBIENT: thresholds.get('ambient', 0.5),
        }

    def map_predictions(self, predictions: List[Tuple[str, float]]) -> List[Tuple[SoundCategory, float, str]]:
        """Map YAMNet predictions to (category, confidence, class_name), filtered by threshold."""
        results = []
        for class_name, confidence in predictions:
            cat = self._find_category(class_name)
            if cat is not None and confidence >= self._thresholds[cat]:
                results.append((cat, confidence, class_name))
        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def _find_category(self, class_name: str) -> Optional[SoundCategory]:
        name_lower = class_name.lower()
        for cat, names in self._categories.items():
            if name_lower in names:
                return cat
        return None

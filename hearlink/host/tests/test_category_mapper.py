import pytest
import yaml
import tempfile
import os
from classification.category_mapper import CategoryMapper, SoundCategory


@pytest.fixture
def config_file(tmp_path):
    cfg = {
        'dangerous': ['Siren', 'Fire alarm', 'Screaming'],
        'social': ['Speech', 'Doorbell'],
        'ambient': ['Music', 'Dog'],
        'confidence_thresholds': {
            'dangerous': 0.3,
            'social': 0.4,
            'ambient': 0.5,
        }
    }
    p = tmp_path / 'categories.yaml'
    with open(p, 'w') as f:
        yaml.dump(cfg, f)
    return str(p)


class TestCategoryMapper:
    def test_dangerous_class_mapped(self, config_file):
        mapper = CategoryMapper(config_file)
        results = mapper.map_predictions([('Siren', 0.85)])
        assert len(results) == 1
        cat, conf, name = results[0]
        assert cat == SoundCategory.DANGEROUS
        assert abs(conf - 0.85) < 1e-6
        assert name == 'Siren'

    def test_below_threshold_filtered(self, config_file):
        mapper = CategoryMapper(config_file)
        results = mapper.map_predictions([('Siren', 0.1)])  # threshold is 0.3
        assert len(results) == 0

    def test_above_threshold_kept(self, config_file):
        mapper = CategoryMapper(config_file)
        results = mapper.map_predictions([('Music', 0.6)])  # threshold 0.5
        assert len(results) == 1

    def test_ambient_below_threshold_dropped(self, config_file):
        mapper = CategoryMapper(config_file)
        results = mapper.map_predictions([('Music', 0.45)])  # threshold 0.5
        assert len(results) == 0

    def test_case_insensitive_siren(self, config_file):
        mapper = CategoryMapper(config_file)
        results = mapper.map_predictions([('siren', 0.9)])
        assert len(results) == 1 and results[0][0] == SoundCategory.DANGEROUS

    def test_case_insensitive_SIREN(self, config_file):
        mapper = CategoryMapper(config_file)
        results = mapper.map_predictions([('SIREN', 0.9)])
        assert len(results) == 1

    def test_sorted_by_confidence(self, config_file):
        mapper = CategoryMapper(config_file)
        results = mapper.map_predictions([
            ('Music', 0.7),
            ('Siren', 0.4),
            ('Speech', 0.8),
        ])
        assert len(results) == 3
        confs = [r[1] for r in results]
        assert confs == sorted(confs, reverse=True)

    def test_unknown_class_ignored(self, config_file):
        mapper = CategoryMapper(config_file)
        results = mapper.map_predictions([('UnknownNoise', 0.99)])
        assert len(results) == 0

    def test_multiple_categories_in_single_call(self, config_file):
        mapper = CategoryMapper(config_file)
        results = mapper.map_predictions([
            ('Siren', 0.85),
            ('Speech', 0.75),
            ('Music', 0.60),
        ])
        cats = [r[0] for r in results]
        assert SoundCategory.DANGEROUS in cats
        assert SoundCategory.SOCIAL in cats
        assert SoundCategory.AMBIENT in cats

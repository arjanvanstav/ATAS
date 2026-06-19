"""
Tests for config/settings.py and config/functions.py.
"""

from atas.config.settings import get_settings
import atas.config.functions as functions

settings = get_settings()


class TestSettings:
    def test_repr(self):
        print(settings)

    def test_describe(self):
        print(settings.describe())

    def test_to_df(self):
        print(settings.to_df())


class TestConfigFuncs:
    def test_poisson_distribution_returns_points(self):
        pts = functions.Poisson_distribution(0, 10000, 0, 10000)
        assert pts.ndim == 2
        assert pts.shape[1] == 2
        assert len(pts) > 0

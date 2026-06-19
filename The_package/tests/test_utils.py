"""
Tests for utils/util_OSMnx.py.
"""

from atas.utils.util_OSMnx import get_graph, get_features


class TestUtilsOSMnx:
    def test_get_graph(self):
        G = get_graph("Groningen")

    def test_get_features(self):
        gdf = get_features("Groningen")

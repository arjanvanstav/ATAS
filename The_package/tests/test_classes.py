"""
Tests for core/_classes.py — Database and Network.

Run from The_package/: pytest tests/test_classes.py -v
"""

import os
from atas.core._classes import Database, Network

CSV      = "tests/TestDatasets/test.csv"
GEOPACKAGE = os.path.abspath("tests/TestDatasets/test.gpkg")

network  = Network("Amsterdam", store_in_file=True,
                   store_dir=os.path.expanduser("~/.percolation_cache/"))
database = Database(CSV, GEOPACKAGE)


class TestDatabase:
    def test_init(self):
        Database(CSV, GEOPACKAGE)

    def test_get_cities(self):
        cities = database.get_cities()
        assert len(cities) >= 1

    def test_load_network(self):
        database.set_city("Amsterdam")
        database.load_network(network)

    def test_obtain_features(self):
        database.obtain_features()

    def test_pre_process(self):
        # Fresh instances required: load_network mutates network.graph_pedestrian
        # in-memory (adds drive-network nodes without x/y via add_edges_to_ped_network),
        # so re-using the shared module-level network causes KeyError: 'x' on the
        # second get_pedestrian_nodes_df() call.
        net = Network("Amsterdam", store_in_file=True,
                      store_dir=os.path.expanduser("~/.percolation_cache/"))
        db = Database(CSV, GEOPACKAGE)
        db.set_city("Amsterdam")
        db.load_network(net)
        db.obtain_features()
        db.pre_process()

    def test_create_pts_per_neighborhood(self):
        database.create_pts_per_neighborhood()

    def test_remove_f_edges(self):
        database.remove_f_edges(0.2, use_population=False, use_amenity=True)

    def test_move_transit_simple(self):
        database.link_busses()
        database.move_transit_minimal()

    def test_calculate_distances_to_nearest_transit(self):
        database.calculate_distances_to_nearest_transit()

    def test_get_dist_per_neighborhood(self):
        database.get_dist_per_neighborhood()

    def test_get_demographic_average_distance(self):
        database.get_demographic_average_distance()

    def test_to_csv(self):
        database.to_csv(limit=10)

"""
test_accessibility.py - Integration tests for accessibility computations (t_walk, attractiveness, R5).

Tests that require real OSM/GTFS data (~/datasets/) are skipped automatically when absent.
Plots are written to pytest's tmp_path so they never pollute debug/.
"""
import os
import pytest
import matplotlib
matplotlib.use("Agg")
from datetime import datetime
from atas.core._classes import Network, Database
from atas.config.data_path import PBF_FILE, GTFS_FILE

csv  = "tests/TestDatasets/test.csv"
geopackage = os.path.abspath("tests/TestDatasets/test.gpkg")

_real_data_available = PBF_FILE.exists() and GTFS_FILE.exists()
requires_real_data = pytest.mark.skipif(
    not _real_data_available,
    reason="Real OSM/GTFS data not available at ~/datasets/",
)


def test_t_walk_full(tmp_path):
    """Integration test: database → t_walk → geometry → visualization."""
    from atas.core._t_walk import compute_t_walk, attach_geometry_to_t_walk
    from atas.utils.util_plotting import plot_t_walk_map

    network = Network(
        "Amsterdam",
        store_in_file=True,
        store_dir=os.path.expanduser("~/.percolation_cache/")
    )
    database = Database(csv, geopackage)
    database.set_city("Amsterdam")
    database.load_network(network)
    database.pre_process()
    database.obtain_features()

    df  = compute_t_walk(database, network)
    gdf = attach_geometry_to_t_walk(database, df)
    plot_t_walk_map(gdf, storage_folder=str(tmp_path), name="t_walk")

    assert len(df) > 0
    assert len(gdf) > 0
    assert (tmp_path / "t_walk.png").exists()


def test_attractiveness_full(tmp_path):
    """Integration test: database → attractiveness → geometry → visualization."""
    from atas.core._attractiveness import compute_attractiveness
    from atas.utils.util_plotting import attach_geometry_to_attractiveness, plot_attractiveness_map

    network  = Network("Amsterdam", store_in_file=True)
    database = Database(csv, geopackage)
    database.set_city("Amsterdam")
    database.load_network(network)
    database.pre_process()

    df_attr  = compute_attractiveness(database, normalize_cols=True)
    gdf_attr = attach_geometry_to_attractiveness(database, df_attr)
    plot_attractiveness_map(gdf_attr, storage_folder=str(tmp_path), name="attractiveness")

    assert len(df_attr) > 0
    assert len(gdf_attr) > 0
    assert (tmp_path / "attractiveness.png").exists()
    assert "attractiveness" in df_attr.columns
    assert df_attr["attractiveness"].notna().all()
    assert (df_attr["attractiveness"] >= 0).all()


@requires_real_data
def test_t_travel_matrix_small(tmp_path):
    """Integration test: Database → centroids → R5 → OD matrix. Uses small sample to keep runtime low."""
    from atas.core._t_travel import compute_t_travel_matrix, compute_avg_travel_time_per_origin
    from atas.core._accessibility_model import _get_neighborhood_centroids
    from atas.utils.util_plotting import attach_geometry_to_t_travel, plot_t_travel_avg_map

    network  = Network("Amsterdam", store_in_file=True)
    database = Database(csv, geopackage)
    database.set_city("Amsterdam")
    database.load_network(network)
    database.pre_process()
    database.obtain_features()
    database.create_pts_per_neighborhood()

    network.build_r5_network(osm_pbf_path=PBF_FILE, gtfs_files=[GTFS_FILE])

    centroids = _get_neighborhood_centroids(database).sample(517)
    df = compute_t_travel_matrix(
        network=network,
        origins=centroids.copy(),
        destinations=centroids.copy(),
        departure_time=datetime(2026, 4, 28, 8, 0),
        batch_size=10
    )

    assert len(df) > 0
    assert "from_id" in df.columns
    assert "to_id" in df.columns
    assert "travel_time" in df.columns
    assert df["from_id"].nunique() > 1
    assert df["to_id"].nunique() > 1
    assert df["travel_time"].notna().mean() > 0.9
    assert len(df) / (len(centroids) ** 2) > 0.5
    assert df["travel_time"].max() > 20
    assert df["travel_time"].median() > 10

    gdf = attach_geometry_to_t_travel(database, compute_avg_travel_time_per_origin(df))
    plot_t_travel_avg_map(gdf, storage_folder=str(tmp_path), name="t_travel")
    assert (tmp_path / "t_travel.png").exists()


@requires_real_data
def test_accessibility_score_full(tmp_path):
    """Full integration test for compute_accessibility_score()."""
    from datetime import timedelta
    from atas.core._accessibility_score import compute_accessibility_score
    from atas.utils.util_plotting import attach_geometry_to_accessibility_score, plot_accessibility_score_map

    network  = Network("Amsterdam", store_in_file=True)
    database = Database(csv, geopackage)
    database.set_city("Amsterdam")
    database.load_network(network)
    database.obtain_features()
    database.pre_process()
    network.build_r5_network(osm_pbf_path=PBF_FILE, gtfs_files=[GTFS_FILE])

    df  = compute_accessibility_score(
        network=network, database=database,
        departure_time=datetime(2026, 4, 28, 8, 0),
        beta=0.1, t_travel_max_time=timedelta(minutes=120),
        print_progress=True
    )
    gdf = attach_geometry_to_accessibility_score(database, df)
    plot_accessibility_score_map(gdf, storage_folder=str(tmp_path), name="accessibility_score")

    assert len(df) > 0
    assert "accessibility_score" in df.columns
    assert (df["accessibility_score"] > 0).all()
    assert len(df) / database.conn.sql("SELECT COUNT(*) FROM Neighborhoods").fetchone()[0] > 0.5
    assert len(gdf) > 0
    assert (tmp_path / "accessibility_score.png").exists()


@requires_real_data
def test_benefit(tmp_path):
    """Integration test: database → compute_benefit → geometry → visualization."""
    from atas.core._benefit import compute_benefit
    from atas.utils.util_plotting import attach_geometry_to_benefit, plot_benefit_map

    network  = Network("Amsterdam", store_in_file=True)
    database = Database(csv, geopackage)
    database.set_city("Amsterdam")
    database.load_network(network)
    database.obtain_features()
    database.pre_process()
    network.build_r5_network(osm_pbf_path=PBF_FILE, gtfs_files=[GTFS_FILE])

    df  = compute_benefit(
        network=network, database=database,
        departure_time=datetime(2026, 4, 28, 8, 0),
        beta=0.1, print_progress=True
    )
    gdf = attach_geometry_to_benefit(database, df)
    plot_benefit_map(gdf, storage_folder=str(tmp_path), name="benefit_score")

    assert len(df) > 0
    assert "benefit_score" in df.columns
    assert df["benefit_score"].notna().all()
    assert (df["benefit_score"] >= 0).any()
    assert len(gdf) > 0
    assert (tmp_path / "benefit_score.png").exists()

"""
run_correlations.py — Compute all metrics and generate the correlation plot.

Runs R5 twice (rush hour 08:00 + off-hours 10:30) so the rush vs off-hours
panel in metric_correlations.png is populated.

compute_t_walk mutates the pedestrian graph in-memory, so it is called only
once; t_walk_min is derived from the result and reused for both OD matrices.
"""

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, "src")

import matplotlib
matplotlib.use("Agg")

from atas.core._classes import Network, Database
from atas.core._t_walk import compute_t_walk, attach_geometry_to_t_walk
from atas.core._attractiveness import compute_attractiveness
from atas.core._accessibility_score import _apply_gravity_model
from atas.core._accessibility_model import _get_t_travel_od_matrix
from atas.core._benefit import _apply_benefit_model
from atas.config.data_path import PBF_FILE, GTFS_FILE
from atas.utils.util_plotting import (
    attach_geometry_to_accessibility_score,
    attach_geometry_to_benefit,
    plot_metric_correlations,
)

CSV  = "tests/TestDatasets/test.csv"
GPKG = os.path.abspath("tests/TestDatasets/test.gpkg")
OUT  = "debug"
os.makedirs(OUT, exist_ok=True)

# Rush hour is the canonical departure time for accessibility and benefit scores.
# Off-hours is kept as a secondary comparison; scores are near-identical (ρ ≈ 0.998).
DEPARTURE_RUSH     = datetime(2026, 4, 28, 8, 0)
DEPARTURE_OFFHOURS = datetime(2026, 4, 28, 10, 30)
BETA               = 0.1
MAX_TIME           = timedelta(minutes=120)
BATCH_SIZE         = 50
WALKING_SPEED      = 83.33  # m/min (5 km/h)
MIN_POPULATION     = 50


def _normalise_accessibility(raw_df, database):
    """Filter non-residential areas and normalise gravity scores to 0–100."""
    valid_ids = database.conn.sql(f"""
        SELECT id AS neighborhood_id FROM Neighborhoods
        WHERE population >= {MIN_POPULATION}
    """).df()["neighborhood_id"].tolist()
    df = raw_df[raw_df["neighborhood_id"].isin(valid_ids)].copy().reset_index(drop=True)
    A_max = df["accessibility_score"].max()
    if A_max > 0:
        df["accessibility_score"] = df["accessibility_score"] / A_max * 100
    return df


# Setup
print("Setting up network and database...")
network  = Network("Amsterdam", store_in_file=True,
                   store_dir=os.path.expanduser("~/.percolation_cache/"))
database = Database(CSV, GPKG)
database.set_city("Amsterdam")
database.load_network(network)
database.obtain_features()
database.pre_process()

network.build_r5_network(osm_pbf_path=PBF_FILE, gtfs_files=[GTFS_FILE])

# t_walk (called once — mutates pedestrian graph)
print("Computing t_walk...")
df_t_walk = compute_t_walk(database, network)
gdf_t_walk = attach_geometry_to_t_walk(database, df_t_walk)
print(f"  -> {len(df_t_walk)} neighbourhoods")

t_walk_min = df_t_walk[["neighborhood_id"]].copy()
t_walk_min["t_walk_min"] = df_t_walk["avg_dist"] / WALKING_SPEED

# Attractiveness (computed once, shared)
print("Computing attractiveness...")
df_attr = compute_attractiveness(database, normalize_cols=True)

# Rush-hour OD matrix (R5 run 1/2)
print("Computing t_travel OD matrix — rush hour (R5 run 1/2)...")
t_travel_rush = _get_t_travel_od_matrix(network, database, DEPARTURE_RUSH, BATCH_SIZE, MAX_TIME)

acc_rush = _normalise_accessibility(
    _apply_gravity_model(t_walk_min, t_travel_rush, df_attr, BETA), database
)
gdf_rush = attach_geometry_to_accessibility_score(database, acc_rush)
print(f"  -> {len(acc_rush)} neighbourhoods (rush hour)")

pop_df = database.conn.sql(
    f"SELECT id AS neighborhood_id, population FROM Neighborhoods WHERE population >= {MIN_POPULATION}"
).df()
ben = _apply_benefit_model(t_walk_min, t_travel_rush, df_attr, BETA, pop_df)
gdf_benefit = attach_geometry_to_benefit(database, ben)

# Off-hours OD matrix (R5 run 2/2)
print("Computing t_travel OD matrix — off-hours (R5 run 2/2)...")
t_travel_off = _get_t_travel_od_matrix(network, database, DEPARTURE_OFFHOURS, BATCH_SIZE, MAX_TIME)

acc_off = _normalise_accessibility(
    _apply_gravity_model(t_walk_min, t_travel_off, df_attr, BETA), database
)
gdf_off = attach_geometry_to_accessibility_score(database, acc_off)
print(f"  -> {len(acc_off)} neighbourhoods (off-hours)")

# Correlation plot
print("Generating correlation plot...")
plot_metric_correlations(
    database=database,
    gdf_acc=gdf_rush,
    gdf_benefit=gdf_benefit,
    gdf_t_walk=df_t_walk,
    gdf_rush=gdf_rush,
    gdf_off=gdf_off,
    storage_folder=OUT,
    name="metric_correlations",
    show=False,
)

print(f"Done! Saved to {OUT}/metric_correlations/")

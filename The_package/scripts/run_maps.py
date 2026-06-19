"""
run_maps.py — Generate all choropleth maps for the Amsterdam accessibility analysis.

Runs R5 twice (rush hour 08:00 + off-hours 10:30) and saves 8 maps to debug/:
  neighbourhood_pts.png      — Poisson-disk sample points per neighbourhood
  t_walk.png                 — Avg walking time to nearest transit stop
  attractiveness.png         — Composite attractiveness (population + jobs + amenities)
  t_travel.png               — Avg transit travel time per origin (rush hour)
  accessibility_rush.png     — Transit accessibility score (rush hour)
  benefit_score.png          — Benefit score (underserved × densely populated)
  accessibility_offhours.png — Transit accessibility score (off-hours)
  accessibility_diff.png     — Score change: rush hour vs off-hours

R5 runs exactly twice — rush and off-hours OD matrices are computed separately,
then shared across accessibility, benefit, and the diff map.

compute_t_walk mutates the pedestrian graph in-memory, so it is called only
once; t_walk_min is derived from the result and reused for both gravity models.
"""

import os
import sys
import matplotlib
matplotlib.use("Agg")
from datetime import datetime, timedelta

sys.path.insert(0, "src")

from atas.core._classes import Network, Database
from atas.core._t_walk import compute_t_walk, attach_geometry_to_t_walk
from atas.core._t_travel import compute_avg_travel_time_per_origin
from atas.core._attractiveness import compute_attractiveness
from atas.core._accessibility_score import _apply_gravity_model
from atas.core._accessibility_model import _get_t_travel_od_matrix
from atas.core._benefit import _apply_benefit_model
from atas.config.data_path import PBF_FILE, GTFS_FILE
from atas.utils.util_plotting import (
    plot_neighborhood_pts_map,
    plot_t_walk_map,
    plot_attractiveness_map, attach_geometry_to_attractiveness,
    plot_t_travel_avg_map, attach_geometry_to_t_travel,
    plot_accessibility_score_map, attach_geometry_to_accessibility_score,
    plot_benefit_map, attach_geometry_to_benefit,
    plot_accessibility_diff_map,
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
    """Filter non-residential areas and normalise gravity scores to 0–100.
    Mirrors the post-processing in compute_accessibility_score."""
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

# Neighbourhood sample points
print("1/8  Plotting neighbourhood sample points...")
database.create_pts_per_neighborhood()
plot_neighborhood_pts_map(database, storage_folder=OUT, name="neighbourhood_pts")
print(f"     -> {OUT}/neighbourhood_pts.png")

# t_walk
print("2/8  Computing t_walk...")
df_t_walk = compute_t_walk(database, network)
gdf_t_walk = attach_geometry_to_t_walk(database, df_t_walk)
plot_t_walk_map(gdf_t_walk, storage_folder=OUT, name="t_walk")
print(f"     -> {OUT}/t_walk.png")

# Derive t_walk_min once; reused for both gravity models without re-running
# compute_t_walk (which would mutate the network graph a second time).
t_walk_min = df_t_walk[["neighborhood_id"]].copy()
t_walk_min["t_walk_min"] = df_t_walk["avg_dist"] / WALKING_SPEED

# Attractiveness
print("3/8  Computing attractiveness...")
df_attr = compute_attractiveness(database, normalize_cols=True)
gdf_attr = attach_geometry_to_attractiveness(database, df_attr)
plot_attractiveness_map(gdf_attr, storage_folder=OUT, name="attractiveness")
print(f"     -> {OUT}/attractiveness.png")

# Rush-hour OD matrix (R5 run 1/2)
print("     Computing t_travel OD matrix — rush hour (R5 run 1/2)...")
t_travel_rush = _get_t_travel_od_matrix(
    network, database, DEPARTURE_RUSH, BATCH_SIZE, MAX_TIME
)

print("4/8  Plotting avg transit travel time map (rush hour)...")
df_avg_rush = compute_avg_travel_time_per_origin(t_travel_rush)
gdf_t_travel = attach_geometry_to_t_travel(database, df_avg_rush)
plot_t_travel_avg_map(gdf_t_travel, storage_folder=OUT, name="t_travel")
print(f"     -> {OUT}/t_travel.png")

print("5/8  Computing accessibility score (rush hour)...")
acc_rush = _normalise_accessibility(
    _apply_gravity_model(t_walk_min, t_travel_rush, df_attr, BETA), database
)
gdf_acc_rush = attach_geometry_to_accessibility_score(database, acc_rush)
plot_accessibility_score_map(gdf_acc_rush, storage_folder=OUT, name="accessibility_rush")
print(f"     -> {OUT}/accessibility_rush.png")

print("6/8  Computing benefit score...")
pop_df = database.conn.sql(
    "SELECT id AS neighborhood_id, population FROM Neighborhoods WHERE population >= 50"
).df()
ben = _apply_benefit_model(t_walk_min, t_travel_rush, df_attr, BETA, pop_df)
gdf_benefit = attach_geometry_to_benefit(database, ben)
plot_benefit_map(gdf_benefit, storage_folder=OUT, name="benefit_score")
print(f"     -> {OUT}/benefit_score.png")

# Off-hours OD matrix (R5 run 2/2)
print("     Computing t_travel OD matrix — off-hours (R5 run 2/2)...")
t_travel_off = _get_t_travel_od_matrix(
    network, database, DEPARTURE_OFFHOURS, BATCH_SIZE, MAX_TIME
)

print("7/8  Computing accessibility score (off-hours)...")
acc_off = _normalise_accessibility(
    _apply_gravity_model(t_walk_min, t_travel_off, df_attr, BETA), database
)
gdf_acc_off = attach_geometry_to_accessibility_score(database, acc_off)
plot_accessibility_score_map(gdf_acc_off, storage_folder=OUT, name="accessibility_offhours")
print(f"     -> {OUT}/accessibility_offhours.png")

# Rush vs off-hours diff
print("8/8  Plotting rush vs off-hours diff...")
plot_accessibility_diff_map(gdf_acc_rush, gdf_acc_off, storage_folder=OUT, name="accessibility_diff")
print(f"     -> {OUT}/accessibility_diff.png")

print(f"\nDone — 8 maps saved to {OUT}/")

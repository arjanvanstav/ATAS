"""
compare_scores.py

Runs both accessibility and benefit pipelines once, sharing the R5 OD matrix,
then prints a per-neighborhood comparison to verify the inverse relationship.
"""
import os
from datetime import datetime, timedelta

from atas.core._classes import Network, Database
from atas.core._accessibility_score import _apply_gravity_model
from atas.core._accessibility_model import (
    _get_t_walk_in_minutes,
    _get_t_travel_od_matrix,
)
from atas.core._benefit import _apply_benefit_model
from atas.core._attractiveness import compute_attractiveness
from atas.config.data_path import PBF_FILE, GTFS_FILE

csv = "tests/TestDatasets/test.csv"
geopackage = "tests/TestDatasets/test.gpkg"

DEPARTURE = datetime(2026, 4, 28, 8, 0)
BETA = 0.1

# --- Setup ---
network = Network("Amsterdam", store_in_file=True)
database = Database(csv, geopackage)
database.set_city("Amsterdam")
database.load_network(network)
database.obtain_features()
database.pre_process()
network.build_r5_network(osm_pbf_path=PBF_FILE, gtfs_files=[GTFS_FILE])

# --- Shared components (R5 runs only once) ---
print("Computing t_walk...")
t_walk_df = _get_t_walk_in_minutes(database, network)

print("Computing t_travel (R5)...")
t_travel_df = _get_t_travel_od_matrix(
    network, database, DEPARTURE, batch_size=50, max_time=timedelta(minutes=120)
)

print("Computing attractiveness...")
attractiveness_df = compute_attractiveness(database)

# --- Accessibility score ---
print("Applying gravity model (accessibility)...")
acc_df = _apply_gravity_model(t_walk_df, t_travel_df, attractiveness_df, BETA)

# --- Benefit score ---
print("Applying benefit model...")
pop_df = database.conn.sql("SELECT id AS neighborhood_id, population FROM Neighborhoods WHERE population >= 50").df()
ben_df = _apply_benefit_model(t_walk_df, t_travel_df, attractiveness_df, BETA, pop_df)

# --- Merge and compare ---
merged = acc_df.merge(ben_df, on="neighborhood_id")

A_max = merged["accessibility_score"].max()
merged["expected_benefit"] = merged.apply(
    lambda r: r["benefit_score"] / (A_max - r["accessibility_score"])
    if (A_max - r["accessibility_score"]) > 0 else None,
    axis=1
)

corr = merged["accessibility_score"].corr(merged["benefit_score"])
print(f"\n{'='*60}")
print(f"Neighborhoods with both scores: {len(merged)}")
print(f"Pearson correlation (accessibility vs benefit): {corr:.4f}")
print("  -> Expected: strongly negative (inverse relationship)")
print(f"{'='*60}")

print("\nTop 10 most accessible (should have lowest benefit):")
top_acc = merged.nlargest(10, "accessibility_score")[
    ["neighborhood_id", "accessibility_score", "benefit_score"]
]
print(top_acc.to_string(index=False))

print("\nBottom 10 least accessible (should have highest benefit):")
bot_acc = merged.nsmallest(10, "accessibility_score")[
    ["neighborhood_id", "accessibility_score", "benefit_score"]
]
print(bot_acc.to_string(index=False))

print("\nTop 10 highest benefit (should have low accessibility):")
top_ben = merged.nlargest(10, "benefit_score")[
    ["neighborhood_id", "accessibility_score", "benefit_score"]
]
print(top_ben.to_string(index=False))

# Sanity check: any neighborhood where high accessibility also has high benefit?
A_median = merged["accessibility_score"].median()
B_median = merged["benefit_score"].median()
contradictions = merged[
    (merged["accessibility_score"] > A_median) & (merged["benefit_score"] > B_median)
]
print(f"\nContradictions (above median on both): {len(contradictions)}")
if len(contradictions) > 0:
    print(contradictions[["neighborhood_id", "accessibility_score", "benefit_score"]].to_string(index=False))

os.makedirs("debug", exist_ok=True)
merged[["neighborhood_id", "accessibility_score", "benefit_score"]].to_csv(
    "debug/score_comparison.csv", index=False
)
print("\nFull comparison saved to debug/score_comparison.csv")

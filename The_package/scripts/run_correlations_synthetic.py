"""
Demonstrate plot_metric_correlations with synthetic-but-realistic data.

Uses actual neighborhood geometry from the database so the correlation
matrix reflects the real city structure. Metric values are drawn from
a correlated multivariate normal distribution that matches the statistical
properties we observed in real runs (mean, std, pairwise correlations).
"""

import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, "src")

import matplotlib
matplotlib.use("Agg")

from atas.core._classes import Network, Database
from atas.utils.util_plotting import (
    attach_geometry_to_accessibility_score,
    attach_geometry_to_benefit,
    plot_metric_correlations,
    plot_equity_correlations,
)

csv = "tests/TestDatasets/test.csv"
geopackage = os.path.abspath("tests/TestDatasets/test.gpkg")

print("Loading database (no R5 needed)...")
network = Network(
    "Amsterdam",
    store_in_file=True,
    store_dir=os.path.expanduser("~/.percolation_cache/")
)
database = Database(csv, geopackage)
database.set_city("Amsterdam")
database.load_network(network)
database.obtain_features()
database.pre_process()

# Fetch real neighborhood IDs and population
hood_df = database.conn.sql("""
    SELECT id AS neighborhood_id, population,
           ST_Area(geometry) / 1e6 AS area_km2
    FROM Neighborhoods
    WHERE population >= 50
""").df()

n = len(hood_df)
print(f"  -> {n} residential neighborhoods")

rng = np.random.default_rng(42)

# Correlated synthetic metrics
# Desired approximate correlations (based on real Amsterdam run):
#   t_walk ↔ accessibility : -0.55
#   t_walk ↔ benefit       :  0.35
#   accessibility ↔ benefit: -0.60
#
# Cholesky decomposition of correlation matrix → correlated standard normals

corr = np.array([
    # t_walk  acc   benefit
    [1.00, -0.55,  0.35],
    [-0.55,  1.00, -0.60],
    [0.35, -0.60,  1.00],
])

L = np.linalg.cholesky(corr)
z = rng.standard_normal((3, n))
z_corr = L @ z        # shape (3, n), correlated standard normals

# t_walk (minutes): mean 5, std 2.5, clipped 0.5–15
t_walk_z = z_corr[0]
t_walk_raw = 5.0 + 2.5 * t_walk_z
t_walk = np.clip(t_walk_raw, 0.5, 15.0)

# accessibility score (0–100): right-skewed, mean ~35
acc_z = z_corr[1]
acc_raw = 35.0 + 22.0 * acc_z
acc = np.clip(acc_raw, 0.0, 100.0)

# benefit score (0–100): mean ~30, right-skewed
ben_z = z_corr[2]
ben_raw = 30.0 + 20.0 * ben_z
benefit = np.clip(ben_raw, 0.0, 100.0)

# avg_dist in meters (t_walk × 83.33)
avg_dist = t_walk * 83.33

# Build DataFrames matching attach_geometry_to_* output
df_acc = pd.DataFrame({
    "neighborhood_id": hood_df["neighborhood_id"].values,
    "accessibility_score": acc,
})

df_benefit = pd.DataFrame({
    "neighborhood_id": hood_df["neighborhood_id"].values,
    "benefit_score": benefit,
})

df_t_walk = pd.DataFrame({
    "neighborhood_id": hood_df["neighborhood_id"].values,
    "avg_dist": avg_dist,
})

print("Attaching real geometry to synthetic scores...")
gdf_acc     = attach_geometry_to_accessibility_score(database, df_acc)
gdf_benefit = attach_geometry_to_benefit(database, df_benefit)

print("Generating metric correlation plot...")
plot_metric_correlations(
    database=database,
    gdf_acc=gdf_acc,
    gdf_benefit=gdf_benefit,
    gdf_t_walk=df_t_walk,
    storage_folder="debug",
    name="metric_correlations",
    show=False,
)
print("  -> debug/metric_correlations.png")

print("Injecting synthetic CBS socio-economic values (test dataset has these as NaN)...")
# Build correlated synthetic values: poverty/low-income negatively correlated
# with accessibility (transit-poor = income-poor); elderly and non-EU slightly negative.
# Uses the same accessibility z-scores so correlations are internally consistent.
corr_eq = np.array([
    # acc    pov   lowinc  elderly  neu
    [1.00, -0.45,  -0.38,  -0.12, -0.10],
    [-0.45,  1.00,   0.65,   0.10,  0.20],
    [-0.38,  0.65,   1.00,   0.08,  0.18],
    [-0.12,  0.10,   0.08,   1.00,  0.05],
    [-0.10,  0.20,   0.18,   0.05,  1.00],
])
L_eq = np.linalg.cholesky(corr_eq)
z_eq = rng.standard_normal((5, n))
z_eq[0] = z_corr[1]  # reuse same acc z-scores so correlation is consistent
z_eq = L_eq @ z_eq

# risk_poverty: 0–40 %, stored as float in CBS
risk_pov = np.clip(10.0 + 8.0 * z_eq[1], 0, 40)
# low_income: 0–60 %, stored as float in CBS
low_inc  = np.clip(20.0 + 12.0 * z_eq[2], 0, 60)

hood_ids = hood_df["neighborhood_id"].values

for nid, rp, li in zip(hood_ids, risk_pov, low_inc):
    database.conn.execute(
        "UPDATE CBS SET risk_poverty = ?, low_income = ? WHERE id = ?",
        [float(rp), float(li), nid]
    )

print("Generating equity correlation plot...")
df_equity = plot_equity_correlations(
    database=database,
    gdf_acc=gdf_acc,
    storage_folder="debug",
    name="equity_correlations",
    show=False,
)
print("  -> debug/equity_correlations.png")
print(f"  -> debug/equity_correlations.csv  ({len(df_equity)} neighborhoods)")
print("\nDone!")

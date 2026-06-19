"""
run_sensitivity.py — Parameter sensitivity analysis using real Amsterdam data.

Phase 1  (slow, runs once — requires R5):
    Runs the full pipeline and saves raw intermediates to parquet cache:
        debug/sensitivity_cache/t_walk.parquet
        debug/sensitivity_cache/t_travel.parquet
        debug/sensitivity_cache/attractiveness.parquet

Phase 2  (fast, reloads from cache — no R5 needed):
    Sweeps beta and attractiveness weight configurations using _apply_gravity_model.

Phase 3  (fast):
    Saves two figures:
        debug/sensitivity_beta.png    — score distributions + rank stability
        debug/sensitivity_weights.png — rank scatter across weight configurations

Re-running this script skips Phase 1 when the cache already exists.
"""

import os
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.stats import spearmanr
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, "src")

from atas.core._classes import Network, Database
from atas.core._t_walk import compute_t_walk
from atas.core._t_travel import compute_t_travel_matrix
from atas.core._attractiveness import compute_attractiveness
from atas.core._accessibility_model import _get_neighborhood_centroids
from atas.core._accessibility_score import _apply_gravity_model
from atas.core._accessibility_model import WALKING_SPEED_METERS_PER_MINUTE
from atas.config.data_path import PBF_FILE, GTFS_FILE

CSV   = "tests/TestDatasets/test.csv"
GPKG  = os.path.abspath("tests/TestDatasets/test.gpkg")
OUT   = "debug"
CACHE = Path(OUT) / "sensitivity_cache"
os.makedirs(OUT, exist_ok=True)
CACHE.mkdir(exist_ok=True)

# Parameters to sweep
BETAS    = [0.02, 0.05, 0.1, 0.2, 0.5, 1.0]
BETA_REF = 0.1   # the value used in run_equity.py — reference for weight plots

WEIGHT_CONFIGS = {
    "pop + jobs + amenities (default)": {"population": 1.0, "jobs": 1.0, "amenities": 1.0},
    "population only":                  {"population": 1.0},
    "jobs only":                        {"jobs": 1.0},
    "population + jobs":                {"population": 1.0, "jobs": 1.0},
}

T_WALK_PATH   = CACHE / "t_walk.parquet"
T_TRAVEL_PATH = CACHE / "t_travel.parquet"
ATTR_PATH     = CACHE / "attractiveness.parquet"

# =============================================================================
# Phase 1 — Run full pipeline and cache intermediates
# =============================================================================

cache_hit = T_WALK_PATH.exists() and T_TRAVEL_PATH.exists() and ATTR_PATH.exists()

if cache_hit:
    print("Phase 1: Cache found — loading intermediates...")
    t_walk_df         = pd.read_parquet(T_WALK_PATH)
    t_travel_df       = pd.read_parquet(T_TRAVEL_PATH)
    attractiveness_df = pd.read_parquet(ATTR_PATH)
    print(f"  t_walk:        {len(t_walk_df)} neighbourhoods")
    print(f"  t_travel:      {len(t_travel_df)} OD pairs")
    print(f"  attractiveness:{len(attractiveness_df)} neighbourhoods")

    # Database still needed for compute_attractiveness (weight sweep)
    print("  Setting up database for weight sweep (no R5 needed)...")
    network  = Network("Amsterdam", store_in_file=True,
                       store_dir=os.path.expanduser("~/.percolation_cache/"))
    database = Database(CSV, GPKG)
    database.set_city("Amsterdam")
    database.load_network(network)
    database.obtain_features()
    database.pre_process()

else:
    print("Phase 1: No cache found — running full pipeline (R5 required)...")

    network  = Network("Amsterdam", store_in_file=True,
                       store_dir=os.path.expanduser("~/.percolation_cache/"))
    database = Database(CSV, GPKG)
    database.set_city("Amsterdam")
    database.load_network(network)
    database.obtain_features()
    database.pre_process()
    network.build_r5_network(osm_pbf_path=PBF_FILE, gtfs_files=[GTFS_FILE])

    print("  Computing t_walk...")
    df_raw    = compute_t_walk(database, network)
    t_walk_df = df_raw[["neighborhood_id"]].copy()
    t_walk_df["t_walk_min"] = df_raw["avg_dist"] / WALKING_SPEED_METERS_PER_MINUTE
    t_walk_df.to_parquet(T_WALK_PATH)
    print(f"    -> {len(t_walk_df)} neighbourhoods  (saved)")

    print("  Computing t_travel OD matrix via R5...")
    centroids   = _get_neighborhood_centroids(database)
    t_travel_df = compute_t_travel_matrix(
        network=network,
        origins=centroids.copy(),
        destinations=centroids.copy(),
        departure_time=datetime(2026, 4, 28, 8, 0),
        batch_size=50,
        max_time=timedelta(minutes=120),
    )
    t_travel_df.to_parquet(T_TRAVEL_PATH)
    print(f"    -> {len(t_travel_df)} OD pairs  (saved)")

    print("  Computing attractiveness (default weights)...")
    attractiveness_df = compute_attractiveness(database, normalize_cols=True)
    attractiveness_df.to_parquet(ATTR_PATH)
    print(f"    -> {len(attractiveness_df)} neighbourhoods  (saved)")

# =============================================================================
# Phase 2 — Parameter sweep (pure Python, no R5)
# =============================================================================

def _normalized_scores(t_walk, t_travel, attr, beta):
    """Apply gravity model and normalize result to [0, 100]."""
    result = _apply_gravity_model(t_walk, t_travel, attr, beta)
    A_max  = result["accessibility_score"].max()
    if A_max > 0:
        result["accessibility_score"] = result["accessibility_score"] / A_max * 100
    return result.set_index("neighborhood_id")["accessibility_score"]


print("\nPhase 2: Sweeping beta values...")
scores_by_beta = {}
for beta in BETAS:
    s = _normalized_scores(t_walk_df, t_travel_df, attractiveness_df, beta)
    scores_by_beta[beta] = s
    print(f"  β={beta:<5}  mean={s.mean():.1f}  std={s.std():.1f}  CV={s.std()/s.mean():.3f}")

print("\nPhase 2: Sweeping attractiveness weight configurations...")
scores_by_weights = {}
for name, weights in WEIGHT_CONFIGS.items():
    attr = compute_attractiveness(database, weights=weights, normalize_cols=True)
    scores_by_weights[name] = _normalized_scores(t_walk_df, t_travel_df, attr, BETA_REF)
    print(f"  {name}")

# Shared neighborhood set for each group
beta_ids   = sorted(set.intersection(*[set(s.index) for s in scores_by_beta.values()]))
weight_ids = sorted(set.intersection(*[set(s.index) for s in scores_by_weights.values()]))

beta_df   = pd.DataFrame({b: scores_by_beta[b].reindex(beta_ids)     for b in BETAS})
weight_df = pd.DataFrame({n: scores_by_weights[n].reindex(weight_ids)
                           for n in WEIGHT_CONFIGS})

# =============================================================================
# Phase 3 — Visualization (one file per panel)
# =============================================================================

PALETTE = ["#1a6faf", "#2e86c1", "#2980b9", "#5dade2", "#85c1e9", "#aed6f1"]

BETA_DIR   = Path(OUT) / "sensitivity_beta"
WEIGHT_DIR = Path(OUT) / "sensitivity_weights"
BETA_DIR.mkdir(exist_ok=True)
WEIGHT_DIR.mkdir(exist_ok=True)


def _save_fig(fig, path):
    fig.savefig(path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> {path}")


# Beta: score distributions (violin)
fig, ax = plt.subplots(figsize=(8, 5))
data  = [beta_df[b].dropna().values for b in BETAS]
parts = ax.violinplot(data, positions=range(len(BETAS)), showmedians=True, showextrema=False)
for i, pc in enumerate(parts["bodies"]):
    pc.set_facecolor(PALETTE[i])
    pc.set_alpha(0.75)
parts["cmedians"].set_color("#222222")
parts["cmedians"].set_linewidth(1.5)
ax.set_xticks(range(len(BETAS)))
ax.set_xticklabels([str(b) for b in BETAS])
ax.set_xlabel("β  (distance-decay parameter)", fontsize=11)
ax.set_ylabel("Accessibility score  (normalised 0–100)", fontsize=11)
ax.set_title("Score Distributions Across β Values", fontsize=12, fontweight="bold")
ax.spines[["top", "right"]].set_visible(False)
plt.tight_layout()
_save_fig(fig, BETA_DIR / "score_distributions.png")

# Beta: mean ± 1σ vs beta
means = [beta_df[b].mean() for b in BETAS]
stds  = [beta_df[b].std()  for b in BETAS]
fig, ax = plt.subplots(figsize=(7, 5))
ax.fill_between(BETAS,
                [m - s for m, s in zip(means, stds)],
                [m + s for m, s in zip(means, stds)],
                alpha=0.25, color="#2980B9", label="±1σ")
ax.plot(BETAS, means, "o-", color="#2980B9", linewidth=1.8, markersize=6, label="mean")
ax.axvline(BETA_REF, color="#E74C3C", linestyle="--", linewidth=1.3,
           label=f"Reference β = {BETA_REF}")
ax.set_xlabel("β", fontsize=11)
ax.set_ylabel("Accessibility score", fontsize=11)
ax.set_title("Mean ± 1σ vs β", fontsize=12, fontweight="bold")
ax.legend(fontsize=10)
ax.spines[["top", "right"]].set_visible(False)
plt.tight_layout()
_save_fig(fig, BETA_DIR / "mean_std.png")

# Beta: pairwise Spearman rank-correlation heatmap
n_b = len(BETAS)
rho_matrix = np.ones((n_b, n_b))
for i in range(n_b):
    for j in range(n_b):
        if i != j:
            pair = beta_df[[BETAS[i], BETAS[j]]].dropna()
            rho_matrix[i, j], _ = spearmanr(pair.iloc[:, 0], pair.iloc[:, 1])

beta_labels = [str(b) for b in BETAS]
fig, ax = plt.subplots(figsize=(6, 5))
im = ax.imshow(rho_matrix, vmin=0.5, vmax=1.0, cmap="YlOrRd")
ax.set_xticks(range(n_b)); ax.set_xticklabels(beta_labels, fontsize=10)
ax.set_yticks(range(n_b)); ax.set_yticklabels(beta_labels, fontsize=10)
ax.set_xlabel("β", fontsize=11); ax.set_ylabel("β", fontsize=11)
ax.set_title("Pairwise Rank Correlation (Spearman ρ)", fontsize=12, fontweight="bold")
for i in range(n_b):
    for j in range(n_b):
        ax.text(j, i, f"{rho_matrix[i, j]:.2f}", ha="center", va="center", fontsize=9,
                color="black" if rho_matrix[i, j] > 0.75 else "white")
plt.colorbar(im, ax=ax, shrink=0.85)
plt.tight_layout()
_save_fig(fig, BETA_DIR / "rank_heatmap.png")

# Beta: rank scatter β_lo vs β_hi
beta_lo, beta_hi = 0.05, 0.2
pair = beta_df[[beta_lo, beta_hi]].dropna()
rho, _ = spearmanr(pair[beta_lo], pair[beta_hi])
fig, ax = plt.subplots(figsize=(6, 6))
ax.scatter(pair[beta_lo], pair[beta_hi], s=20, alpha=0.5, color="#8E44AD", edgecolors="none")
ax.plot([0, 100], [0, 100], color="#aaa", linestyle="--", linewidth=1)
ax.text(0.05, 0.93, f"ρ = {rho:.3f}", transform=ax.transAxes,
        fontsize=11, color="#333333", va="top")
ax.set_xlabel(f"Accessibility score  (β = {beta_lo})", fontsize=11)
ax.set_ylabel(f"Accessibility score  (β = {beta_hi})", fontsize=11)
ax.set_title(f"Rank Scatter: β = {beta_lo} vs β = {beta_hi}", fontsize=12, fontweight="bold")
ax.set_xlim(0, 100); ax.set_ylim(0, 100)
ax.spines[["top", "right"]].set_visible(False)
plt.tight_layout()
_save_fig(fig, BETA_DIR / "rank_scatter.png")

print(f"\nSaved 4 beta plots → {BETA_DIR}/")


# Weights: one scatter per alternative configuration
config_names   = list(WEIGHT_CONFIGS.keys())
ref_name       = config_names[0]
alt_names      = config_names[1:]
scatter_colors = ["#E74C3C", "#27AE60", "#2980B9"]
filenames      = ["population_only.png", "jobs_only.png", "population_jobs.png"]

for alt_name, color, filename in zip(alt_names, scatter_colors, filenames):
    pair = weight_df[[ref_name, alt_name]].dropna()
    rho, pval = spearmanr(pair[ref_name], pair[alt_name])
    sig = "**" if pval < 0.01 else ("*" if pval < 0.05 else "")

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.scatter(pair[ref_name], pair[alt_name],
               s=20, alpha=0.55, color=color, edgecolors="none")
    ax.plot([0, 100], [0, 100], color="#aaa", linestyle="--", linewidth=1)
    ax.text(0.05, 0.93, f"ρ = {rho:.3f}{sig}",
            transform=ax.transAxes, fontsize=11, color="#333333", va="top")
    ax.set_xlabel(f"Score: {ref_name}", fontsize=10)
    ax.set_ylabel(f"Score: {alt_name}", fontsize=10)
    ax.set_title(alt_name, fontsize=11, fontweight="bold")
    ax.set_xlim(0, 100); ax.set_ylim(0, 100)
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    _save_fig(fig, WEIGHT_DIR / filename)

print(f"Saved 3 weight plots → {WEIGHT_DIR}/")
print("\nDone.")

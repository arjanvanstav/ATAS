"""
run_equity.py — Transit accessibility vs socio-economic equity indicators.
"""

import os
import sys
import numpy as np
import pandas as pd
import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, "src")

from atas.core._classes import Network, Database
from atas.core._accessibility_score import compute_accessibility_score
from atas.utils.util_plotting import attach_geometry_to_accessibility_score
from atas.config.data_path import PBF_FILE, GTFS_FILE
from atas.utils.data_manager import ensure_cbs_income

CSV      = "tests/TestDatasets/test.csv"
GPKG     = os.path.abspath("tests/TestDatasets/test.gpkg")
CBS_GPKG = Path.home() / ".percolation_cache/cbs/2025/WijkBuurtkaart_2025_v1/wijkenbuurten_2025_v1.gpkg"
OUT      = "debug"
OUT_DIR  = Path(OUT) / "equity_correlations"
os.makedirs(OUT, exist_ok=True)
OUT_DIR.mkdir(exist_ok=True)

# Rush hour is the main departure time.
DEPARTURE_RUSH = datetime(2026, 4, 28, 8, 0)
BETA           = 0.1

# Pipeline
print("Setting up network and database...")
network = Network("Amsterdam", store_in_file=True,
                  store_dir=os.path.expanduser("~/.percolation_cache/"))
database = Database(CSV, GPKG)
database.set_city("Amsterdam")
database.load_network(network)
database.obtain_features()
database.pre_process()
network.build_r5_network(osm_pbf_path=PBF_FILE, gtfs_files=[GTFS_FILE])

print("Computing accessibility score (rush hour — canonical)...")
df_acc = compute_accessibility_score(
    network=network, database=database,
    departure_time=DEPARTURE_RUSH,
    beta=BETA, t_travel_max_time=timedelta(minutes=120),
    print_progress=True,
)
gdf_acc = attach_geometry_to_accessibility_score(database, df_acc)

# Residential filter
# Population >= 500 removes harbour zones, industrial areas, and very sparse
# peripheral areas on top of the pipeline's default >= 50 filter.
MIN_POPULATION = 500
pop_df = database.conn.sql(f"""
    SELECT id AS neighborhood_id, population
    FROM Neighborhoods WHERE population >= {MIN_POPULATION}
""").df()
residential_ids = set(pop_df["neighborhood_id"])
print(f"Residential filter: {len(residential_ids)} neighbourhoods (population >= {MIN_POPULATION})")
gdf_acc = gdf_acc[gdf_acc["neighborhood_id"].isin(residential_ids)].copy()

# CBS socio-economic indicators
print("Loading CBS GeoPackage for socio-economic indicators...")
cbs_gdf = gpd.read_file(str(CBS_GPKG), layer="buurten")
cbs_gdf = cbs_gdf[cbs_gdf["gemeentecode"] == "GM0363"].copy()
for col in cbs_gdf.select_dtypes(include="number").columns:
    cbs_gdf.loc[cbs_gdf[col] < -999, col] = np.nan

cbs_slim = cbs_gdf[[
    "buurtcode",
    "percentage_personen_65_jaar_en_ouder",
    "percentage_met_herkomstland_buiten_europa",
    "percentage_eenpersoonshuishoudens",
    "bevolkingsdichtheid_inwoners_per_km2",
]].rename(columns={
    "buurtcode":                                    "neighborhood_id",
    "percentage_personen_65_jaar_en_ouder":         "pct_elderly",
    "percentage_met_herkomstland_buiten_europa":    "pct_non_eu",
    "percentage_eenpersoonshuishoudens":            "pct_single_hh",
    "bevolkingsdichtheid_inwoners_per_km2":         "pop_density",
})

income_path = ensure_cbs_income(gemeente_code="GM0363")
income_df   = pd.read_csv(income_path)
cbs_slim = cbs_slim.merge(
    income_df[["neighborhood_id", "pct_low_income", "pct_poverty"]],
    on="neighborhood_id", how="left"
)

acc_slim = gdf_acc[["neighborhood_id", "accessibility_score"]].dropna()
combined = acc_slim.merge(cbs_slim, on="neighborhood_id", how="inner")
combined = combined[combined["neighborhood_id"].isin(residential_ids)]
combined.to_csv(f"{OUT}/equity_correlations.csv", index=False)
print(f"  -> {OUT}/equity_correlations.csv  ({len(combined)} neighbourhoods)")

# Individual equity scatter plots
panels = [
    ("pct_poverty",    "Persons in poverty (%)",
     "Poverty Rate vs Transit Accessibility",             "#E74C3C", "poverty.png"),
    ("pct_low_income", "Persons in lowest 40% income bracket (%)",
     "Low-income Share vs Transit Accessibility",         "#C0392B", "low_income.png"),
    ("pct_elderly",    "Elderly residents (% aged 65+)",
     "Elderly Population vs Transit Accessibility",       "#8E44AD", "elderly.png"),
    ("pct_non_eu",     "Non-EU origin (% of residents)",
     "Non-EU Origin vs Transit Accessibility",            "#2980B9", "non_eu_origin.png"),
    ("pct_single_hh",  "Single-person households (%)",
     "Single-Person Households vs Transit Accessibility", "#E67E22", "single_households.png"),
    ("pop_density",    "Population density (per km²)",
     "Population Density vs Transit Accessibility",       "#27AE60", "pop_density.png"),
]

print("Generating equity plots...")
for x_col, xlabel, title, color, filename in panels:
    # Exclude CBS-suppressed zeros (reported as 0 when count is below privacy threshold)
    if x_col in ("pct_poverty", "pct_low_income"):
        mask = combined[x_col].notna() & (combined[x_col] > 0) & combined["accessibility_score"].notna()
    else:
        mask = combined[x_col].notna() & combined["accessibility_score"].notna()

    x = combined.loc[mask, x_col].values
    y = combined.loc[mask, "accessibility_score"].values

    fig, ax = plt.subplots(figsize=(7, 5))
    ax.scatter(x, y, s=20, alpha=0.55, color=color, edgecolors="none")

    if len(x) > 2:
        slope, intercept, r, p, _ = stats.linregress(x, y)
        x_line = np.linspace(x.min(), x.max(), 200)
        ax.plot(x_line, slope * x_line + intercept,
                color="#333333", linewidth=1.2, linestyle="--")
        sig = "**" if p < 0.01 else ("*" if p < 0.05 else "")
        ax.text(0.05, 0.93, f"r = {r:.2f}{sig}",
                transform=ax.transAxes, fontsize=10, color="#333333", va="top")
        ax.text(0.95, 0.05, f"n = {mask.sum()}",
                transform=ax.transAxes, fontsize=8, color="#888888",
                ha="right", va="bottom")

    ax.set_xlabel(xlabel, fontsize=11)
    ax.set_ylabel("Accessibility score", fontsize=11)
    ax.set_title(title, fontsize=12, fontweight="bold")
    ax.tick_params(labelsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    fig.savefig(OUT_DIR / filename, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"  -> {OUT_DIR}/{filename}")

print("\nDone!")

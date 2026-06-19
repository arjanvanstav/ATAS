"""
_benefit.py — Compute a benefit score for each neighborhood.

The benefit score identifies which neighborhoods would gain the most from better transit.
It multiplies two factors, both normalized to [0, 1]:
  - Accessibility gap:  (A_max - A_i) / A_max  — how underserved compared to the best-served
  - Population weight:  population_i / pop_max  — how many people live there

Final score (0–100): gap_fraction * pop_fraction, then normalized so the max is 100.
A neighborhood scores high only if it is BOTH poorly served AND densely populated.
"""

import numpy as np
from datetime import datetime, timedelta

from atas.core._classes import Network, Database
from atas.core._attractiveness import compute_attractiveness
from atas.core._accessibility_model import (
    _get_t_walk_in_minutes,
    _get_t_travel_od_matrix,
)


def compute_benefit(
    network: Network,
    database: Database,
    departure_time: datetime,
    beta: float,
    min_population: int = 50,
    t_travel_batch_size: int = 50,
    t_travel_max_time: timedelta = timedelta(minutes=120),
    print_progress: bool = True,
):
    """
    Run the full benefit pipeline and return a score (0–100) per neighborhood.

    Same pipeline as compute_accessibility_score, but converts the gravity score into
    a priority score that rewards underserved, densely populated neighborhoods.

    Parameters:
        network: Network with build_r5_network() already called
        database: Database with pre_process() already run
        departure_time: Trip departure time
        beta: Distance decay parameter (same value as in accessibility)
        min_population: Exclude neighborhoods with fewer residents
        t_travel_batch_size: Origins per R5 batch
        t_travel_max_time: Maximum trip duration considered by R5
        print_progress: Print progress to the terminal

    Returns:
        DataFrame with columns: neighborhood_id, benefit_score (0–100)
    """

    if print_progress:
        print("Step 1/3: Computing t_walk (walking time to nearest transit stop)...")

    t_walk_df = _get_t_walk_in_minutes(database, network)

    if print_progress:
        print(f"  -> t_walk computed for {len(t_walk_df)} neighborhoods.")

    if print_progress:
        print("Step 2/3: Computing t_travel (transit travel time OD matrix)...")

    t_travel_df = _get_t_travel_od_matrix(
        network,
        database,
        departure_time,
        t_travel_batch_size,
        t_travel_max_time,
    )

    if print_progress:
        print(f"  -> t_travel computed for {len(t_travel_df)} OD pairs.")

    if print_progress:
        print("Step 3/3: Computing attractiveness (opportunity weights)...")

    attractiveness_df = compute_attractiveness(database, normalize_cols=True)

    if print_progress:
        print(f"  -> attractiveness computed for {len(attractiveness_df)} neighborhoods.")

    # Load population for residential neighborhoods only
    pop_df = database.conn.sql(f"""
        SELECT id AS neighborhood_id, population FROM Neighborhoods
        WHERE population >= {min_population}
    """).df()

    if print_progress:
        print(f"  -> {len(pop_df)} neighborhoods pass population filter (>= {min_population}).")
        print("Combining components and computing benefit score...")

    result = _apply_benefit_model(t_walk_df, t_travel_df, attractiveness_df, beta, pop_df)

    if print_progress:
        print(f"Done. Benefit score computed for {len(result)} neighborhoods.")

    return result


def _apply_benefit_model(t_walk_df, t_travel_df, attractiveness_df, beta, pop_df):
    """
    Compute benefit scores from pre-computed t_walk, t_travel, and attractiveness data.

    First computes raw gravity scores (same as _apply_gravity_model), then converts
    them into benefit scores that prioritize underserved, populous neighborhoods.

    Parameters:
        t_walk_df: DataFrame with columns neighborhood_id, t_walk_min
        t_travel_df: DataFrame with columns from_id, to_id, travel_time
        attractiveness_df: DataFrame with columns neighborhood_id, attractiveness
        beta: Distance decay parameter
        pop_df: DataFrame with columns neighborhood_id, population
                (pre-filtered to population >= min_population)

    Returns:
        DataFrame with columns: neighborhood_id, benefit_score (0–100)
    """

    df = t_travel_df.copy()

    df = df.merge(
        t_walk_df,
        left_on="from_id",
        right_on="neighborhood_id",
        how="left",
    )

    # Missing t_walk gets the worst observed value as a penalty
    max_t_walk = t_walk_df["t_walk_min"].max() if len(t_walk_df) > 0 else 0.0
    df["t_walk_min"] = df["t_walk_min"].fillna(max_t_walk)

    df["t_total"] = df["t_walk_min"] + df["travel_time"]
    df = df.dropna(subset=["t_total"])

    df = df.merge(
        attractiveness_df,
        left_on="to_id",
        right_on="neighborhood_id",
        how="left",
    )
    df = df.dropna(subset=["attractiveness"])

    df["gravity_term"] = df["attractiveness"] * np.exp(-beta * df["t_total"])

    # Sum gravity terms per origin → raw accessibility score A_i
    score_per_origin = df.groupby("from_id")["gravity_term"].sum()
    score_per_origin = score_per_origin.reset_index()
    score_per_origin = score_per_origin.rename(columns={
        "from_id": "neighborhood_id",
        "gravity_term": "accessibility_score",
    })

    # Filter to residential neighborhoods and merge population
    score_per_origin = score_per_origin.merge(pop_df, on="neighborhood_id", how="inner")

    # Accessibility gap: 0 = best-served, 1 = worst-served
    A_max = score_per_origin["accessibility_score"].max()
    score_per_origin["gap_fraction"] = (A_max - score_per_origin["accessibility_score"]) / A_max

    # Population fraction: 0 = least populous, 1 = most populous
    pop_max = score_per_origin["population"].max()
    score_per_origin["pop_fraction"] = score_per_origin["population"] / pop_max

    # Multiply and normalize to 0–100
    raw_benefit = score_per_origin["gap_fraction"] * score_per_origin["pop_fraction"]
    score_per_origin["benefit_score"] = raw_benefit / raw_benefit.max() * 100

    return score_per_origin[["neighborhood_id", "benefit_score"]]

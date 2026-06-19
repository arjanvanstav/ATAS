"""
_accessibility_score.py — Compute transit accessibility per neighborhood using a gravity model.

Formula:  A_i = sum_j ( attractiveness_j * exp(-beta * t_total_ij) )

Where t_total_ij = t_walk_i + t_travel_ij, and exp(-beta * t) decreases as travel time grows.
Scores are normalized to 0–100. Only residential neighborhoods (population >= min_population) are included.
"""

import numpy as np
from datetime import datetime, timedelta

from atas.core._classes import Network, Database
from atas.core._attractiveness import compute_attractiveness
from atas.core._accessibility_model import (
    _get_t_walk_in_minutes,
    _get_t_travel_od_matrix,
)


def compute_accessibility_score(
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
    Run the full accessibility pipeline and return a score (0–100) per neighborhood.

    Steps: (1) t_walk, (2) t_travel OD matrix via R5, (3) attractiveness weights,
    (4) gravity model, (5) filter non-residential, (6) normalize to 0–100.

    Parameters:
        network: Network with build_r5_network() already called
        database: Database with pre_process() already run
        departure_time: Trip departure time
        beta: Distance decay parameter (higher = steeper drop-off with travel time)
        min_population: Exclude neighborhoods with fewer residents (removes industrial areas)
        t_travel_batch_size: Origins per R5 batch; reduce if memory runs out
        t_travel_max_time: Trips longer than this are treated as unreachable
        print_progress: Print progress to the terminal

    Returns:
        DataFrame with columns: neighborhood_id, accessibility_score (0–100)
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

    if print_progress:
        print("Combining components and computing accessibility score...")

    result = _apply_gravity_model(t_walk_df, t_travel_df, attractiveness_df, beta)

    # Exclude non-residential areas (harbours, parks, industrial zones)
    residential_ids = database.conn.sql(f"""
        SELECT id AS neighborhood_id FROM Neighborhoods
        WHERE population >= {min_population}
    """).df()["neighborhood_id"].tolist()

    result = result[result["neighborhood_id"].isin(residential_ids)].reset_index(drop=True)

    # Normalize to 0–100: highest raw score becomes 100
    A_max = result["accessibility_score"].max()
    if A_max > 0:
        result["accessibility_score"] = result["accessibility_score"] / A_max * 100

    if print_progress:
        print(f"Done. Accessibility score computed for {len(result)} neighborhoods.")

    return result


def _apply_gravity_model(t_walk_df, t_travel_df, attractiveness_df, beta):
    """
    Compute the raw gravity score for each origin neighborhood.

    For each origin i:  score_i = sum_j ( attractiveness_j * exp(-beta * (t_walk_i + t_travel_ij)) )

    Parameters:
        t_walk_df: DataFrame with columns neighborhood_id, t_walk_min
        t_travel_df: DataFrame with columns from_id, to_id, travel_time
        attractiveness_df: DataFrame with columns neighborhood_id, attractiveness
        beta: Distance decay parameter

    Returns:
        DataFrame with columns: neighborhood_id, accessibility_score (raw, not normalized)
    """

    df = t_travel_df.copy()

    # Add walking time for each origin (same for all destinations from that origin)
    df = df.merge(
        t_walk_df,
        left_on="from_id",
        right_on="neighborhood_id",
        how="left",
    )

    # Origins with no t_walk data get the worst observed walking time as a penalty
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

    # Gravity contribution: large for short trips, small for long trips
    df["gravity_term"] = df["attractiveness"] * np.exp(-beta * df["t_total"])

    score_per_origin = df.groupby("from_id")["gravity_term"].sum()
    score_per_origin = score_per_origin.reset_index()
    score_per_origin = score_per_origin.rename(columns={
        "from_id": "neighborhood_id",
        "gravity_term": "accessibility_score",
    })

    return score_per_origin

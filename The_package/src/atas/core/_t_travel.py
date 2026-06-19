"""
_t_travel.py — Compute transit travel times between all pairs of neighborhoods (OD matrix).

Each row in the result is one trip: from_id → to_id → travel_time (minutes, using transit + walking).
Routing is done by R5 using GTFS schedules and an OSM road network.
The matrix is computed in batches to avoid running out of memory.
"""

from datetime import datetime, timedelta
import pandas as pd
from r5py import TravelTimeMatrix


def compute_t_travel_matrix(
    network,
    origins,
    destinations,
    departure_time: datetime,
    batch_size: int = 50,
    max_time: timedelta = timedelta(minutes=120),
):
    """
    Compute travel times from every origin to every destination using R5 (transit + walking).

    Parameters:
        network: Network object with the R5 transit network built
        origins: GeoDataFrame of origin points in EPSG:4326
        destinations: GeoDataFrame of destination points in EPSG:4326
        departure_time: Trip departure time (affects which buses/trains run)
        batch_size: Origins per R5 call; reduce if memory runs out
        max_time: Trips longer than this are treated as unreachable

    Returns:
        DataFrame with columns: from_id, to_id, travel_time (minutes; NaN = unreachable)
    """

    r5_network = network.get_r5_network()
    batch_results = []

    for batch_start in range(0, len(origins), batch_size):
        batch_end = batch_start + batch_size
        batch = origins.iloc[batch_start:batch_end]

        print(f"[t_travel] batch {batch_start}–{batch_start + len(batch)}")

        travel_time_matrix = TravelTimeMatrix(
            transport_network=r5_network,
            origins=batch,
            destinations=destinations,
            departure=departure_time,
            transport_modes=["WALK", "TRANSIT"],
            max_time=max_time,
        )

        batch_results.append(pd.DataFrame(travel_time_matrix))

    df_all = pd.concat(batch_results, ignore_index=True)

    # Drop self-trips (a neighborhood doesn't need to travel to itself)
    df_all = df_all[df_all["from_id"] != df_all["to_id"]]

    return df_all


def compute_avg_travel_time_per_origin(df):
    """
    Collapse the OD matrix to one average travel time per origin neighborhood.

    Parameters:
        df: DataFrame with columns from_id, to_id, travel_time

    Returns:
        DataFrame with columns: from_id, avg_travel_time (mean across all reachable destinations)
    """

    avg_per_origin = df.groupby("from_id")["travel_time"].mean()
    avg_per_origin = avg_per_origin.reset_index()
    avg_per_origin = avg_per_origin.rename(columns={"travel_time": "avg_travel_time"})
    return avg_per_origin

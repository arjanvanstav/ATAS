"""
_accessibility_model.py — Shared helpers used by both the accessibility and benefit pipelines.

Provides two functions:
  _get_t_walk_in_minutes   — walking time from each neighborhood to its nearest transit stop
  _get_t_travel_od_matrix  — transit travel times between all pairs of neighborhoods (OD matrix)
"""

import geopandas as gpd
from shapely import wkb

from atas.core._t_walk import compute_t_walk
from atas.core._t_travel import compute_t_travel_matrix

# 5 km/h walking speed in meters per minute
WALKING_SPEED_METERS_PER_MINUTE = 83.33


def _get_neighborhood_centroids(database):
    """
    Return the center point of each neighborhood as a GeoDataFrame in EPSG:4326 (WGS84).

    R5 needs lat/lon coordinates, so we convert from the internal Dutch CRS (EPSG:28992).
    """

    df = database.conn.sql("""
        SELECT
            id,
            ST_AsWKB(ST_Centroid(geometry)) AS geometry
        FROM Neighborhoods
    """).df()

    df["geometry"] = df["geometry"].apply(_load_wkb_geometry)
    df = df.dropna(subset=["geometry"])
    gdf = gpd.GeoDataFrame(df, geometry="geometry", crs="EPSG:28992")
    return gdf.to_crs("EPSG:4326")


def _load_wkb_geometry(raw_bytes):
    """Convert raw WKB bytes from DuckDB into a Shapely geometry. Returns None on failure."""
    try:
        return wkb.loads(bytes(raw_bytes))
    except Exception:
        return None


def _get_t_walk_in_minutes(database, network):
    """
    Compute average walking time (minutes) from each neighborhood to its nearest transit stop.

    Calls compute_t_walk() which uses Dijkstra on the pedestrian network.
    Returns a DataFrame with columns: neighborhood_id, t_walk_min.
    Note: modifies the database by linking transit stops to the pedestrian network.
    """

    df = compute_t_walk(database, network)
    df["t_walk_min"] = df["avg_dist"] / WALKING_SPEED_METERS_PER_MINUTE
    return df[["neighborhood_id", "t_walk_min"]].copy()


def _get_t_travel_od_matrix(network, database, departure_time, batch_size, max_time):
    """
    Compute the transit travel time between all pairs of neighborhoods (OD matrix).

    Uses neighborhood centroids as origins and destinations, routed via R5.

    Parameters:
        network: Network object with the R5 transit network built
        database: Database object with neighborhood geometries
        departure_time: Departure time (affects which services run)
        batch_size: Origins per R5 batch (reduce if memory runs out)
        max_time: Trips longer than this are treated as unreachable

    Returns:
        DataFrame with columns: from_id, to_id, travel_time (minutes)
    """

    centroids = _get_neighborhood_centroids(database)
    return compute_t_travel_matrix(
        network=network,
        origins=centroids.copy(),
        destinations=centroids.copy(),
        departure_time=departure_time,
        batch_size=batch_size,
        max_time=max_time,
    )

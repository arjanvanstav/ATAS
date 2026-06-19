"""
_t_walk.py — Compute average walking time from each neighborhood to the nearest transit stop.

Algorithm:
  1. Link each transit stop to the nearest pedestrian network node
  2. Relocate isolated stops that can't be walked to
  3. Run multi-source Dijkstra from all stops to find walking distance per node
  4. Match neighborhood sample points to reachable nodes
  5. Average distances across all sample points per neighborhood

Returns one average walking distance (meters) per neighborhood.
Side effect: modifies the database by linking transit stops to the pedestrian network.
"""

import geopandas as gpd
from shapely import wkb



def compute_t_walk(database, network, max_pts_dist: int = 50):
    """
    Compute average walking distance (meters) from each neighborhood to its nearest transit stop.

    Parameters:
        database: Database object (must have pre_process() run)
        network: Network object with a pedestrian street graph
        max_pts_dist: Max distance (meters) between a sample point and a reachable network node.
                      Default 50m is slightly higher than the settings default (30m) to avoid
                      losing borderline neighborhoods.

    Returns:
        DataFrame with columns: neighborhood_id, avg_dist (meters)
    """

    # Link transit stops to pedestrian network nodes
    database.link_busses()

    # Move stops that are isolated (not reachable on foot)
    database.move_transit_minimal()

    # Multi-source Dijkstra from all stops simultaneously
    database.calculate_distances_to_nearest_transit()

    # Assign sample points only to nodes reachable from at least one stop
    database.create_pts_per_neighborhood_reachable(max_pts_dist=max_pts_dist)

    # Average walking distances per neighborhood
    df = database.get_dist_per_neighborhood()

    return df


def attach_geometry_to_t_walk(database, df):
    """
    Add neighborhood boundary polygons to the t_walk results for mapping.

    All neighborhoods are included; those with no t_walk result get NaN for avg_dist.

    Parameters:
        database: Database object with a Neighborhoods table
        df: DataFrame from compute_t_walk() — columns: neighborhood_id, avg_dist

    Returns:
        GeoDataFrame with columns: id, regio, neighborhood_id, avg_dist, geometry
    """

    geom_df = database.conn.sql("""
        SELECT id, regio, ST_AsWKB(geometry) AS geometry
        FROM Neighborhoods
    """).df()

    geom_df["geometry"] = geom_df["geometry"].apply(
        lambda raw: wkb.loads(bytes(raw))
    )

    gdf_geom = gpd.GeoDataFrame(geom_df, geometry="geometry", crs="EPSG:28992")

    merged = gdf_geom.merge(
        df[["neighborhood_id", "avg_dist"]],
        left_on="id",
        right_on="neighborhood_id",
        how="left",
    )

    return gpd.GeoDataFrame(merged, geometry="geometry", crs="EPSG:28992")

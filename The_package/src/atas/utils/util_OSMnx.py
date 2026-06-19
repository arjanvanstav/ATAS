"""
util_OSMnx.py — Wrappers around OSMnx for downloading street networks and POI features.

OSMnx downloads OpenStreetMap data and converts it to NetworkX graphs.
All graphs are projected to EPSG:28992 (Dutch RD New) after download.
"""

import osmnx as ox


def get_graph(city:str, project=True, network_type="drive"):
    """
    Download and return a street graph for the given city, projected to EPSG:28992.

    Args:
        city: City name in Dutch (e.g. "Amsterdam").
        network_type: "drive" or "walk".

    Returns:
        NetworkX MultiDiGraph in EPSG:28992.
    """
    G = ox.graph_from_place(f"{city}, Netherlands", simplify=True, retain_all=True, network_type=network_type)
    if project:
        return ox.project_graph(G, to_crs="epsg:28992", to_latlong=False)
    else:
        return G

def get_features(city:str, amenity=True, public_transport=True, project=True):
    """
    Download and return OSMnx amenity and/or public transport features for the given city.

    Returns:
        GeoDataFrame of features in EPSG:28992.
    """
    if amenity and public_transport:
        tags = {"amenity": True, "public_transport": True}
    elif amenity and not public_transport:
        tags = {"amenity": True}
    elif not amenity and public_transport:
        tags = {"public_transport": True}
    else:
        raise ValueError("amenity and public_transport can not be both False.")
    gdf = ox.features_from_place(f"{city}, Netherlands", tags=tags)  # pyright: ignore[reportArgumentType]
    if project:
        return ox.projection.project_gdf(gdf, to_crs="epsg:28992", to_latlong=False)
    else:
        return gdf


def get_graph_from_polygon(polygon, project=True, network_type="drive"):
    """
    Download a street graph for the given polygon boundary.

    Use this instead of get_graph() when the city name doesn't match the CBS boundary
    (e.g. Amsterdam after the 2022 merger with Weesp).

    Args:
        polygon: Shapely polygon in EPSG:4326.
        project: If True, project to EPSG:28992.
        network_type: "drive" or "walk".

    Returns:
        NetworkX MultiDiGraph in EPSG:28992.
    """
    G = ox.graph_from_polygon(polygon, simplify=True, retain_all=True, network_type=network_type)
    if project:
        return ox.project_graph(G, to_crs="epsg:28992", to_latlong=False)
    return G


def get_features_from_polygon(polygon, amenity=True, public_transport=True, project=True):
    """
    Download OSMnx features within a given polygon boundary.

    Polygon-based alternative to get_features() — use alongside get_graph_from_polygon().

    Returns:
        GeoDataFrame of features in EPSG:28992.
    """
    if amenity and public_transport:
        tags = {"amenity": True, "public_transport": True}
    elif amenity and not public_transport:
        tags = {"amenity": True}
    elif not amenity and public_transport:
        tags = {"public_transport": True}
    else:
        raise ValueError("amenity and public_transport cannot both be False.")
    gdf = ox.features_from_polygon(polygon, tags=tags)  # pyright: ignore[reportArgumentType]
    if project:
        return ox.projection.project_gdf(gdf, to_crs="epsg:28992", to_latlong=False)
    return gdf

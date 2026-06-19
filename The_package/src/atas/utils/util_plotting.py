"""
util_plotting.py — Functions for visualizing pipeline results as maps and charts.

Each metric computed by the pipeline (t_walk, t_travel, accessibility, benefit, etc.)
has a corresponding plotting function here. Plots are saved as PNG files to the output folder.

There are two types of functions in this file:
  - attach_geometry_to_*  : joins a results DataFrame to neighborhood polygons so it can be mapped
  - plot_*                : creates and saves the actual map or chart

The maps use choropleth styling (neighborhoods colored by their metric value).
The coordinate system used internally is EPSG:28992 (Dutch RD New, in meters).
"""

import osmnx as ox
import networkx as nx
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.cm as cm
import matplotlib as mpl
import os
import numpy as np

from atas.config.settings import get_settings
settings = get_settings()


def bar_demographic_average_distance(df: pd.DataFrame, title='Average Distance per Group', subtitle='', storage_folder='.', name='dist_per_dem_grp'):
    """Bar chart of average walking distance per demographic group with a red horizontal mean line."""
    # Splitting average from dataframes
    avg = df.loc[df["dem_grp"] == "avg", "avg_dist"].iloc[0]
    df = df[df["dem_grp"] != "avg"]

    # Creating bar diagraph
    fig, ax = plt.subplots()
    ax.bar(df["dem_grp"], df["avg_dist"], color='lightgrey', rasterized=True)
    ax.axhline(y=avg, color='red')

    # Setting labels
    ax.set_xlabel("Demographic Groups")
    ax.set_ylabel("Average Distance")
    plt.suptitle(title)
    plt.title(subtitle, fontsize=8)
    ax.tick_params(axis='x', which='major', pad=5)
    plt.xticks(rotation=90)
    plt.tight_layout()

    ax.annotate(
        f"Average = {int(avg)}",
        xy=(1, avg),
        xytext=(-5, 5),
        xycoords=("axes fraction", "data"),
        textcoords="offset points",
        ha="right",
        va="bottom",
        color="red"
    )

    # Save bar-diagraph
    if not os.path.isdir(storage_folder):
        os.makedirs(storage_folder)

    fig.savefig(os.path.join(storage_folder, name + '.svg'))


def plot_points(xs: np.ndarray, ys: np.ndarray, title='Average Distance per Group', subtitle='', storage_folder='.', name='generated_points'):
    """Plot sample points as a scatter. Saves as SVG for small sets or PNG for > 5000 points."""
    # Create figure
    fig = plt.figure()
    plt.scatter(xs, ys, s=0.5, edgecolors='none')

    # Labels
    plt.suptitle(title)
    plt.title(subtitle, fontsize=8)

    # Make sure directory exists
    if not os.path.isdir(storage_folder):
        os.makedirs(storage_folder)

    # Save figure .svg if small, .png if large
    if xs.size < 5000:
        fig.savefig(os.path.join(storage_folder, name + '.svg'), format='svg')
    else:
        fig.savefig(os.path.join(storage_folder, name + '.png'), format='png', dpi=settings.png_dpi)


def bar_dist_per_neighborhood(df: gpd.GeoDataFrame, title='Average Distance per Neighbourhood', subtitle='', storage_folder='.', name='dist_per_neighborhood'):
    """Bar chart of average walking distance per neighborhood."""

    # Creating bar diagraph
    fig, ax = plt.subplots()
    ax.bar(df["neighborhood"], df["avg_dist"], color='lightgrey', rasterized=True)

    # Setting labels
    ax.set_xlabel("Neighbourhoods")
    ax.set_ylabel("Average Distances")
    plt.suptitle(title)
    plt.title(subtitle, fontsize=8)
    ax.set_xticklabels([])
    plt.tight_layout()


    # Save bar-diagraph
    if not os.path.isdir(storage_folder):
        os.makedirs(storage_folder)

    fig.savefig(os.path.join(storage_folder, name + '.svg'))


def colored_network(gdf: gpd.GeoDataFrame, graph: nx.MultiDiGraph, title='Average Distance per Neighbourhood', subtitle='', storage_folder='.', name='dist_per_neighborhood', svg=True, force_linear=False):
    """
    Choropleth network map colored by avg_dist from get_dist_per_neighborhood().

    Neighborhoods are colored red (increase) through yellow (no change) to green (decrease).
    """
    # Create Colormap
    vals = gdf['avg_dist']
    v_min, v_max = vals.min(), vals.max()
    if force_linear:
        norm = plt.Normalize(v_min, v_max) # type: ignore
    else:
        norm = settings.color_normalization(v_min, v_max) # type: ignore
    cmap = mpl.colormaps[settings.colormap]

    # Add use Colormap to determine the color for every neighborhood
    gdf['color'] = gdf['avg_dist'].apply(lambda x: cmap(norm(x)))

    # Plot the neighborhood colors
    fig, ax = ox.plot_footprints(gdf, color=gdf['color'], edge_color='black', alpha=0.4, show=False, close=False) # type: ignore

    # Plot the network
    fig, ax = ox.plot_graph(graph, ax=ax, node_size=0, edge_color='white', edge_linewidth=0.5, show=False, close=False)

    # Create the color-bar used for the legenda
    sm = cm.ScalarMappable(norm=norm, cmap=cmap)
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax, orientation='vertical', pad=0.02, shrink=0.8)

    # Create the labels for the legenda
    u = np.linspace(0, 1, num=settings.legend_num_labels)
    tick_values = norm.inverse(u).tolist()
    # tick_values = np.linspace(v_min, v_max, num=5)
    cbar.set_ticks(tick_values)
    cbar.set_ticklabels([str(int(x)) for x in tick_values])
    cbar.set_label('Average Distance', fontsize=10)

    # Save bar-diagraph
    if not os.path.isdir(storage_folder):
        os.makedirs(storage_folder)

    if svg:
        fig.savefig(os.path.join(storage_folder, name + '.svg'))
    else:
        fig.savefig(os.path.join(storage_folder, name + '.png'), dpi=settings.png_dpi)

def plot_neighborhood_pts_map(database, storage_folder="debug", name="neighborhood_pts", show=False):
    """
    Plot Poisson-disk sample points for all neighbourhoods on a CartoDB Positron basemap.
    Each point represents one representative location used to compute t_walk.
    """
    import os
    import contextily as cx
    import matplotlib.pyplot as plt
    from shapely import wkb
    from shapely.geometry import Point

    os.makedirs(storage_folder, exist_ok=True)

    # Fetch neighborhood outlines
    geom_df = database.conn.sql("""
        SELECT id, regio, ST_AsWKB(geometry) AS geometry
        FROM Neighborhoods
    """).df()
    geom_df["geometry"] = geom_df["geometry"].apply(lambda x: wkb.loads(bytes(x)))
    gdf_neighbourhoods = gpd.GeoDataFrame(geom_df, geometry="geometry", crs="EPSG:28992")

    # Fetch sample points
    pts_df = database.conn.sql("""
        SELECT ST_X(pt) AS x, ST_Y(pt) AS y
        FROM Neighborhood_pts
    """).df()
    gdf_pts = gpd.GeoDataFrame(
        pts_df,
        geometry=[Point(row.x, row.y) for _, row in pts_df.iterrows()],
        crs="EPSG:28992"
    )

    # Reproject to Web Mercator for basemap
    gdf_neighbourhoods = gdf_neighbourhoods.to_crs(epsg=3857)
    gdf_pts = gdf_pts.to_crs(epsg=3857)

    fig, ax = plt.subplots(figsize=(14, 12))

    gdf_neighbourhoods.plot(
        ax=ax, color="none", edgecolor="#555555", linewidth=0.5, alpha=0.8
    )
    gdf_pts.plot(
        ax=ax, color="#E74C3C", markersize=1.5, alpha=0.6
    )

    cx.add_basemap(ax, crs=gdf_neighbourhoods.crs, source=cx.providers.CartoDB.Positron)

    n_pts = len(pts_df)
    n_hoods = database.conn.sql(
        "SELECT COUNT(DISTINCT neighborhood_id) FROM Neighborhood_pts"
    ).fetchone()[0]
    ax.set_title(
        f"Poisson-disk sample points ({n_pts:,} points across {n_hoods} neighbourhoods)",
        fontsize=13
    )
    ax.axis("off")

    plt.tight_layout()
    plt.savefig(f"{storage_folder}/{name}.png", dpi=300, bbox_inches="tight")

    if show:
        plt.show()

    plt.close()


def plot_t_walk_map(gdf, storage_folder="debug", name="t_walk", show=False, clip_minutes=15):
    """
    Choropleth map of average walking time to the nearest transit stop.

    Converts avg_dist (meters) to minutes at 5 km/h. Times above clip_minutes are
    clamped to avoid compressing the color scale. Neighbourhoods with no data are
    shown with grey hatching.
    """
    import os
    import contextily as cx
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import matplotlib.gridspec as gridspec
    from matplotlib.colors import LinearSegmentedColormap

    os.makedirs(storage_folder, exist_ok=True)

    gdf = gdf.copy()
    gdf["t_walk_min"] = gdf["avg_dist"] / 83.33

    # Reproject to Web Mercator for contextily tile alignment
    gdf = gdf.to_crs(epsg=3857)

    # Custom colormap: light green (short walk = good) → dark red (long walk = bad)
    walk_cmap = LinearSegmentedColormap.from_list(
        "walk_time", ["#A8D5A2", "#FFF176", "#FF8F00", "#B71C1C"]
    )

    fig = plt.figure(figsize=(18, 10))
    gs = gridspec.GridSpec(1, 2, width_ratios=[2.5, 1], figure=fig)
    ax_map = fig.add_subplot(gs[0])
    ax_table = fig.add_subplot(gs[1])
    ax_table.axis("off")

    # Excluded neighbourhoods (no t_walk result — outside pedestrian network)
    gdf_excluded = gdf[gdf["t_walk_min"].isna()]
    if len(gdf_excluded) > 0:
        gdf_excluded.plot(
            color="#D6CFC7", edgecolor="#AAAAAA", linewidth=0.4,
            hatch="///", ax=ax_map, alpha=0.6
        )

    # Clip and plot choropleth for neighbourhoods with data
    gdf_valid = gdf[gdf["t_walk_min"].notna()].copy()
    gdf_valid["t_walk_plot"] = gdf_valid["t_walk_min"].clip(upper=clip_minutes)

    bin_step = clip_minutes / 5
    bins = [bin_step * i for i in range(1, 6)]  # 5 equal-width bins

    if len(gdf_valid) > 0:
        gdf_valid.plot(
            column="t_walk_plot",
            cmap=walk_cmap,
            scheme="user_defined",
            classification_kwds={"bins": bins},
            legend=True,
            ax=ax_map,
            alpha=0.75,
            legend_kwds={
                "title": f"Walking time (min, capped at {clip_minutes})",
                "loc": "lower right"
            }
        )

    # CartoDB Positron basemap
    cx.add_basemap(ax_map, crs=gdf.crs, source=cx.providers.CartoDB.Positron)

    # Manual legend for excluded neighbourhoods
    excl_patch = mpatches.Patch(
        facecolor="#D6CFC7", edgecolor="#AAAAAA", hatch="///",
        label="No data (outside pedestrian network)"
    )
    existing_legend = ax_map.get_legend()
    if existing_legend is not None:
        ax_map.add_artist(existing_legend)
    ax_map.legend(handles=[excl_patch], loc="upper left", fontsize=8)

    ax_map.set_title(
        "Average Walking Time to Nearest Transit Stop\n(5 km/h walking speed)",
        fontsize=13
    )
    ax_map.axis("off")

    # --- Table: longest and shortest walks ---
    name_col = "regio" if "regio" in gdf.columns else "neighborhood_id"
    df_tbl = gdf[gdf["t_walk_min"].notna()][[name_col, "t_walk_min"]].copy()
    top5 = df_tbl.nlargest(5, "t_walk_min")
    bot5 = df_tbl.nsmallest(5, "t_walk_min")

    header = ["Neighbourhood", "Walk (min)"]
    top_label = ["── Longest walk ──", ""]
    bot_label = ["── Shortest walk ──", ""]
    def _fmt_walk(v):
        return "< 0.1" if v < 0.1 else f"{v:.1f}"

    top_rows = [[row[name_col], _fmt_walk(row["t_walk_min"])] for _, row in top5.iterrows()]
    bot_rows = [[row[name_col], _fmt_walk(row["t_walk_min"])] for _, row in bot5.iterrows()]

    cell_text = [top_label] + top_rows + [bot_label] + bot_rows

    table = ax_table.table(
        cellText=cell_text,
        colLabels=header,
        loc="center",
        cellLoc="left"
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.2, 1.8)

    for col in range(2):
        table[0, col].set_facecolor("#2c3e50")
        table[0, col].set_text_props(color="white", fontweight="bold")

    top_label_row = 1
    bot_label_row = 1 + len(top_rows) + 1
    for col in range(2):
        table[top_label_row, col].set_facecolor("#dce8f5")
        table[top_label_row, col].set_text_props(fontweight="bold")
        table[bot_label_row, col].set_facecolor("#dce8f5")
        table[bot_label_row, col].set_text_props(fontweight="bold")

    ax_table.set_title("Neighbourhood Rankings", fontsize=11, pad=12)

    plt.tight_layout()
    plt.savefig(f"{storage_folder}/{name}.png", dpi=300, bbox_inches="tight")

    if show:
        plt.show()

    plt.close()

def attach_geometry_to_attractiveness(database, df):
    """

        Returns:
            GeoDataFrame with columns: id, regio, attractiveness, geometry. All neighbourhoods included; missing scores are NaN.
    """
    from shapely import wkb

    geom_df = database.conn.sql("""
        SELECT id, regio, ST_AsWKB(geometry) AS geometry
        FROM Neighborhoods
    """).df()

    geom_df["geometry"] = geom_df["geometry"].apply(lambda x: wkb.loads(bytes(x)))
    gdf_geom = gpd.GeoDataFrame(geom_df, geometry="geometry", crs="EPSG:28992")

    merged = gdf_geom.merge(df, left_on="id", right_on="neighborhood_id", how="left")
    return gpd.GeoDataFrame(merged, geometry="geometry", crs="EPSG:28992")


def attach_geometry_to_t_travel(database, df_avg):
    """

        Returns:
            GeoDataFrame with columns: id, regio, avg_travel_time, geometry. All neighbourhoods included; unreachable origins have NaN travel time.
    """
    from shapely import wkb

    geom_df = database.conn.sql("""
        SELECT id, regio, ST_AsWKB(geometry) AS geometry
        FROM Neighborhoods
    """).df()

    geom_df["geometry"] = geom_df["geometry"].apply(lambda x: wkb.loads(bytes(x)))
    gdf_geom = gpd.GeoDataFrame(geom_df, geometry="geometry", crs="EPSG:28992")

    merged = gdf_geom.merge(df_avg, left_on="id", right_on="from_id", how="left")
    return gpd.GeoDataFrame(merged, geometry="geometry", crs="EPSG:28992")


def plot_attractiveness_map(gdf, storage_folder="debug", name="attractiveness", show=False):
    """
    Choropleth map of composite attractiveness (population + jobs + amenities) per neighbourhood.

    Uses quantile classification; dark green = most attractive. Includes a top-5/bottom-5 table.
    """
    import os
    import contextily as cx
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import matplotlib.gridspec as gridspec
    from matplotlib.colors import LinearSegmentedColormap

    os.makedirs(storage_folder, exist_ok=True)

    gdf = gdf.to_crs(epsg=3857)

    attract_cmap = LinearSegmentedColormap.from_list(
        "attract_green", ["#D5F5E3", "#27AE60", "#1A5E35"]
    )

    fig = plt.figure(figsize=(18, 10))
    gs = gridspec.GridSpec(1, 2, width_ratios=[2.5, 1], figure=fig)
    ax_map = fig.add_subplot(gs[0])
    ax_table = fig.add_subplot(gs[1])
    ax_table.axis("off")

    gdf_excluded = gdf[gdf["attractiveness"].isna()]
    if len(gdf_excluded) > 0:
        gdf_excluded.plot(
            color="#D6CFC7", edgecolor="#AAAAAA", linewidth=0.4,
            hatch="///", ax=ax_map, alpha=0.6
        )

    gdf_valid = gdf[gdf["attractiveness"].notna()].copy()
    if len(gdf_valid) > 0:
        gdf_valid.plot(
            column="attractiveness",
            cmap=attract_cmap,
            scheme="quantiles",
            k=5,
            legend=True,
            ax=ax_map,
            alpha=0.75,
            legend_kwds={"title": "Attractiveness (quantiles)", "loc": "lower right"}
        )

    cx.add_basemap(ax_map, crs=gdf.crs, source=cx.providers.CartoDB.Positron)

    excl_patch = mpatches.Patch(
        facecolor="#D6CFC7", edgecolor="#AAAAAA", hatch="///",
        label="No data"
    )
    existing_legend = ax_map.get_legend()
    if existing_legend is not None:
        ax_map.add_artist(existing_legend)
    ax_map.legend(handles=[excl_patch], loc="upper left", fontsize=8)

    ax_map.set_title(
        "Neighbourhood Attractiveness\n(population + jobs + amenities, darker = more attractive)",
        fontsize=13
    )
    ax_map.axis("off")

    name_col = "regio" if "regio" in gdf.columns else "id"
    df_valid = gdf[gdf["attractiveness"].notna()][[name_col, "attractiveness"]].copy()
    top5 = df_valid.nlargest(5, "attractiveness")
    bot5 = df_valid.nsmallest(5, "attractiveness")

    header = ["Neighbourhood", "Score"]
    top_label = ["── Most attractive ──", ""]
    bot_label = ["── Least attractive ──", ""]
    top_rows = [[row[name_col], f"{row['attractiveness']:.1f}"] for _, row in top5.iterrows()]
    bot_rows = [[row[name_col], f"{row['attractiveness']:.1f}"] for _, row in bot5.iterrows()]

    cell_text = [top_label] + top_rows + [bot_label] + bot_rows
    table = ax_table.table(
        cellText=cell_text, colLabels=header, loc="center", cellLoc="left"
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.2, 1.8)

    for col in range(2):
        table[0, col].set_facecolor("#1A5E35")
        table[0, col].set_text_props(color="white", fontweight="bold")

    for row_idx in [1, 1 + len(top_rows) + 1]:
        for col in range(2):
            table[row_idx, col].set_facecolor("#D5F5E3")
            table[row_idx, col].set_text_props(fontweight="bold")

    ax_table.set_title("Neighbourhood Rankings", fontsize=11, pad=12)

    plt.tight_layout()
    plt.savefig(f"{storage_folder}/{name}.png", dpi=300, bbox_inches="tight")

    if show:
        plt.show()

    plt.close()


def plot_t_travel_avg_map(gdf, storage_folder="debug", name="t_travel", show=False):
    """
    Choropleth map of average transit travel time per neighbourhood.

    Yellow = short / well-connected, red = long. Unreachable neighbourhoods shown with grey hatching.
    """
    import os
    import contextily as cx
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import matplotlib.gridspec as gridspec
    from matplotlib.colors import LinearSegmentedColormap

    os.makedirs(storage_folder, exist_ok=True)

    gdf = gdf.to_crs(epsg=3857)

    travel_cmap = LinearSegmentedColormap.from_list(
        "travel_warm", ["#FFF176", "#FF8C00", "#CC0000"]
    )

    fig = plt.figure(figsize=(18, 10))
    gs = gridspec.GridSpec(1, 2, width_ratios=[2.5, 1], figure=fig)
    ax_map = fig.add_subplot(gs[0])
    ax_table = fig.add_subplot(gs[1])
    ax_table.axis("off")

    gdf_excluded = gdf[gdf["avg_travel_time"].isna()]
    if len(gdf_excluded) > 0:
        gdf_excluded.plot(
            color="#D6CFC7", edgecolor="#AAAAAA", linewidth=0.4,
            hatch="///", ax=ax_map, alpha=0.6
        )

    gdf_valid = gdf[gdf["avg_travel_time"].notna()].copy()
    if len(gdf_valid) > 0:
        gdf_valid.plot(
            column="avg_travel_time",
            cmap=travel_cmap,
            scheme="quantiles",
            k=5,
            legend=True,
            ax=ax_map,
            alpha=0.75,
            legend_kwds={"title": "Avg travel time (min, quantiles)", "loc": "lower right"}
        )

    cx.add_basemap(ax_map, crs=gdf.crs, source=cx.providers.CartoDB.Positron)

    excl_patch = mpatches.Patch(
        facecolor="#D6CFC7", edgecolor="#AAAAAA", hatch="///",
        label="Unreachable / no data"
    )
    existing_legend = ax_map.get_legend()
    if existing_legend is not None:
        ax_map.add_artist(existing_legend)
    ax_map.legend(handles=[excl_patch], loc="upper left", fontsize=8)

    ax_map.set_title(
        "Average Transit Travel Time per Neighbourhood\n(yellow = short / well-connected, red = long)",
        fontsize=13
    )
    ax_map.axis("off")

    name_col = "regio" if "regio" in gdf.columns else "id"
    df_valid = gdf[gdf["avg_travel_time"].notna()][[name_col, "avg_travel_time"]].copy()
    top5 = df_valid.nsmallest(5, "avg_travel_time")   # best = shortest
    bot5 = df_valid.nlargest(5, "avg_travel_time")    # worst = longest

    header = ["Neighbourhood", "Avg time (min)"]
    top_label = ["── Best connected ──", ""]
    bot_label = ["── Worst connected ──", ""]
    top_rows = [[row[name_col], f"{row['avg_travel_time']:.1f}"] for _, row in top5.iterrows()]
    bot_rows = [[row[name_col], f"{row['avg_travel_time']:.1f}"] for _, row in bot5.iterrows()]

    cell_text = [top_label] + top_rows + [bot_label] + bot_rows
    table = ax_table.table(
        cellText=cell_text, colLabels=header, loc="center", cellLoc="left"
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.2, 1.8)

    for col in range(2):
        table[0, col].set_facecolor("#2c3e50")
        table[0, col].set_text_props(color="white", fontweight="bold")

    for row_idx in [1, 1 + len(top_rows) + 1]:
        for col in range(2):
            table[row_idx, col].set_facecolor("#FFF9C4")
            table[row_idx, col].set_text_props(fontweight="bold")

    ax_table.set_title("Neighbourhood Rankings", fontsize=11, pad=12)

    plt.tight_layout()
    plt.savefig(f"{storage_folder}/{name}.png", dpi=300, bbox_inches="tight")

    if show:
        plt.show()

    plt.close()

def attach_geometry_to_accessibility_score(database, df):
    """
    Join accessibility scores to neighborhood polygons.

    All neighbourhoods are included; non-residential ones (excluded by the population filter)
    appear with NaN scores and can be rendered distinctly (e.g. grey hatching) in the plot.
    """
    from shapely import wkb

    geom_df = database.conn.sql("""
        SELECT id, regio, ST_AsWKB(geometry) AS geometry
        FROM Neighborhoods
    """).df()

    geom_df["geometry"] = geom_df["geometry"].apply(lambda x: wkb.loads(bytes(x)))

    gdf_geom = gpd.GeoDataFrame(geom_df, geometry="geometry", crs="EPSG:28992")

    merged = gdf_geom.merge(
        df,
        left_on="id",
        right_on="neighborhood_id",
        how="left"
    )

    return gpd.GeoDataFrame(merged, geometry="geometry", crs="EPSG:28992")


def plot_accessibility_score_map(gdf, storage_folder="debug", name="accessibility_score", show=False):
    """
    Choropleth map of transit accessibility score (0–100) per neighbourhood.

    Uses equal-interval bins (0-20, …, 80-100); dark blue = best served. Includes a
    top-5/bottom-5 table. Non-residential neighbourhoods are shown with grey hatching.
    """
    import os
    import contextily as cx
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import matplotlib.gridspec as gridspec
    from matplotlib.colors import LinearSegmentedColormap

    os.makedirs(storage_folder, exist_ok=True)

    # Reproject to Web Mercator for contextily tile alignment
    gdf = gdf.to_crs(epsg=3857)

    # Custom cool colormap: light blue → medium blue → dark navy (low → high accessibility)
    access_cmap = LinearSegmentedColormap.from_list(
        "access_cool", ["#C6E2FF", "#4A90D9", "#1A5276"]
    )

    fig = plt.figure(figsize=(18, 10))
    gs = gridspec.GridSpec(1, 2, width_ratios=[2.5, 1], figure=fig)
    ax_map = fig.add_subplot(gs[0])
    ax_table = fig.add_subplot(gs[1])
    ax_table.axis("off")

    # Excluded neighbourhoods (non-residential, filtered by population threshold)
    gdf_excluded = gdf[gdf["accessibility_score"].isna()]
    if len(gdf_excluded) > 0:
        gdf_excluded.plot(
            color="#D6CFC7",
            edgecolor="#AAAAAA",
            linewidth=0.4,
            hatch="///",
            ax=ax_map,
            alpha=0.6
        )

    # Equal-interval choropleth for all residential neighbourhoods
    gdf_valid = gdf[gdf["accessibility_score"].notna()].copy()
    if len(gdf_valid) > 0:
        gdf_valid.plot(
            column="accessibility_score",
            cmap=access_cmap,
            scheme="user_defined",
            classification_kwds={"bins": [20, 40, 60, 80, 100]},
            legend=True,
            ax=ax_map,
            alpha=0.75,
            legend_kwds={"title": "Accessibility score (%)", "loc": "lower right"}
        )

    # CartoDB Positron basemap — light streets and labels, minimal visual noise
    cx.add_basemap(ax_map, crs=gdf.crs, source=cx.providers.CartoDB.Positron)

    # Manual legend entry for excluded neighbourhoods
    excl_patch = mpatches.Patch(
        facecolor="#D6CFC7", edgecolor="#AAAAAA", hatch="///",
        label="Excluded (non-residential)"
    )
    existing_legend = ax_map.get_legend()
    if existing_legend is not None:
        ax_map.add_artist(existing_legend)
    ax_map.legend(handles=[excl_patch], loc="upper left", fontsize=8)

    ax_map.set_title(
        "Transit Accessibility Score per Neighbourhood\n(high = best served by public transit)",
        fontsize=13
    )
    ax_map.axis("off")

    # --- Table: top 5 and bottom 5 ---
    name_col = "regio" if "regio" in gdf.columns else "neighborhood_id"
    df_valid = gdf[gdf["accessibility_score"].notna()][[name_col, "accessibility_score"]].copy()
    top5 = df_valid.nlargest(5, "accessibility_score")
    bot5 = df_valid.nsmallest(5, "accessibility_score")

    header = ["Neighbourhood", "Score (%)"]
    top_label = ["── Highest accessibility ──", ""]
    bot_label = ["── Lowest accessibility ──", ""]
    top_rows = [[row[name_col], f"{row['accessibility_score']:.1f}"] for _, row in top5.iterrows()]
    bot_rows = [[row[name_col], f"{row['accessibility_score']:.1f}"] for _, row in bot5.iterrows()]

    cell_text = [top_label] + top_rows + [bot_label] + bot_rows
    col_labels = header

    table = ax_table.table(
        cellText=cell_text,
        colLabels=col_labels,
        loc="center",
        cellLoc="left"
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.2, 1.8)

    # Style: column headers
    for col in range(2):
        table[0, col].set_facecolor("#2c3e50")
        table[0, col].set_text_props(color="white", fontweight="bold")

    # Style: section label rows
    top_label_row = 1
    bot_label_row = 1 + len(top_rows) + 1
    for col in range(2):
        table[top_label_row, col].set_facecolor("#dce8f5")
        table[top_label_row, col].set_text_props(fontweight="bold")
        table[bot_label_row, col].set_facecolor("#dce8f5")
        table[bot_label_row, col].set_text_props(fontweight="bold")

    ax_table.set_title("Neighbourhood Rankings", fontsize=11, pad=12)

    path = f"{storage_folder}/{name}.png"
    plt.tight_layout()
    plt.savefig(path, dpi=300, bbox_inches="tight")

    if show:
        plt.show()

    plt.close()


def attach_geometry_to_benefit(database, df):
    """
    Join benefit scores to neighborhood polygons.

    All neighbourhoods are included; non-residential ones appear with NaN benefit_score
    so they can be rendered distinctly in the plot.
    """
    from shapely import wkb

    geom_df = database.conn.sql("""
        SELECT id, regio, ST_AsWKB(geometry) AS geometry
        FROM Neighborhoods
    """).df()

    geom_df["geometry"] = geom_df["geometry"].apply(lambda x: wkb.loads(bytes(x)))

    gdf_geom = gpd.GeoDataFrame(geom_df, geometry="geometry", crs="EPSG:28992")

    merged = gdf_geom.merge(
        df,
        left_on="id",
        right_on="neighborhood_id",
        how="left"
    )

    return gpd.GeoDataFrame(merged, geometry="geometry", crs="EPSG:28992")


def plot_benefit_map(gdf, storage_folder="debug", name="benefit", show=False):
    """
    Choropleth map of benefit score per neighbourhood using equal-interval bins.

    Neighbourhoods with benefit = 0 (best served) are shown in light blue. Non-residential
    neighbourhoods with no data are shown in grey. Includes a top-5/bottom-5 priority table.
    """
    import os
    import contextily as cx
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import matplotlib.gridspec as gridspec
    from matplotlib.colors import LinearSegmentedColormap

    os.makedirs(storage_folder, exist_ok=True)

    # Reproject to Web Mercator for contextily tile alignment
    gdf = gdf.to_crs(epsg=3857)

    # Custom warm colormap: bright yellow → orange → red
    benefit_cmap = LinearSegmentedColormap.from_list(
        "benefit_warm", ["#FFD700", "#FF8C00", "#FF4500", "#CC0000"]
    )

    fig = plt.figure(figsize=(18, 10))
    gs = gridspec.GridSpec(1, 2, width_ratios=[2.5, 1], figure=fig)
    ax_map = fig.add_subplot(gs[0])
    ax_table = fig.add_subplot(gs[1])
    ax_table.axis("off")

    # Excluded neighbourhoods (non-residential, filtered by population threshold)
    gdf_excluded = gdf[gdf["benefit_score"].isna()]
    if len(gdf_excluded) > 0:
        gdf_excluded.plot(
            color="#D6CFC7",
            edgecolor="#AAAAAA",
            linewidth=0.4,
            hatch="///",
            ax=ax_map,
            alpha=0.6
        )

    # Light blue for neighbourhoods with zero benefit (best served)
    gdf_zero = gdf[(gdf["benefit_score"].notna()) & (gdf["benefit_score"] == 0)]
    if len(gdf_zero) > 0:
        gdf_zero.plot(color="#a8d8ea", ax=ax_map, alpha=0.7)

    # Equal-interval choropleth for neighbourhoods with positive benefit
    gdf_pos = gdf[gdf["benefit_score"] > 0].copy()
    if len(gdf_pos) > 0:
        gdf_pos.plot(
            column="benefit_score",
            cmap=benefit_cmap,
            scheme="user_defined",
            classification_kwds={"bins": [20, 40, 60, 80, 100]},
            legend=True,
            ax=ax_map,
            alpha=0.75,
            legend_kwds={"title": "Benefit score (%)", "loc": "lower right"}
        )

    # CartoDB Positron basemap — light streets and labels, minimal visual noise
    cx.add_basemap(ax_map, crs=gdf.crs, source=cx.providers.CartoDB.Positron)

    # Manual legend entries for special categories
    zero_patch = mpatches.Patch(color="#a8d8ea", label="0% — best served")
    excl_patch = mpatches.Patch(
        facecolor="#D6CFC7", edgecolor="#AAAAAA", hatch="///",
        label="Excluded (non-residential)"
    )
    existing_legend = ax_map.get_legend()
    if existing_legend is not None:
        ax_map.add_artist(existing_legend)
    ax_map.legend(handles=[zero_patch, excl_patch], loc="upper left", fontsize=8)

    ax_map.set_title(
        "Transit Benefit Score per Neighbourhood\n(high = underserved AND densely populated)",
        fontsize=13
    )
    ax_map.axis("off")

    # --- Table: top 5 and bottom 5 ---
    name_col = "regio" if "regio" in gdf.columns else "neighborhood_id"
    df_valid = gdf[gdf["benefit_score"].notna()][[name_col, "benefit_score"]].copy()
    top5 = df_valid.nlargest(5, "benefit_score")
    bot5 = df_valid.nsmallest(5, "benefit_score")

    header = ["Neighbourhood", "Score (%)"]
    top_label = ["── Highest priority ──", ""]
    bot_label = ["── Lowest priority ──", ""]
    top_rows = [[row[name_col], f"{row['benefit_score']:.1f}"] for _, row in top5.iterrows()]
    bot_rows = [[row[name_col], f"{row['benefit_score']:.1f}"] for _, row in bot5.iterrows()]

    cell_text = [top_label] + top_rows + [bot_label] + bot_rows
    col_labels = header

    table = ax_table.table(
        cellText=cell_text,
        colLabels=col_labels,
        loc="center",
        cellLoc="left"
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.2, 1.8)

    # Style: column headers
    for col in range(2):
        table[0, col].set_facecolor("#2c3e50")
        table[0, col].set_text_props(color="white", fontweight="bold")

    # Style: section label rows
    top_label_row = 1
    bot_label_row = 1 + len(top_rows) + 1
    for col in range(2):
        table[top_label_row, col].set_facecolor("#dce8f5")
        table[top_label_row, col].set_text_props(fontweight="bold")
        table[bot_label_row, col].set_facecolor("#dce8f5")
        table[bot_label_row, col].set_text_props(fontweight="bold")

    ax_table.set_title("Neighbourhood Rankings", fontsize=11, pad=12)

    path = f"{storage_folder}/{name}.png"
    plt.tight_layout()
    plt.savefig(path, dpi=300, bbox_inches="tight")

    if show:
        plt.show()

    plt.close()

def plot_accessibility_diff_map(gdf_rush, gdf_off, storage_folder="debug", name="accessibility_diff", show=False):
    """
    Diverging choropleth of accessibility change: rush hour minus off-hours score.

    Blue = neighbourhood benefits more at rush hour; red = better off-hours.
    The colormap is centered at zero. A table lists the five biggest gainers at each time.
    """
    import os
    import contextily as cx
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    import matplotlib.gridspec as gridspec
    from matplotlib.colors import TwoSlopeNorm, Normalize

    os.makedirs(storage_folder, exist_ok=True)

    # Build delta GDF: use geometry + names from rush run
    scores_rush = gdf_rush[["id", "accessibility_score"]].rename(
        columns={"accessibility_score": "score_rush"}
    )
    scores_off = gdf_off[["id", "accessibility_score"]].rename(
        columns={"accessibility_score": "score_off"}
    )

    gdf = gdf_rush[["id", "regio", "geometry"]].copy()
    gdf = gdf.merge(scores_rush, on="id", how="left")
    gdf = gdf.merge(scores_off, on="id", how="left")
    gdf["delta"] = gdf["score_rush"] - gdf["score_off"]

    gdf = gpd.GeoDataFrame(gdf, geometry="geometry", crs="EPSG:28992")
    gdf = gdf.to_crs(epsg=3857)

    fig = plt.figure(figsize=(18, 10))
    gs = gridspec.GridSpec(1, 2, width_ratios=[2.5, 1], figure=fig)
    ax_map = fig.add_subplot(gs[0])
    ax_table = fig.add_subplot(gs[1])
    ax_table.axis("off")

    # Excluded neighbourhoods (not scored in either run)
    gdf_excluded = gdf[gdf["delta"].isna()]
    if len(gdf_excluded) > 0:
        gdf_excluded.plot(
            color="#D6CFC7", edgecolor="#AAAAAA", linewidth=0.4,
            hatch="///", ax=ax_map, alpha=0.6
        )

    gdf_valid = gdf[gdf["delta"].notna()].copy()

    if len(gdf_valid) > 0:
        v_min = gdf_valid["delta"].min()
        v_max = gdf_valid["delta"].max()

        # TwoSlopeNorm requires vmin < vcenter < vmax; fall back if all same sign
        if v_min < 0 < v_max:
            norm = TwoSlopeNorm(vmin=v_min, vcenter=0, vmax=v_max)
        else:
            norm = Normalize(vmin=v_min, vmax=v_max)

        gdf_valid.plot(
            column="delta",
            cmap="RdBu",
            norm=norm,
            legend=True,
            ax=ax_map,
            alpha=0.75,
            legend_kwds={
                "label": "Score difference (rush - off-hours)",
                "shrink": 0.6,
            }
        )

    cx.add_basemap(ax_map, crs=gdf.crs, source=cx.providers.CartoDB.Positron)

    excl_patch = mpatches.Patch(
        facecolor="#D6CFC7", edgecolor="#AAAAAA", hatch="///",
        label="Excluded (non-residential)"
    )
    existing_legend = ax_map.get_legend()
    if existing_legend is not None:
        ax_map.add_artist(existing_legend)
    ax_map.legend(handles=[excl_patch], loc="upper left", fontsize=8)

    ax_map.set_title(
        "Accessibility Change: Rush Hour vs Off-Hours\n"
        "(blue = better at rush hour  |  red = better off-hours)",
        fontsize=13
    )
    ax_map.axis("off")

    # Table: top 5 gainers and top 5 losers at rush hour
    name_col = "regio" if "regio" in gdf.columns else "id"
    df_tbl = gdf[gdf["delta"].notna()][[name_col, "delta"]].copy()
    top5 = df_tbl.nlargest(5, "delta")
    bot5 = df_tbl.nsmallest(5, "delta")

    header = ["Neighbourhood", "delta score"]
    top_label = ["-- Biggest rush-hour gain --", ""]
    bot_label = ["-- Biggest off-hours gain --", ""]
    top_rows = [[row[name_col], f"+{row['delta']:.1f}"] for _, row in top5.iterrows()]
    bot_rows = [[row[name_col], f"{row['delta']:.1f}"] for _, row in bot5.iterrows()]

    cell_text = [top_label] + top_rows + [bot_label] + bot_rows

    table = ax_table.table(
        cellText=cell_text,
        colLabels=header,
        loc="center",
        cellLoc="left"
    )
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1.2, 1.8)

    for col in range(2):
        table[0, col].set_facecolor("#2c3e50")
        table[0, col].set_text_props(color="white", fontweight="bold")

    top_label_row = 1
    bot_label_row = 1 + len(top_rows) + 1
    for col in range(2):
        table[top_label_row, col].set_facecolor("#dce8f5")
        table[top_label_row, col].set_text_props(fontweight="bold")
        table[bot_label_row, col].set_facecolor("#dce8f5")
        table[bot_label_row, col].set_text_props(fontweight="bold")

    ax_table.set_title("Rush Hour vs Off-Hours", fontsize=11, pad=12)

    plt.tight_layout()
    plt.savefig(f"{storage_folder}/{name}.png", dpi=300, bbox_inches="tight")

    if show:
        plt.show()

    plt.close()


def plot_metric_correlations(
    database,
    gdf_acc,
    gdf_benefit,
    gdf_t_walk=None,
    gdf_rush=None,
    gdf_off=None,
    storage_folder="debug",
    name="metric_correlations",
    show=False,
):
    """
    Generate a set of diagnostic scatter plots and a metric correlation heatmap.

    Panels include: accessibility score histogram, t_walk vs accessibility, population
    density vs accessibility, accessibility vs benefit, rush-hour vs off-hours scatter,
    and a Pearson correlation matrix heatmap. Each scatter has a regression line and
    annotated r value. Saves individual .png files to {storage_folder}/{name}/.
    """
    import os
    import matplotlib.pyplot as plt
    from scipy import stats

    out_dir = os.path.join(storage_folder, name)
    os.makedirs(out_dir, exist_ok=True)

    # -------------------------------------------------------------------------
    # Build a single merged DataFrame — neighborhood_id as primary key
    # -------------------------------------------------------------------------
    def _id_col(df):
        return "neighborhood_id" if "neighborhood_id" in df.columns else "id"

    combined = gdf_acc[[_id_col(gdf_acc), "accessibility_score"]].copy().rename(
        columns={_id_col(gdf_acc): "neighborhood_id"}
    )
    combined = combined[combined["accessibility_score"].notna()].reset_index(drop=True)

    ben_slim = gdf_benefit[[_id_col(gdf_benefit), "benefit_score"]].copy().rename(
        columns={_id_col(gdf_benefit): "neighborhood_id"}
    )
    combined = combined.merge(ben_slim, on="neighborhood_id", how="left")

    has_t_walk = gdf_t_walk is not None
    if has_t_walk:
        tw_slim = gdf_t_walk[[_id_col(gdf_t_walk), "avg_dist"]].copy().rename(
            columns={_id_col(gdf_t_walk): "neighborhood_id"}
        )
        tw_slim["t_walk_min"] = tw_slim["avg_dist"] / 83.33
        combined = combined.merge(tw_slim[["neighborhood_id", "t_walk_min"]],
                                  on="neighborhood_id", how="left")

    has_temporal = gdf_rush is not None and gdf_off is not None
    if has_temporal:
        rush_slim = gdf_rush[[_id_col(gdf_rush), "accessibility_score"]].copy().rename(
            columns={_id_col(gdf_rush): "neighborhood_id", "accessibility_score": "score_rush"}
        )
        off_slim = gdf_off[[_id_col(gdf_off), "accessibility_score"]].copy().rename(
            columns={_id_col(gdf_off): "neighborhood_id", "accessibility_score": "score_off"}
        )
        combined = combined.merge(rush_slim, on="neighborhood_id", how="left")
        combined = combined.merge(off_slim, on="neighborhood_id", how="left")

    # Population density from database (population / area_km²)
    pop_df = database.conn.sql("""
        SELECT id AS neighborhood_id,
               population,
               ST_Area(geometry) / 1e6 AS area_km2
        FROM Neighborhoods
        WHERE population IS NOT NULL
    """).df()
    pop_df["pop_density"] = pop_df["population"] / pop_df["area_km2"].replace(0, np.nan)
    combined = combined.merge(pop_df[["neighborhood_id", "pop_density"]],
                              on="neighborhood_id", how="left")

    # Distance to city centre — centroid of all neighbourhood centroids (EPSG:28992, metres)
    centre_df = database.conn.sql("""
        SELECT id AS neighborhood_id,
               ST_X(ST_Centroid(geometry)) AS cx,
               ST_Y(ST_Centroid(geometry)) AS cy
        FROM Neighborhoods
        WHERE population IS NOT NULL
    """).df()
    city_cx = centre_df["cx"].mean()
    city_cy = centre_df["cy"].mean()
    centre_df["dist_to_centre_km"] = (
        ((centre_df["cx"] - city_cx) ** 2 + (centre_df["cy"] - city_cy) ** 2) ** 0.5 / 1000
    )
    combined = combined.merge(centre_df[["neighborhood_id", "dist_to_centre_km"]],
                              on="neighborhood_id", how="left")

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------
    def _save(fig, filename):
        fig.savefig(os.path.join(out_dir, filename), dpi=300, bbox_inches="tight")
        if show:
            plt.show()
        plt.close(fig)

    def _scatter_fig(x_col, y_col, xlabel, ylabel, color, title, filename):
        mask = combined[x_col].notna() & combined[y_col].notna()
        x = combined.loc[mask, x_col].values
        y = combined.loc[mask, y_col].values
        fig, ax = plt.subplots(figsize=(7, 5))
        ax.scatter(x, y, s=18, alpha=0.55, color=color, edgecolors="none")
        if len(x) > 2:
            slope, intercept, r, p, _ = stats.linregress(x, y)
            x_line = np.linspace(x.min(), x.max(), 200)
            ax.plot(x_line, slope * x_line + intercept,
                    color="#333333", linewidth=1.2, linestyle="--")
            sig = "**" if p < 0.01 else ("*" if p < 0.05 else "")
            ax.text(0.05, 0.93, f"r = {r:.2f}{sig}",
                    transform=ax.transAxes, fontsize=10, color="#333333", va="top")
        ax.set_xlabel(xlabel, fontsize=11)
        ax.set_ylabel(ylabel, fontsize=11)
        ax.set_title(title, fontsize=12, fontweight="bold")
        ax.tick_params(labelsize=9)
        ax.spines[["top", "right"]].set_visible(False)
        plt.tight_layout()
        _save(fig, filename)

    # -------------------------------------------------------------------------
    # 1. Accessibility score distribution
    # -------------------------------------------------------------------------
    valid_acc = combined["accessibility_score"].dropna()
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.hist(valid_acc, bins=20, color="#4A90D9", edgecolor="white", linewidth=0.5, alpha=0.85)
    ax.axvline(valid_acc.mean(), color="#CC0000", linewidth=1.5, linestyle="--",
               label=f"Mean: {valid_acc.mean():.1f}")
    ax.axvline(valid_acc.median(), color="#FF8C00", linewidth=1.5, linestyle=":",
               label=f"Median: {valid_acc.median():.1f}")
    ax.set_xlabel("Accessibility score", fontsize=11)
    ax.set_ylabel("Neighbourhoods", fontsize=11)
    ax.set_title("Accessibility Score Distribution", fontsize=12, fontweight="bold")
    ax.legend(fontsize=9, framealpha=0.7)
    ax.tick_params(labelsize=9)
    ax.spines[["top", "right"]].set_visible(False)
    plt.tight_layout()
    _save(fig, "acc_distribution.png")

    # -------------------------------------------------------------------------
    # 2. t_walk vs accessibility
    # -------------------------------------------------------------------------
    if has_t_walk and "t_walk_min" in combined.columns:
        _scatter_fig("t_walk_min", "accessibility_score",
                     "Walking time to stop (min)", "Accessibility score",
                     "#27AE60", "t_walk vs Accessibility", "twalk_vs_acc.png")

    # -------------------------------------------------------------------------
    # 3. Population density vs accessibility
    # -------------------------------------------------------------------------
    _scatter_fig("pop_density", "accessibility_score",
                 "Population density (per km²)", "Accessibility score",
                 "#8E44AD", "Population Density vs Accessibility", "popdensity_vs_acc.png")

    # -------------------------------------------------------------------------
    # 4. Distance to city centre vs accessibility
    # -------------------------------------------------------------------------
    _scatter_fig("dist_to_centre_km", "accessibility_score",
                 "Distance to city centre (km)", "Accessibility score",
                 "#2980B9", "Distance to City Centre vs Accessibility", "dist_vs_acc.png")

    # -------------------------------------------------------------------------
    # 5. Accessibility vs benefit
    # -------------------------------------------------------------------------
    _scatter_fig("accessibility_score", "benefit_score",
                 "Accessibility score", "Benefit score",
                 "#E74C3C", "Accessibility vs Benefit Score", "acc_vs_benefit.png")

    # -------------------------------------------------------------------------
    # 6. Rush vs off-hours
    # -------------------------------------------------------------------------
    if has_temporal and "score_rush" in combined.columns and "score_off" in combined.columns:
        mask = combined["score_rush"].notna() & combined["score_off"].notna()
        x = combined.loc[mask, "score_off"].values
        y = combined.loc[mask, "score_rush"].values
        fig, ax = plt.subplots(figsize=(6, 6))
        ax.scatter(x, y, s=18, alpha=0.55, color="#F39C12", edgecolors="none")
        if len(x) > 2:
            slope, intercept, r, p, _ = stats.linregress(x, y)
            x_line = np.linspace(x.min(), x.max(), 200)
            ax.plot(x_line, slope * x_line + intercept,
                    color="#333333", linewidth=1.2, linestyle="--")
            sig = "**" if p < 0.01 else ("*" if p < 0.05 else "")
            ax.text(0.05, 0.93, f"r = {r:.2f}{sig}",
                    transform=ax.transAxes, fontsize=10, color="#333333", va="top")
        lo = min(ax.get_xlim()[0], ax.get_ylim()[0])
        hi = max(ax.get_xlim()[1], ax.get_ylim()[1])
        ax.plot([lo, hi], [lo, hi], color="#AAAAAA", linewidth=1, linestyle="-", zorder=0)
        ax.set_xlim(lo, hi)
        ax.set_ylim(lo, hi)
        ax.set_xlabel("Off-hours accessibility", fontsize=11)
        ax.set_ylabel("Rush-hour accessibility", fontsize=11)
        ax.set_title("Off-Hours vs Rush-Hour Accessibility", fontsize=12, fontweight="bold")
        ax.tick_params(labelsize=9)
        ax.spines[["top", "right"]].set_visible(False)
        plt.tight_layout()
        _save(fig, "rush_vs_offhours.png")

    # -------------------------------------------------------------------------
    # 7. Metric correlation matrix heatmap
    # -------------------------------------------------------------------------
    corr_labels = {}
    if has_t_walk and "t_walk_min" in combined.columns:
        corr_labels["t_walk (min)"] = "t_walk_min"
    corr_labels["Accessibility"] = "accessibility_score"
    corr_labels["Benefit"] = "benefit_score"
    corr_labels["Pop. density"] = "pop_density"
    corr_labels["Dist. to centre"] = "dist_to_centre_km"
    if has_temporal and "score_rush" in combined.columns:
        corr_labels["Rush-hour"] = "score_rush"
        corr_labels["Off-hours"] = "score_off"

    available = {k: v for k, v in corr_labels.items() if v in combined.columns}
    corr_df = combined[[v for v in available.values()]].rename(
        columns={v: k for k, v in available.items()}
    )
    corr_matrix = corr_df.corr()
    labels = corr_matrix.columns.tolist()
    n = len(labels)

    fig, ax = plt.subplots(figsize=(max(5, n * 0.9 + 1), max(4, n * 0.9)))
    im = ax.imshow(corr_matrix.values, cmap="RdBu_r", vmin=-1, vmax=1, aspect="auto")
    plt.colorbar(im, ax=ax, shrink=0.85, label="Pearson r")
    ax.set_xticks(range(n))
    ax.set_yticks(range(n))
    ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=9)
    ax.set_yticklabels(labels, fontsize=9)
    for i in range(n):
        for j in range(n):
            val = corr_matrix.values[i, j]
            txt_color = "white" if abs(val) > 0.6 else "black"
            ax.text(j, i, f"{val:.2f}", ha="center", va="center",
                    fontsize=8.5, color=txt_color)
    ax.set_title("Metric Correlation Matrix", fontsize=12, fontweight="bold")
    plt.tight_layout()
    _save(fig, "correlation_matrix.png")


def plot_equity_correlations(
    database,
    gdf_acc,
    storage_folder="debug",
    name="equity_correlations",
    show=False,
):
    """
    Generate scatter plots of CBS socio-economic indicators vs accessibility score.

    Panels: poverty risk, elderly share, low-income share, non-EU background.
    Each panel has a regression line and annotated Pearson r (* p<0.05, ** p<0.01).
    Saves individual .png files and a merged CSV to {storage_folder}/{name}/.

    Returns:
        DataFrame with merged accessibility + CBS indicator data.
    """
    import os
    import matplotlib.pyplot as plt
    from scipy import stats

    out_dir = os.path.join(storage_folder, name)
    os.makedirs(out_dir, exist_ok=True)

    # -------------------------------------------------------------------------
    # Fetch CBS indicators and compute fractions
    # -------------------------------------------------------------------------
    cbs_df = database.conn.sql("""
        SELECT
            id AS neighborhood_id,
            pop,
            CAST(risk_poverty   AS DOUBLE) AS risk_poverty,
            CAST(low_income     AS DOUBLE) AS low_income,
            CAST(age_65_oo      AS DOUBLE) AS age_65_oo,
            CAST(background_neu AS DOUBLE) AS background_neu
        FROM CBS
        WHERE pop IS NOT NULL AND pop > 0
    """).df()

    cbs_df["pct_elderly"] = cbs_df["age_65_oo"]     / cbs_df["pop"] * 100
    cbs_df["pct_neu"]     = cbs_df["background_neu"] / cbs_df["pop"] * 100

    # -------------------------------------------------------------------------
    # Merge with accessibility score
    # -------------------------------------------------------------------------
    def _id_col(df):
        return "neighborhood_id" if "neighborhood_id" in df.columns else "id"

    acc_slim = gdf_acc[[_id_col(gdf_acc), "accessibility_score"]].copy().rename(
        columns={_id_col(gdf_acc): "neighborhood_id"}
    )
    acc_slim = acc_slim[acc_slim["accessibility_score"].notna()]

    combined = acc_slim.merge(
        cbs_df[["neighborhood_id", "risk_poverty", "low_income", "pct_elderly", "pct_neu"]],
        on="neighborhood_id",
        how="inner",
    )

    # -------------------------------------------------------------------------
    # Save merged data as CSV
    # -------------------------------------------------------------------------
    combined.to_csv(os.path.join(out_dir, f"{name}.csv"), index=False)

    # -------------------------------------------------------------------------
    # Individual scatter panels
    # -------------------------------------------------------------------------
    panels = [
        ("risk_poverty", "Poverty risk (%)",
         "Poverty Risk vs Transit Accessibility", "#E74C3C", "poverty_risk.png"),
        ("pct_elderly",  "Elderly residents (% aged 65+)",
         "Elderly Population vs Transit Accessibility", "#8E44AD", "elderly.png"),
        ("low_income",   "Low-income households (%)",
         "Low Income vs Transit Accessibility", "#E67E22", "low_income.png"),
        ("pct_neu",      "Non-EU migration background (% of residents)",
         "Non-EU Background vs Transit Accessibility", "#2980B9", "non_eu_background.png"),
    ]

    for x_col, xlabel, title, color, filename in panels:
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

        ax.set_xlabel(xlabel, fontsize=11)
        ax.set_ylabel("Accessibility score", fontsize=11)
        ax.set_title(title, fontsize=12, fontweight="bold")
        ax.tick_params(labelsize=9)
        ax.spines[["top", "right"]].set_visible(False)
        plt.tight_layout()
        fig.savefig(os.path.join(out_dir, filename), dpi=300, bbox_inches="tight")
        if show:
            plt.show()
        plt.close(fig)

    return combined

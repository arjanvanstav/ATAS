"""
_classes.py — The two central data structures: Network and Database.

Network: holds driving and pedestrian street graphs for a city, plus the R5 transit network.
         Graphs can be cached to .graphml files to avoid re-downloading from OSM.

Database: in-memory DuckDB holding CBS neighborhood stats, street graph, transit stops,
          sample points, and computed distances. Must be set up in order:
            1. Database(csv, geopackage)
            2. database.set_city(city)
            3. database.load_network(network)
            4. database.obtain_features()
            5. database.pre_process()
"""

import duckdb as db
import osmnx as ox
import networkx as nx
import os
import pandas as pd
import geopandas as gpd
import pyarrow as pa
from shapely import wkb


from atas.utils.util_OSMnx import get_graph, get_features, get_graph_from_polygon, get_features_from_polygon

from atas.config.settings import get_settings
settings = get_settings()


class Network:
    def __init__(self, city: str, store_in_file=False, store_dir='network_cache/') -> None:
        """
        Download driving and pedestrian street graphs for the city.
        If store_in_file=True, saves them to .graphml files and reuses them on future runs.
        """
        self.store_in_file = store_in_file
        self.path = f"{store_dir}{city}"
        self.city = city
        self.r5_network = None
        self.osm_pbf_path = None
        self.gtfs_files = None
        self._polygon_4326 = None  # set by from_database() to enable polygon-based feature fetching

        if os.path.isfile(f"{self.path}_drive.graphml"):
            self.graph_drive = ox.io.load_graphml(f"{self.path}_drive.graphml")
        else:
            self.graph_drive = get_graph(city)
            if store_in_file:
                ox.io.save_graphml(self.graph_drive, f"{self.path}_drive.graphml")

        if os.path.isfile(f"{self.path}_ped.graphml"):
            self.graph_pedestrian = ox.io.load_graphml(f"{self.path}_ped.graphml")
        else:
            self.graph_pedestrian = get_graph(city, network_type="walk")
            self.graph_pedestrian.add_nodes_from(self.graph_drive.nodes(data=True))
            if store_in_file:
                ox.io.save_graphml(self.graph_pedestrian, f"{self.path}_ped.graphml")

    def get_drive_network_df(self):
        """Return (nodes, edges) GeoDataFrames for the driving network."""
        return ox.convert.graph_to_gdfs(self.graph_drive)

    def get_pedestrian_nodes_df(self):
        """Return nodes GeoDataFrame for the pedestrian network."""
        return ox.convert.graph_to_gdfs(self.graph_pedestrian, edges=False, fill_edge_geometry=False)

    def get_distances_to_transit(self, ped_transit_nodes):
        """
        Run multi-source Dijkstra from transit stops to all other pedestrian nodes.
        Returns a dict {node_id: distance_to_nearest_stop}.
        """
        G = self.graph_pedestrian.to_undirected(reciprocal=False)
        return nx.multi_source_dijkstra_path_length(G, ped_transit_nodes, weight="length")


    def get_features(self, amenity=True, public_transport=True):
        """Return OSM features as a GeoDataFrame, from cache file or API."""
        if os.path.isfile(f"{self.path}.parquet"):
            self.features = gpd.read_parquet(f"{self.path}.parquet")
        elif self._polygon_4326 is not None:
            self.features = get_features_from_polygon(self._polygon_4326, amenity, public_transport)
            if self.store_in_file:
                self.features.to_parquet(f"{self.path}.parquet")
        else:
            self.features = get_features(self.city, amenity, public_transport)
            if self.store_in_file:
                self.features.to_parquet(f"{self.path}.parquet")
        return self.features

    @classmethod
    def from_database(cls, database, store_in_file=False, store_dir='network_cache/'):
        """
        Polygon-based alternative to Network(city).

        Downloads the street graph for the exact boundary of CBS neighborhoods,
        which guarantees coverage for cities where the OSMnx place name doesn't
        match the CBS extent (e.g. Amsterdam after the 2022 merger with Weesp).
        """
        city = database.city
        polygon_28992 = database.get_neighborhood_polygon()

        # OSMnx needs WGS84 (EPSG:4326); convert from Dutch RD (EPSG:28992)
        polygon_4326 = (
            gpd.GeoDataFrame(geometry=[polygon_28992], crs="EPSG:28992")
            .to_crs("EPSG:4326")
            .geometry.iloc[0]
        )

        instance = cls.__new__(cls)
        instance.store_in_file = store_in_file
        instance.path = f"{store_dir}{city}"
        instance.city = city
        instance.r5_network = None
        instance.osm_pbf_path = None
        instance.gtfs_files = None
        instance._polygon_4326 = polygon_4326

        if os.path.isfile(f"{instance.path}_drive.graphml"):
            instance.graph_drive = ox.io.load_graphml(f"{instance.path}_drive.graphml")
        else:
            instance.graph_drive = get_graph_from_polygon(polygon_4326)
            if store_in_file:
                ox.io.save_graphml(instance.graph_drive, f"{instance.path}_drive.graphml")

        if os.path.isfile(f"{instance.path}_ped.graphml"):
            instance.graph_pedestrian = ox.io.load_graphml(f"{instance.path}_ped.graphml")
        else:
            instance.graph_pedestrian = get_graph_from_polygon(polygon_4326, network_type="walk")
            instance.graph_pedestrian.add_nodes_from(instance.graph_drive.nodes(data=True))
            if store_in_file:
                ox.io.save_graphml(instance.graph_pedestrian, f"{instance.path}_ped.graphml")

        return instance

    def transform_edges(self, ebunch):
        """
        Move edges (u, v, key) from the driving network to the pedestrian network.
        """
        edges_to_add = []
        for (u, v, k) in ebunch:
            data = self.graph_drive.get_edge_data(u, v, k)
            edges_to_add.append((u, v, data))

        self.graph_drive.remove_edges_from(ebunch)
        self.graph_pedestrian.add_edges_from(edges_to_add)

    def add_edges_to_ped_network(self, ebunch):
        """Add edges (u, v) to the pedestrian network."""
        self.graph_pedestrian.add_edges_from(ebunch)

    def build_r5_network(self, osm_pbf_path: str, gtfs_files: list):
        """Build an R5py TransportNetwork from an OSM .pbf and GTFS files."""
        if self.r5_network is not None:
            return self.r5_network

        from r5py import TransportNetwork

        self.osm_pbf_path = osm_pbf_path
        self.gtfs_files = gtfs_files

        self.r5_network = TransportNetwork(osm_pbf_path, gtfs_files)

        return self.r5_network

    def get_r5_network(self):
        if self.r5_network is None:
            raise ValueError("r5 network not initialized. Call build_r5_network() first.")
        return self.r5_network

class Database:
    def __init__(self, csv: str, geopackage: str) -> None:
        """
        Load CBS neighborhood data into an in-memory DuckDB.

        Args:
            csv: Path to the CBS KWB csv file (demographics)
            geopackage: Path to the CBS GeoPackage (neighborhood boundary polygons)
        """
        # Track how many neighborhoods are lost during point generation
        self.num_buurten = 0
        self.lost = 0

        self.conn = db.connect()

        self.conn.sql("INSTALL spatial;")
        self.conn.sql("LOAD spatial;")

        self.conn.sql("CREATE SEQUENCE seq_pts_id START 1;")

        self.conn.sql("""
            CREATE TABLE CBS (
                id VARCHAR PRIMARY KEY,
                regio VARCHAR NOT NULL,
                gm_naam VARCHAR NOT NULL,
                recs VARCHAR NOT NULL,
                pop UBIGINT NOT NULL,
                male UBIGINT,
                female UBIGINT,
                age_00_14 UBIGINT,
                age_15_24 UBIGINT,
                age_25_44 UBIGINT,
                age_45_64 UBIGINT,
                age_65_oo UBIGINT,
                background_nl UBIGINT,
                background_eu UBIGINT,
                background_neu UBIGINT,
                birthplace_nl UBIGINT,
                birthplace_eu UBIGINT,
                birthplace_neu UBIGINT,
                low_education UBIGINT,
                medium_education UBIGINT,
                high_education UBIGINT,
                low_income FLOAT,
                high_income FLOAT,
                risk_poverty FLOAT,
                jobs UBIGINT,
                geom GEOMETRY
            );
            CREATE TABLE Neighborhoods (
                id VARCHAR PRIMARY KEY,
                regio VARCHAR,
                population UBIGINT,
                amenities UBIGINT,
                area UBIGINT,
                num_male UBIGINT,
                num_female UBIGINT,
                num_age_00_14 UBIGINT,
                num_age_15_24 UBIGINT,
                num_age_25_44 UBIGINT,
                num_age_45_64 UBIGINT,
                num_age_65_oo UBIGINT,
                num_background_nl UBIGINT,
                num_background_eu UBIGINT,
                num_background_neu UBIGINT,
                num_birthplace_nl UBIGINT,
                num_birthplace_eu UBIGINT,
                num_birthplace_neu UBIGINT,
                num_low_education UBIGINT,
                num_medium_education UBIGINT,
                num_high_education UBIGINT,
                percent_low_income FLOAT,
                percent_high_income FLOAT,
                percent_risk_poverty FLOAT,
                jobs UBIGINT,
                geometry GEOMETRY
            );
            CREATE TABLE Graph_nodes (
                id UBIGINT PRIMARY KEY,
                street_count INTEGER,
                loc GEOMETRY,
                neighborhood_id VARCHAR
            );
            CREATE TABLE Graph_edges (
                u UBIGINT,
                v UBIGINT,
                key INTEGER,
                length FLOAT NOT NULL,
                oneway BOOLEAN NOT NULL,
                removed BOOLEAN NOT NULL,
                geometry GEOMETRY NOT NULL,
                neighborhood_id VARCHAR,
                PRIMARY KEY (u, v, key)
            );
            CREATE TABLE Neighborhood_pts (
                neighborhood_id VARCHAR,
                pts_id INTEGER DEFAULT NEXTVAL('seq_pts_id'),
                pt GEOMETRY,
                node_id UBIGINT,
                PRIMARY KEY (neighborhood_id, pts_id)
            );
            CREATE TABLE Features (
                element VARCHAR,
                id UBIGINT,
                loc GEOMETRY,
                bus VARCHAR,
                name VARCHAR,
                public_transport VARCHAR,
                amenity VARCHAR,
                railway VARCHAR,
                train VARCHAR,
                brand VARCHAR,
                wheelchair VARCHAR,
                highway VARCHAR,
                PRIMARY KEY (element, id)
            );
        """)

        column_names = settings.dataset_column_names

        # Join CBS csv and GeoPackage (only buurtcode + geom from the geopackage)
        self.conn.sql(f"""
            INSERT INTO CBS
            SELECT
                c.{column_names["id"]},
                c.{column_names["regio"]},
                c.{column_names["gm_naam"]},
                c.{column_names["recs"]},
                c.{column_names["pop"]},
                c.{column_names["male"]},
                c.{column_names["female"]},
                c.{column_names["age_00_14"]},
                c.{column_names["age_15_24"]},
                c.{column_names["age_25_44"]},
                c.{column_names["age_45_64"]},
                c.{column_names["age_65_oo"]},
                c.{column_names["background_nl"]},
                c.{column_names["background_eu"]},
                c.{column_names["background_neu"]},
                c.{column_names["birthplace_nl"]},
                c.{column_names["birthplace_eu"]},
                c.{column_names["birthplace_neu"]},
                c.{column_names["low_education"]},
                c.{column_names["medium_education"]},
                c.{column_names["high_education"]},
                c.{column_names["low_income"]},
                c.{column_names["high_income"]},
                c.{column_names["risk_poverty"]},
                c.{column_names["jobs"]},
                g.{column_names["geom"]}
            FROM read_csv('{csv}', nullstr={str(settings.dataset_nullstring)}, delim='{settings.dataset_delim}', decimal_separator='{settings.dataset_decimal_separator}') c
            JOIN (SELECT {column_names["buurtcode"]}, geom FROM ST_Read('{geopackage}')) g
            ON c.gwb_code = g.{column_names["buurtcode"]}
            """)

    def to_csv(self, limit=10):
        """Export all database tables to CSV files (for debugging)."""
        try:
            self.conn.sql(f"SELECT * FROM CBS LIMIT {limit}").to_csv("CBS_database_preview.csv")
        except Exception:
            pass
        try:
            self.conn.sql(f"SELECT * FROM Neighborhoods LIMIT {limit}").to_csv("Neighborhoods_database_preview.csv")
        except Exception:
            pass
        try:
            self.conn.sql(f"SELECT * FROM Graph_nodes LIMIT {limit}").to_csv("Graph_nodes_database_preview.csv")
        except Exception:
            pass
        try:
            self.conn.sql(f"SELECT * FROM Graph_edges LIMIT {limit}").to_csv("Graph_edges_database_preview.csv")
        except Exception:
            pass
        try:
            self.conn.sql(f"SELECT * FROM Neighborhood_pts LIMIT {limit}").to_csv("Neighborhood_pts_database_preview.csv")
        except Exception:
            pass
        try:
            self.conn.sql(f"SELECT * FROM Features LIMIT {limit}").to_csv("Features_database_preview.csv")
        except Exception:
            pass
        try:
            self.conn.sql(f"SELECT * FROM Bus_stations LIMIT {limit}").to_csv("Bus_stations_database_preview.csv")
        except Exception:
            pass
        try:
            self.conn.sql(f"SELECT * FROM Bus_stations_to_move LIMIT {limit}").to_csv("Bus_stations_to_move_database_preview.csv")
        except Exception:
            pass
        try:
            self.conn.sql(f"SELECT * FROM Graph_nodes_accessible LIMIT {limit}").to_csv("Graph_nodes_accessible_database_preview.csv")
        except Exception:
            pass
        try:
            self.conn.sql(f"SELECT * FROM Graph_nodes_ped LIMIT {limit}").to_csv("Graph_nodes_ped_database_preview.csv")
        except Exception:
            pass
        try:
            self.conn.sql(f"SELECT * FROM Distances LIMIT {limit}").to_csv("Distances_database_preview.csv")
        except Exception:
            pass
        try:
            self.conn.sql(f"SELECT * FROM Dist_per_neighborhood LIMIT {limit}").to_csv("Dist_per_neighborhood_database_preview.csv")
        except Exception:
            pass

    def get_cities(self):
        """Return list of municipality names in the CBS dataset."""
        query = """
            SELECT DISTINCT gm_naam
            FROM CBS
            """
        res = self.conn.sql(query).fetchnumpy()
        return res["gm_naam"].tolist()

    def set_city(self, city: str):
        """Set the city for subsequent pipeline steps."""
        self.city = city

    def get_neighborhood_polygon(self):
        """Return the merged boundary polygon of all neighborhoods for the current city (EPSG:28992)."""
        result = self.conn.sql(f"""
            SELECT ST_AsWKB(ST_Union_Agg(geom)) AS union_geom
            FROM CBS
            WHERE recs='Buurt' AND gm_naam='{self.city}'
        """).fetchone()[0]
        return wkb.loads(bytes(result))

    def load_network(self, network: Network):
        """Load a Network object into the database, populating Graph_nodes and Graph_edges."""
        self.network = network

        self.conn.sql("DELETE FROM Graph_nodes")
        self.conn.sql("DELETE FROM Graph_edges")

        nodes_df, edges_df = self.network.get_drive_network_df()

        # Convert geometry to WKT strings so DuckDB can import them
        nodes_df_reg = nodes_df.reset_index()
        nodes_df_reg["geometry"] = nodes_df_reg["geometry"].astype(str) # pyright: ignore[reportArgumentType]
        self.conn.register("nodes", nodes_df_reg)
        edges_df = edges_df.reset_index()
        edges_df["geometry"] = edges_df["geometry"].astype(str) # pyright: ignore[reportArgumentType]
        self.conn.register("edges", edges_df)

        # Load nodes and assign each one to its CBS neighborhood
        self.conn.sql(f"""
                INSERT INTO Graph_nodes (id, street_count, loc, neighborhood_id)
                SELECT n.osmid, n.street_count, ST_GeomFromText(n.geometry), c.id
                FROM nodes n
                JOIN CBS c
                ON ST_Within(ST_GeomFromText(n.geometry), c.geom)
                WHERE recs='Buurt' AND gm_naam='{self.city}'
            """)
        # Load edges; assign each to the neighborhood containing its midpoint
        self.conn.sql(f"""
                INSERT INTO Graph_edges (u, v, key, length, oneway, removed, geometry, neighborhood_id)
                SELECT u, v, key, length, oneway, false, ST_GeomFromText(geometry), c.id
                FROM edges e
                JOIN Graph_nodes n1
                ON e.u = n1.id
                JOIN Graph_nodes n2
                ON e.v = n2.id
                JOIN CBS c
                ON ST_Within(ST_Point((ST_X(n1.loc) + ST_X(n2.loc)) / 2,
                                      (ST_Y(n1.loc) + ST_Y(n2.loc)) / 2
                             ), c.geom)
                WHERE recs='Buurt' AND gm_naam='{self.city}'
            """)
        ped_nodes_df = self.network.get_pedestrian_nodes_df()
        ped_nodes_df_reg = ped_nodes_df.reset_index()
        ped_nodes_df_reg["geometry"] = ped_nodes_df_reg["geometry"].astype(str) # pyright: ignore[reportArgumentType]
        self.conn.register("ped_nodes", ped_nodes_df_reg)

        # Store pedestrian network nodes
        self.conn.sql("""
            CREATE TABLE IF NOT EXISTS Graph_nodes_ped AS
            SELECT osmid, street_count, ST_GeomFromText(geometry) AS geometry
            FROM ped_nodes
        """)

        # Drive nodes that are close enough to a pedestrian node to be walked to
        self.conn.sql(f"""
            CREATE OR REPLACE TABLE Graph_nodes_accessible AS
            SELECT n.*, p.osmid AS pedestrian_node_id
            FROM Graph_nodes n
            JOIN Graph_nodes_ped p
            ON ST_DWithin(p.geometry, n.loc, {settings.max_dist_ped_transit})
        """)

        # Link the two networks by adding edges between nearby nodes
        df = self.conn.sql("""
            SELECT id, pedestrian_node_id
            FROM Graph_nodes_accessible
        """).df()
        ebunch = df.itertuples(index=False, name=None)
        self.network.add_edges_to_ped_network(ebunch)

    def obtain_features(self, amenity=True, public_transport=True):
        """Fetch OSM amenity and/or public transport features and populate the Features table."""
        self.conn.sql("DELETE FROM Features")
        if not (amenity and public_transport):
            return

        features_gdf = self.network.get_features(amenity, public_transport)

        features_df = features_gdf.reset_index()
        features_df["geometry"] = features_df["geometry"].astype(str) # pyright: ignore[reportArgumentType]
        self.conn.register("features_arrow", features_df)

        self.conn.sql("""
                INSERT INTO Features
                SELECT
                    element,
                    id,
                    ST_GeomFromText(geometry),
                    bus,
                    name,
                    public_transport,
                    amenity,
                    railway,
                    train,
                    brand,
                    wheelchair,
                    highway
                FROM features_arrow
            """)

    def pre_process(self):
        """Populate the Neighborhoods table from CBS data and compute amenity counts."""
        self.conn.sql("DELETE FROM Neighborhoods")

        self.conn.sql(f"""
                INSERT INTO Neighborhoods
                SELECT
                    c.id,
                    c.regio,
                    c.pop,
                    coalesce(a.count, 0),
                    area,
                    c.male,
                    c.female,
                    c.age_00_14,
                    c.age_15_24,
                    c.age_25_44,
                    c.age_45_64,
                    c.age_65_oo,
                    c.background_nl,
                    c.background_eu,
                    c.background_neu,
                    c.birthplace_nl,
                    c.birthplace_eu,
                    c.birthplace_neu,
                    c.low_education,
                    c.medium_education,
                    c.high_education,
                    c.low_income,
                    c.high_income,
                    c.risk_poverty,
                    c.jobs,
                    c.geom
                FROM (SELECT *, ST_Area(geom) as area
                      FROM CBS
                      WHERE gm_naam='{self.city}' AND recs='Buurt') c
                LEFT JOIN (SELECT c2.id, count(*) as count
                           FROM features f
                           JOIN CBS c2
                           ON ST_Within(f.loc, c2.geom)
                           WHERE gm_naam='{self.city}' AND recs='Buurt' AND public_transport IS NULL
                           GROUP BY c2.id ) a
                ON c.id = a.id
            """)

    def create_pts_per_neighborhood(self):
        """Sample representative points per neighborhood using Poisson disk sampling and link them to the pedestrian network."""
        # Get bounding box of each neighborhood
        df = self.conn.sql("""
            SELECT id, ST_XMin(geometry) as lower_x, ST_XMax(geometry) as upper_x,
                      ST_YMin(geometry) as lower_y, ST_YMax(geometry) as upper_y
            FROM Neighborhoods
            """).df()

        ids = []
        xs = []
        ys = []
        for row in df.itertuples():
            pts = settings.neighborhood_distribution(row.lower_x, # type: ignore
                                                     row.upper_x, # type: ignore
                                                     row.lower_y, # type: ignore
                                                     row.upper_y) # type: ignore
            if pts.size == 0:
                continue
            ids.extend([row.id] * (int)(pts.size/2))
            xs.extend(pts[:, 0])
            ys.extend(pts[:, 1])

        Neighborhood_pts_df = pd.DataFrame({
            "ids":ids,
            "xs":xs,
            "ys":ys
        })

        # Insert points: filter to those inside the neighborhood and near a pedestrian node
        self.conn.sql(f"""
            INSERT INTO Neighborhood_pts (neighborhood_id, pt, node_id)
            SELECT pt.ids, ST_Point(pt.xs, pt.ys), ped.osmid
            FROM Neighborhood_pts_df pt
            JOIN Neighborhoods n
            ON pt.ids = n.id AND ST_Within(ST_Point(pt.xs, pt.ys), n.geometry)
            JOIN Graph_nodes_ped ped
            ON ST_DWithin(ST_Point(pt.xs, pt.ys), ped.geometry, {settings.transit_max_pts_dist})
            QUALIFY row_number()
            OVER (PARTITION BY ped.osmid
                  ORDER BY ST_Distance(ST_Point(pt.xs, pt.ys), ped.geometry) ASC) = 1
            """)

        # Count how many neighborhoods ended up with no points
        self.num_buurten = self.conn.sql("SELECT count(id) FROM Neighborhoods").fetchone()[0] # type: ignore
        self.lost = self.num_buurten - self.conn.sql("SELECT count(neighborhood_id) FROM (SELECT DISTINCT neighborhood_id FROM Neighborhood_pts)").fetchone()[0] # type: ignore

    def create_pts_per_neighborhood_reachable(self, max_pts_dist: int = None, max_iterations: int = 10):
        """
        Like create_pts_per_neighborhood, but only assigns points to nodes that are
        reachable from a transit stop (so avg_dist is never incorrectly zero).

        Retries missing neighborhoods up to max_iterations times.

        Args:
            max_pts_dist: Max distance (meters) between a point and a reachable node.
            max_iterations: Max retry attempts; stops early when all neighborhoods are covered.
        """
        if max_pts_dist is None:
            max_pts_dist = settings.transit_max_pts_dist

        # Clear any existing points before repopulating
        self.conn.sql("DELETE FROM Neighborhood_pts")

        # Obtain bounding boxes for all neighborhoods
        all_neighborhoods_df = self.conn.sql("""
            SELECT id, ST_XMin(geometry) as lower_x, ST_XMax(geometry) as upper_x,
                      ST_YMin(geometry) as lower_y, ST_YMax(geometry) as upper_y
            FROM Neighborhoods
            """).df()

        # Track which neighborhoods still need a point
        missing_ids = set(all_neighborhoods_df["id"].tolist())

        for iteration in range(max_iterations):

            # Stop early if all neighborhoods are covered
            if not missing_ids:
                break

            # Only sample neighborhoods that are still missing
            df = all_neighborhoods_df[all_neighborhoods_df["id"].isin(missing_ids)]

            # Generate points for each missing neighborhood
            ids = []
            xs  = []
            ys  = []
            for row in df.itertuples():
                pts = settings.neighborhood_distribution(row.lower_x, # type: ignore
                                                         row.upper_x, # type: ignore
                                                         row.lower_y, # type: ignore
                                                         row.upper_y) # type: ignore
                if pts.size == 0:
                    continue
                ids.extend([row.id] * (int)(pts.size / 2))
                xs.extend(pts[:, 0])
                ys.extend(pts[:, 1])

            if not ids:
                break

            Neighborhood_pts_df = pd.DataFrame({
                "ids": ids,
                "xs":  xs,
                "ys":  ys
            })

            # Link each point to its nearest reachable pedestrian node.
            # d.dist > 0 excludes transit stop nodes themselves (Dijkstra sources
            # have dist=0), so representative points always have a positive walking
            # distance and avg_dist never collapses to 0 due to sampling artifacts.
            self.conn.sql(f"""
                INSERT INTO Neighborhood_pts (neighborhood_id, pt, node_id)
                SELECT pt.ids, ST_Point(pt.xs, pt.ys), ped.osmid
                FROM Neighborhood_pts_df pt
                JOIN Neighborhoods n
                ON pt.ids = n.id AND ST_Within(ST_Point(pt.xs, pt.ys), n.geometry)
                JOIN Graph_nodes_ped ped
                ON ST_DWithin(ST_Point(pt.xs, pt.ys), ped.geometry, {max_pts_dist})
                JOIN Distances d
                ON ped.osmid = d.node_id AND d.dist > 0
                QUALIFY row_number()
                OVER (PARTITION BY pt.ids
                      ORDER BY ST_Distance(ST_Point(pt.xs, pt.ys), ped.geometry) ASC) = 1
                """)

            # Update the set of neighborhoods still missing after this iteration
            covered = set(self.conn.sql("""
                SELECT DISTINCT neighborhood_id FROM Neighborhood_pts
            """).df()["neighborhood_id"].tolist())

            missing_ids = missing_ids - covered

        # Keeping track of neighborhoods lost during point generation
        # Total neighborhoods.
        self.num_buurten = self.conn.sql("SELECT count(id) FROM Neighborhoods").fetchone()[0] # type: ignore
        # Total lost
        self.lost = self.num_buurten - self.conn.sql("SELECT count(neighborhood_id) FROM (SELECT DISTINCT neighborhood_id FROM Neighborhood_pts)").fetchone()[0] # type: ignore

    def obtain_generated_pts(self):
        """Return (xs, ys) numpy arrays of all generated neighborhood sample point coordinates."""
        arrow = self.conn.sql(""" SELECT ST_X(pt) AS x, ST_Y(pt) AS y FROM Neighborhood_pts """).to_arrow_table()
        return (arrow.column("x").to_numpy(), arrow.column("y").to_numpy())

    def remove_f_edges(self, fraction: float, use_population=True, use_amenity=False):
        """
        Remove driving edges to simulate street conversions.

        Edges are sorted by density (population or amenity per meter) and removed
        until the given fraction of total street length is reached.
        Successive calls build on previous removals.

        Args:
            fraction: Fraction of total street length to remove.
            use_population: Sort by population density.
            use_amenity: Sort by amenity density.
        """
        one_way_worth = settings.one_way_worth
        if not (use_population ^ use_amenity):
            raise ValueError("use_population and use_amenity can't be both true or both false")
        elif use_population:
            density = "n.population / n.area"
        else:
            density = "n.amenities / n.area"

        tot_len = "(SELECT sum(length) from Graph_edges)"
        self.conn.sql(f"""
            CREATE OR REPLACE TEMP TABLE edges_to_remove AS
            SELECT *
            FROM (
                SELECT e.*
                FROM Graph_edges e
                JOIN Neighborhoods n
                ON e.neighborhood_id = n.id
                QUALIFY sum(e.length)
                    OVER (ORDER BY (CASE WHEN e.oneway
                                        THEN ({density} * {one_way_worth})
                                        ELSE ({density}) END ) DESC )
                    <=  ({fraction} * {tot_len}) ) sub
            WHERE sub.removed = 'false'
        """)

        to_remove_df = self.conn.sql("SELECT u, v, key FROM edges_to_remove").df()
        ebunch = list(to_remove_df.itertuples(index=False, name=None))
        self.network.transform_edges(ebunch)

        self.conn.sql("""
            UPDATE Graph_edges
            SET removed = 'true'
            FROM edges_to_remove
            WHERE Graph_edges.u = edges_to_remove.u
                      AND Graph_edges.u = edges_to_remove.u
                      AND Graph_edges.key = edges_to_remove.key
        """)

        # Recalculate street_count after removals
        self.conn.sql("""
            UPDATE Graph_nodes SET street_count = 0;

            UPDATE Graph_nodes
            SET street_count = sub.degree
            FROM (SELECT node_id, count(*) AS degree
                  FROM (
                      SELECT u AS node_id FROM Graph_edges WHERE removed='false'
                      UNION ALL
                      SELECT v AS node_id FROM Graph_edges WHERE removed='false' AND oneway='true'
                      )
                  GROUP BY node_id
                 ) sub
            WHERE id = sub.node_id
        """)

    def link_busses(self):
        """Link bus stations to the nearest driving network node, creating the Bus_stations table."""
        self.conn.sql(f"""
            CREATE TABLE IF NOT EXISTS Bus_stations AS
            SELECT f.id AS feature_id, n.id AS node_id, f.loc
            FROM (SELECT * FROM Features WHERE bus IS NOT NULL) f
            JOIN Graph_nodes n
            ON ST_DWithin(f.loc, n.loc, {settings.transit_max_edge_dist})
            QUALIFY row_number() OVER (PARTITION BY f.element, f.id ORDER BY ST_Distance(f.loc, n.loc) ASC) = 1
        """)

    def move_transit_minimal(self):
        """
        Move transit stops that are on dead-end nodes (degree < 2) to the nearest
        accessible node with at least 2 connections.
        """

        self.conn.sql(f"""
            CREATE OR REPLACE TABLE Bus_stations_to_move AS
            SELECT isolated_busses.feature_id AS feature_id,
                   isolated_busses.node_id AS old_node, node_candidates.id AS new_node,
                   isolated_busses.loc AS old_loc, node_candidates.loc AS new_loc
            FROM (SELECT b.node_id, b.feature_id, b.loc
                  FROM Bus_stations b
                  JOIN Graph_nodes n
                  ON b.node_id = n.id
                  WHERE street_count < 2
                 ) isolated_busses
            JOIN (SELECT DISTINCT id, loc
                  FROM Graph_nodes_accessible
                  WHERE street_count >= 2
                 ) node_candidates
            ON ST_DWithin(isolated_busses.loc, node_candidates.loc, {settings.transit_max_move_dist})
            QUALIFY row_number() OVER (PARTITION BY isolated_busses.feature_id
                                       ORDER BY ST_Distance(isolated_busses.loc, node_candidates.loc) ASC) = 1
        """)

        self.conn.sql("""
            UPDATE Bus_stations
            SET node_id = b.new_node
            FROM Bus_stations_to_move b
            WHERE Bus_stations.feature_id = b.feature_id
            """)

    def calculate_distances_to_nearest_transit(self):
        """Compute shortest walking distance from every pedestrian network node to its nearest transit stop."""
        # Transit stops are the Dijkstra sources
        ped_transit_np = self.conn.sql("""
            SELECT n.pedestrian_node_id
            FROM Graph_nodes_accessible n
            JOIN Bus_stations b
            ON n.id = b.node_id
        """).fetchnumpy()
        ped_transit = ped_transit_np['pedestrian_node_id'].tolist()

        dists = self.network.get_distances_to_transit(ped_transit)

        dists_table = pa.table({
            "node_id": list(dists.keys()),
            "dist": list(dists.values())
        })
        self.conn.register("dists_table", dists_table)
        self.conn.sql("""
            CREATE OR REPLACE TABLE Distances AS
            SELECT *
            FROM dists_table
        """)

    def get_dist_per_neighborhood(self):
        """
        Average walking distances across sample points per neighborhood.

        Returns:
            GeoDataFrame with columns: neighborhood, wkb, neighborhood_id, avg_dist, geometry
        """

        self.conn.sql("""
            CREATE OR REPLACE TABLE Dist_per_neighborhood AS
            SELECT pt.neighborhood_id, avg(d.dist) AS avg_dist
            FROM Neighborhood_pts pt
            LEFT JOIN Distances d
            ON pt.node_id = d.node_id
            GROUP BY pt.neighborhood_id
        """)
        
        df = self.conn.sql("""
            SELECT n.regio AS neighborhood, ST_AsWKB(n.geometry) AS wkb, d.*
            FROM Dist_per_neighborhood d
            JOIN Neighborhoods n
            ON n.id = d.neighborhood_id
            ORDER BY d.avg_dist DESC
            """).df()
        df['geometry'] = df['wkb'].apply(lambda x: wkb.loads(bytes(x))) # type: ignore
        return gpd.GeoDataFrame(df, geometry='geometry', crs='epsg:28992')

    def get_demographic_average_distance(self):
        """
        Compute population-weighted average walking distance to transit per demographic group.

        Returns:
            DataFrame with columns dem_grp and avg_dist, one row per group (male, female,
            age bands, background, education, income, risk_poverty).
        """
        return self.conn.sql("""
            WITH
                Flattened AS (
                    SELECT id, 'avg' AS key, population AS value FROM Neighborhoods
                    UNION ALL
                    SELECT id, 'male', num_male FROM Neighborhoods
                    UNION ALL
                    SELECT id, 'female', num_female FROM Neighborhoods
                    UNION ALL
                    SELECT id, '0-14', num_age_00_14 FROM Neighborhoods
                    UNION ALL
                    SELECT id, '15-24', num_age_15_24 FROM Neighborhoods
                    UNION ALL
                    SELECT id, '25-44', num_age_25_44 FROM Neighborhoods
                    UNION ALL
                    SELECT id, '45-64', num_age_45_64 FROM Neighborhoods
                    UNION ALL
                    SELECT id, '65+', num_age_65_oo FROM Neighborhoods
                    UNION ALL
                    SELECT id, 'background_nl', num_background_nl FROM Neighborhoods
                    UNION ALL
                    SELECT id, 'background_eu', num_background_eu FROM Neighborhoods
                    UNION ALL
                    SELECT id, 'background_neu', num_background_neu FROM Neighborhoods
                    UNION ALL
                    SELECT id, 'born_nl', num_birthplace_nl FROM Neighborhoods
                    UNION ALL
                    SELECT id, 'born_eu', num_birthplace_eu FROM Neighborhoods
                    UNION ALL
                    SELECT id, 'born_neu', num_birthplace_neu FROM Neighborhoods
                    UNION ALL
                    SELECT id, 'low_education', num_low_education FROM Neighborhoods
                    UNION ALL
                    SELECT id, 'mid_education', num_medium_education FROM Neighborhoods
                    UNION ALL
                    SELECT id, 'high_education', num_high_education FROM Neighborhoods
                    UNION ALL
                    SELECT id, 'low_income', percent_low_income * population FROM Neighborhoods
                    UNION ALL
                    SELECT id, 'high_income', percent_high_income * population FROM Neighborhoods
                    UNION ALL
                    SELECT id, 'risk_poverty', percent_risk_poverty * population FROM Neighborhoods
                ),
                Totals AS (
                    SELECT key, sum(value) AS total
                    FROM Flattened
                    GROUP BY key
                )
            SELECT f.key AS dem_grp, sum (f.value * d.avg_dist) / t.total AS avg_dist
            FROM Flattened f
            JOIN Totals t
            ON f.key = t.key
            LEFT JOIN Dist_per_neighborhood d
            ON f.id = d.neighborhood_id
            GROUP BY f.key, t.total
            ORDER BY f.key
        """).df()

= Data Pipeline

This document describes the data ingestion and preparation pipeline that must
be completed before any metric can be computed. Every step produces persistent
state (either in the in-memory DuckDB or in the Network object) that later
steps depend on.

== Inputs

- *CBS CSV* — demographic statistics per neighborhood (buurt), published annually by Statistics Netherlands.
- *GeoPackage* — neighborhood polygon boundaries, published alongside the CSV.
- *City name* — selects which municipality to analyse (e.g. "Amsterdam").
- *OSM data* — street network downloaded on-demand via OSMnx, or loaded from a cached `.graphml` file.

== Step 1: Database initialisation

`Database(csv, geopackage)`

- Load the spatial extension into an in-memory DuckDB instance.
- Read the CSV and GeoPackage, join them on neighborhood code, and insert every
  row into the *CBS* table.
- Create all empty tables: `Neighborhoods`, `Graph_nodes`, `Graph_edges`,
  `Graph_nodes_ped`, `Neighborhood_pts`, `Features`, `Bus_stations`,
  `Distances`, `Dist_per_neighborhood`.
- CRS at this stage: *EPSG:28992* (Dutch RD New) throughout.

== Step 2: Network initialisation

`Network(city)` or `Network.from_database(database)`

- Download (or load from cache) two OSMnx graphs for the city:
  + *Drive network* — car-accessible streets.
  + *Pedestrian network* — walkable paths (OSMnx `network_type="walk"`).
- Both graphs are projected to *EPSG:28992*.
- `from_database()` downloads the graph for the exact CBS polygon extent
  instead of relying on place-name geocoding. This is necessary for
  municipalities whose OSMnx name does not match their CBS boundary
  (e.g. Amsterdam after the 2022 merger with Weesp).
- Graphs are optionally persisted as `.graphml` files to avoid repeated
  API calls.

== Step 3: Set city

`database.set_city(city)`

- Records which municipality is active. Used as a filter in every subsequent
  SQL query against the CBS table.

== Step 4: Load network

`database.load_network(network)`

- Insert drive-network *nodes* into `Graph_nodes`, tagged with the CBS
  neighborhood they fall in (`ST_Within`).
- Insert drive-network *edges* into `Graph_edges`, tagged with the
  neighborhood of their midpoint.
- Insert pedestrian *nodes* into `Graph_nodes_ped`.
- Compute `Graph_nodes_accessible`: drive nodes that lie within
  `max_dist_ped_transit` metres of a pedestrian node. These are the nodes
  where the drive network and the pedestrian network overlap.
- Add cross-network edges to the pedestrian graph in the Network object so
  that Dijkstra can traverse from transit stops (on the drive network) onto
  the pedestrian network.

== Step 5: Obtain features

`database.obtain_features()`

- Download (or load from cache) OSMnx *features* for the city: amenities and
  public transport stops.
- Insert into the *Features* table with their geometry and type tags.
- This step is optional — skipping it results in zero amenity counts in the
  Neighborhoods table.

== Step 6: Pre-process

`database.pre_process()`

- Populate the *Neighborhoods* table by filtering CBS to the active city
  (`recs='Buurt'`) and joining in amenity counts from the Features table.
- Derived columns computed here: `area`, `amenities` (count of non-transit
  features within the neighborhood polygon).
- All downstream metric modules read from *Neighborhoods*, not from CBS
  directly.

== Step 7: Generate sample points

`database.create_pts_per_neighborhood()` or `create_pts_per_neighborhood_reachable()`

- For each neighborhood, compute its axis-aligned bounding box.
- Run *Poisson-disk sampling* (SciPy `qmc.PoissonDisk`) inside that bounding
  box with a configurable minimum spacing (default: 100 m).
- Filter sampled points to those that fall within the actual neighborhood
  polygon (`ST_Within`) and that are within `transit_max_pts_dist` metres of
  a pedestrian node.
- Snap each accepted point to its nearest pedestrian node and store the pair
  `(neighborhood_id, pt, node_id)` in *Neighborhood_pts*.
- The reachable variant additionally restricts to nodes that have a finite
  Dijkstra distance from a transit stop, ensuring that every stored point can
  contribute a non-null walking time.

== Output state

After all seven steps the following are ready for metric computation:

- `Neighborhoods` — one row per buurt with demographics and amenity counts.
- `Graph_nodes` / `Graph_edges` — drive network tagged with neighborhoods.
- `Graph_nodes_ped` — pedestrian network nodes with geometry.
- `Neighborhood_pts` — representative sample points per neighborhood, each
  snapped to a reachable pedestrian node.
- `network.graph_pedestrian` — pedestrian graph with cross-network edges added,
  ready for Dijkstra.

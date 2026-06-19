= Metric Pipeline

This document describes how the three intermediate metrics are computed and
combined into the two final scores. All steps assume the data pipeline has
been completed.

== Relevant files

```
src/
└── package_name/
    │
    ├── core/
    │   ├── _classes.py                  Database + Network class definitions.
    │   │                                Database methods used in the metric
    │   │                                pipeline: link_busses, move_transit,
    │   │                                calculate_distances_to_nearest_transit,
    │   │                                create_pts_per_neighborhood_reachable,
    │   │                                get_dist_per_neighborhood.
    │   │                                Network methods: get_r5_network,
    │   │                                build_r5_network, get_features.
    │   │
    │   ├── _t_walk.py                   compute_t_walk
    │   │                                attach_geometry_to_t_walk
    │   │
    │   ├── _t_travel.py                 compute_t_travel_matrix
    │   │                                compute_avg_travel_time_per_origin
    │   │
    │   ├── _travel_time.py              compute_travel_times_basic (R5 smoke test)
    │   │                                compute_travel_times_from_database (legacy)
    │   │
    │   ├── _attractiveness.py           compute_attractiveness
    │   │                                attach_geometry_to_attractiveness
    │   │                                plot_attractiveness_map
    │   │
    │   ├── _accessibility_model.py      run_accessibility (legacy gravity model)
    │   │                                _get_neighborhood_points (shared helper)
    │   │                                _get_neighborhood_centroids (shared helper)
    │   │                                _get_neighborhood_polygons (shared helper)
    │   │                                _get_opportunities
    │   │                                _compute_accessibility
    │   │
    │   ├── _accessibility_score.py      compute_accessibility_score
    │   │                                _get_t_walk_in_minutes
    │   │                                _get_t_travel_od_matrix
    │   │                                _apply_gravity_model
    │   │
    │   ├── _benefit.py                  compute_benefit
    │   │                                _apply_benefit_model
    │   │
    │   ├── _simulation_transit_distance.py  simulate_transit_distance_range
    │   │                                    simulate_transit_distance_single
    │   │
    │   └── main_class.py                Public API surface / header file.
    │                                    Defines which functions are exposed;
    │                                    delegates to core/ and utils/ modules.
    │
    ├── config/
    │   ├── settings.py                  Global Settings dataclass (get_settings).
    │   │                                Key fields: neighborhood_distribution,
    │   │                                transit_max_edge_dist, transit_max_pts_dist,
    │   │                                transit_max_move_dist, max_dist_ped_transit.
    │   │
    │   ├── functions.py                 Default sampling functions used by
    │   │                                Settings (Poisson-disk via scipy.qmc).
    │   │
    │   └── data_path.py                 Filesystem paths for CBS, OSM .pbf,
    │                                    and GTFS files. Reads from
    │                                    ~/.percolation_cache/ with fallback
    │                                    to ~/datasets/.
    │
    ├── utils/
    │   ├── util_plotting.py             attach_geometry_to_accessibility_score
    │   │                                attach_geometry_to_benefit
    │   │                                plot_accessibility_score_map
    │   │                                plot_benefit_map
    │   │                                plot_accessibility_diff_map
    │   │                                plot_t_walk_map
    │   │
    │   ├── util_OSMnx.py                OSMnx helpers: graph download,
    │   │                                feature extraction, network caching.
    │   │
    │   └── data_manager.py              Automatic dataset download pipeline.
    │                                    ensure_cbs, ensure_gtfs,
    │                                    ensure_city_osm (Nominatim + Geofabrik
    │                                    + osmium clip), prepare_city,
    │                                    delete_all_data, data_status.
    │
    └── gui/
        └── app.py                       PyQt6 dashboard (six tabs):
                                         Setup, Data, Parameters, Run,
                                         Results, Comparison.
                                         Workers: PipelineWorker,
                                         ComparisonWorker, DataWorker.

tests/
├── test_accessibility.py                test_t_walk_full
│                                        test_attractiveness_full
│                                        test_t_travel_matrix_small
│                                        test_accessibility_score_full
│                                        test_benefit
│                                        test_r5_basic
│                                        test_r5_from_database
│
├── test_classes.py                      Unit tests for Database + Network methods
├── test_config.py                       Unit tests for Settings and data paths
├── test_gtfs.py                         Integration test for GTFS loading
│                                        (skipped if gtfs-nl.zip absent)
├── test_gui.py                          Interactive GUI smoke test
├── test_main_class.py                   Tests for the public API surface
└── test_utils.py                        Tests for plotting and OSMnx utilities
```

== Intermediate metrics

=== t_walk — walking time to nearest transit stop

*Module:* `_t_walk.py` \
*Unit:* minutes (converted from metres at 5 km/h = 83.33 m/min)

+ `database.link_busses()` — spatially join transit stops from the Features
  table to their nearest node in the pedestrian graph. Stored in
  *Bus_stations*.
+ `database.move_transit_minimal()` — any stop that maps to an isolated
  pedestrian node (degree < 2) is moved to the nearest node with degree >= 2,
  so Dijkstra has a valid entry point.
+ `database.calculate_distances_to_nearest_transit()` — multi-source Dijkstra
  from all transit stop nodes simultaneously. Stores the shortest distance
  from any transit stop to every reachable pedestrian node in the *Distances*
  table. Transit stop nodes themselves receive `dist = 0`.
+ `database.create_pts_per_neighborhood_reachable()` — links each
  neighborhood sample point to a pedestrian node, restricting to nodes with
  `dist > 0` (excludes transit stop nodes themselves, which would give a
  spurious average of 0 m).
+ `database.get_dist_per_neighborhood()` — averages the Dijkstra distances
  over all sample points per neighborhood. Returns a DataFrame
  `(neighborhood_id, avg_dist)`.
+ Convert `avg_dist` (metres) → `t_walk_min` by dividing by 83.33.

Neighborhoods whose sample points all fall outside the reachable pedestrian
network receive no row. Downstream they are filled with the worst observed
`t_walk_min` rather than zero, to avoid falsely rewarding unreachable areas.

=== t_travel — transit travel time OD matrix

*Module:* `_t_travel.py` \
*Unit:* minutes (as reported by R5)

+ Compute one centroid per neighborhood (geographic centre of the polygon).
+ Reproject centroids from *EPSG:28992* to *EPSG:4326* (required by R5).
+ Run `r5py.TravelTimeMatrix` in batches (configurable batch size) with a
  fixed departure time and a maximum travel time (default: 120 min).
+ R5 uses the GTFS schedule and the OSM pedestrian network internally; waiting
  time at stops is therefore implicitly captured in the result.
+ Returns a DataFrame `(from_id, to_id, travel_time)` — one row per
  origin–destination pair where the destination was reachable. Unreachable
  pairs are absent (not NaN rows).

=== Attractiveness — opportunity weight per neighborhood

*Module:* `_attractiveness.py` \
*Unit:* dimensionless (weighted sum)

+ Query `population`, `jobs`, and `amenities` from the Neighborhoods table.
+ Compute a weighted sum over the configured components (default weights:
  population = 1.0, jobs = 1.0, amenities = 1.0 — equal weighting).
+ Custom weights can be passed at call time, e.g. `{"jobs": 2.0}`.
+ Returns a DataFrame `(neighborhood_id, attractiveness)`.

== Gravity model

*Used by:* `_accessibility_model.py`, `_accessibility_score.py`, `_benefit.py`

The gravity model combines t_walk and t_travel into a single accessibility
score per origin neighborhood:

$
A_i = sum_j ( "attractiveness"_j dot e^(-beta dot (t_"walk"_i + t_"travel"_(i j))) )
$

Steps:

+ Merge `t_walk_min` onto the OD matrix as an origin-side cost.
+ Compute total travel time: `t_total = t_walk_min + travel_time`.
+ Drop OD pairs where the destination was unreachable (`travel_time` is NaN).
+ Merge `attractiveness` as a destination-side weight.
+ Compute `gravity_term = attractiveness × exp(−β × t_total)` per OD pair.
+ Sum gravity terms over all destinations for each origin → `A_i`.

The parameter `β` (beta) controls distance decay: higher values penalise
longer journeys more steeply.

== Final scores

=== Accessibility score

*Output:* `(neighborhood_id, accessibility_score)` — range 0–100

+ Apply the gravity model to get raw `A_i` per neighborhood.
+ Filter to residential neighborhoods (`population >= min_population`, default 50).
+ Normalise: `accessibility_score_i = A_i / A_max × 100`.
+ The most accessible neighborhood always scores 100; all others are relative
  to it.

=== Benefit score

*Output:* `(neighborhood_id, benefit_score)` — range 0–100

The benefit score identifies neighborhoods that are both *underserved* (low
accessibility) and *densely populated* (high need). It is computed from the
same gravity model output:

+ `gap_fraction_i = (A_max − A_i) / A_max` — normalised accessibility gap.
+ `pop_fraction_i = population_i / pop_max` — normalised population.
+ `raw_i = gap_fraction_i × pop_fraction_i` — both factors on a 0–1 scale
  before multiplying, so neither dominates.
+ `benefit_score_i = raw_i / max(raw) × 100` — rescaled so the
  highest-priority neighborhood always scores 100.

Neighborhoods excluded by the population filter (harbours, industrial zones)
receive no score and are rendered with grey hatching in the map.

== Summary of data flow

```
CBS + GeoPackage
      │
      ▼
  Database ──► Network (OSMnx)
      │               │
      ▼               ▼
 pre_process     load_network
      │
      ├──► t_walk ──────────────────────┐
      │         (Dijkstra, ped. network) │
      │                                  │
      ├──► t_travel ────────────────────►  Gravity model ──► Accessibility score
      │         (R5, GTFS + OSM)         │                        │
      │                                  │                        ▼
      └──► Attractiveness ───────────────┘                   Benefit score
                (population + amenities)
```

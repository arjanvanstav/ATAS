# ATAS — Amsterdam Transit Accessibility Simulation

This package was built as part of a graduation thesis. It simulates what happens to public transit accessibility when car-accessible streets are converted to pedestrian-only. The idea is to quantify the trade-off: pedestrianisation makes walking to transit stops slower (longer routes), but it also makes walking more pleasant in general.

Accessibility is computed per neighbourhood using Dutch CBS demographic data, OpenStreetMap street networks, and real GTFS transit schedules. The core metric is a gravity model that combines walking time to the nearest transit stop, transit travel times between all neighbourhood pairs, and a measure of how attractive each destination neighbourhood is.

---

## Requirements

### Java 17 or 21
r5py (the transit router) needs Java. Java 26+ causes crashes on Apple Silicon so stick to an LTS version.

**macOS:**
```bash
brew install --cask temurin@21
```
**Ubuntu/Debian:**
```bash
sudo apt install temurin-21-jdk
```
Check it works: `java -version`

### osmium-tool
Only needed if you want to use the automatic data download. It clips a city-level OSM file from a province extract.

**macOS:**
```bash
brew install osmium-tool
```
**Ubuntu/Debian:**
```bash
sudo apt install osmium-tool
```

---

## Installation

Python 3.10 is required (r5py constraint).

```bash
python3.10 -m venv venv
source venv/bin/activate

pip install -e .
pip install r5py
```

---

## Getting the data

You can download everything automatically with:

```python
from atas.utils.data_manager import prepare_city
prepare_city("Amsterdam")
```

This pulls in three datasets and caches them under `~/.percolation_cache/`:

| Dataset | What it is |
|---------|-----------|
| CBS KWB 2025 | Neighbourhood statistics and boundary polygons |
| OVapi GTFS | Dutch national transit schedules |
| City OSM extract | Street network clipped to the city boundary |

The province-level OSM file (~100–200 MB) is downloaded temporarily and deleted after clipping.

---

## Running the scripts

From inside `The_package/` with the venv active:

```bash
cd The_package
source ../venv/bin/activate
```

**Generate maps:**
```bash
python scripts/run_maps.py
```
Produces 8 choropleth maps in `debug/`: walking time, attractiveness, travel time, accessibility score (rush hour and off-hours), benefit score, and a rush vs off-hours diff map.

**Equity analysis:**
```bash
python scripts/run_equity.py
```
Scatter plots of accessibility score against socio-economic indicators from CBS (poverty rate, low income share, elderly population, non-EU origin, single-person households, population density).

**Metric correlations:**
```bash
python scripts/run_correlations.py
```
Shows how t_walk, t_travel, attractiveness, and accessibility all correlate with each other.

**Sensitivity analysis:**
```bash
python scripts/run_sensitivity.py
```
Tests how stable the accessibility scores are when you change the beta parameter or the attractiveness weights.

**Before/after comparison:**
```bash
python scripts/compare_scores.py
```
Computes accessibility before and after removing a fraction of streets from the driving network.

---

## How it works

The pipeline has a fixed setup order before you can compute anything:

```python
from atas.core._classes import Network, Database

network  = Network("Amsterdam", store_in_file=True)
database = Database("path/to/kwb.csv", "path/to/boundaries.gpkg")

database.set_city("Amsterdam")
database.load_network(network)
database.obtain_features()
database.pre_process()
```

After that, the metric modules in `core/` can be called:

| Module | What it computes |
|--------|-----------------|
| `_t_walk.py` | Average walking time from neighbourhood sample points to the nearest transit stop |
| `_t_travel.py` | OD travel time matrix between all neighbourhood pairs via R5 |
| `_attractiveness.py` | Weighted combination of population, jobs, and amenities per neighbourhood |
| `_accessibility_score.py` | Gravity model: `A_i = Σ O_j · exp(−β · t_ij)` |
| `_benefit.py` | Which neighbourhoods would benefit most from better connections |

`Network` wraps two OSMnx graphs (one for driving, one for walking) and optionally an r5py transit network. `Database` is an in-memory DuckDB instance that holds all the CBS data, geometries, and computed results.

To simulate pedestrianisation, call `database.remove_f_edges(fraction)`. This removes the highest population-density streets from the driving network and adds them to the pedestrian network. Running the metrics again afterwards shows what the accessibility impact would be.

All internal coordinates use **EPSG:28992** (Dutch RD New). R5py needs **EPSG:4326**, so conversions happen inside each metric module.

---

## Tests

```bash
cd The_package
pytest
```

Tests that need the full Amsterdam OSM or GTFS data are skipped automatically if those files aren't present. Small test datasets for Amsterdam are included in `tests/TestDatasets/`.

---

## Settings

All the tunable parameters are in `src/atas/config/settings.py`. You can change them at runtime without touching the file:

```python
from atas.config.settings import get_settings
settings = get_settings()
settings.transit_max_edge_dist = 50  # max distance (m) from a transit stop to a street node
```

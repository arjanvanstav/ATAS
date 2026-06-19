# ATAS — Amsterdam Transit Accessibility Simulation

This package was built for a  thesis. It simulates what happens to public transit accessibility when streets are converted from car-accessible to pedestrian-only. It computes an accessibility score per neighbourhood using CBS demographic data, OpenStreetMap street networks, and real GTFS transit schedules.

---

## Before you start

You need two things installed before the package will work:

**Java 17 or 21** (the transit router needs it — don't use Java 26+):
```bash
brew install --cask temurin@21        # macOS
sudo apt install temurin-21-jdk       # Ubuntu/Debian
```

**osmium-tool** (for downloading city data):
```bash
brew install osmium-tool              # macOS
sudo apt install osmium-tool          # Ubuntu/Debian
```

---

## Installation

```bash
python3.10 -m venv venv
source venv/bin/activate

cd The_package
pip install -e .
pip install r5py
```

---

## Getting the data

Run this once and it will download everything automatically:

```python
from atas.utils.data_manager import prepare_city
prepare_city("Amsterdam")
```

This downloads the CBS neighbourhood data, Dutch transit schedules (GTFS), and a city-level street network. Everything is saved to `~/.percolation_cache/` so you only need to do it once.

---

## Running the analysis

All scripts are run from inside `The_package/`:

```bash
cd The_package
source ../venv/bin/activate

python scripts/run_maps.py          # generates 8 maps (walking time, accessibility, etc.)
python scripts/run_equity.py        # accessibility vs poverty, age, income, etc.
python scripts/run_correlations.py  # how the different metrics relate to each other
python scripts/run_sensitivity.py   # tests how sensitive the results are to parameter choices
```

Output is saved to `debug/`.

---

## How it works (briefly)

The core idea is a gravity model: a neighbourhood's accessibility score is higher if there are many attractive destinations reachable in a short time by transit. Three things go into it:

- **t_walk** — how long it takes to walk from a neighbourhood to the nearest transit stop
- **t_travel** — how long it takes to travel between every pair of neighbourhoods by transit
- **attractiveness** — how many people, jobs, and amenities a neighbourhood has

Combining these gives an accessibility score per neighbourhood. You can then simulate pedestrianisation by removing streets from the driving network and rerunning the model to see what changes.

---

## Running the tests

```bash
cd The_package
pytest
```

Tests that need the full Amsterdam data are skipped automatically if you haven't downloaded it yet.

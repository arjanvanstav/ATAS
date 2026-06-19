"""
data_path.py — Paths to the large external datasets (OSM + GTFS) used by the pipeline.

Both files live in ~/datasets/ by default. If you used the GUI or data_manager.prepare_city()
to download them, they are in ~/.percolation_cache/ instead — update the paths below.
"""

from pathlib import Path

DATA_DIR = Path.home() / "datasets"

PBF_FILE  = DATA_DIR / "osm/amsterdam.osm.pbf"
GTFS_FILE = DATA_DIR / "gtfs/amsterdam_gtfs.zip"

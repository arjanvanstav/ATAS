"""
data_manager.py — Download and cache CBS, GTFS, and city-level OSM data.

Cache structure:  ~/.percolation_cache/
    cbs/    — CBS KWB 2025 GeoPackage + CBS KWB 2024 income data (CSV)
    gtfs/   — OVapi national GTFS feed  (gtfs-nl.zip)
    osm/    — City-level .osm.pbf extracts (clipped from province extract)

Province .pbf files are downloaded temporarily and deleted after clipping.
Requires osmium-tool on PATH:
    macOS:  brew install osmium-tool
    Ubuntu: sudo apt install osmium-tool
"""
from pathlib import Path
import zipfile
import json
import shutil
import subprocess

CACHE_DIR = Path.home() / ".percolation_cache"
CBS_DIR  = CACHE_DIR / "cbs"
GTFS_DIR = CACHE_DIR / "gtfs"
OSM_DIR  = CACHE_DIR / "osm"

CBS_URL   = "https://geodata.cbs.nl/files/Wijkenbuurtkaart/WijkBuurtkaart_2025_v1.zip"
CBS_INCOME_API = "https://opendata.cbs.nl/ODataApi/odata/85984NED/TypedDataSet"  # KWB 2024
GTFS_URL  = "https://gtfs.ovapi.nl/nl/gtfs-nl.zip"
_GEOFABRIK  = "https://download.geofabrik.de/europe/netherlands"
_NOMINATIM  = "https://nominatim.openstreetmap.org/search"
_USER_AGENT = "percolation-street-transformation/1.0"


def _log(fn, msg: str):
    if fn:
        fn(msg)


def _download_file(url: str, dest: Path, log_fn=None):
    """Stream-download url to dest, reporting progress every ~25 MB."""
    import requests
    _log(log_fn, f"  Connecting to {url.split('/')[-1]} ...")
    with requests.get(url, stream=True, timeout=300,
                      headers={"User-Agent": _USER_AGENT}) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        downloaded = 0
        report_every = 25 * 1024 * 1024
        next_report = report_every
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
                downloaded += len(chunk)
                if downloaded >= next_report:
                    if total:
                        pct = downloaded * 100 // total
                        _log(log_fn, f"  {pct}%  ({downloaded // (1024*1024)} / {total // (1024*1024)} MB)")
                    else:
                        _log(log_fn, f"  {downloaded // (1024*1024)} MB downloaded ...")
                    next_report += report_every
    _log(log_fn, f"  Saved → {dest}")


# ---------------------------------------------------------------------------
# CBS KWB 2025 — GeoPackage (geometry + demographics)
# ---------------------------------------------------------------------------

def ensure_cbs(log_fn=None) -> tuple[None, Path]:
    """
    Download CBS KWB 2025 GeoPackage if not already cached.
    Returns (None, gpkg_path) — the 2025 zip contains only a GeoPackage,
    no CSV. Use ensure_cbs_income() for income/poverty data.
    """
    CBS_DIR.mkdir(parents=True, exist_ok=True)

    existing_gpkg = _find_first(CBS_DIR, "wijkenbuurten_2025*.gpkg")
    if existing_gpkg:
        _log(log_fn, f"[data] CBS GeoPackage already cached → {existing_gpkg.name}")
        return None, existing_gpkg

    _log(log_fn, "[data] Downloading CBS KWB 2025 GeoPackage (~103 MB) ...")
    tmp_zip = CBS_DIR / "_tmp_cbs.zip"
    _download_file(CBS_URL, tmp_zip, log_fn)

    _log(log_fn, "[data] Extracting CBS GeoPackage ...")
    with zipfile.ZipFile(tmp_zip) as zf:
        for name in zf.namelist():
            if name.endswith(".gpkg"):
                flat_name = Path(name).name
                with zf.open(name) as src, open(CBS_DIR / flat_name, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                _log(log_fn, f"  Extracted {flat_name}")

    tmp_zip.unlink(missing_ok=True)

    gpkg_path = _find_first(CBS_DIR, "*.gpkg")
    if not gpkg_path:
        raise RuntimeError("CBS 2025 zip did not contain a .gpkg file.")

    _log(log_fn, "[data] CBS GeoPackage ready.")
    return None, gpkg_path


def ensure_cbs_income(gemeente_code: str = "GM0363", log_fn=None) -> Path:
    """
    Download CBS KWB 2024 income/poverty data for the given municipality
    from the CBS OData API (dataset 85984NED) if not already cached.
    Returns path to the saved CSV.

    Columns in the output CSV:
        neighborhood_id          — buurtcode (e.g. BU0363AA01)
        pct_low_income           — % persons in lowest 40% income bracket
        pct_poverty              — % persons in poverty
        avg_income_per_resident  — average standardised household income (€k)
    """
    import urllib.request, urllib.parse, json
    import csv as csv_mod

    CBS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = CBS_DIR / f"income_{gemeente_code}.csv"

    if out_path.exists():
        _log(log_fn, f"[data] CBS income already cached → {out_path.name}")
        return out_path

    _log(log_fn, f"[data] Downloading CBS KWB 2024 income data for {gemeente_code} ...")
    # gemeente_code = "GM0363" → buurt prefix = "BU0363"
    buurt_prefix = "BU" + gemeente_code[2:]
    params = urllib.parse.urlencode({
        "$filter": (f"startswith(WijkenEnBuurten,'{buurt_prefix}') "
                    f"and SoortRegio_2 eq 'Buurt'"),
        "$select": ("WijkenEnBuurten,"
                    "k_40PersonenMetLaagsteInkomen_79,"
                    "PersonenInArmoede_81,"
                    "GemGestandaardiseerdInkomen_83"),
        "$format": "json",
    })
    url = f"{CBS_INCOME_API}?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())

    rows = data.get("value", [])
    with open(out_path, "w", newline="") as f:
        writer = csv_mod.writer(f)
        writer.writerow(["neighborhood_id", "pct_low_income", "pct_poverty",
                          "avg_income_per_resident"])
        for row in rows:
            writer.writerow([
                row["WijkenEnBuurten"].strip(),
                row["k_40PersonenMetLaagsteInkomen_79"],
                row["PersonenInArmoede_81"],
                row["GemGestandaardiseerdInkomen_83"],
            ])

    _log(log_fn, f"[data] CBS income data ready → {out_path.name} ({len(rows)} buurten)")
    return out_path


# ---------------------------------------------------------------------------
# GTFS (OVapi national feed)
# ---------------------------------------------------------------------------

def ensure_gtfs(log_fn=None) -> Path:
    """
    Download OVapi national GTFS feed if not already cached.
    Returns path to gtfs-nl.zip.
    """
    GTFS_DIR.mkdir(parents=True, exist_ok=True)
    gtfs_path = GTFS_DIR / "gtfs-nl.zip"
    if gtfs_path.exists():
        _log(log_fn, f"[data] GTFS already cached → {gtfs_path}")
        return gtfs_path

    _log(log_fn, "[data] Downloading OVapi GTFS feed (~200 MB) ...")
    _download_file(GTFS_URL, gtfs_path, log_fn)
    _log(log_fn, "[data] GTFS data ready.")
    return gtfs_path


# ---------------------------------------------------------------------------
# OSM (city-level via Geofabrik + osmium clip)
# ---------------------------------------------------------------------------

def _city_key(city: str) -> str:
    return city.lower().replace(" ", "_")


def _get_province(city: str) -> str:
    """Return Dutch province name for a city via Nominatim."""
    import requests
    resp = requests.get(
        _NOMINATIM,
        params={"q": f"{city}, Netherlands", "countrycodes": "nl",
                "addressdetails": "1", "format": "json", "limit": "1"},
        headers={"User-Agent": _USER_AGENT},
        timeout=30,
    )
    resp.raise_for_status()
    results = resp.json()
    if not results:
        raise ValueError(f"City '{city}' not found via Nominatim.")
    state = results[0].get("address", {}).get("state", "")
    if not state:
        raise ValueError(f"Could not determine province for '{city}'.")
    return state


def _get_city_boundary_geojson(city: str) -> dict:
    """Return GeoJSON geometry for the city boundary via Nominatim."""
    import requests
    resp = requests.get(
        _NOMINATIM,
        params={"q": f"{city}, Netherlands", "countrycodes": "nl",
                "polygon_geojson": "1", "format": "json", "limit": "1"},
        headers={"User-Agent": _USER_AGENT},
        timeout=30,
    )
    resp.raise_for_status()
    results = resp.json()
    if not results:
        raise ValueError(f"No boundary polygon found for '{city}'.")
    return results[0]["geojson"]


def ensure_city_osm(city: str, log_fn=None) -> Path:
    """
    Ensure a city-level OSM .pbf exists in the cache.

    Downloads the province extract from Geofabrik, clips it to the city
    boundary using osmium-tool, then deletes the (large) province file.
    Returns path to <city_key>.osm.pbf.
    """
    OSM_DIR.mkdir(parents=True, exist_ok=True)
    key      = _city_key(city)
    out_path = OSM_DIR / f"{key}.osm.pbf"

    if out_path.exists():
        size_mb = out_path.stat().st_size // (1024 * 1024)
        _log(log_fn, f"[data] OSM for {city} already cached ({size_mb} MB)")
        return out_path

    if shutil.which("osmium") is None:
        raise RuntimeError(
            "osmium-tool is not installed or not in PATH.\n"
            "  macOS:  brew install osmium-tool\n"
            "  Ubuntu: sudo apt install osmium-tool\n"
            "See README for details."
        )

    # 1. Look up province via Nominatim
    _log(log_fn, f"[data] Looking up province for '{city}' via Nominatim ...")
    province = _get_province(city)
    slug = province.lower().replace(" ", "-")
    _log(log_fn, f"[data] Province: {province}  (Geofabrik slug: {slug})")

    # 2. Fetch city boundary polygon
    _log(log_fn, "[data] Fetching city boundary polygon ...")
    geometry = _get_city_boundary_geojson(city)
    boundary_path = OSM_DIR / f"{key}_boundary.geojson"
    with open(boundary_path, "w") as f:
        json.dump({
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "geometry": geometry, "properties": {}}],
        }, f)

    # 3. Download province .pbf (kept only until clipping is done)
    province_url  = f"{_GEOFABRIK}/{slug}-latest.osm.pbf"
    province_path = OSM_DIR / f"_tmp_{slug}.osm.pbf"
    _log(log_fn, f"[data] Downloading {province} province OSM (~90–200 MB, temporary) ...")
    _download_file(province_url, province_path, log_fn)

    # 4. Clip city extract from province
    _log(log_fn, f"[data] Clipping '{city}' from province data ...")
    result = subprocess.run(
        ["osmium", "extract",
         f"--polygon={boundary_path}",
         str(province_path),
         "-o", str(out_path),
         "--overwrite"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"osmium extract failed:\n{result.stderr.strip()}")

    # 5. Remove temporary files
    province_path.unlink(missing_ok=True)
    boundary_path.unlink(missing_ok=True)

    size_mb = out_path.stat().st_size // (1024 * 1024)
    _log(log_fn, f"[data] City OSM saved ({size_mb} MB) → {out_path}")
    return out_path


# ---------------------------------------------------------------------------
# High-level orchestration
# ---------------------------------------------------------------------------

def prepare_city(city: str, log_fn=None) -> dict:
    """
    Download CBS, GTFS, and city OSM data (skipping anything already cached).
    Returns dict with keys: csv, gpkg, gtfs, pbf  (all str paths).
    """
    csv_path, gpkg_path = ensure_cbs(log_fn)
    gtfs_path           = ensure_gtfs(log_fn)
    pbf_path            = ensure_city_osm(city, log_fn)
    return {
        "csv":  str(csv_path),
        "gpkg": str(gpkg_path),
        "gtfs": str(gtfs_path),
        "pbf":  str(pbf_path),
    }


def delete_all_data(log_fn=None):
    """Remove the entire cache directory."""
    if CACHE_DIR.exists():
        size = cache_size_mb()
        shutil.rmtree(CACHE_DIR)
        _log(log_fn, f"[data] Deleted {CACHE_DIR}  ({size} MB freed)")
    else:
        _log(log_fn, "[data] Cache is already empty.")


def data_status(city: str = None) -> dict:
    """
    Return a dict describing what is currently cached.
    Values are path strings when cached, None otherwise.
    Keys: cbs_csv, cbs_gpkg, gtfs, [osm if city provided].
    """
    csv_p  = _find_first(CBS_DIR, "*.csv")  if CBS_DIR.exists()  else None
    gpkg_p = _find_first(CBS_DIR, "*.gpkg") if CBS_DIR.exists()  else None
    gtfs_p = GTFS_DIR / "gtfs-nl.zip"
    status = {
        "cbs_csv":  str(csv_p)  if csv_p  else None,
        "cbs_gpkg": str(gpkg_p) if gpkg_p else None,
        "gtfs":     str(gtfs_p) if gtfs_p.exists() else None,
    }
    if city:
        osm_p = OSM_DIR / f"{_city_key(city)}.osm.pbf"
        status["osm"] = str(osm_p) if osm_p.exists() else None
    return status


def cache_size_mb() -> int:
    """Return total cache size in MB."""
    if not CACHE_DIR.exists():
        return 0
    return sum(f.stat().st_size for f in CACHE_DIR.rglob("*") if f.is_file()) // (1024 * 1024)


# ---------------------------------------------------------------------------
# Path accessors
# ---------------------------------------------------------------------------

def get_cbs_csv() -> Path | None:
    return _find_first(CBS_DIR, "*.csv") if CBS_DIR.exists() else None


def get_cbs_gpkg() -> Path | None:
    return _find_first(CBS_DIR, "*.gpkg") if CBS_DIR.exists() else None


def get_gtfs_path() -> Path | None:
    p = GTFS_DIR / "gtfs-nl.zip"
    return p if p.exists() else None


def get_osm_path(city: str) -> Path | None:
    p = OSM_DIR / f"{_city_key(city)}.osm.pbf"
    return p if p.exists() else None


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _find_first(directory: Path, pattern: str) -> Path | None:
    matches = sorted(directory.glob(pattern))
    return matches[0] if matches else None

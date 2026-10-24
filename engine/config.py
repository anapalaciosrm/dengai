"""Shared settings and helpers for every engine step.

All assumptions come from config/assumptions.csv, so nothing is hardcoded in the steps.
"""

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = ROOT / "config" / "assumptions.csv"
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
OUTPUTS = ROOT / "outputs"

AREA_FILE = RAW / "tallo_area.gpkg"
GRAPH_FILE = RAW / "tallo_walk.graphml"
SITES_FILE = PROCESSED / "sites.csv"
ENRICHED_FILE = PROCESSED / "sites_enriched.csv"
SCORED_FILE = PROCESSED / "sites_scored.csv"
MATRIX_FILE = PROCESSED / "travel_minutes.csv"
START_FILE = PROCESSED / "start_point.csv"
ACCESS_FILE = PROCESSED / "site_access.csv"

UTM = "EPSG:32750"  # meters, for buffers and distances
WGS = "EPSG:4326"   # lat and lon, for storing and mapping


def load_assumptions():
    """Return assumptions as a dict. Numbers become floats, everything else stays text."""
    table = pd.read_csv(CONFIG_FILE)
    values = {}
    for key, value in zip(table["key"], table["value"]):
        try:
            values[key] = float(value)
        except (TypeError, ValueError):
            values[key] = str(value)
    return values


def type_weight(cfg, site_type):
    """Weight for a site type, from keys like w_tire. Unknown types get 0.5."""
    return cfg.get(f"w_{site_type}", 0.5)


def inspect_minutes(cfg, site_type):
    """Minutes to inspect a site type, from keys like inspect_min_tire. Unknown types get 15."""
    return cfg.get(f"inspect_min_{site_type}", 15.0)

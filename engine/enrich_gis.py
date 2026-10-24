"""Step 2: add GIS information to each site.

Reads  data/processed/sites.csv and data/raw/tallo_area.gpkg (buildings)
Writes data/processed/sites_enriched.csv with new columns:
    buildings_nearby  buildings within buffer_m of the site (exposure, people affected)
    sites_nearby      other predicted sites within buffer_m (clustering, hotspots)
    exposure          buildings_nearby rescaled to scale_min..scale_max
    clustering        sites_nearby rescaled to scale_min..scale_max

Method (see docs/METHODS.md, layer 2): buffer + spatial join in meters (EPSG:32750).
buffer_m = 100 m, the average Aedes aegypti flight range (Moore and Brown 2022).

Run: python engine/enrich_gis.py
"""

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent))
import config as C  # noqa: E402


def rescale(values, low, high):
    """Map values linearly onto low..high. If all values are equal, return the middle."""
    values = np.asarray(values, dtype=float)
    span = values.max() - values.min()
    if span == 0:
        return np.full(len(values), (low + high) / 2)
    return low + (values - values.min()) / span * (high - low)


def count_within(points, targets, radius_m):
    """For each point, count targets within radius_m. Both GeoDataFrames in meters."""
    buffers = gpd.GeoDataFrame(geometry=points.geometry.buffer(radius_m), crs=points.crs)
    buffers["point_index"] = range(len(points))
    joined = gpd.sjoin(targets[["geometry"]], buffers, predicate="within")
    counts = joined.groupby("point_index").size()
    return counts.reindex(range(len(points)), fill_value=0).to_numpy()


def main():
    cfg = C.load_assumptions()
    radius = cfg["buffer_m"]
    low, high = cfg["scale_min"], cfg["scale_max"]

    sites = pd.read_csv(C.SITES_FILE)
    pts = gpd.GeoDataFrame(sites, geometry=gpd.points_from_xy(sites["lon"], sites["lat"]),
                           crs=C.WGS).to_crs(C.UTM)

    # Exposure: buildings near each site
    if C.AREA_FILE.exists():
        buildings = gpd.read_file(C.AREA_FILE, layer="buildings").to_crs(C.UTM)
        sites["buildings_nearby"] = count_within(pts, buildings, radius)
    else:
        print("No buildings file; exposure set to neutral. Run engine/setup_area.py.")
        sites["buildings_nearby"] = 0

    # Clustering: other sites near each site (subtract 1 so a site does not count itself)
    sites["sites_nearby"] = count_within(pts, pts, radius) - 1

    sites["exposure"] = rescale(sites["buildings_nearby"], low, high).round(3)
    sites["clustering"] = rescale(sites["sites_nearby"], low, high).round(3)

    sites.to_csv(C.ENRICHED_FILE, index=False)
    print(f"Enriched {len(sites)} sites using a {radius:.0f} m buffer")
    print(f"Buildings nearby: median {sites['buildings_nearby'].median():.0f}, "
          f"max {sites['buildings_nearby'].max()}")
    print(f"Other sites nearby: median {sites['sites_nearby'].median():.0f}, "
          f"max {sites['sites_nearby'].max()}")


if __name__ == "__main__":
    main()

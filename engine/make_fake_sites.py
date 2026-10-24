"""Make realistic synthetic breeding sites inside Tallo, Makassar.

Why: the real Tallo detections were not released during the hackathon (the brief made them
subject to data-sharing approval, with synthetic data as the fallback). These synthetic sites
follow the published studies, so the pipeline can be built and evaluated; load_sites.py swaps
in real detections when they are available.

Run (after engine/setup_area.py):
    python engine/make_fake_sites.py
    python engine/make_fake_sites.py --n 300 --scenario dense --seed 2

Writes:
    data/processed/sites_fake_<scenario>.csv
    data/processed/sites.csv            (copy of the chosen scenario, what the pipeline reads)

How sites are placed (all assumptions, stated in the pitch):
    * Inside Tallo's real boundary, near real buildings (trash and tires sit where people live).
    * Clustered: the source team's analysis found tire hotspots, so most sites come in clusters.
    * A mix of site types with tires most common, since tires are the study's focus.
    * Each site has a detection confidence. `is_real` is simulated ground truth, drawn from
      that confidence. It is ONLY for evaluation (Monte Carlo); the planner must never use it.
"""

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import Point, box

AREA_FILE = Path("data/raw/tallo_area.gpkg")
OUT_DIR = Path("data/processed")
UTM = "EPSG:32750"
WGS = "EPSG:4326"

# Rough box around Tallo, used ONLY if setup_area.py has not been run yet.
FALLBACK_BOX = box(119.415, -5.135, 119.455, -5.095)

SITE_TYPES = ["tire", "container", "drain", "trash"]
TYPE_SHARE = [0.40, 0.25, 0.15, 0.20]
# Average detection confidence by type. Tires near the study's F1 of 0.87.
TYPE_CONFIDENCE = {"tire": 0.87, "container": 0.75, "drain": 0.70, "trash": 0.80}

# Scenario settings: how many clusters, and what share of sites sit in clusters.
SCENARIOS = {
    "sparse": {"n_clusters": 8, "cluster_share": 0.4, "spread_m": 60},
    "clustered": {"n_clusters": 15, "cluster_share": 0.7, "spread_m": 40},
    "dense": {"n_clusters": 30, "cluster_share": 0.8, "spread_m": 30},
}


def load_area():
    """Return (boundary polygon in meters, building points in meters or None)."""
    if AREA_FILE.exists():
        boundary = gpd.read_file(AREA_FILE, layer="boundary").to_crs(UTM).geometry.iloc[0]
        try:
            buildings = gpd.read_file(AREA_FILE, layer="buildings").to_crs(UTM)
            if len(buildings) == 0:
                buildings = None
        except Exception:
            buildings = None
        print("Using real Tallo boundary" + (" and buildings" if buildings is not None else ""))
        return boundary, buildings
    print("No data/raw/tallo_area.gpkg yet. Using a rough box around Tallo.")
    print("Run engine/setup_area.py on a computer with internet for the real boundary.")
    boundary = gpd.GeoSeries([FALLBACK_BOX], crs=WGS).to_crs(UTM).iloc[0]
    return boundary, None


def random_point_in(polygon, rng):
    """Uniform random point inside a polygon."""
    minx, miny, maxx, maxy = polygon.bounds
    while True:
        p = Point(rng.uniform(minx, maxx), rng.uniform(miny, maxy))
        if polygon.contains(p):
            return p


def anchor_point(boundary, buildings, rng):
    """A random building location, or a random point if we have no buildings."""
    if buildings is not None:
        return buildings.geometry.iloc[rng.integers(len(buildings))]
    return random_point_in(boundary, rng)


def place_sites(n, scenario, boundary, buildings, rng):
    """Return a list of site points (in meters) following the scenario."""
    cfg = SCENARIOS[scenario]
    centers = [anchor_point(boundary, buildings, rng) for _ in range(cfg["n_clusters"])]
    points = []
    while len(points) < n:
        if rng.random() < cfg["cluster_share"]:
            c = centers[rng.integers(len(centers))]
            spread = cfg["spread_m"]
        else:
            c = anchor_point(boundary, buildings, rng)
            spread = 15  # scattered sites sit right next to a building
        p = Point(c.x + rng.normal(0, spread), c.y + rng.normal(0, spread))
        if boundary.contains(p):
            points.append(p)
    return points


def draw_confidence(site_type, rng):
    """Confidence around the type average, kept between 0.3 and 0.99."""
    mean = TYPE_CONFIDENCE[site_type]
    # Beta distribution with this mean; 20 controls how spread out it is.
    value = rng.beta(mean * 20, (1 - mean) * 20)
    return float(np.clip(value, 0.30, 0.99))


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--n", type=int, default=200, help="number of sites")
    parser.add_argument("--scenario", choices=SCENARIOS, default="clustered")
    parser.add_argument("--seed", type=int, default=42, help="change for a different random layout")
    args = parser.parse_args()

    rng = np.random.default_rng(args.seed)
    boundary, buildings = load_area()
    points = place_sites(args.n, args.scenario, boundary, buildings, rng)

    types = rng.choice(SITE_TYPES, size=len(points), p=TYPE_SHARE)
    confidence = [draw_confidence(t, rng) for t in types]
    is_real = [bool(rng.random() < c) for c in confidence]

    gdf = gpd.GeoDataFrame(
        {"site_type": types, "confidence": np.round(confidence, 3), "is_real": is_real},
        geometry=points, crs=UTM,
    ).to_crs(WGS)
    gdf.insert(0, "site_id", [f"S{i:04d}" for i in range(1, len(gdf) + 1)])
    gdf["lat"] = gdf.geometry.y.round(6)
    gdf["lon"] = gdf.geometry.x.round(6)

    table = pd.DataFrame(gdf[["site_id", "lat", "lon", "site_type", "confidence", "is_real"]])
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUT_DIR / f"sites_fake_{args.scenario}.csv", index=False)
    table.to_csv(OUT_DIR / "sites.csv", index=False)

    print(f"Made {len(table)} fake sites ({args.scenario}, seed {args.seed})")
    print(table["site_type"].value_counts().to_string())
    print(f"Average confidence: {table['confidence'].mean():.2f}, "
          f"simulated real share: {table['is_real'].mean():.2f}")
    print("Saved data/processed/sites.csv. Next: streamlit run app.py")


if __name__ == "__main__":
    main()

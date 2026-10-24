"""Step 1: convert the organizers' data into our data contract, data/processed/sites.csv.

    site_id, lat, lon, site_type, confidence, detections, source_id

We do not know the exact format yet, so this accepts what detection models usually produce:
    * Files: .csv, .xlsx, .geojson / .json, .shp, .gpkg, .kml
    * Geometry: points, or polygons and lines (for example tire outlines from a segmentation
      model like the Rosser lab's U-Net++), which become their center point
    * Coordinates: lat and lon columns, or a geometry. Degrees or UTM meters.
    * Column names in English or Indonesian, any capitalization (see GUESSES below)
    * Confidence as 0 to 1 or 0 to 100. If missing, scoring.py uses default_confidence.

Detections closer than merge_radius_m (assumptions.csv) are merged into one site, because
a segmentation model can outline every tire in a pile, and a team inspects the pile once.
The merged site keeps the most common type, the highest confidence, and a count.

Run:
    python engine/load_sites.py data/raw/<organizer file>
    python engine/load_sites.py data/raw/<file> --type-column kelas --conf-column skor   (if guessing fails)
Then: python run_pipeline.py

Never edits data/raw/.
"""

import argparse
import re
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent))
import config as C  # noqa: E402

# Possible column names, checked in order (lowercase).
GUESSES = {
    "lat": ["lat", "latitude", "y", "lintang"],
    "lon": ["lon", "lng", "long", "longitude", "x", "bujur"],
    "type": ["site_type", "type", "class", "class_name", "label", "category", "object",
             "jenis", "kelas", "kategori"],
    "conf": ["confidence", "conf", "score", "prob", "probability", "p", "skor", "kepercayaan"],
    "id": ["id", "site_id", "fid", "object_id", "objectid"],
}

# Text found in a type label -> our site type. English and Indonesian.
TYPE_WORDS = [
    ("tire", r"tire|tyre|ban\b|ban |\bban"),
    ("drain", r"drain|gutter|selokan|got\b|saluran|parit"),
    ("trash", r"trash|garbage|waste|litter|rubbish|sampah"),
    ("container", r"container|pot|drum|bucket|barrel|bottle|tank|tandon|ember|wadah|kaleng|botol"),
]


def find_column(columns, kind, forced=None):
    """Return the matching column name, or None."""
    if forced:
        if forced not in columns:
            sys.exit(f"Column '{forced}' not found. Columns are: {list(columns)}")
        return forced
    lower = {c.lower().strip(): c for c in columns}
    for name in GUESSES[kind]:
        if name in lower:
            return lower[name]
    return None


def normalize_type(label):
    """Map any label to tire, drain, trash, container, or other."""
    text = str(label).lower()
    for site_type, pattern in TYPE_WORDS:
        if re.search(pattern, text):
            return site_type
    return "other"


def read_any(path, lat_col=None, lon_col=None):
    """Read the file into a GeoDataFrame of points in EPSG:4326."""
    suffix = path.suffix.lower()
    if suffix in [".csv", ".xlsx", ".xls"]:
        table = pd.read_csv(path) if suffix == ".csv" else pd.read_excel(path)
        lat = find_column(table.columns, "lat", lat_col)
        lon = find_column(table.columns, "lon", lon_col)
        if not lat or not lon:
            sys.exit(f"Could not find coordinate columns in {list(table.columns)}. "
                     "Use --lat-column and --lon-column.")
        x, y = table[lon].astype(float), table[lat].astype(float)
        # Degrees are small numbers; UTM meters are large.
        crs = C.WGS if x.abs().max() <= 180 and y.abs().max() <= 90 else C.UTM
        print(f"Coordinates from columns '{lat}' and '{lon}' ({'degrees' if crs == C.WGS else 'UTM meters'})")
        gdf = gpd.GeoDataFrame(table, geometry=gpd.points_from_xy(x, y), crs=crs)
    else:
        gdf = gpd.read_file(path)
        if gdf.crs is None:
            b = gdf.total_bounds
            gdf = gdf.set_crs(C.WGS if abs(b).max() <= 180 else C.UTM)
            print(f"File has no coordinate system; assumed {gdf.crs}")
        kinds = gdf.geom_type.value_counts().to_dict()
        print(f"Geometry: {kinds}")
        # Polygons and lines become their center (computed in meters, then back to degrees).
        gdf = gdf.set_geometry(gdf.to_crs(C.UTM).geometry.centroid).to_crs(gdf.crs)
    return gdf.to_crs(C.WGS)


def merge_close(points_m, radius_m):
    """Group detections within radius_m of each other (chains count as one group)."""
    if radius_m <= 0 or len(points_m) < 2:
        return np.arange(len(points_m))
    blobs = gpd.GeoDataFrame(geometry=[points_m.geometry.buffer(radius_m / 2).union_all()], crs=points_m.crs)
    blobs = blobs.explode(index_parts=False).reset_index(drop=True)
    blobs["group"] = range(len(blobs))
    joined = gpd.sjoin(points_m[["geometry"]], blobs, predicate="within", how="left")
    joined = joined[~joined.index.duplicated()]
    return joined["group"].to_numpy()


def main():
    parser = argparse.ArgumentParser(description="Convert organizer data into data/processed/sites.csv")
    parser.add_argument("path", type=Path)
    parser.add_argument("--type-column")
    parser.add_argument("--conf-column")
    parser.add_argument("--lat-column")
    parser.add_argument("--lon-column")
    parser.add_argument("--default-type", default="tire",
                        help="type to use if the data has no type column (the source study detects tires)")
    parser.add_argument("--out", type=Path, default=C.SITES_FILE)
    args = parser.parse_args()

    cfg = C.load_assumptions()
    gdf = read_any(args.path, args.lat_column, args.lon_column)
    print(f"Read {len(gdf)} detections from {args.path.name}")

    # Type
    type_col = find_column(gdf.columns, "type", args.type_column)
    if type_col:
        gdf["site_type"] = gdf[type_col].map(normalize_type)
        print(f"Types from column '{type_col}':")
        print(pd.crosstab(gdf[type_col].astype(str), gdf["site_type"]).to_string())
    else:
        gdf["site_type"] = args.default_type
        print(f"No type column found; every site is '{args.default_type}'.")

    # Confidence
    conf_col = find_column(gdf.columns, "conf", args.conf_column)
    if conf_col:
        conf = pd.to_numeric(gdf[conf_col], errors="coerce")
        if conf.max() > 1:
            conf = conf / 100
            print(f"Confidence from '{conf_col}', converted from 0 to 100 into 0 to 1")
        else:
            print(f"Confidence from '{conf_col}'")
        gdf["confidence"] = conf.clip(0, 1)
    else:
        gdf["confidence"] = np.nan
        print("No confidence column; scoring.py will use default_confidence.")

    id_col = find_column(gdf.columns, "id")
    gdf["source_id"] = gdf[id_col].astype(str) if id_col else [str(i) for i in range(len(gdf))]

    # Merge detections that are really one site
    pts_m = gdf.to_crs(C.UTM)
    radius = float(cfg.get("merge_radius_m", 10))
    gdf["group"] = merge_close(pts_m, radius)
    pts_m["group"] = gdf["group"].to_numpy()
    centers = pts_m.dissolve(by="group").geometry.centroid.to_crs(C.WGS)
    sites = gdf.groupby("group").agg(
        site_type=("site_type", lambda s: s.mode().iloc[0]),
        confidence=("confidence", "max"),
        detections=("site_type", "size"),
        source_id=("source_id", lambda s: ";".join(s.head(5))),
    )
    sites["lat"] = centers.y.reindex(sites.index).round(6)
    sites["lon"] = centers.x.reindex(sites.index).round(6)
    sites = sites.reset_index(drop=True)
    sites.insert(0, "site_id", [f"S{i:04d}" for i in range(1, len(sites) + 1)])
    sites = sites[["site_id", "lat", "lon", "site_type", "confidence", "detections", "source_id"]]
    print(f"Merged detections within {radius:.0f} m: {len(gdf)} detections -> {len(sites)} sites")

    # Check the study area
    if C.AREA_FILE.exists():
        boundary = gpd.read_file(C.AREA_FILE, layer="boundary").to_crs(C.WGS).geometry.iloc[0]
        inside = gpd.points_from_xy(sites["lon"], sites["lat"]).within(boundary)
        if (~inside).sum():
            print(f"Note: {(~inside).sum()} sites are outside the Tallo boundary (kept).")

    if len(sites) > 500:
        print(f"Warning: {len(sites)} sites. Travel times and the optimizer will be slower; "
              "consider a larger merge_radius_m or a higher solver_seconds.")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    sites.to_csv(args.out, index=False)
    print(f"Wrote {args.out}")
    print(sites["site_type"].value_counts().to_string())


if __name__ == "__main__":
    main()

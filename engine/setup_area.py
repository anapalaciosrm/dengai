"""Download the study area once: Tallo boundary, walking network, health centers, buildings.

Run from the repo folder (needs internet, takes a few minutes):
    python engine/setup_area.py

Writes:
    data/raw/tallo_area.gpkg      layers: boundary, health_centers, buildings
    data/raw/tallo_walk.graphml   street and footpath network for walking times

Sources: OpenStreetMap via OSMnx. Tallo sub-district is the study area of the
source team's drone study (Hassan et al. 2026).
"""

from pathlib import Path

import geopandas as gpd
import osmnx as ox

RAW = Path("data/raw")
AREA_FILE = RAW / "tallo_area.gpkg"
GRAPH_FILE = RAW / "tallo_walk.graphml"

# OpenStreetMap may spell the place differently, so we try a few names.
PLACE_NAMES = [
    "Tallo, Makassar, South Sulawesi, Indonesia",
    "Kecamatan Tallo, Kota Makassar, Sulawesi Selatan, Indonesia",
    "Tallo, Makassar, Indonesia",
]

UTM = "EPSG:32750"  # meters, for buffering
WGS = "EPSG:4326"   # lat and lon, for storing and mapping


def get_boundary():
    """Return the Tallo boundary as a one row GeoDataFrame in lat and lon."""
    for name in PLACE_NAMES:
        try:
            gdf = ox.geocode_to_gdf(name)
            if gdf.geometry.iloc[0].geom_type in ("Polygon", "MultiPolygon"):
                print(f"Found boundary using: {name}")
                return gdf[["geometry"]].assign(name="Tallo").to_crs(WGS)
        except Exception as err:  # keep trying the next spelling
            print(f"Could not geocode '{name}': {err}")
    raise RuntimeError("No boundary found. Ask Claude for a bounding box fallback.")


def buffered(boundary, meters):
    """Boundary grown by some meters, so we include clinics and streets just outside it."""
    return boundary.to_crs(UTM).buffer(meters).to_crs(WGS).iloc[0]


def get_health_centers(area_polygon):
    """Clinics, hospitals, and puskesmas from OpenStreetMap, as points."""
    tags = {"amenity": ["clinic", "hospital", "doctors"], "healthcare": True}
    feats = ox.features_from_polygon(area_polygon, tags=tags)
    feats = feats.reset_index()
    pts = feats.to_crs(UTM)
    pts["geometry"] = pts.geometry.centroid
    pts = pts.to_crs(WGS)
    for col in ["name", "amenity", "healthcare"]:
        if col not in pts.columns:
            pts[col] = None
    pts = pts[["name", "amenity", "healthcare", "geometry"]].copy()
    pts["is_puskesmas"] = pts["name"].fillna("").str.lower().str.contains("puskesmas")
    return pts


def get_buildings(area_polygon):
    """Building footprints from OpenStreetMap, stored as center points."""
    feats = ox.features_from_polygon(area_polygon, tags={"building": True}).reset_index()
    pts = feats.to_crs(UTM)
    pts["geometry"] = pts.geometry.centroid
    return pts[["geometry"]].to_crs(WGS)


def main():
    RAW.mkdir(parents=True, exist_ok=True)

    boundary = get_boundary()
    boundary.to_file(AREA_FILE, layer="boundary", driver="GPKG")
    print("Saved boundary")

    health = get_health_centers(buffered(boundary, 1500))
    health.to_file(AREA_FILE, layer="health_centers", driver="GPKG")
    print(f"Saved {len(health)} health facilities "
          f"({int(health['is_puskesmas'].sum())} named puskesmas)")

    buildings = get_buildings(boundary.geometry.iloc[0])
    buildings.to_file(AREA_FILE, layer="buildings", driver="GPKG")
    print(f"Saved {len(buildings)} buildings")

    graph = ox.graph_from_polygon(buffered(boundary, 500), network_type="walk")
    ox.save_graphml(graph, GRAPH_FILE)
    print(f"Saved walking network: {len(graph.nodes)} nodes, {len(graph.edges)} edges")

    print("Done. Next: python engine/make_fake_sites.py")


if __name__ == "__main__":
    main()

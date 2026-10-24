"""Step 3: walking minutes between the start point and every site, on Tallo's real streets.

Reads  data/processed/sites_scored.csv, data/raw/tallo_walk.graphml, data/raw/tallo_area.gpkg
Writes data/processed/travel_minutes.csv  square table, rows and columns = START + site ids
       data/processed/start_point.csv     the chosen puskesmas

Method (docs/METHODS.md, layer 4):
    1. Snap each site and the start point to its nearest street node (in meters).
    2. Shortest walking paths on the street network (Dijkstra, edge length in meters).
    3. minutes = (network meters + snap meters at both ends) / walking speed.
Fallback if the network file is missing: straight line × detour_factor.

Start point: the puskesmas named in start_puskesmas, or with "auto" the puskesmas inside
Tallo closest to the center of the sites.

Run: python engine/travel_matrix.py
"""

import sys
from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent))
import config as C  # noqa: E402


def choose_start(cfg, sites_m):
    """Return (name, lat, lon) of the start puskesmas."""
    if not C.AREA_FILE.exists():
        center = sites_m.geometry.union_all().centroid
        pt = gpd.GeoSeries([center], crs=C.UTM).to_crs(C.WGS).iloc[0]
        print("No health center file; starting from the center of the sites.")
        return "Center of sites", pt.y, pt.x

    health = gpd.read_file(C.AREA_FILE, layer="health_centers")
    pusk = health[health["is_puskesmas"]].drop_duplicates("name").to_crs(C.UTM)
    wanted = str(cfg.get("start_puskesmas", "auto"))

    if wanted.lower() != "auto":
        match = pusk[pusk["name"].str.lower() == wanted.lower()]
        if len(match):
            chosen = match.iloc[0]
        else:
            print(f"'{wanted}' not found; falling back to auto.")
            wanted = "auto"

    if wanted.lower() == "auto":
        boundary = gpd.read_file(C.AREA_FILE, layer="boundary").to_crs(C.UTM).geometry.iloc[0]
        inside = pusk[pusk.within(boundary)]
        candidates = inside if len(inside) else pusk
        center = sites_m.geometry.union_all().centroid
        chosen = candidates.loc[candidates.distance(center).idxmin()]

    pt = gpd.GeoSeries([chosen.geometry], crs=C.UTM).to_crs(C.WGS).iloc[0]
    return chosen["name"], pt.y, pt.x


def nearest_nodes(node_xy, points_xy):
    """For each point, index of the nearest node and the distance in meters (brute force)."""
    idx, dist = [], []
    for x, y in points_xy:
        d = np.hypot(node_xy[:, 0] - x, node_xy[:, 1] - y)
        i = int(d.argmin())
        idx.append(i)
        dist.append(float(d[i]))
    return idx, np.array(dist)


def network_minutes(points_m, speed_m_per_min):
    """Walking minutes between all points using the street network."""
    import osmnx as ox

    graph = ox.load_graphml(C.GRAPH_FILE)
    nodes = ox.graph_to_gdfs(graph, edges=False).to_crs(C.UTM)
    node_ids = list(nodes.index)
    node_xy = np.column_stack([nodes.geometry.x, nodes.geometry.y])
    points_xy = np.column_stack([points_m.geometry.x, points_m.geometry.y])

    snap_idx, snap_m = nearest_nodes(node_xy, points_xy)
    snap_nodes = [node_ids[i] for i in snap_idx]
    undirected = graph.to_undirected()  # people can walk both ways on a street

    n = len(points_m)
    meters = np.zeros((n, n))
    for i, source in enumerate(snap_nodes):
        lengths = nx.single_source_dijkstra_path_length(undirected, source, weight="length")
        for j, target in enumerate(snap_nodes):
            if i == j:
                continue
            network = lengths.get(target, np.inf)
            meters[i, j] = network + snap_m[i] + snap_m[j]

    unreachable = np.isinf(meters).sum()
    if unreachable:
        print(f"Warning: {unreachable} pairs not connected; using straight line for them.")
        straight = np.hypot(points_xy[:, None, 0] - points_xy[None, :, 0],
                            points_xy[:, None, 1] - points_xy[None, :, 1]) * 1.3
        meters = np.where(np.isinf(meters), straight, meters)
    print(f"Snapped points to streets: median {np.median(snap_m):.0f} m, max {snap_m.max():.0f} m")

    # Accessibility: sites far from any mapped path are hard to reach (brief: geographic accessibility).
    access = pd.DataFrame({"id": list(points_m["id"]), "meters_to_path": snap_m.round(0)})
    access["hard_to_reach"] = access["meters_to_path"] > 300
    access.to_csv(C.PROCESSED / "site_access.csv", index=False)
    n_hard = int(access["hard_to_reach"].sum())
    if n_hard:
        print(f"{n_hard} point(s) are over 300 m from any mapped path (see site_access.csv)")
    return meters / speed_m_per_min


def straight_minutes(points_m, speed_m_per_min, detour):
    """Fallback: straight line distance × detour factor."""
    xy = np.column_stack([points_m.geometry.x, points_m.geometry.y])
    meters = np.hypot(xy[:, None, 0] - xy[None, :, 0], xy[:, None, 1] - xy[None, :, 1]) * detour
    return meters / speed_m_per_min


def main():
    cfg = C.load_assumptions()
    sites = pd.read_csv(C.SCORED_FILE)
    sites_m = gpd.GeoDataFrame(sites, geometry=gpd.points_from_xy(sites["lon"], sites["lat"]),
                               crs=C.WGS).to_crs(C.UTM)

    name, lat, lon = choose_start(cfg, sites_m)
    pd.DataFrame([{"name": name, "lat": lat, "lon": lon}]).to_csv(C.START_FILE, index=False)
    print(f"Start point: {name}")

    ids = ["START"] + list(sites["site_id"])
    points = gpd.GeoDataFrame(
        {"id": ids},
        geometry=gpd.points_from_xy([lon] + list(sites["lon"]), [lat] + list(sites["lat"])),
        crs=C.WGS,
    ).to_crs(C.UTM)

    speed = cfg["walk_speed_kmh"] * 1000 / 60  # meters per minute
    if C.GRAPH_FILE.exists():
        minutes = network_minutes(points, speed)
        method = "street network"
    else:
        minutes = straight_minutes(points, speed, cfg["detour_factor"])
        method = "straight line fallback"

    table = pd.DataFrame(np.round(minutes, 2), index=ids, columns=ids)
    table.to_csv(C.MATRIX_FILE)
    from_start = table.loc["START"].drop("START")
    print(f"Travel times ({method}): from start to sites median {from_start.median():.1f} min, "
          f"max {from_start.max():.1f} min")


if __name__ == "__main__":
    main()

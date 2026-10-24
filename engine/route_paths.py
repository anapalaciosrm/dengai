"""Step 7: street paths for drawing each team's route on the map.

The planners already use walking times along Tallo's real streets (travel_matrix.py).
This step only recovers the street geometry of each leg, so the map follows the
roads instead of drawing straight lines between stops.

For every plan in outputs/:
    START -> site -> site -> ... -> START, each leg is the shortest walking path
    on the same OpenStreetMap network and the same snapping as travel_matrix.py.

Reads  outputs/plan_<method>.csv, data/raw/tallo_walk.graphml, data/processed/start_point.csv
Writes outputs/paths_<method>.json   {team_id: [[lat, lon], ...]}

If the street network file is missing, nothing is written and the app draws straight lines.

Run: python engine/route_paths.py
"""

import json
import sys
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent))
import config as C  # noqa: E402

METHODS = ["nearest", "priority", "optimized"]


def load_network():
    """Load the street network once. Returns a dict used by paths_for_plan, or None."""
    if not C.GRAPH_FILE.exists():
        return None
    import geopandas as gpd
    import osmnx as ox

    graph = ox.load_graphml(C.GRAPH_FILE)
    nodes = ox.graph_to_gdfs(graph, edges=False)
    nodes_m = nodes.to_crs(C.UTM)
    return {
        "walk": graph.to_undirected(),  # people can walk both ways on a street
        "ids": list(nodes.index),
        "xy": np.column_stack([nodes_m.geometry.x, nodes_m.geometry.y]),
        "latlon": {n: (float(nodes.at[n, "y"]), float(nodes.at[n, "x"])) for n in nodes.index},
        "gpd": gpd,
    }


def snap(net, lat, lon):
    """Nearest street node to a point (same brute force method as travel_matrix.py)."""
    gpd = net["gpd"]
    pt = gpd.GeoSeries(gpd.points_from_xy([lon], [lat]), crs=C.WGS).to_crs(C.UTM).iloc[0]
    return net["ids"][int(np.hypot(net["xy"][:, 0] - pt.x, net["xy"][:, 1] - pt.y).argmin())]


def paths_for_plan(plan, start, net):
    """{team_id: [[lat, lon], ...]} following the streets, START -> stops -> START."""
    start_node = snap(net, start["lat"], start["lon"])
    paths = {}
    for team_id, team in plan.groupby("team_id"):
        team = team.sort_values("visit_order")
        stops = [(start["lat"], start["lon"], start_node)]
        stops += [(r.lat, r.lon, snap(net, r.lat, r.lon)) for r in team.itertuples()]
        stops += [stops[0]]  # back to the puskesmas

        line = []
        for (lat_a, lon_a, a), (lat_b, lon_b, b) in zip(stops[:-1], stops[1:]):
            line.append([lat_a, lon_a])  # the stop itself, then onto the street
            try:
                route = nx.shortest_path(net["walk"], a, b, weight="length")
                line += [list(net["latlon"][n]) for n in route]
            except nx.NetworkXNoPath:
                pass  # disconnected streets: fall back to a straight segment
            line.append([lat_b, lon_b])
        paths[str(int(team_id))] = [[round(y, 6), round(x, 6)] for y, x in line]
    return paths


def main():
    net = load_network()
    if net is None:
        print("No street network file; the map will draw straight lines. Run engine/setup_area.py.")
        return
    start = pd.read_csv(C.START_FILE).iloc[0]
    for method in METHODS:
        plan_file = C.OUTPUTS / f"plan_{method}.csv"
        if not plan_file.exists():
            continue
        paths = paths_for_plan(pd.read_csv(plan_file), start, net)
        with open(C.OUTPUTS / f"paths_{method}.json", "w") as f:
            json.dump(paths, f)
        print(f"{method:>9}: street paths for {len(paths)} teams")


if __name__ == "__main__":
    main()

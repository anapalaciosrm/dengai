"""Plan one day with the coordinator's settings. Used by the app's "Generate team routes" button.

The coordinator chooses the start puskesmas and, for EACH team, how it travels, how many
hours it is in the field, and when it leaves. Every method (both baselines and the optimizer)
replans with the same teams, so the comparison stays fair. Results go to outputs/ like
run_pipeline.py, so the whole app shows them.

Travel modes (docs/METHODS.md, layer 4):
    The street part of each trip is converted from walking speed to the team's speed.
    The off path part (street to site: yards, alleys) is always walked, because a bike or
    motorbike is parked at the street. Vehicles add park_min per stop.
    All modes use the OpenStreetMap walking network, which includes small alleys; for cars
    some alleys may be too narrow, so motorbike is the realistic vehicle in Tallo.

Start puskesmas: if it differs from the one in travel_minutes.csv, the START row is
recomputed with one shortest path search from the new puskesmas (a second or two).

Command line:
    python engine/plan_day.py --teams 6 --mode moto --hours 5
"""

import argparse
import json
import sys
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent))
import config as C  # noqa: E402
import cost as K  # noqa: E402
import optimizer as O  # noqa: E402
import plan_tools as P  # noqa: E402

MODES = {  # key: (label, speed key in assumptions.csv, default km/h)
    "walk": ("Walking", "walk_speed_kmh", 4),
    "bike": ("Bicycle", "bike_speed_kmh", 10),
    "moto": ("Motorbike", "moto_speed_kmh", 15),
    "car": ("Car", "car_speed_kmh", 12),
}
SETTINGS_FILE = C.OUTPUTS / "plan_settings.json"
METHODS = ["nearest", "priority", "optimized"]


def puskesmas_options():
    """Puskesmas to start from: name, lat, lon, in_tallo. Ones inside Tallo come first."""
    import geopandas as gpd
    if not C.AREA_FILE.exists():
        start = pd.read_csv(C.START_FILE)
        return start.assign(in_tallo=True)[["name", "lat", "lon", "in_tallo"]]
    health = gpd.read_file(C.AREA_FILE, layer="health_centers")
    pusk = health[health["is_puskesmas"]].drop_duplicates("name").to_crs(C.UTM)
    boundary = gpd.read_file(C.AREA_FILE, layer="boundary").to_crs(C.UTM).geometry.iloc[0]
    pusk["in_tallo"] = pusk.within(boundary)
    pusk = pusk.to_crs(C.WGS)
    out = pd.DataFrame({"name": pusk["name"], "lat": pusk.geometry.y, "lon": pusk.geometry.x,
                        "in_tallo": pusk["in_tallo"]})
    return out.sort_values(["in_tallo", "name"], ascending=[False, True]).reset_index(drop=True)


def offpath_minutes(travel):
    """Walked minutes between the street and each point (from site_access.csv), by id."""
    off = pd.Series(0.0, index=travel.index)
    if C.ACCESS_FILE.exists():
        access = pd.read_csv(C.ACCESS_FILE).set_index("id")
        if "offpath_minutes" in access:
            off = access["offpath_minutes"].reindex(travel.index).fillna(0)
    return off


def move_start(travel, off, start, net, cfg, coords):
    """Return (travel, off) with START moved to another puskesmas. Walking minutes."""
    import route_paths as R
    if net is None:
        return travel, off
    walk_m_per_min = cfg.get("walk_speed_kmh", 4) * 1000 / 60
    slow = cfg.get("offpath_slowdown", 1.0)
    node = R.snap(net, start["lat"], start["lon"])
    gpd = net["gpd"]
    pt = gpd.GeoSeries(gpd.points_from_xy([start["lon"]], [start["lat"]]), crs=C.WGS).to_crs(C.UTM).iloc[0]
    start_snap_m = float(np.hypot(*(net["xy"][net["ids"].index(node)] - [pt.x, pt.y])))

    lengths = nx.single_source_dijkstra_path_length(net["walk"], node, weight="length")
    access = pd.read_csv(C.ACCESS_FILE).set_index("id") if C.ACCESS_FILE.exists() else None
    travel, off = travel.copy(), off.copy()
    off["START"] = start_snap_m * slow / walk_m_per_min
    for site in travel.index.drop("START"):
        lat, lon = coords[site]
        site_node = R.snap(net, lat, lon)
        site_snap = float(access.at[site, "meters_to_path"]) if access is not None and site in access.index else 0
        meters = lengths.get(site_node, np.inf) + slow * (start_snap_m + site_snap)
        minutes = meters / walk_m_per_min if np.isfinite(meters) else travel.at["START", site]
        travel.at["START", site] = travel.at[site, "START"] = round(minutes, 2)
    return travel, off



def travel_for_mode(travel, cfg, mode, off=None):
    """Travel minutes table for a travel mode, built from the walking table."""
    if mode == "walk":
        return travel
    walk_speed = cfg.get("walk_speed_kmh", 4)
    speed = cfg.get(MODES[mode][1], MODES[mode][2])
    ratio = walk_speed / speed
    park = cfg.get("park_min", 2)
    if off is None:
        off = offpath_minutes(travel)

    t = travel.to_numpy()
    o = off.reindex(travel.index).fillna(0).to_numpy()
    both_ends = o[:, None] + o[None, :]
    street = np.clip(t - both_ends, 0, None)          # street minutes at walking speed
    converted = street * ratio + both_ends + park       # ride the street, walk the last bit, park
    np.fill_diagonal(converted, 0)
    return pd.DataFrame(converted.round(2), index=travel.index, columns=travel.columns)


def plan_day(teams, seconds, start=None, net=None):
    """Replan all methods for these teams and save everything. Returns the summaries.

    teams: list of {"mode": "walk", "hours": 6, "leave": "08:00"}, one per team.
    start: {"name", "lat", "lon"} of the start puskesmas, or None for start_point.csv.
    """
    import route_paths as R

    cfg, sites, travel, _ = P.load_inputs()
    default_start = pd.read_csv(C.START_FILE).iloc[0]
    if start is None:
        start = {"name": default_start["name"], "lat": float(default_start["lat"]),
                 "lon": float(default_start["lon"])}
    if net is None:
        net = R.load_network()

    off = offpath_minutes(travel)
    if start["name"] != default_start["name"]:
        all_sites = pd.read_csv(C.SCORED_FILE).set_index("site_id")
        coords = {s: (all_sites.at[s, "lat"], all_sites.at[s, "lon"]) for s in all_sites.index}
        travel, off = move_start(travel, off, start, net, cfg, coords)

    by_mode = {}
    for team in teams:
        if team["mode"] not in by_mode:
            by_mode[team["mode"]] = travel_for_mode(travel, cfg, team["mode"], off)
    travels = [by_mode[t["mode"]] for t in teams]
    days = [t["hours"] * 60 for t in teams]
    n = len(teams)

    nearest = lambda cur, feas, tr: min(feas, key=lambda s: tr.at[cur, s])  # noqa: E731
    best = lambda cur, feas, tr: max(feas, key=lambda s: (sites.at[s, "priority"], -tr.at[cur, s]))  # noqa: E731
    plans = {
        "nearest": P.greedy_plan(sites, travels, n, days, nearest),
        "priority": P.greedy_plan(sites, travels, n, days, best),
        "optimized": O.optimized_plan(sites, travels, n, days, seconds),
    }

    summaries = {}
    for method, plan in plans.items():
        summary = P.summarize(method, plan, sites, travels)
        costs = K.plan_costs(plan, teams, sites, travel, off.to_dict(), cfg)
        summary["total_cost_idr"] = int(costs.iloc[-1]["Total (IDR)"])
        summary["cost_per_high_priority_idr"] = K.cost_per_high_priority(costs, summary)
        P.save(method, plan, summary)
        costs.to_csv(C.OUTPUTS / f"costs_{method}.csv", index=False)
        if net is not None:
            with open(C.OUTPUTS / f"paths_{method}.json", "w") as f:
                json.dump(R.paths_for_plan(plan, start, net), f)
        summaries[method] = summary

    with open(SETTINGS_FILE, "w") as f:
        json.dump({"teams": teams, "start": start, "solver_seconds": seconds}, f, indent=2)
    return summaries


def load_settings(cfg):
    """Settings from the last Generate click, falling back to assumptions.csv."""
    default = {"mode": str(cfg.get("travel_mode", "walk")), "hours": float(cfg["hours_per_day"]),
               "leave": str(cfg.get("day_start", "08:00"))}
    settings = {"teams": [dict(default) for _ in range(int(cfg["n_teams"]))], "start": None,
                "solver_seconds": int(cfg.get("solver_seconds", 30))}
    if SETTINGS_FILE.exists():
        saved = json.loads(SETTINGS_FILE.read_text())
        if "teams" in saved:
            settings.update(saved)
    return settings


def main():
    cfg = C.load_assumptions()
    parser = argparse.ArgumentParser(description="Plan one day with the same settings for every team")
    parser.add_argument("--teams", type=int, default=int(cfg["n_teams"]))
    parser.add_argument("--mode", choices=MODES, default=str(cfg.get("travel_mode", "walk")))
    parser.add_argument("--hours", type=float, default=float(cfg["hours_per_day"]))
    parser.add_argument("--leave", default=str(cfg.get("day_start", "08:00")))
    parser.add_argument("--seconds", type=int, default=int(cfg.get("solver_seconds", 30)))
    a = parser.parse_args()
    teams = [{"mode": a.mode, "hours": a.hours, "leave": a.leave} for _ in range(a.teams)]
    for method, s in plan_day(teams, a.seconds).items():
        print(f"{method:>9}: {s['sites_visited']} sites, {s['high_priority_visited']}/"
              f"{s['high_priority_total']} high priority, total priority {s['total_priority']}, "
              f"cost {s['total_cost_idr']:,} IDR")


if __name__ == "__main__":
    main()

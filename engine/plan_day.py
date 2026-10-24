"""Plan one day from the coordinator's inputs. Used by the app's "Generate team routes" button.

The coordinator lists the puskesmas taking part today and, for each one, its budget, paid
workers, volunteers, motorbikes, bicycles, hours, and leave time. Then:
    1. teams.py forms the teams (who goes together, on what vehicle, labor cost, budget left).
    2. Travel times are built from each puskesmas: every team starts and ends at its own one.
    3. Both baselines and the optimizer plan with the same teams, times, and budgets.
    4. Plans, costs, and street paths are saved to outputs/ for the app.

Travel modes (docs/METHODS.md, layer 4):
    The street part of each trip is converted from walking speed to the team's speed.
    The off path part (street to site: yards, alleys) is always walked, because a bike or
    motorbike is parked at the street. Vehicles add park_min per stop.
    All modes use the OpenStreetMap walking network, which includes small alleys; for cars
    some alleys may be too narrow, so motorbike is the realistic vehicle in Tallo.

Command line (one puskesmas, from assumptions.csv):
    python engine/plan_day.py --paid 4 --volunteers 4 --motorbikes 2 --budget 1500000
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
import reports as R2  # noqa: E402
import teams as T  # noqa: E402

MODES = {  # key: (label, speed key in assumptions.csv, default km/h)
    "walk": ("Walking", "walk_speed_kmh", 4),
    "bike": ("Bicycle", "bike_speed_kmh", 10),
    "moto": ("Motorbike", "moto_speed_kmh", 15),
    "car": ("Car", "car_speed_kmh", 12),
}
SETTINGS_FILE = C.OUTPUTS / "plan_settings.json"


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


def with_depots(travel, off, depots, net, cfg):
    """Walking table whose first rows are the chosen puskesmas ("P:<name>"), then the sites.

    One shortest path search from each puskesmas over the street network. Without the
    network, distances fall back to straight line × detour_factor.
    """
    import route_paths as R

    walk_m_per_min = cfg.get("walk_speed_kmh", 4) * 1000 / 60
    slow = cfg.get("offpath_slowdown", 1.0)
    site_ids = [i for i in travel.index if i != "START"]
    all_sites = pd.read_csv(C.SCORED_FILE).set_index("site_id")
    access = pd.read_csv(C.ACCESS_FILE).set_index("id") if C.ACCESS_FILE.exists() else None
    ids = [f"P:{d['name']}" for d in depots] + site_ids
    table = pd.DataFrame(0.0, index=ids, columns=ids)
    table.loc[site_ids, site_ids] = travel.loc[site_ids, site_ids].to_numpy()
    new_off = off.reindex(site_ids).fillna(0)

    def utm(lat, lon):
        g = __import__("geopandas")
        p = g.GeoSeries(g.points_from_xy([lon], [lat]), crs=C.WGS).to_crs(C.UTM).iloc[0]
        return np.array([p.x, p.y])

    site_xy = {s: utm(all_sites.at[s, "lat"], all_sites.at[s, "lon"]) for s in site_ids}
    depot_xy = {f"P:{d['name']}": utm(d["lat"], d["lon"]) for d in depots}

    if net is not None:
        site_nodes = {s: R.snap(net, all_sites.at[s, "lat"], all_sites.at[s, "lon"]) for s in site_ids}
        depot_nodes, depot_snap = {}, {}
        for d in depots:
            key = f"P:{d['name']}"
            node = R.snap(net, d["lat"], d["lon"])
            depot_nodes[key] = node
            depot_snap[key] = float(np.hypot(*(net["xy"][net["ids"].index(node)] - depot_xy[key])))
        for key, node in depot_nodes.items():
            lengths = nx.single_source_dijkstra_path_length(net["walk"], node, weight="length")
            for s in site_ids:
                snap_s = float(access.at[s, "meters_to_path"]) if access is not None and s in access.index else 0
                meters = lengths.get(site_nodes[s], np.inf) + slow * (depot_snap[key] + snap_s)
                if not np.isfinite(meters):
                    meters = np.hypot(*(depot_xy[key] - site_xy[s])) * cfg.get("detour_factor", 1.3)
                table.at[key, s] = table.at[s, key] = meters / walk_m_per_min
            for other, other_node in depot_nodes.items():
                if other != key:
                    table.at[key, other] = lengths.get(other_node, 0) / walk_m_per_min
            new_off[key] = depot_snap[key] * slow / walk_m_per_min
    else:
        for key, xy in depot_xy.items():
            for s in site_ids:
                table.at[key, s] = table.at[s, key] = \
                    np.hypot(*(xy - site_xy[s])) * cfg.get("detour_factor", 1.3) / walk_m_per_min
            new_off[key] = 0.0
    return table.round(2), new_off.reindex(ids).fillna(0)


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


def plan_day(puskesmas, seconds, net=None, save=True):
    """Form teams, plan every method, and save everything. Returns (summaries, teams, notes).

    puskesmas: list of {"name", "lat", "lon", "budget_idr", "paid", "volunteers",
                        "motorbikes", "bicycles", "hours", "leave"}
    """
    import route_paths as R

    cfg, sites, travel, _ = P.load_inputs()
    sites, feedback_note = R2.apply_feedback(sites, cfg)   # yesterday's reports, if saved
    teams, notes = T.form_teams(puskesmas, cfg)
    if net is None:
        net = R.load_network()

    walk, off = with_depots(travel, offpath_minutes(travel), puskesmas, net, cfg)
    km = K.street_km_table(walk, off, cfg)

    by_mode, money_by_mode = {}, {}
    for team in teams:
        if team["mode"] not in by_mode:
            by_mode[team["mode"]] = travel_for_mode(walk, cfg, team["mode"], off)
            money_by_mode[team["mode"]] = K.money_table(km, sites, team["mode"], cfg)
    n = len(teams)
    travels = [by_mode[t["mode"]] for t in teams]
    days = [t["hours"] * 60 for t in teams]
    starts = [t["start_id"] for t in teams]
    limited = any(t["budget_idr"] is not None for t in teams)
    costs = [money_by_mode[t["mode"]] for t in teams] if limited else None
    budgets = [t["budget_idr"] if t["budget_idr"] is not None else 1e12 for t in teams] if limited else None

    if n == 0:
        plans = {m: P.to_table([], sites) for m in ["nearest", "priority", "optimized"]}
    else:
        nearest = lambda cur, feas, tr: min(feas, key=lambda s: tr.at[cur, s])  # noqa: E731
        best = lambda cur, feas, tr: max(feas, key=lambda s: (sites.at[s, "priority"], -tr.at[cur, s]))  # noqa: E731
        plans = {
            "nearest": P.greedy_plan(sites, travels, n, days, nearest, starts, costs, budgets),
            "priority": P.greedy_plan(sites, travels, n, days, best, starts, costs, budgets),
            "optimized": O.optimized_plan(sites, travels, n, days, seconds, starts, costs, budgets),
        }

    points = {f"P:{p['name']}": {"name": p["name"], "lat": p["lat"], "lon": p["lon"]} for p in puskesmas}
    summaries = {}
    for method, plan in plans.items():
        summary = P.summarize(method, plan, sites, travels) if n else P.summarize(method, plan, sites, walk)
        table = K.plan_costs(plan, teams, sites, km, cfg)
        summary["total_cost_idr"] = int(table.iloc[-1]["Total (IDR)"])
        summary["cost_per_high_priority_idr"] = K.cost_per_high_priority(table, summary)
        summaries[method] = summary
        if not save:              # scenario runs (scenarios.py) only need the numbers
            continue
        P.save(method, plan, summary)
        table.to_csv(C.OUTPUTS / f"costs_{method}.csv", index=False)
        if net is not None and n:
            with open(C.OUTPUTS / f"paths_{method}.json", "w") as f:
                json.dump(R.paths_for_plan(plan, points, net), f)

    if not save:
        return summaries, teams, notes
    with open(SETTINGS_FILE, "w") as f:
        json.dump({"puskesmas": puskesmas, "teams": teams, "notes": notes,
                   "solver_seconds": seconds, "plan_id": R2.new_plan_id(),
                   "feedback_note": feedback_note}, f, indent=2)
    return summaries, teams, notes


def default_puskesmas(cfg):
    """One puskesmas from start_point.csv with teams like assumptions.csv describes."""
    start = pd.read_csv(C.START_FILE).iloc[0]
    n, size = int(cfg["n_teams"]), int(cfg.get("team_size", 2))
    return [{"name": start["name"], "lat": float(start["lat"]), "lon": float(start["lon"]),
             "budget_idr": 0, "paid": n, "volunteers": n * (size - 1), "motorbikes": 0, "bicycles": 0,
             "hours": float(cfg["hours_per_day"]), "leave": str(cfg.get("day_start", "08:00"))}]


def load_settings(cfg):
    """Inputs and teams of the last Generate click, or defaults from assumptions.csv."""
    settings = {"puskesmas": default_puskesmas(cfg) if C.START_FILE.exists() else [],
                "teams": None, "notes": {}, "solver_seconds": int(cfg.get("solver_seconds", 30)),
                "plan_id": "default"}
    if SETTINGS_FILE.exists():
        saved = json.loads(SETTINGS_FILE.read_text())
        if "puskesmas" in saved:
            settings.update(saved)
    if settings["teams"] is None and settings["puskesmas"]:
        settings["teams"], settings["notes"] = T.form_teams(settings["puskesmas"], cfg)
    return settings


def main():
    cfg = C.load_assumptions()
    p = default_puskesmas(cfg)[0]
    parser = argparse.ArgumentParser(description="Plan one day for one puskesmas")
    parser.add_argument("--paid", type=int, default=p["paid"])
    parser.add_argument("--volunteers", type=int, default=p["volunteers"])
    parser.add_argument("--motorbikes", type=int, default=0)
    parser.add_argument("--bicycles", type=int, default=0)
    parser.add_argument("--budget", type=float, default=0, help="rupiah for the day, 0 = no limit")
    parser.add_argument("--hours", type=float, default=p["hours"])
    parser.add_argument("--seconds", type=int, default=int(cfg.get("solver_seconds", 30)))
    a = parser.parse_args()
    p.update(paid=a.paid, volunteers=a.volunteers, motorbikes=a.motorbikes, bicycles=a.bicycles,
             budget_idr=a.budget, hours=a.hours)
    summaries, teams, notes = plan_day([p], a.seconds)
    print(T.describe(teams, p["name"]), "|", " ".join(notes.get(p["name"], [])))
    for method, s in summaries.items():
        print(f"{method:>9}: {s['sites_visited']} sites, {s['high_priority_visited']}/"
              f"{s['high_priority_total']} high priority, total priority {s['total_priority']}, "
              f"cost {s['total_cost_idr']:,} IDR")


if __name__ == "__main__":
    main()

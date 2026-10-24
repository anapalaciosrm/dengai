"""Plan one day with the organizer's settings. Used by the app's "Create routes" button.

The organizer chooses: number of teams, how teams travel, hours in the field, and start time.
Every method (both baselines and the optimizer) replans with the same settings, so the
comparison stays fair. Results are written to outputs/ like run_pipeline.py does, so the
rest of the app shows them.

Travel mode (docs/METHODS.md, layer 4):
    The street part of each trip is converted from walking speed to the chosen speed.
    The off path part (street to site: yards, alleys) is always walked, because a bike or
    motorbike is parked at the street. Vehicles add park_min per stop for parking.
    All modes use the OpenStreetMap walking network, which includes small alleys; for cars
    some alleys may be too narrow, so motorbike is the realistic vehicle in Tallo.

Run from the command line too:
    python engine/plan_day.py --teams 6 --mode moto --hours 5
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent))
import config as C  # noqa: E402
import optimizer as O  # noqa: E402
import plan_tools as P  # noqa: E402

MODES = {  # key: (label, speed key in assumptions.csv, default km/h)
    "walk": ("Walking", "walk_speed_kmh", 4),
    "bike": ("Bicycle", "bike_speed_kmh", 10),
    "moto": ("Motorbike", "moto_speed_kmh", 15),
    "car": ("Car", "car_speed_kmh", 12),
}
SETTINGS_FILE = C.OUTPUTS / "plan_settings.json"


def travel_for_mode(travel, cfg, mode):
    """Travel minutes table for a travel mode, built from the walking table."""
    if mode == "walk":
        return travel
    walk_speed = cfg.get("walk_speed_kmh", 4)
    speed = cfg.get(MODES[mode][1], MODES[mode][2])
    ratio = walk_speed / speed
    park = cfg.get("park_min", 2)

    off = pd.Series(0.0, index=travel.index)  # walked minutes between street and site
    if C.ACCESS_FILE.exists():
        access = pd.read_csv(C.ACCESS_FILE).set_index("id")
        if "offpath_minutes" in access:
            off = access["offpath_minutes"].reindex(travel.index).fillna(0)

    t = travel.to_numpy()
    o = off.to_numpy()
    both_ends = o[:, None] + o[None, :]
    street = np.clip(t - both_ends, 0, None)          # street minutes at walking speed
    converted = street * ratio + both_ends + park       # ride the street, walk the last bit, park
    np.fill_diagonal(converted, 0)
    return pd.DataFrame(converted.round(2), index=travel.index, columns=travel.columns)


def plan_day(n_teams, mode, hours, day_start, seconds, net=None, start=None):
    """Replan all methods with these settings and save them. Returns the summaries."""
    import route_paths as R

    cfg, sites, travel, _ = P.load_inputs()
    cfg.update({"n_teams": n_teams, "hours_per_day": hours, "travel_mode": mode, "day_start": day_start})
    travel = travel_for_mode(travel, cfg, mode)
    day = hours * 60

    nearest = lambda cur, feas: min(feas, key=lambda s: travel.at[cur, s])  # noqa: E731
    best = lambda cur, feas: max(feas, key=lambda s: (sites.at[s, "priority"], -travel.at[cur, s]))  # noqa: E731
    plans = {
        "nearest": P.greedy_plan(sites, travel, n_teams, day, nearest),
        "priority": P.greedy_plan(sites, travel, n_teams, day, best),
        "optimized": O.optimized_plan(sites, travel, n_teams, day, seconds),
    }

    if start is None:
        start = pd.read_csv(C.START_FILE).iloc[0]
    if net is None:
        net = R.load_network()

    summaries = {}
    for method, plan in plans.items():
        summary = P.summarize(method, plan, sites, travel)
        P.save(method, plan, summary)
        if net is not None:
            with open(C.OUTPUTS / f"paths_{method}.json", "w") as f:
                json.dump(R.paths_for_plan(plan, start, net), f)
        summaries[method] = summary

    settings = {"n_teams": n_teams, "travel_mode": mode, "hours_per_day": hours,
                "day_start": day_start, "solver_seconds": seconds}
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)
    return summaries


def load_settings(cfg):
    """Settings from the last Create routes click, falling back to assumptions.csv."""
    settings = {"n_teams": int(cfg["n_teams"]), "travel_mode": str(cfg.get("travel_mode", "walk")),
                "hours_per_day": float(cfg["hours_per_day"]), "day_start": str(cfg.get("day_start", "08:00")),
                "solver_seconds": int(cfg.get("solver_seconds", 30))}
    if SETTINGS_FILE.exists():
        settings.update(json.loads(SETTINGS_FILE.read_text()))
    return settings


def main():
    cfg = C.load_assumptions()
    s = load_settings(cfg)
    parser = argparse.ArgumentParser(description="Plan one day with chosen settings")
    parser.add_argument("--teams", type=int, default=s["n_teams"])
    parser.add_argument("--mode", choices=MODES, default=s["travel_mode"])
    parser.add_argument("--hours", type=float, default=s["hours_per_day"])
    parser.add_argument("--start", default=s["day_start"])
    parser.add_argument("--seconds", type=int, default=s["solver_seconds"])
    a = parser.parse_args()
    for method, summary in plan_day(a.teams, a.mode, a.hours, a.start, a.seconds).items():
        print(f"{method:>9}: {summary['sites_visited']} sites, "
              f"{summary['high_priority_visited']}/{summary['high_priority_total']} high priority, "
              f"total priority {summary['total_priority']}")


if __name__ == "__main__":
    main()

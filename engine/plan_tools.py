"""Shared helpers for building and measuring plans, used by the baselines and the optimizer.

A plan is a table with one row per visit:
    team_id, visit_order, site_id, lat, lon, arrival_minute, priority
Every team starts and ends at the START point and must be back within the work day.
"""

import json

import pandas as pd

import config as C


def load_inputs():
    """Return (cfg, sites indexed by site_id, travel minutes table, day length in minutes)."""
    cfg = C.load_assumptions()
    sites = pd.read_csv(C.SCORED_FILE).set_index("site_id")
    travel = pd.read_csv(C.MATRIX_FILE, index_col=0)
    day_minutes = cfg["hours_per_day"] * 60
    return cfg, sites, travel, day_minutes


def greedy_plan(sites, travel, n_teams, day_minutes, choose):
    """Build a plan where teams take turns picking their next site with `choose`.

    choose(current_location, feasible_site_ids) returns one site id.
    A site is feasible if the team can walk there, inspect it, and still walk back
    to START before the day ends.
    """
    unvisited = set(sites.index)
    teams = [{"at": "START", "clock": 0.0, "stops": []} for _ in range(n_teams)]
    active = list(range(n_teams))

    while active and unvisited:
        for t in list(active):
            team = teams[t]
            feasible = [
                s for s in unvisited
                if team["clock"] + travel.at[team["at"], s] + sites.at[s, "inspect_min"]
                + travel.at[s, "START"] <= day_minutes
            ]
            if not feasible:
                active.remove(t)
                continue
            nxt = choose(team["at"], feasible)
            arrival = team["clock"] + travel.at[team["at"], nxt]
            team["stops"].append((nxt, arrival))
            team["clock"] = arrival + sites.at[nxt, "inspect_min"]
            team["at"] = nxt
            unvisited.discard(nxt)

    return to_table(teams, sites)


def to_table(teams, sites):
    """Turn team stop lists into the standard plan table."""
    rows = []
    for t, team in enumerate(teams, start=1):
        for order, (site_id, arrival) in enumerate(team["stops"], start=1):
            rows.append({
                "team_id": t,
                "visit_order": order,
                "site_id": site_id,
                "lat": sites.at[site_id, "lat"],
                "lon": sites.at[site_id, "lon"],
                "arrival_minute": round(arrival, 1),
                "priority": sites.at[site_id, "priority"],
            })
    return pd.DataFrame(rows)


def summarize(method, plan, sites, travel):
    """Key numbers for comparing plans. Uses is_real only if present (fake data evaluation)."""
    visited = list(plan["site_id"]) if len(plan) else []
    travel_total = 0.0
    for _, team in plan.groupby("team_id"):
        path = ["START"] + list(team.sort_values("visit_order")["site_id"]) + ["START"]
        travel_total += sum(travel.at[a, b] for a, b in zip(path[:-1], path[1:]))

    summary = {
        "method": method,
        "sites_visited": len(visited),
        "high_priority_visited": int(sites.loc[visited, "high_priority"].sum()) if visited else 0,
        "high_priority_total": int(sites["high_priority"].sum()),
        "total_priority": round(float(sites.loc[visited, "priority"].sum()), 3) if visited else 0.0,
        "expected_real_sites": round(float(sites.loc[visited, "confidence"].sum()), 1) if visited else 0.0,
        "travel_minutes": round(travel_total, 1),
        "inspection_minutes": round(float(sites.loc[visited, "inspect_min"].sum()), 1) if visited else 0.0,
    }
    if "is_real" in sites.columns and visited:
        summary["simulated_real_sites_reached"] = int(sites.loc[visited, "is_real"].sum())
    return summary


def save(method, plan, summary):
    """Write outputs/plan_<method>.csv and outputs/summary_<method>.json."""
    C.OUTPUTS.mkdir(parents=True, exist_ok=True)
    plan.to_csv(C.OUTPUTS / f"plan_{method}.csv", index=False)
    with open(C.OUTPUTS / f"summary_{method}.json", "w") as f:
        json.dump(summary, f, indent=2)

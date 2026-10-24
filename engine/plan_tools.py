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
    sites = routable(sites)
    day_minutes = cfg["hours_per_day"] * 60
    return cfg, sites, travel, day_minutes


def routable(sites):
    """Drop hard to reach sites (see travel_matrix.py). Every method plans on the same set."""
    if not C.ACCESS_FILE.exists():
        return sites
    access = pd.read_csv(C.ACCESS_FILE).set_index("id")
    hard = [s for s in sites.index if s in access.index and bool(access.at[s, "hard_to_reach"])]
    if hard:
        print(f"Leaving {len(hard)} hard to reach site(s) out of walking routes: {', '.join(hard)}")
    return sites.drop(index=hard)


def per_team(value, n_teams):
    """A travel table or day length shared by all teams, or one per team, as a list."""
    return list(value) if isinstance(value, (list, tuple)) else [value] * n_teams


def greedy_plan(sites, travel, n_teams, day_minutes, choose, starts=None, costs=None, budgets=None):
    """Build a plan where teams take turns picking their next site with `choose`.

    travel and day_minutes: one for all teams, or a list with one per team
    (teams can travel differently and work different hours).
    starts: start (and end) node id per team, default "START" (teams can leave from
    different puskesmas). costs and budgets (optional): per team table of the money spent
    moving from one node to the next (fuel, larvicide) and the money the team may spend.
    choose(current_location, feasible_site_ids) or choose(current, feasible, team_travel)
    returns one site id. A site is feasible if the team can get there, inspect it, get back
    before its day ends, and stay within its budget.
    """
    travels, days = per_team(travel, n_teams), per_team(day_minutes, n_teams)
    starts = per_team(starts or "START", n_teams)
    takes_travel = choose.__code__.co_argcount >= 3
    unvisited = set(sites.index)
    teams = [{"at": starts[t], "clock": 0.0, "spent": 0.0, "stops": [], "start": starts[t]}
             for t in range(n_teams)]
    active = list(range(n_teams))

    def affordable(t, team, s):
        if costs is None or budgets is None:
            return True
        cost = costs[t]
        return team["spent"] + cost.at[team["at"], s] + cost.at[s, team["start"]] <= budgets[t]

    while active and unvisited:
        for t in list(active):
            team, tr = teams[t], travels[t]
            feasible = [
                s for s in unvisited
                if team["clock"] + tr.at[team["at"], s] + sites.at[s, "inspect_min"]
                + tr.at[s, team["start"]] <= days[t] and affordable(t, team, s)
            ]
            if not feasible:
                active.remove(t)
                continue
            nxt = choose(team["at"], feasible, tr) if takes_travel else choose(team["at"], feasible)
            arrival = team["clock"] + tr.at[team["at"], nxt]
            if costs is not None:
                team["spent"] += costs[t].at[team["at"], nxt]
            team["stops"].append((nxt, arrival))
            team["clock"] = arrival + sites.at[nxt, "inspect_min"]
            team["at"] = nxt
            unvisited.discard(nxt)

    return to_table(teams, sites)


def to_table(teams, sites):
    """Turn team stop lists into the standard plan table (one row per visit)."""
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
                "start_id": team.get("start", "START"),
            })
    cols = ["team_id", "visit_order", "site_id", "lat", "lon", "arrival_minute", "priority", "start_id"]
    return pd.DataFrame(rows, columns=cols)


def team_route(team):
    """[start, site, site, ..., start] for one team's rows of a plan table."""
    team = team.sort_values("visit_order")
    start = team["start_id"].iloc[0] if "start_id" in team and len(team) else "START"
    return [start] + list(team["site_id"]) + [start]


def summarize(method, plan, sites, travel):
    """Key numbers for comparing plans. Uses is_real only if present (fake data evaluation)."""
    visited = list(plan["site_id"]) if len(plan) else []
    travel_total = 0.0
    for team_id, team in plan.groupby("team_id"):
        tr = travel[int(team_id) - 1] if isinstance(travel, (list, tuple)) else travel
        path = team_route(team)
        travel_total += sum(tr.at[a, b] for a, b in zip(path[:-1], path[1:]))

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

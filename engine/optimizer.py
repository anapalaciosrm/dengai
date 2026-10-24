"""Step 6: optimized daily plan with OR-Tools, as a team orienteering problem.

The problem (Chao, Golden, Wasil 1996):
    Several teams leave the puskesmas, visit sites, and must be back before the day ends.
    There is not enough time to visit every site, so the plan has to CHOOSE which sites
    to visit and in what ORDER, to collect the most total priority.

How we hand it to OR-Tools (guide: "Penalties and Dropping Visits"):
    OR-Tools is built for vehicle routing, which normally visits every stop. We make
    every site optional: skipping a site adds a penalty equal to its priority.
    OR-Tools minimizes   total travel + total penalties of skipped sites.
    The penalties are scaled to be much larger than travel, so the solver's first goal
    is to collect priority; travel only breaks ties between plans of equal priority.

    A "time" dimension tracks each team's clock: walking minutes plus inspection minutes.
    Its upper limit is the work day (hours_per_day), so every route fits in the day.

Search:
    1. A quick first solution (cheapest arc).
    2. Guided local search improves it until the time limit (solver_seconds).
    If the solver finds nothing, we fall back to the nearest site baseline so the
    demo never breaks.

Reads  data/processed/sites_scored.csv, data/processed/travel_minutes.csv
Writes outputs/plan_optimized.csv, outputs/summary_optimized.json

Run: python engine/optimizer.py
"""

import sys
import time
from pathlib import Path

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

sys.path.append(str(Path(__file__).resolve().parent))
import plan_tools as P  # noqa: E402

# OR-Tools only works with whole numbers, so we scale our decimals.
TIME_SCALE = 10         # minutes -> tenths of a minute (keeps 0.1 minute precision)
PRIORITY_SCALE = 100_000  # priority 1.0 -> penalty 100,000, far above any day's travel


MONEY_SCALE = 0.1  # rupiah -> tens of rupiah for the budget dimension


def build_model(sites, travel, n_teams, day_minutes, starts=None, costs=None, budgets=None):
    """Set up the OR-Tools routing model. The first nodes are start points, then the sites.

    travel and day_minutes: one for all teams, or a list with one per team, so teams
    can travel differently (walk, bike, motorbike) and work different hours.
    starts: start (and end) node id per team, default "START" for all (teams can leave
    from different puskesmas). costs and budgets (optional): per team table of money spent
    per move (fuel, larvicide) and the money the team may spend; added as a "Money"
    dimension so no team goes over its budget.
    """
    travels, days = P.per_team(travel, n_teams), P.per_team(day_minutes, n_teams)
    starts = P.per_team(starts or "START", n_teams)
    depots = list(dict.fromkeys(starts))
    ids = depots + list(sites.index)
    n_depots = len(depots)
    inspect_int = [0] * n_depots + [int(round(sites.at[s, "inspect_min"] * TIME_SCALE)) for s in sites.index]

    # The manager translates between our node numbers and OR-Tools' internal indexes.
    depot_of = [depots.index(s) for s in starts]
    manager = pywrapcp.RoutingIndexManager(len(ids), n_teams, depot_of, depot_of)
    routing = pywrapcp.RoutingModel(manager)

    def int_table(table, scale):
        return [[int(round(table.at[a, b] * scale)) for b in ids] for a in ids]

    time_callbacks, money_callbacks = [], []
    cache = {}  # teams with the same tables share callbacks
    for team in range(n_teams):
        tr = travels[team]
        if id(tr) not in cache:
            travel_int = int_table(tr, TIME_SCALE)

            # Cost of each move = travel time. This is the "travel" part of the objective.
            def travel_cost(from_index, to_index, t=travel_int):
                return t[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]

            # Time used by each move = inspect the site you are at, then travel to the next one.
            def time_used(from_index, to_index, t=travel_int):
                a, b = manager.IndexToNode(from_index), manager.IndexToNode(to_index)
                return inspect_int[a] + t[a][b]

            cache[id(tr)] = (routing.RegisterTransitCallback(travel_cost),
                             routing.RegisterTransitCallback(time_used))
        cost_cb, time_cb = cache[id(tr)]
        routing.SetArcCostEvaluatorOfVehicle(cost_cb, team)
        time_callbacks.append(time_cb)

        if costs is not None:
            money = costs[team]
            if ("money", id(money)) not in cache:
                money_int = int_table(money, MONEY_SCALE)

                def money_used(from_index, to_index, m=money_int):
                    return m[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]

                cache[("money", id(money))] = routing.RegisterTransitCallback(money_used)
            money_callbacks.append(cache[("money", id(money))])

    routing.AddDimensionWithVehicleTransitAndCapacity(
        time_callbacks,
        0,                                              # no waiting time allowed
        [int(d * TIME_SCALE) for d in days],            # each team's own day limit
        True,                                           # every team's clock starts at 0
        "Time",
    )
    if costs is not None and budgets is not None:
        routing.AddDimensionWithVehicleTransitAndCapacity(
            money_callbacks, 0, [max(int(b * MONEY_SCALE), 0) for b in budgets], True, "Money")

    # Every site is optional. Skipping it costs its priority (scaled).
    for node, site_id in enumerate(sites.index, start=n_depots):
        penalty = int(round(sites.at[site_id, "priority"] * PRIORITY_SCALE))
        routing.AddDisjunction([manager.NodeToIndex(node)], penalty)

    return manager, routing, ids, n_depots


def solve(manager, routing, seconds):
    """Run the search for up to `seconds`. Returns the solution or None."""
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.seconds = int(seconds)
    return routing.SolveWithParameters(params)


def read_routes(manager, routing, solution, ids, n_teams, n_depots=1, starts=None):
    """Turn the solution into team stop lists: [(site_id, arrival minute), ...] per team."""
    time_dim = routing.GetDimensionOrDie("Time")
    starts = P.per_team(starts or "START", n_teams)
    teams = []
    for team in range(n_teams):
        stops = []
        index = routing.Start(team)
        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            if node >= n_depots:
                arrival = solution.Value(time_dim.CumulVar(index)) / TIME_SCALE
                stops.append((ids[node], arrival))
            index = solution.Value(routing.NextVar(index))
        teams.append({"stops": stops, "start": starts[team]})
    return teams


def optimized_plan(sites, travel, n_teams, day_minutes, seconds, starts=None, costs=None, budgets=None):
    """Build, solve, and return the optimized plan table. Used here, plan_day.py, evaluate.py."""
    manager, routing, ids, n_depots = build_model(sites, travel, n_teams, day_minutes, starts, costs, budgets)
    solution = solve(manager, routing, seconds)
    if solution is None:
        # Never leave the demo without a plan.
        print("Solver found no plan; using the nearest site baseline instead.")
        return P.greedy_plan(sites, travel, n_teams, day_minutes,
                             lambda cur, feas, tr: min(feas, key=lambda s: tr.at[cur, s]),
                             starts, costs, budgets)
    teams = read_routes(manager, routing, solution, ids, n_teams, n_depots, starts)
    return P.to_table(teams, sites)


def main():
    cfg, sites, travel, day_minutes = P.load_inputs()
    n_teams = int(cfg["n_teams"])
    seconds = cfg.get("solver_seconds", 30)

    print(f"Planning {len(sites)} sites for {n_teams} teams, {day_minutes:.0f} min each, "
          f"searching up to {seconds:.0f} s")
    start = time.time()
    plan = optimized_plan(sites, travel, n_teams, day_minutes, seconds)

    summary = P.summarize("optimized", plan, sites, travel)
    summary["solve_seconds"] = round(time.time() - start, 1)
    P.save("optimized", plan, summary)
    print(f"optimized: {summary['sites_visited']} sites, "
          f"{summary['high_priority_visited']}/{summary['high_priority_total']} high priority, "
          f"total priority {summary['total_priority']}, "
          f"travel {summary['travel_minutes']:.0f} min, solved in {summary['solve_seconds']} s")


if __name__ == "__main__":
    main()

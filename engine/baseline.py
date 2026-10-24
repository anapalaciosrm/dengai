"""Step 5: two simple baseline plans to compare our optimizer against.

Baseline 1, nearest: each team always walks to the closest unvisited site
    (greedy nearest neighbor, a classic routing heuristic).
Baseline 2, priority: each team always walks to the highest priority unvisited site,
    ignoring travel time (simple ranking strategy).

Both use the same sites, start point, teams, hours, and walking times as the optimizer,
so the comparison is fair. Teams take turns choosing, so they spread across the area.

Reads  data/processed/sites_scored.csv, data/processed/travel_minutes.csv
Writes outputs/plan_nearest.csv, outputs/plan_priority.csv and matching summary json files

Run: python engine/baseline.py
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))
import plan_tools as P  # noqa: E402


def main():
    cfg, sites, travel, day_minutes = P.load_inputs()
    n_teams = int(cfg["n_teams"])

    def nearest(current, feasible):
        return min(feasible, key=lambda s: travel.at[current, s])

    def highest_priority(current, feasible):
        # Break ties by distance so equal priority sites are not chosen at random.
        return max(feasible, key=lambda s: (sites.at[s, "priority"], -travel.at[current, s]))

    for method, chooser in [("nearest", nearest), ("priority", highest_priority)]:
        plan = P.greedy_plan(sites, travel, n_teams, day_minutes, chooser)
        summary = P.summarize(method, plan, sites, travel)
        P.save(method, plan, summary)
        print(f"{method:>9}: {summary['sites_visited']} sites, "
              f"{summary['high_priority_visited']}/{summary['high_priority_total']} high priority, "
              f"total priority {summary['total_priority']}, "
              f"travel {summary['travel_minutes']:.0f} min")


if __name__ == "__main__":
    main()

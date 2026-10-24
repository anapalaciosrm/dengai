"""Step 8: how good and how robust are the plans?

Part A, robustness (Monte Carlo simulation, docs/METHODS.md layer 5):
    Detections are predictions, not confirmed sites. We treat each site's confidence as
    the chance it is real, draw 1,000 versions of reality, and count how many REAL sites
    each plan reaches, and how much real value (priority without the confidence term).
    Two realities:
        "as predicted"     the confidence values are right
        "detector worse"   every site is 25% less likely to be real than predicted
                           (tests what happens if the detector is overconfident)
    Report the mean, the 5th to 95th percentile range, and how often our plan beats each baseline.

Part B, sensitivity (one assumption changed at a time):
    teams, hours per day, inspection minutes, and the site type weights.
    Every method replans with the changed assumption. If the optimizer still wins,
    our conclusion does not depend on a guessed number.

Reads  data/processed/sites_scored.csv, travel_minutes.csv, outputs/plan_<method>.csv
Writes outputs/robustness.csv, outputs/sensitivity.csv

Run: python engine/evaluate.py          (about 1 minute: the optimizer runs 5 s per case)
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent))
import config as C  # noqa: E402
import optimizer as O  # noqa: E402
import plan_tools as P  # noqa: E402

METHODS = ["nearest", "priority", "optimized"]
SENSITIVITY_SECONDS = 5  # shorter search per case so the whole test runs in about a minute


# ---------- Part A: Monte Carlo ----------

def monte_carlo(sites, plans, runs, seed=42, detector_factor=1.0):
    """Simulate `runs` realities. Returns {method: (real sites array, real value array)}."""
    rng = np.random.default_rng(seed)
    p_real = np.clip(sites["confidence"].to_numpy() * detector_factor, 0, 1)
    real = rng.random((runs, len(sites))) < p_real          # runs × sites, True = real site
    # Value of a site if it is real: priority without the confidence term.
    value = (sites["priority"] / sites["confidence"]).to_numpy()
    position = {s: i for i, s in enumerate(sites.index)}

    results = {}
    for method, plan in plans.items():
        cols = [position[s] for s in plan["site_id"]]
        hit = real[:, cols]
        results[method] = (hit.sum(axis=1), (hit * value[cols]).sum(axis=1))
    return results


def robustness_table(sites, plans, runs):
    """Mean, 5th and 95th percentile per method and reality, plus win rates for the optimizer."""
    rows = []
    for label, factor in [("as predicted", 1.0), ("detector 25% worse", 0.75)]:
        sim = monte_carlo(sites, plans, runs, detector_factor=factor)
        for method, (count, value) in sim.items():
            row = {
                "reality": label,
                "method": method,
                "real_sites_mean": round(count.mean(), 1),
                "real_sites_p5": int(np.percentile(count, 5)),
                "real_sites_p95": int(np.percentile(count, 95)),
                "real_value_mean": round(value.mean(), 1),
                "real_value_p5": round(np.percentile(value, 5), 1),
                "real_value_p95": round(np.percentile(value, 95), 1),
            }
            if method == "optimized":
                for base in ["nearest", "priority"]:
                    if base in sim:
                        row[f"beats_{base}_pct"] = round(100 * (value > sim[base][1]).mean(), 1)
            rows.append(row)
    return pd.DataFrame(rows)


# ---------- Part B: sensitivity ----------

def rescore(sites, cfg):
    """Recompute inspection minutes, priority, and high priority after an assumption changes."""
    s = sites.copy()
    s["type_weight"] = [C.type_weight(cfg, t) for t in s["site_type"]]
    s["inspect_min"] = [C.inspect_minutes(cfg, t) for t in s["site_type"]]
    s["priority"] = (s["type_weight"] * s["confidence"] * s["exposure"]
                     * s["clustering"] * s["urgency"]).round(4)
    s["high_priority"] = s["priority"] >= s["priority"].quantile(cfg["high_priority_quantile"])
    return s


def all_plans(sites, travel, cfg, seconds):
    """Plans from both baselines and the optimizer under the same assumptions."""
    n_teams = int(cfg["n_teams"])
    day = cfg["hours_per_day"] * 60
    nearest = lambda cur, feas: min(feas, key=lambda s: travel.at[cur, s])  # noqa: E731
    best = lambda cur, feas: max(feas, key=lambda s: (sites.at[s, "priority"], -travel.at[cur, s]))  # noqa: E731
    return {
        "nearest": P.greedy_plan(sites, travel, n_teams, day, nearest),
        "priority": P.greedy_plan(sites, travel, n_teams, day, best),
        "optimized": O.optimized_plan(sites, travel, n_teams, day, seconds),
    }


def sensitivity_cases(cfg):
    """(group, label, changed cfg) for each one at a time change."""
    cases = []

    def case(group, label, **changes):
        c = dict(cfg)
        c.update(changes)
        cases.append((group, label, c))

    for n in [2, 6]:
        case("Teams", f"{n} teams", n_teams=n)
    for h in [4, 8]:
        case("Hours per day", f"{h} hours", hours_per_day=h)
    for k in [0.5, 1.5]:
        case("Inspection minutes", f"× {k}",
             **{key: cfg[key] * k for key in cfg if key.startswith("inspect_min_")})
    case("Type weights", "all types equal", **{key: 1.0 for key in cfg if key.startswith("w_")})
    case("Type weights", "only tires matter",
         **{key: (1.0 if key == "w_tire" else 0.1) for key in cfg if key.startswith("w_")})
    return cases


def sensitivity_table(sites, travel, cfg):
    rows = []
    for group, label, c in [("Base", "our assumptions", cfg)] + sensitivity_cases(cfg):
        s = rescore(sites, c)
        plans = all_plans(s, travel, c, SENSITIVITY_SECONDS)
        totals = {m: P.summarize(m, plans[m], s, travel) for m in METHODS}
        best_base = max(totals["nearest"]["total_priority"], totals["priority"]["total_priority"])
        rows.append({
            "assumption": group,
            "case": label,
            "nearest_priority": totals["nearest"]["total_priority"],
            "priority_first_priority": totals["priority"]["total_priority"],
            "optimized_priority": totals["optimized"]["total_priority"],
            "gain_vs_best_baseline_pct": round(100 * (totals["optimized"]["total_priority"] / best_base - 1), 1),
            "optimized_high_priority": f"{totals['optimized']['high_priority_visited']}"
                                       f"/{totals['optimized']['high_priority_total']}",
        })
        print(f"  {group:>18} | {label:<18} gain vs best baseline {rows[-1]['gain_vs_best_baseline_pct']:+.1f}%")
    return pd.DataFrame(rows)


def main():
    cfg, sites, travel, _ = P.load_inputs()
    runs = int(cfg.get("monte_carlo_runs", 1000))

    plans = {m: pd.read_csv(C.OUTPUTS / f"plan_{m}.csv") for m in METHODS
             if (C.OUTPUTS / f"plan_{m}.csv").exists()}
    print(f"Part A: Monte Carlo, {runs} simulated realities")
    robust = robustness_table(sites, plans, runs)
    robust.to_csv(C.OUTPUTS / "robustness.csv", index=False)
    print(robust[["reality", "method", "real_sites_mean", "real_value_mean"]].to_string(index=False))

    print("\nPart B: sensitivity, one assumption at a time")
    sens = sensitivity_table(sites, travel, cfg)
    sens.to_csv(C.OUTPUTS / "sensitivity.csv", index=False)
    wins = (sens["gain_vs_best_baseline_pct"] > 0).sum()
    print(f"\nOptimizer beats both baselines in {wins} of {len(sens)} cases.")


if __name__ == "__main__":
    main()

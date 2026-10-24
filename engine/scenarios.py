"""Step 9: what if? The same city under different resources, to show how the plan adapts.

Each scenario changes the puskesmas inputs (people, vehicles, budget, hours) and replans with
both baselines and the optimizer. Nothing in outputs/ is overwritten except scenarios.csv.
Prices are the placeholders in assumptions.csv until the team sources them.

Run: python engine/scenarios.py      (about 10 seconds per scenario)
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).resolve().parent))
import config as C  # noqa: E402
import plan_day as D  # noqa: E402
import route_paths as R  # noqa: E402
import teams as T  # noqa: E402

SECONDS = 10


def scenarios(base, second):
    """(name, description, puskesmas list). base and second are puskesmas dicts."""
    def p(src, **changes):
        out = dict(src)
        out.update(changes)
        return out

    rate = C.load_assumptions().get("idr_per_usd", 16000)
    return [
        ("Base day", "4 paid + 4 volunteers walking, 6 h", [p(base)]),
        ("Short staffed", "2 paid + 2 volunteers walking", [p(base, paid=2, volunteers=2)]),
        ("Two motorbikes", "Base + 2 motorbikes", [p(base, motorbikes=2)]),
        ("Half day", "Base, 3 h in the field", [p(base, hours=3)]),
        ("Tight budget", "Base + 2 motorbikes, US$ 36 for the day",
         [p(base, motorbikes=2, budget_idr=36 * rate)]),
        ("Two puskesmas", "Base split across two puskesmas, 2 teams each",
         [p(base, paid=2, volunteers=2), p(second, paid=2, volunteers=2)]),
        ("Scale up", "Two puskesmas, 4 teams each, 2 motorbikes each",
         [p(base, motorbikes=2), p(second, motorbikes=2)]),
    ]


def main():
    cfg = C.load_assumptions()
    rate = cfg.get("idr_per_usd", 16000)
    base = D.default_puskesmas(cfg)[0]
    options = D.puskesmas_options()
    other = options[(options["name"] != base["name"]) & options["in_tallo"]].iloc[-1]
    second = dict(base, name=other["name"], lat=float(other["lat"]), lon=float(other["lon"]))
    net = R.load_network()

    rows = []
    for name, desc, pusk in scenarios(base, second):
        s, teams, _ = D.plan_day(pusk, SECONDS, net=net, save=False)
        opt, near, pri = s["optimized"], s["nearest"], s["priority"]
        best_base = max(near["high_priority_visited"], pri["high_priority_visited"])
        rows.append({
            "Scenario": name, "Setup": desc,
            "Teams": "; ".join(T.describe(teams, p["name"]) for p in pusk),
            "Dengai high priority": f"{opt['high_priority_visited']} of {opt['high_priority_total']}",
            "Best baseline": f"{best_base} of {opt['high_priority_total']}",
            "Value gain vs best baseline (%)": round(100 * (opt["total_priority"] /
                                                     max(near["total_priority"], pri["total_priority"]) - 1)),
            "Sites inspected": opt["sites_visited"],
            "Cost (US$)": round(opt["total_cost_idr"] / rate, 2),
            "US$ per high priority site": round(opt["cost_per_high_priority_idr"] / rate, 2)
            if opt.get("cost_per_high_priority_idr") else None,
        })
        print(f"{name:>15}: Dengai {rows[-1]['Dengai high priority']}, best baseline {rows[-1]['Best baseline']}, "
              f"value +{rows[-1]['Value gain vs best baseline (%)']}%, US$ {rows[-1]['Cost (US$)']}")
    table = pd.DataFrame(rows)
    table.to_csv(C.OUTPUTS / "scenarios.csv", index=False)
    print(f"Wrote {C.OUTPUTS / 'scenarios.csv'}")


if __name__ == "__main__":
    main()

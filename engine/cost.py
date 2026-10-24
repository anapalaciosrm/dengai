"""Cost of a daily plan: labor, fuel, and larvicide, per team and in total.

All prices come from config/assumptions.csv (placeholders until Lara sources them):
    team_size              people per team
    wage_idr_per_hour      pay per person per hour in the field
    fuel_idr_per_km_<mode> fuel per km for bike (0), moto, car; walking costs nothing
    larvicide_idr_per_site larvicide used where a site turns out to be real
    idr_per_usd            exchange rate for the USD column

Labor is paid for the scheduled hours. Fuel uses the street distance actually traveled.
Larvicide is counted for the EXPECTED real sites (sum of confidence of visited sites),
since a false detection needs no treatment.
"""

import pandas as pd

FUEL_KEYS = {"walk": None, "bike": None, "moto": "fuel_idr_per_km_moto", "car": "fuel_idr_per_km_car"}


def street_km(route, walk_travel, off, cfg):
    """Street kilometers of a route START -> stops -> START (off path walking excluded)."""
    walk_m_per_min = cfg.get("walk_speed_kmh", 4) * 1000 / 60
    km = 0.0
    for a, b in zip(route[:-1], route[1:]):
        street_min = max(walk_travel.at[a, b] - off.get(a, 0) - off.get(b, 0), 0)
        km += street_min * walk_m_per_min / 1000
    return km


def plan_costs(plan, teams, sites, walk_travel, off, cfg):
    """One row per team plus a total row. teams: list of {mode, hours, ...} in team order."""
    size = cfg.get("team_size", 2)
    wage = cfg.get("wage_idr_per_hour", 20000)
    larvicide = cfg.get("larvicide_idr_per_site", 5000)
    usd = cfg.get("idr_per_usd", 16000)

    rows = []
    for t, team_cfg in enumerate(teams, start=1):
        team = plan[plan["team_id"] == t].sort_values("visit_order") if len(plan) else plan
        route = ["START"] + list(team["site_id"]) + ["START"] if len(team) else ["START", "START"]
        km = street_km(route, walk_travel, off, cfg)
        fuel_key = FUEL_KEYS.get(team_cfg["mode"])
        fuel = km * cfg.get(fuel_key, 0) if fuel_key else 0.0
        labor = size * team_cfg["hours"] * wage
        expected_real = float(sites.loc[list(team["site_id"]), "confidence"].sum()) if len(team) else 0.0
        chem = expected_real * larvicide
        rows.append({"Team": f"Team {t}", "Travel": team_cfg["mode"], "Sites": int(len(team)),
                     "Km": round(km, 1), "Labor (IDR)": labor, "Fuel (IDR)": fuel,
                     "Larvicide (IDR)": chem, "Total (IDR)": labor + fuel + chem})
    table = pd.DataFrame(rows)
    total = table[["Sites", "Km", "Labor (IDR)", "Fuel (IDR)", "Larvicide (IDR)", "Total (IDR)"]].sum()
    table = pd.concat([table, pd.DataFrame([{"Team": "Total", "Travel": "", **total.to_dict()}])],
                      ignore_index=True)
    table["Sites"] = table["Sites"].astype(int)
    table["Km"] = table["Km"].round(1)
    table["Total (USD)"] = (table["Total (IDR)"] / usd).round(2)
    for col in ["Labor (IDR)", "Fuel (IDR)", "Larvicide (IDR)", "Total (IDR)"]:
        table[col] = table[col].round(-2).astype(int)
    return table


def cost_per_high_priority(table, summary):
    """Total cost divided by high priority sites reached (IDR), or None."""
    reached = summary.get("high_priority_visited", 0)
    return round(float(table.iloc[-1]["Total (IDR)"]) / reached) if reached else None

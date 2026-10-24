"""Cost of a daily plan: labor, fuel, and larvicide, per team and in total.

All prices come from config/assumptions.csv, with their sources:
    wage_idr_per_hour             pay per paid worker per hour in the field
    volunteer_stipend_idr_per_day transport or meal allowance per volunteer (0 if none)
    fuel_idr_per_km_moto / _car   fuel per km; walking and bicycles cost nothing
    larvicide_idr_per_site        larvicide used where a site turns out to be real
    idr_per_usd                   exchange rate for the USD column

Labor is paid for the scheduled hours. Fuel uses the street distance actually traveled.
Larvicide is counted for the EXPECTED real sites (sum of confidence of visited sites),
since a false detection needs no treatment.
"""

import numpy as np
import pandas as pd

import plan_tools as P

FUEL_KEYS = {"walk": None, "bike": None, "moto": "fuel_idr_per_km_moto", "car": "fuel_idr_per_km_car"}


def street_km_table(walk_travel, off, cfg):
    """Street kilometers between every pair of nodes (off path walking excluded)."""
    walk_m_per_min = cfg.get("walk_speed_kmh", 4) * 1000 / 60
    o = pd.Series(off).reindex(walk_travel.index).fillna(0).to_numpy()
    street_min = np.clip(walk_travel.to_numpy() - (o[:, None] + o[None, :]), 0, None)
    return pd.DataFrame(street_min * walk_m_per_min / 1000, index=walk_travel.index,
                        columns=walk_travel.columns)


def money_table(km, sites, mode, cfg):
    """Rupiah spent moving from a node to the next: fuel for the trip + larvicide at the site
    you arrive at (expected: price × confidence). Used as the optimizer's budget dimension."""
    fuel_key = FUEL_KEYS.get(mode)
    fuel = km.to_numpy() * (cfg.get(fuel_key, 0) if fuel_key else 0)
    larvicide = cfg.get("larvicide_idr_per_site", 0)
    arrive = np.array([larvicide * sites.at[c, "confidence"] if c in sites.index else 0.0
                       for c in km.columns])
    money = fuel + arrive[None, :]
    np.fill_diagonal(money, 0)
    return pd.DataFrame(money, index=km.index, columns=km.columns)


def plan_costs(plan, teams, sites, km, cfg):
    """One row per team plus a total row. teams: list of team dicts (teams.form_teams)."""
    wage = cfg.get("wage_idr_per_hour", 20000)
    larvicide = cfg.get("larvicide_idr_per_site", 5000)
    usd = cfg.get("idr_per_usd", 16000)
    size = cfg.get("team_size", 2)

    rows = []
    for t, team_cfg in enumerate(teams, start=1):
        team = plan[plan["team_id"] == t] if len(plan) else plan
        route = P.team_route(team) if len(team) else [team_cfg.get("start_id", "START")] * 2
        trip_km = sum(km.at[a, b] for a, b in zip(route[:-1], route[1:]))
        fuel_key = FUEL_KEYS.get(team_cfg["mode"])
        fuel = trip_km * cfg.get(fuel_key, 0) if fuel_key else 0.0
        labor = team_cfg.get("labor_idr", size * team_cfg["hours"] * wage)
        expected_real = float(sites.loc[list(team["site_id"]), "confidence"].sum()) if len(team) else 0.0
        chem = expected_real * larvicide
        rows.append({"Team": f"Team {t}", "Puskesmas": team_cfg.get("puskesmas", ""),
                     "Travel": team_cfg["mode"], "Sites": int(len(team)), "Km": round(trip_km, 1),
                     "Labor (IDR)": labor, "Fuel (IDR)": fuel, "Larvicide (IDR)": chem,
                     "Total (IDR)": labor + fuel + chem})
    table = pd.DataFrame(rows)
    money = ["Labor (IDR)", "Fuel (IDR)", "Larvicide (IDR)", "Total (IDR)"]
    total = table[["Sites", "Km"] + money].sum()
    table = pd.concat([table, pd.DataFrame([{"Team": "Total", "Puskesmas": "", "Travel": "",
                                             **total.to_dict()}])], ignore_index=True)
    table["Sites"] = table["Sites"].astype(int)
    table["Km"] = table["Km"].round(1)
    table["Total (USD)"] = (table["Total (IDR)"] / usd).round(2)
    for col in money:
        table[col] = table[col].round(-2).astype(int)
    return table


def cost_per_high_priority(table, summary):
    """Total cost divided by high priority sites reached (IDR), or None."""
    reached = summary.get("high_priority_visited", 0)
    return round(float(table.iloc[-1]["Total (IDR)"]) / reached) if reached else None

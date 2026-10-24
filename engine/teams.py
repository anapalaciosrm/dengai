"""Turn each puskesmas's people, vehicles, and budget into field teams.

The coordinator enters, for every puskesmas taking part today:
    budget_idr   money for the day (0 = no limit)
    paid         paid workers available
    volunteers   volunteers available (for example jumantik larva monitors)
    motorbikes, bicycles
    hours, leave time in the field

Rules (all settings in config/assumptions.csv):
    * Teams have team_size people. If team_needs_paid_lead is 1, every team has one paid
      worker who leads it; the other places go to volunteers first (they cost less), then paid.
    * Faster vehicles go to teams first: a motorbike carries 2 people, so a team of
      team_size needs ceil(team_size / 2) motorbikes; a bicycle team needs one bicycle each.
      Teams without a vehicle walk.
    * Labor = paid members × hours × wage_idr_per_hour + volunteers × volunteer_stipend_idr_per_day.
    * Budget: if labor alone is over the budget, the slowest teams stay home until it fits.
      What is left after labor is split evenly between the teams as their budget for fuel and
      larvicide. The optimizer and the baselines will not plan visits beyond it.
"""

import math


def form_teams(puskesmas, cfg):
    """Return (teams, notes). teams: one dict per team, in order; notes: messages per puskesmas."""
    size = int(cfg.get("team_size", 2))
    needs_lead = bool(cfg.get("team_needs_paid_lead", 1))
    wage = cfg.get("wage_idr_per_hour", 20000)
    stipend = cfg.get("volunteer_stipend_idr_per_day", 0)
    motos_per_team = math.ceil(size / 2)

    teams, notes = [], {}
    for p in puskesmas:
        name, msgs = p["name"], []
        paid, vol = int(p.get("paid", 0)), int(p.get("volunteers", 0))
        n = (paid + vol) // size
        if needs_lead:
            n = min(n, paid)
        if n == 0:
            msgs.append("No team possible: needs at least "
                        + (f"1 paid worker and {size} people." if needs_lead else f"{size} people."))
            notes[name] = msgs
            continue

        # Members: one paid lead each (if required), then volunteers, then paid.
        members = [{"paid": 1 if needs_lead else 0, "volunteers": 0} for _ in range(n)]
        free_paid, free_vol = paid - (n if needs_lead else 0), vol
        for team in members:
            while team["paid"] + team["volunteers"] < size:
                if free_vol:
                    team["volunteers"] += 1
                    free_vol -= 1
                else:
                    team["paid"] += 1
                    free_paid -= 1
        if free_paid + free_vol:
            msgs.append(f"{free_paid + free_vol} person(s) not in a team (teams of {size}).")

        # Vehicles: motorbikes first, then bicycles, the rest walk.
        moto = min(n, int(p.get("motorbikes", 0)) // motos_per_team)
        bike = min(n - moto, int(p.get("bicycles", 0)) // size)
        modes = ["moto"] * moto + ["bike"] * bike + ["walk"] * (n - moto - bike)

        hours = float(p.get("hours", 6))
        group = []
        for mode, m in zip(modes, members):
            labor = m["paid"] * hours * wage + m["volunteers"] * stipend
            group.append({"puskesmas": name, "start_id": f"P:{name}", "mode": mode, "hours": hours,
                          "leave": p.get("leave", "08:00"), "paid": m["paid"],
                          "volunteers": m["volunteers"], "labor_idr": labor})

        # Budget: keep the fastest teams that the budget can pay for.
        budget = float(p.get("budget_idr", 0) or 0)
        if budget > 0:
            while group and sum(t["labor_idr"] for t in group) > budget:
                group.pop()  # slowest team stays home
            if len(group) < n:
                msgs.append(f"Budget pays for {len(group)} of {n} possible teams.")
            left = budget - sum(t["labor_idr"] for t in group)
            for t in group:
                t["budget_idr"] = left / len(group) if group else 0
            if group:
                amount = f"{left:,.0f}".replace(",", ".")
                msgs.append(f"After labor, Rp {amount} is left for fuel and larvicide.")
        else:
            for t in group:
                t["budget_idr"] = None
        teams += group
        notes[name] = msgs

    for i, t in enumerate(teams, start=1):
        t["team_id"] = i
    return teams, notes


def describe(teams, name):
    """'3 teams: 2 by motorbike, 1 walking' for one puskesmas."""
    group = [t for t in teams if t["puskesmas"] == name]
    if not group:
        return "No teams"
    labels = {"moto": "by motorbike", "bike": "by bicycle", "walk": "walking", "car": "by car"}
    counts = {}
    for t in group:
        counts[t["mode"]] = counts.get(t["mode"], 0) + 1
    parts = [f"{c} {labels.get(m, m)}" for m, c in counts.items()]
    return f"{len(group)} team{'s' if len(group) > 1 else ''}: " + ", ".join(parts)

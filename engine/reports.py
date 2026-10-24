"""End of day reports from the field teams.

Each team gets a link (by WhatsApp) to a small mobile page in the Dengai app. The leader marks
every stop of the day's route and writes a short summary. Reports are saved per plan in
outputs/reports/<plan_id>/team_<n>.json and shown in the app's "Finish the day" tab, which turns
them into a daily report and carries missed sites over to the next day's plan.

The link carries a short key so only the team that received it can open its form.
Phones must be able to reach the app's address: the "Network URL" Streamlit prints works for
phones on the same Wi-Fi; for teams anywhere, the app has to be deployed (for example on
Streamlit Community Cloud) or exposed with a tunnel.
"""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

import config as C

REPORT_DIR = C.OUTPUTS / "reports"

# What can happen at a stop. The first word is the code saved in the report.
STATUSES = {
    "breeding": "Inspected: breeding found (larvae or pupae)",
    "clear": "Inspected: no breeding",
    "false": "Not a breeding site (wrong detection)",
    "cleared": "Already cleared by residents",
    "no_access": "Could not get in",
    "not_reached": "Did not get there",
}


def new_plan_id():
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def key(plan_id, team_id):
    """Short key so a link only opens its own team's form."""
    return hashlib.sha256(f"dengai|{plan_id}|{team_id}".encode()).hexdigest()[:10]


def link(base_url, plan_id, team_id):
    """Address of a team's report form, e.g. http://10.0.0.5:8501/?report=2&plan=...&k=..."""
    query = urlencode({"report": team_id, "plan": plan_id, "k": key(plan_id, team_id)})
    return f"{base_url.rstrip('/')}/?{query}"


def path(plan_id, team_id):
    return REPORT_DIR / str(plan_id) / f"team_{team_id}.json"


# Field form (designed by Lara). Per stop and end of day answers; codes are what is saved.
ACCESS = {"yes": "Yes", "not_there": "Not there", "no_access": "No access", "skipped": "Skipped"}
REAL_TYPES = {"tire": "Tire", "drain": "Drain", "trash": "Trash", "pot": "Pot", "other": "Other"}
ACTIONS = {"larvicide": "Larvicide", "emptied": "Emptied", "removed": "Removed",
           "needs_pickup": "Needs pickup", "none": "None"}


def status_from_detail(d):
    """One status code per stop (used by totals, the daily report, and tomorrow's plan)."""
    access = d.get("access")
    if access == "skipped":
        return "not_reached"
    if access == "no_access":
        return "no_access"
    if access == "not_there":
        return "false"
    return "breeding" if d.get("larvae") == "yes" else "clear"


def photo_path(plan_id, team_id, site_id, suffix=".jpg"):
    p = REPORT_DIR / str(plan_id) / "photos" / f"team{team_id}_{site_id}{suffix}"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def save(plan_id, team_id, stops, summary, leader="", details=None, day=None):
    """stops: {site_id: status code}; details: {site_id: answers}; day: end of day answers.
    Overwrites an earlier report from the same team."""
    p = path(plan_id, team_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    record = {"plan_id": plan_id, "team_id": int(team_id), "leader": leader, "stops": stops,
              "details": details or {}, "day": day or {},
              "summary": summary, "submitted": datetime.now().isoformat(timespec="minutes")}
    p.write_text(json.dumps(record, indent=2, ensure_ascii=False))
    return record


def load(plan_id, team_id):
    p = path(plan_id, team_id)
    return json.loads(p.read_text()) if p.exists() else None


def load_all(plan_id):
    """{team_id: report} for every team that has reported on this plan."""
    folder = REPORT_DIR / str(plan_id)
    if not folder.exists():
        return {}
    out = {}
    for f in sorted(folder.glob("team_*.json")):
        r = json.loads(f.read_text())
        out[int(r["team_id"])] = r
    return out


def tally(reports):
    """Count of each status across all reports."""
    counts = {code: 0 for code in STATUSES}
    for r in reports.values():
        for status in r["stops"].values():
            counts[status] = counts.get(status, 0) + 1
    return counts


# ---------- daily report and feedback into tomorrow's plan ----------

DONE = {"breeding", "clear", "false", "cleared"}       # inspected: no need to go back tomorrow
MISSED = {"no_access", "not_reached"}                  # carry over to tomorrow
FEEDBACK_FILE = C.OUTPUTS / "tomorrow.json"


def daily_report(plan, received, sites, teams, labels):
    """Numbers, missed places, detector accuracy by type, and a text version of the day.

    plan: today's optimized plan table; received: {team_id: report}; sites: indexed by site_id;
    teams: team dicts; labels: {status code: short label}.
    """
    import pandas as pd

    rows = []
    for t in teams:
        r = received.get(t["team_id"])
        team = plan[plan["team_id"] == t["team_id"]].sort_values("visit_order")
        for n, site in enumerate(team["site_id"], start=1):
            status = r["stops"].get(site) if r else None
            rows.append({"team_id": t["team_id"], "puskesmas": t["puskesmas"], "stop": n, "site_id": site,
                         "site_type": sites.at[site, "site_type"] if site in sites.index else "",
                         "priority": sites.at[site, "priority"] if site in sites.index else None,
                         "lat": sites.at[site, "lat"] if site in sites.index else None,
                         "lon": sites.at[site, "lon"] if site in sites.index else None,
                         "status": status})
    stops = pd.DataFrame(rows)
    reported = stops[stops["status"].notna()] if len(stops) else stops
    missed = reported[reported["status"].isin(MISSED)].copy() if len(reported) else reported
    if len(missed):
        missed["reason"] = missed["status"].map(labels)
        missed = missed.sort_values("priority", ascending=False)

    inspected = reported[reported["status"].isin(DONE)] if len(reported) else reported
    accuracy = []
    for kind, g in inspected.groupby("site_type") if len(inspected) else []:
        wrong = int((g["status"] == "false").sum())
        accuracy.append({"Site type": kind, "Inspected": len(g), "Wrong detections": wrong,
                         "Real": len(g) - wrong, "Share real": f"{(len(g) - wrong) / len(g):.0%}",
                         "Breeding found": int((g["status"] == "breeding").sum())})
    accuracy = pd.DataFrame(accuracy)

    # Field details (Lara's form): real types, minutes on site, larvicide, pickups, containers.
    details = []
    for tid, r in received.items():
        for site, d in (r.get("details") or {}).items():
            detected = sites.at[site, "site_type"] if site in sites.index else ""
            details.append({"team_id": tid, "site_id": site, "detected": detected, **d})
    details = pd.DataFrame(details)
    field = {"larvicide_g": 0.0, "containers": 0, "pickups": pd.DataFrame(), "minutes": pd.DataFrame(),
             "type_check": pd.DataFrame(), "photos": 0}
    if len(details):
        seen = details[details.get("access") == "yes"] if "access" in details else details.iloc[0:0]
        field["larvicide_g"] = float(pd.to_numeric(seen.get("larvicide_g", 0), errors="coerce").fillna(0).sum())
        field["containers"] = int(pd.to_numeric(seen.get("containers", 0), errors="coerce").fillna(0).sum())
        field["photos"] = int(seen.get("photo", pd.Series(dtype=object)).notna().sum()) if "photo" in seen else 0
        if "action" in seen:
            field["pickups"] = seen[seen["action"] == "needs_pickup"][["site_id", "detected", "team_id"]]
        if "minutes" in seen and len(seen):
            mins = seen.assign(minutes=pd.to_numeric(seen["minutes"], errors="coerce")).dropna(subset=["minutes"])
            if len(mins):
                field["minutes"] = (mins.groupby("detected")["minutes"].agg(["count", "mean"]).round(1)
                                    .reset_index().rename(columns={"detected": "Site type", "count": "Stops",
                                                                   "mean": "Average minutes"}))
        if "real_type" in seen and len(seen):
            check = seen.dropna(subset=["real_type"])
            check = check.assign(match=check["real_type"].replace({"pot": "container"}) == check["detected"])
            field["type_check"] = (check.groupby("detected")["match"].agg(["count", "sum"]).reset_index()
                                   .rename(columns={"detected": "Detected as", "count": "Checked",
                                                    "sum": "Same type on site"}))

    numbers = {
        "teams_reported": len(received), "teams_total": len(teams),
        "planned": len(stops), "reported": len(reported), "inspected": len(inspected),
        "breeding": int((reported["status"] == "breeding").sum()) if len(reported) else 0,
        "wrong": int((reported["status"] == "false").sum()) if len(reported) else 0,
        "cleared": int((reported["status"] == "cleared").sum()) if len(reported) else 0,
        "missed": len(missed),
    }

    text = [f"Dengai daily report, {datetime.now():%d %B %Y}", "",
            f"Teams reported: {numbers['teams_reported']} of {numbers['teams_total']}",
            f"Sites inspected: {numbers['inspected']} of {numbers['planned']} planned",
            f"Breeding found: {numbers['breeding']}",
            f"Already cleared by residents: {numbers['cleared']}",
            f"Wrong detections: {numbers['wrong']}",
            f"Missed (carry over): {numbers['missed']}", ""]
    if len(accuracy):
        text.append("Detector accuracy by site type:")
        for a in accuracy.to_dict("records"):
            text.append(f"  {a['Site type']}: {a['Real']} of {a['Inspected']} real ({a['Share real']})")
        text.append("")
    if field["larvicide_g"] or field["containers"]:
        text.append(f"Containers with larvae: {field['containers']}; larvicide used: {field['larvicide_g']:g} g")
    if len(field["minutes"]):
        text.append("Average minutes on site: " + ", ".join(
            f"{r['Site type']} {r['Average minutes']:g}" for r in field["minutes"].to_dict("records")))
    if len(field["pickups"]):
        text.append("Needs pickup (tell the city): " + ", ".join(
            f"{r['site_id']} ({r['detected']}, team {r['team_id']})" for r in field["pickups"].to_dict("records")))
    if len(field["minutes"]) or len(field["pickups"]) or field["containers"]:
        text.append("")
    if len(missed):
        text.append("Missed places:")
        for m in missed.to_dict("records"):
            text.append(f"  {m['site_id']} ({m['site_type']}), team {m['team_id']}: {m['reason']}")
        text.append("")
    for tid, r in sorted(received.items()):
        day = r.get("day") or {}
        if day.get("start") and day.get("end"):
            text.append(f"Team {tid} worked {day['start']} to {day['end']}"
                        + (f", {day['larvicide_left_g']:g} g larvicide left" if day.get("larvicide_left_g") is not None else ""))
    notes = [(tid, r["summary"], r.get("leader", "")) for tid, r in sorted(received.items()) if r.get("summary")]
    if notes:
        text.append("What the teams said:")
        for tid, summary, leader in notes:
            text.append(f"  Team {tid}{' (' + leader + ')' if leader else ''}: {summary}")
    return {"numbers": numbers, "stops": stops, "missed": missed, "accuracy": accuracy,
            "field": field, "text": "\n".join(text)}


def save_feedback(plan_id, done_sites, missed_sites):
    """Tell tomorrow's plan which sites were inspected (skip) and which were missed (go first)."""
    FEEDBACK_FILE.write_text(json.dumps({"from_plan": plan_id, "done": sorted(done_sites),
                                         "missed": sorted(missed_sites),
                                         "saved": datetime.now().isoformat(timespec="minutes")}, indent=2))


def load_feedback():
    return json.loads(FEEDBACK_FILE.read_text()) if FEEDBACK_FILE.exists() else None


def apply_feedback(sites, cfg):
    """Drop sites inspected on the last reported day; raise the priority of missed ones.
    Returns (sites, note) and changes nothing if no feedback was saved."""
    fb = load_feedback()
    if not fb:
        return sites, ""
    boost = cfg.get("carryover_boost", 1.5)
    done = [s for s in fb["done"] if s in sites.index]
    missed = [s for s in fb["missed"] if s in sites.index]
    sites = sites.drop(index=done).copy()
    sites.loc[missed, "priority"] = sites.loc[missed, "priority"] * boost
    note = (f"From the last reports: {len(done)} inspected site(s) skipped, "
            f"{len(missed)} missed site(s) moved up (priority × {boost:g}).")
    return sites, note

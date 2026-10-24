"""End of day reports from the field teams.

Each team gets a link (by WhatsApp) to a small mobile page in the Dengai app. The leader marks
every stop of the day's route and writes a short summary. Reports are saved per plan in
outputs/reports/<plan_id>/team_<n>.json and shown in the app's "Finish the day" tab, where the
AI agent can turn them into a daily report and suggested changes.

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


def save(plan_id, team_id, stops, summary, leader=""):
    """stops: {site_id: status code}. Overwrites an earlier report from the same team."""
    p = path(plan_id, team_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    record = {"plan_id": plan_id, "team_id": int(team_id), "leader": leader, "stops": stops,
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

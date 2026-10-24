"""Dengai dashboard. Run with: streamlit run app.py (after python run_pipeline.py once)

Tabs:
    Today's plan            the coordinator: choose puskesmas and teams, generate routes, see cost,
                            send each team its route on WhatsApp
    Weights and comparisons how sites are prioritized, Dengai vs simpler strategies, robustness
    Finish the day          teams report what happened (the AI agent works from this)
"""

import json
import sys
from datetime import date, datetime
from urllib.parse import urlparse
from pathlib import Path

import folium
import geopandas as gpd
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

sys.path.append(str(Path(__file__).resolve().parent / "engine"))
import config as C  # noqa: E402
import navigation as N  # noqa: E402
import plan_day as D  # noqa: E402
import route_paths as R  # noqa: E402
import reports as RP  # noqa: E402
import teams as T  # noqa: E402

AREA_FILE = Path("data/raw/tallo_area.gpkg")
SITES_FILE = Path("data/processed/sites_scored.csv")
RAW_SITES_FILE = Path("data/processed/sites.csv")
START_FILE = Path("data/processed/start_point.csv")
OUTPUTS = Path("outputs")
CONTACTS_FILE = OUTPUTS / "team_contacts.json"   # local only (outputs/ is not on GitHub)
DEBRIEF_DIR = OUTPUTS / "debriefs"

TYPE_COLORS = {"tire": "#d7301f", "container": "#fc8d59", "drain": "#4575b4", "trash": "#7b3294"}
PRIORITY_COLORS = [("High priority", "#b2182b"), ("Medium", "#ef8a62"), ("Low", "#fddbc7")]
TEAM_COLORS = ["#1b9e77", "#d95f02", "#7570b3", "#e7298a", "#66a61e", "#e6ab02", "#a6761d", "#666666",
               "#1f78b4", "#b15928", "#6a3d9a", "#33a02c"]
METHOD_LABELS = {
    "nearest": "Baseline 1: nearest site next",
    "priority": "Baseline 2: highest priority next",
    "optimized": "Dengai optimizer",
}

st.set_page_config(page_title="Dengai", page_icon="🦟", layout="wide")


# ---------- loading helpers ----------

@st.cache_data
def load_layer(layer):
    """Read one layer of the study area file, or None if it is missing."""
    if not AREA_FILE.exists():
        return None
    try:
        return gpd.read_file(AREA_FILE, layer=layer)
    except Exception:
        return None


@st.cache_data
def load_csv(path):
    """Read a csv, or None if it does not exist yet."""
    return pd.read_csv(path) if Path(path).exists() else None


@st.cache_data
def load_json(path):
    return json.loads(Path(path).read_text()) if Path(path).exists() else None


@st.cache_data
def puskesmas():
    return D.puskesmas_options()


@st.cache_resource
def street_network():
    """Load the street network once per app session (a few seconds)."""
    return R.load_network()


def load_contacts():
    try:
        return json.loads(CONTACTS_FILE.read_text())
    except Exception:
        return {}


def save_contacts(contacts):
    OUTPUTS.mkdir(exist_ok=True)
    CONTACTS_FILE.write_text(json.dumps(contacts, indent=2))


def usd(idr_amount):
    """Rupiah (the engine's unit) shown as US dollars, using idr_per_usd from assumptions.csv."""
    dollars = float(idr_amount) / RATE
    return f"US$ {dollars:,.2f}" if abs(dollars) < 100 else f"US$ {dollars:,.0f}"


def mode_label(key):
    return D.MODES.get(key, (key,))[0]


# ---------- data ----------

sites = load_csv(SITES_FILE)
if sites is None:
    sites = load_csv(RAW_SITES_FILE)
if sites is None:
    st.warning("No sites yet. Run: python engine/make_fake_sites.py, then python run_pipeline.py")
    st.stop()

cfg = C.load_assumptions()
RATE = float(cfg.get("idr_per_usd", 16000))
boundary = load_layer("boundary")
health = load_layer("health_centers")
default_start = load_csv(START_FILE)
pusk = puskesmas()
saved = D.load_settings(cfg)                    # inputs and teams of the plan in outputs/
plan_ready = all((OUTPUTS / f"plan_{m}.csv").exists() for m in METHOD_LABELS) and bool(saved["teams"])
can_plan = SITES_FILE.exists() and C.MATRIX_FILE.exists()
points = {p["name"]: p for p in pusk.to_dict("records")}


def team_start(team):
    """(name, lat, lon) of the puskesmas a team leaves from."""
    p = points.get(team["puskesmas"]) or next(x for x in saved["puskesmas"] if x["name"] == team["puskesmas"])
    return p["name"], float(p["lat"]), float(p["lon"])


# ---------- puskesmas inputs kept between reruns ----------

ss = st.session_state
FIELDS = {  # key: (label, default, step)
    "budget_usd": ("Budget today (US$, 0 = no limit)", 0, 10),
    "paid": ("Paid workers", 2, 1),
    "volunteers": ("Volunteers", 2, 1),
    "motorbikes": ("Motorbikes", 0, 1),
    "bicycles": ("Bicycles", 0, 1),
}
if "pusk_selected" not in ss:
    ss.pusk_selected = [p["name"] for p in saved["puskesmas"] if p["name"] in points] or [pusk["name"].iloc[0]]
    for p in saved["puskesmas"]:
        p = dict(p, budget_usd=p.get("budget_usd", round(float(p.get("budget_idr", 0) or 0) / RATE)))
        for f in FIELDS:
            ss[f"{p['name']}|{f}"] = int(p.get(f, FIELDS[f][1]))
        ss[f"{p['name']}|hours"] = float(p.get("hours", 6))
        ss[f"{p['name']}|leave"] = datetime.strptime(p.get("leave", "08:00"), "%H:%M").time()
if "pending_add" in ss:                 # a puskesmas clicked on the map last run
    name = ss.pop("pending_add")
    if name not in ss.pusk_selected:
        ss.pusk_selected = ss.pusk_selected + [name]


def current_puskesmas():
    """The coordinator's inputs right now, one dict per selected puskesmas."""
    out = []
    for name in ss.pusk_selected:
        p = points[name]
        item = {"name": name, "lat": float(p["lat"]), "lon": float(p["lon"])}
        for f, (_, default, _) in FIELDS.items():
            item[f] = int(ss.get(f"{name}|{f}", default))
        item["budget_idr"] = item["budget_usd"] * RATE      # the engine works in rupiah
        item["hours"] = float(ss.get(f"{name}|hours", 6.0))
        leave = ss.get(f"{name}|leave")
        item["leave"] = leave.strftime("%H:%M") if leave is not None else "08:00"
        out.append(item)
    return out


# ---------- map ----------

def build_map(method=None, show_routes=True, starts=(), color_by="priority"):
    """Folium map: sites as dots, optional routes of one plan, puskesmas, and the start."""
    m = folium.Map(location=[sites["lat"].mean(), sites["lon"].mean()], zoom_start=15,
                   tiles="OpenStreetMap")
    m.fit_bounds([[sites["lat"].min(), sites["lon"].min()], [sites["lat"].max(), sites["lon"].max()]],
                 padding=(20, 20))
    if boundary is not None:
        folium.GeoJson(boundary, name="Tallo boundary",
                       style_function=lambda _: {"color": "#333", "weight": 2, "fill": False}).add_to(m)

    visited = set()
    if method and show_routes and plan_ready:
        plan = load_csv(OUTPUTS / f"plan_{method}.csv")
        visited = set(plan["site_id"])
        street_paths = load_json(OUTPUTS / f"paths_{method}.json") or {}
        for team_id, team in plan.groupby("team_id"):
            team = team.sort_values("visit_order")
            path = street_paths.get(str(int(team_id)))
            if not path and int(team_id) <= len(saved["teams"]):
                _, lat, lon = team_start(saved["teams"][int(team_id) - 1])
                path = [[lat, lon]] + team[["lat", "lon"]].values.tolist() + [[lat, lon]]
            folium.PolyLine(path, color=TEAM_COLORS[(team_id - 1) % len(TEAM_COLORS)], weight=4,
                            opacity=0.85, tooltip=f"Team {team_id}: {len(team)} sites").add_to(m)

    top = sites["priority"].max() if "priority" in sites else 1
    for _, row in sites.iterrows():
        if color_by == "priority" and "priority" in row:
            level = row["priority"] / top
            color = PRIORITY_COLORS[0][1] if level > 0.66 else PRIORITY_COLORS[1][1] if level > 0.33 \
                else PRIORITY_COLORS[2][1]
        else:
            color = TYPE_COLORS.get(row["site_type"], "#555")
        is_visited = row["site_id"] in visited
        tip = f"{row['site_id']}: {row['site_type']}, confidence {row['confidence']:.2f}"
        if "priority" in row:
            tip += f", priority {row['priority']:.2f}"
        if visited:
            tip += " (in today's routes)" if is_visited else " (not today)"
        folium.CircleMarker(
            location=[row["lat"], row["lon"]], radius=4 + 4 * row["confidence"],
            color="#000" if is_visited else color, weight=2 if is_visited else 1,
            fill=True, fill_color=color, fill_opacity=0.9 if (is_visited or not visited) else 0.35,
            tooltip=tip,
        ).add_to(m)

    for _, p in pusk.iterrows():
        is_start = p["name"] in starts
        folium.Marker([p["lat"], p["lon"]], tooltip=f"Puskesmas: {p['name']}",
                      icon=folium.Icon(color="green" if is_start else "blue",
                                       icon="home" if is_start else "plus")).add_to(m)
    return m


def legend(color_by):
    """Vertical color key next to the map."""
    items = PRIORITY_COLORS if color_by == "priority" else \
        [(k.capitalize(), v) for k, v in TYPE_COLORS.items()]
    html = ["<div style='font-size:0.85rem;line-height:1.9'>"]
    html.append(f"<b>{'Priority' if color_by == 'priority' else 'Site type'}</b><br>")
    for label, color in items:
        html.append(f"<span style='display:inline-block;width:12px;height:12px;border-radius:50%;"
                    f"background:{color};margin-right:6px;vertical-align:middle'></span>{label}<br>")
    html.append("<span style='display:inline-block;width:12px;height:12px;border-radius:50%;"
                "border:2px solid #888;margin-right:6px;vertical-align:middle'></span>In today's routes<br>")
    html.append("<br><b>Places</b><br>🟢 Taking part today<br>🔵 Other puskesmas<br>")
    if plan_ready:
        html.append("<br><b>Teams</b><br>")
        several = len({t["puskesmas"] for t in saved["teams"]}) > 1
        for i, t in enumerate(saved["teams"]):
            short = t["puskesmas"].replace("Puskesmas Pembantu", "").replace("Puskesmas", "").strip()
            label = f"Team {i + 1}" + (f" · {short.split()[0]}" if several else "")
            html.append(f"<div style='white-space:nowrap'><span style='display:inline-block;width:18px;"
                        f"height:4px;background:{TEAM_COLORS[i % len(TEAM_COLORS)]};margin-right:6px;"
                        f"vertical-align:middle'></span>{label}</div>")
    html.append("</div>")
    return "".join(html)


# ---------- page ----------

# ---------- end of day report page (opened from a team's WhatsApp link) ----------

SHORT_STATUS = {"breeding": "Breeding found", "clear": "No breeding", "false": "Wrong detection",
                "cleared": "Cleared by residents", "no_access": "Couldn't get in", "not_reached": "Didn't get there"}


def report_page(team_id, plan_id, k):
    """Mobile form: mark every stop, write a summary, submit."""
    st.markdown("<style>.block-container{max-width:640px;padding-top:3.5rem}</style>", unsafe_allow_html=True)
    st.markdown(f"### Dengai · Team {team_id} report")
    if k != RP.key(plan_id, team_id):
        st.error("This link is not valid. Ask your coordinator for a new one.")
        return
    if str(saved.get("plan_id")) != str(plan_id):
        st.warning("This link is from an earlier plan. Ask your coordinator for today's link.")
        return
    plan = load_csv(OUTPUTS / "plan_optimized.csv")
    team = plan[plan["team_id"] == team_id].sort_values("visit_order") if plan is not None else None
    tcfg = next((t for t in saved["teams"] if t["team_id"] == team_id), None)
    if team is None or tcfg is None or not len(team):
        st.info("No stops were planned for this team.")
        return
    info = sites.set_index("site_id")
    earlier = RP.load(plan_id, team_id)
    st.caption(f"{tcfg['puskesmas']} · {len(team)} stops · tap what happened at each one")
    if earlier:
        st.success(f"Report received at {earlier['submitted'][-5:]}. You can change it and send again.")

    with st.form("report"):
        leader = st.text_input("Your name", earlier.get("leader", "") if earlier else
                               load_contacts().get(str(team_id), {}).get("name", ""))
        stops = {}
        for n, row in enumerate(team.itertuples(), start=1):
            kind = info.at[row.site_id, "site_type"] if row.site_id in info.index else ""
            when = N.clock(tcfg["leave"], row.arrival_minute)
            st.markdown(f"**{n}. {row.site_id}** · {kind} · planned {when} · "
                        f"[map]({N.stop_link(row.lat, row.lon, tcfg['mode'])})")
            default = (earlier or {}).get("stops", {}).get(row.site_id)
            stops[row.site_id] = st.pills(f"Stop {n}", list(SHORT_STATUS), format_func=SHORT_STATUS.get,
                                          default=default, key=f"stop_{row.site_id}",
                                          label_visibility="collapsed")
        summary = st.text_area("What happened today?", (earlier or {}).get("summary", ""), height=120,
                               placeholder="Anything that slowed you down, places to revisit, residents "
                                           "who helped. Indonesian or English is fine.")
        sent = st.form_submit_button("Send report", type="primary", use_container_width=True)
    if sent:
        missing = [s for s, v in stops.items() if not v]
        if missing:
            st.warning(f"{len(missing)} stop(s) have no answer yet. Choose one for each, "
                       "or 'Didn't get there' if you did not reach it.")
        else:
            RP.save(plan_id, team_id, stops, summary, leader)
            st.success("Thank you! Your report was sent to the coordinator. You can close this page.")


q = st.query_params
if "report" in q:
    try:
        report_page(int(q.get("report")), q.get("plan", ""), q.get("k", ""))
    except ValueError:
        st.error("This link is not valid.")
    st.stop()


def app_base_url():
    """Address of this app as the coordinator's browser sees it, without path or query."""
    try:
        u = urlparse(st.context.url)
        return f"{u.scheme}://{u.netloc}"
    except Exception:
        return "http://localhost:8501"


st.markdown("<style>.block-container{padding-top:2rem;padding-bottom:2rem}</style>", unsafe_allow_html=True)
st.markdown("## Dengai <span style='font-size:0.9rem;font-weight:400;opacity:0.7'>"
            "daily dengue inspection routes for Tallo, Makassar</span>", unsafe_allow_html=True)
st.caption("Sites are predicted, not confirmed, breeding sites; numbers show inspection value, not health outcomes.")

tab_plan, tab_details, tab_day = st.tabs(["Today's plan", "Weights and comparisons", "Finish the day"])

# ===== Tab 1: the coordinator's daily plan =====
with tab_plan:
    left, center, right = st.columns([0.8, 4, 2.2], gap="small")
    PANEL = 600  # map and right panel share this height so the page lines up

    with right:
        panel = st.container(height=PANEL, border=True)
        with panel:
            st.markdown("**Puskesmas taking part**")
            st.multiselect("Puskesmas", list(pusk["name"]), key="pusk_selected", label_visibility="collapsed",
                           placeholder="Choose, or click one on the map")
            draft = current_puskesmas()
            draft_teams, draft_notes = T.form_teams(draft, cfg) if draft else ([], {})
            for p in draft:
                name = p["name"]
                for f, (_, default, _) in FIELDS.items():
                    ss.setdefault(f"{name}|{f}", default)
                ss.setdefault(f"{name}|hours", 6.0)
                ss.setdefault(f"{name}|leave", datetime.strptime("08:00", "%H:%M").time())
                with st.container(border=True):
                    st.markdown(f"**{name.replace('Puskesmas ', '')}**  \n"
                                f"<small>{T.describe(draft_teams, name)}</small>", unsafe_allow_html=True)
                    label, _, step = FIELDS["budget_usd"]
                    st.number_input(label, min_value=0, step=step, key=f"{name}|budget_usd")
                    a1, a2 = st.columns(2)
                    a1.number_input("Paid workers", min_value=0, step=1, key=f"{name}|paid")
                    a2.number_input("Volunteers", min_value=0, step=1, key=f"{name}|volunteers")
                    b1, b2 = st.columns(2)
                    b1.number_input("Motorbikes", min_value=0, step=1, key=f"{name}|motorbikes")
                    b2.number_input("Bicycles", min_value=0, step=1, key=f"{name}|bicycles")
                    c1_, c2_ = st.columns(2)
                    c1_.number_input("Hours", min_value=1.0, max_value=12.0, step=0.5, key=f"{name}|hours")
                    c2_.time_input("Leave at", key=f"{name}|leave", step=900)
                    for note in draft_notes.get(name, []):
                        st.caption(note)
            with st.expander("Advanced"):
                seconds = st.slider("Optimizer search time (seconds)", 5, 60, int(saved["solver_seconds"]), 5,
                                    help="Longer can find slightly better routes.")
                st.caption(f"Teams of {cfg.get('team_size', 2):g}; "
                           + ("each led by a paid worker. " if cfg.get("team_needs_paid_lead", 1) else "")
                           + f"US$ 1 = Rp {RATE:,.0f}. Change in config/assumptions.csv.")

    def inputs(plist):
        """The parts of the inputs that change a plan (ignores tiny coordinate differences)."""
        return [(p["name"], *(int(p.get(f, 0) or 0) for f in FIELDS), float(p.get("hours", 6)),
                 str(p.get("leave", "08:00"))) for p in plist]

    stale = plan_ready and inputs(draft) != inputs(saved["puskesmas"])

    with left:
        color_by = st.selectbox("Color dots by", ["priority", "site type"])
        st.markdown(legend(color_by), unsafe_allow_html=True)

    with center:
        fmap = build_map("optimized", plan_ready and not stale, ss.pusk_selected, color_by)
        out = st_folium(fmap, height=PANEL, use_container_width=True, key="plan_map",
                        returned_objects=["last_object_clicked_tooltip"])
        clicked = (out or {}).get("last_object_clicked_tooltip") or ""
        if clicked.startswith("Puskesmas: ") and clicked[11:] not in ss.pusk_selected:
            ss.pending_add = clicked[11:]
            st.rerun()

        generate = st.button("Generate team routes", type="primary", use_container_width=True,
                             disabled=not (can_plan and draft_teams))
        if not can_plan:
            st.info("Run python run_pipeline.py once to prepare sites and travel times.")
        elif not draft_teams:
            st.info("Add people to a puskesmas to form at least one team.")
        elif stale:
            st.warning("Inputs changed. Click Generate team routes to update the plan.")
        elif not plan_ready:
            st.info("Choose the puskesmas and their resources, then click Generate team routes.")

    if generate:
        with st.spinner(f"Planning routes for {len(draft_teams)} teams (about {seconds + 5} seconds)..."):
            D.plan_day(draft, int(seconds), net=street_network())
        st.cache_data.clear()
        st.rerun()

    if plan_ready and not stale:
        summary = load_json(OUTPUTS / "summary_optimized.json")
        costs = load_csv(OUTPUTS / "costs_optimized.csv")
        plan = load_csv(OUTPUTS / "plan_optimized.csv")

        st.divider()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Sites inspected today", summary["sites_visited"])
        c2.metric("High priority sites reached", f"{summary['high_priority_visited']} of {summary['high_priority_total']}")
        if costs is not None:
            total = costs.iloc[-1]
            c3.metric("Cost of the day", usd(total["Total (IDR)"]))
            if summary.get("cost_per_high_priority_idr"):
                c4.metric("Cost per high priority site", usd(summary["cost_per_high_priority_idr"]))

        routes_col, cost_col = st.columns([1, 1], gap="large")

        with cost_col:
            st.markdown("#### Budget by puskesmas")
            if costs is not None:
                body = costs[costs["Team"] != "Total"]
                rows = []
                for p in saved["puskesmas"]:
                    spent = body.loc[body["Puskesmas"] == p["name"], "Total (IDR)"].sum()
                    budget = p.get("budget_idr", 0)
                    rows.append({"Puskesmas": p["name"].replace("Puskesmas ", ""),
                                 "Teams": T.describe(saved["teams"], p["name"]),
                                 "Budget": usd(budget) if budget else "No limit", "Planned cost": usd(spent),
                                 "Left": usd(budget - spent) if budget else ""})
                st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

                st.markdown("#### Cost by team")
                show = costs.copy()
                show["Travel"] = show["Travel"].fillna("").map(lambda k: mode_label(k) if k else "")
                show["Puskesmas"] = show["Puskesmas"].fillna("").str.replace("Puskesmas ", "", regex=False)
                for col in ["Labor", "Fuel", "Larvicide", "Total"]:
                    show[f"{col} (US$)"] = (show[f"{col} (IDR)"] / RATE).round(2)
                show = show.drop(columns=[c for c in show.columns if "(IDR)" in c or c == "Total (USD)"])
                st.dataframe(show, hide_index=True, width="stretch",
                             column_config={c: st.column_config.NumberColumn(format="$%.2f")
                                            for c in show.columns if "(US$)" in c})
                st.caption(f"Labor: paid workers × hours × {usd(cfg.get('wage_idr_per_hour', 0))} per hour"
                           + (f", volunteers {usd(cfg.get('volunteer_stipend_idr_per_day', 0))} per day"
                              if cfg.get("volunteer_stipend_idr_per_day") else ", volunteers unpaid")
                           + ". Fuel: street km × price per km. Larvicide: expected real sites × price. "
                             "Prices are placeholders in config/assumptions.csv until sourced.")
            access = load_csv(Path("data/processed/site_access.csv"))
            if access is not None and "hard_to_reach" in access and access["hard_to_reach"].any():
                hard = access[access["hard_to_reach"]].merge(sites, left_on="id", right_on="site_id")
                with st.expander(f"{len(hard)} site(s) need a special visit"):
                    st.caption("Far from any mapped street or path (fenced, on a roof, across water). "
                               "Left out of routes; plan them with the owner or a vehicle.")
                    st.dataframe(hard[["site_id", "site_type", "priority", "meters_to_path"]]
                                 .rename(columns={"meters_to_path": "Meters from path"}), hide_index=True)

        with routes_col:
            st.markdown("#### Team routes")
            st.caption("Each team gets its stops in order with a free Google Maps link per stop, and a "
                       "link to report at the end of the day. Add the leader's WhatsApp number once; "
                       "it is saved on this computer.")
            ss.setdefault("base_url", app_base_url())
            base = st.text_input("Address teams' phones open for reports", key="base_url",
                                 help="Use the Network URL Streamlit prints (phones on the same Wi-Fi), "
                                      "or the address of a deployed app.")
            if "localhost" in base or "127.0.0.1" in base:
                st.caption("⚠️ Phones cannot open localhost. Use the Network URL from the terminal, "
                           "for example http://10.34.185.35:8501.")
            plan_id = saved.get("plan_id", "default")
            contacts = load_contacts()
            site_info = sites.set_index("site_id")
            for tcfg in saved["teams"]:
                team_id = tcfg["team_id"]
                team = plan[plan["team_id"] == team_id]
                key = str(team_id)
                start_name, lat, lon = team_start(tcfg)
                msg_cfg = dict(cfg, travel_mode=tcfg["mode"], day_start=tcfg["leave"])
                person = contacts.get(key, {})
                color = TEAM_COLORS[(team_id - 1) % len(TEAM_COLORS)]
                crew = f"{tcfg['paid']} paid" + (f" + {tcfg['volunteers']} volunteer{'s' if tcfg['volunteers'] > 1 else ''}"
                                                  if tcfg["volunteers"] else "")
                title = f"Team {team_id}" + (f" ({person['name']})" if person.get("name") else "")
                with st.expander(f"{title}: {len(team)} sites, {mode_label(tcfg['mode']).lower()}, {crew}"):
                    st.markdown(f"<div style='height:4px;background:{color};margin-bottom:8px'></div>"
                                f"<small>From {start_name}, leaves {tcfg['leave']}, {tcfg['hours']:g} h</small>",
                                unsafe_allow_html=True)
                    if not len(team):
                        st.caption("No sites fit this team's time or budget today.")
                        continue
                    a, b = st.columns(2)
                    name = a.text_input("Team leader", person.get("name", ""), key=f"name_{key}")
                    phone = b.text_input("WhatsApp number", person.get("phone", ""), key=f"phone_{key}",
                                         placeholder="+62 812 3456 7890")
                    if name != person.get("name", "") or phone != person.get("phone", ""):
                        contacts[key] = {"name": name, "phone": phone}
                        save_contacts(contacts)
                    report_url = RP.link(base, plan_id, team_id)
                    text, links = N.team_message(team_id, team, start_name, (lat, lon), msg_cfg, site_info,
                                                 report_link=report_url)
                    if name:
                        text = text.replace(f"*Dengai: Team {team_id}*", f"*Dengai: Team {team_id}*\nHi {name}!", 1)
                    x, y, z = st.columns(3)
                    x.link_button(f"Send to {name or 'team'}" if phone else "Share on WhatsApp",
                                  N.whatsapp_link(text, phone), type="primary" if phone else "secondary",
                                  use_container_width=True)
                    y.link_button("Preview route", links[0], use_container_width=True)
                    z.download_button("Download", text, file_name=f"team_{team_id}.txt",
                                      key=f"dl_{team_id}", use_container_width=True)
                    r1, r2 = st.columns(2)
                    r1.link_button("Send end of day link", N.whatsapp_link(
                        N.report_message(team_id, name, report_url), phone), use_container_width=True)
                    r2.link_button("Open report form", report_url, use_container_width=True)
                    with st.popover("See message"):
                        st.code(text, language=None)
            first = team_start(saved["teams"][0])
            kml = N.plan_kml(plan, first[0], (first[1], first[2]), site_info,
                             load_json(OUTPUTS / "paths_optimized.json"), cfg, title="Dengai: today's routes")
            st.download_button("Download all routes for Google My Maps (.kml)", kml,
                               file_name="dengai_routes.kml", mime="application/vnd.google-earth.kml+xml",
                               help="Free: mymaps.google.com, create a map, Import, choose this file.")

# ===== Tab 2: weights and comparisons =====
with tab_details:
    if plan_ready:
        st.markdown("### Dengai compared with simpler strategies")
        st.caption("Same teams, hours, start point, and travel times for every method.")
        rows = []
        for m in METHOD_LABELS:
            s = load_json(OUTPUTS / f"summary_{m}.json")
            rows.append({
                "Method": METHOD_LABELS[m],
                "Sites inspected": s["sites_visited"],
                "High priority reached": f"{s['high_priority_visited']} of {s['high_priority_total']}",
                "Total priority": s["total_priority"],
                "Expected real sites": s["expected_real_sites"],
                "Travel minutes": s["travel_minutes"],
                "Cost": usd(s["total_cost_idr"]) if s.get("total_cost_idr") else "",
                "Cost per high priority site": usd(s["cost_per_high_priority_idr"])
                if s.get("cost_per_high_priority_idr") else "",
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

        method = st.radio("Show routes on the map for", list(METHOD_LABELS), format_func=METHOD_LABELS.get,
                          horizontal=True, index=2)
        st_folium(build_map(method, True, [p["name"] for p in saved["puskesmas"]]), height=420, use_container_width=True, key="compare_map",
                  returned_objects=[])

    st.markdown("### How each site is prioritized")
    st.markdown("**priority = type weight × confidence × exposure × clustering × urgency**")
    weights = pd.DataFrame({
        "Factor": ["Type weight", "Confidence", "Exposure", "Clustering", "Urgency"],
        "Question it answers": ["How much does this kind of site breed mosquitoes?",
                                "How likely is the detection real?",
                                "How many people live nearby?",
                                "Is it part of a hotspot?",
                                "Did rain refill containers?"],
        "Current values": [
            ", ".join(f"{t} {cfg.get('w_' + t, 0.5):g}" for t in ["tire", "container", "drain", "trash"]),
            f"from the detector; {cfg.get('default_confidence', 0.87):g} if missing",
            f"buildings within {cfg.get('buffer_m', 100):g} m, scaled {cfg.get('scale_min', 0.5):g} to {cfg.get('scale_max', 1.5):g}",
            f"other sites within {cfg.get('buffer_m', 100):g} m, scaled {cfg.get('scale_min', 0.5):g} to {cfg.get('scale_max', 1.5):g}",
            f"{cfg.get('rain_boost', 1.3):g} after {cfg.get('rain_threshold_mm', 10):g} mm of rain in 7 days, else 1",
        ],
        "Source": ["Tun Lin 2009; Mwakutwaa 2023 (exact values our choice)",
                   "Hassan et al. 2026, U-Net++ F1 0.87 in Tallo",
                   "Aedes aegypti flight range about 106 m (Moore and Brown 2022)",
                   "Same radius; one visit clears a hotspot",
                   "Egg to adult in 7 to 10 days (CDC)"],
    })
    st.dataframe(weights, hide_index=True, width="stretch")
    st.caption("Factors are multiplied, so a weak one pulls the score down: a probably false detection "
               "stays low even in a crowded block. High priority means the top 25% of scores.")

    if "priority" in sites:
        top = sites.sort_values("priority", ascending=False).iloc[0]
        st.markdown(f"**Example, top site {top['site_id']}:** {top['site_type']} "
                    f"{top['type_weight']:g} × confidence {top['confidence']:g} × exposure {top['exposure']:g} "
                    f"× clustering {top['clustering']:g} × urgency {top['urgency']:g} = **{top['priority']:.2f}**")
        with st.expander("Top 20 sites"):
            cols = [c for c in ["site_id", "site_type", "confidence", "buildings_nearby", "sites_nearby",
                                "exposure", "clustering", "priority"] if c in sites]
            st.dataframe(sites.sort_values("priority", ascending=False)[cols].head(20), hide_index=True)

    st.markdown("### How routes are chosen")
    st.markdown(
        "A **team orienteering problem** (Chao, Golden and Wasil 1996): teams cannot visit every site in a day, "
        "so the plan chooses which sites and in what order to collect the most priority, with every team back "
        "before its day ends. Solved with Google OR-Tools: every site is optional, skipping one costs its "
        "priority, and guided local search improves the plan for the chosen search time. Each team can travel "
        "differently and work different hours. Full equations: `docs/METHODS.md`.")

    robust, sens = load_csv(OUTPUTS / "robustness.csv"), load_csv(OUTPUTS / "sensitivity.csv")
    if robust is not None or sens is not None:
        st.markdown("### Robustness and sensitivity")
        st.caption("Computed by run_pipeline.py with the default settings in assumptions.csv.")
    if robust is not None:
        show = pd.DataFrame({
            "Reality": robust["reality"],
            "Method": robust["method"].map(METHOD_LABELS),
            "Real sites reached": [f"{m} ({a} to {b})" for m, a, b in
                                   zip(robust["real_sites_mean"], robust["real_sites_p5"], robust["real_sites_p95"])],
            "Real value reached": [f"{m} ({a} to {b})" for m, a, b in
                                   zip(robust["real_value_mean"], robust["real_value_p5"], robust["real_value_p95"])],
        })
        st.dataframe(show, hide_index=True, width="stretch")
        opt = robust[robust["method"] == "optimized"]
        if "beats_nearest_pct" in opt:
            st.caption(f"1,000 simulated realities where each site is real with its confidence. Dengai beats "
                       f"nearest next in {opt['beats_nearest_pct'].min():.0f}% and highest priority next in "
                       f"{opt['beats_priority_pct'].min():.0f}% of them, even if the detector is 25% worse.")
    if sens is not None:
        st.dataframe(sens.rename(columns={
            "assumption": "Assumption changed", "case": "Case",
            "nearest_priority": "Nearest next", "priority_first_priority": "Priority next",
            "optimized_priority": "Dengai", "gain_vs_best_baseline_pct": "Gain vs best baseline (%)",
            "optimized_high_priority": "Dengai high priority reached"}),
            hide_index=True, width="stretch")
        st.caption("Each row changes one assumption and replans with every method.")

# ===== Tab 3: finish the day =====
with tab_day:
    st.markdown("### Finish the day")
    plan_id = saved.get("plan_id", "default")
    received = RP.load_all(plan_id) if plan_ready else {}
    team_list = saved["teams"] or []
    st.caption(f"Reports from the teams' end of day links: {len(received)} of {len(team_list)} received. "
               "Send the links from each team's card in Today's plan.")
    if st.button("Check for new reports"):
        st.rerun()

    if received:
        counts = RP.tally(received)
        cols = st.columns(len(SHORT_STATUS))
        for col, (code, label) in zip(cols, SHORT_STATUS.items()):
            col.metric(label, counts.get(code, 0))
        inspected = counts["breeding"] + counts["clear"] + counts["false"] + counts["cleared"]
        if inspected:
            st.caption(f"Detections confirmed real: {counts['breeding'] + counts['clear'] + counts['cleared']} "
                       f"of {inspected} inspected ({counts['false']} wrong detections). "
                       f"{counts['not_reached'] + counts['no_access']} stops to carry over to tomorrow.")

    plan = load_csv(OUTPUTS / "plan_optimized.csv") if plan_ready else None
    contacts = load_contacts()
    for t in team_list:
        team_id = t["team_id"]
        r = received.get(team_id)
        status = f"received {r['submitted'][-5:]}" + (f" from {r['leader']}" if r.get("leader") else "") \
            if r else "waiting"
        with st.expander(f"Team {team_id} ({t['puskesmas'].replace('Puskesmas ', '')}): {status}",
                         expanded=bool(r)):
            if r:
                rows = []
                team = plan[plan["team_id"] == team_id].sort_values("visit_order") if plan is not None else None
                order = list(team["site_id"]) if team is not None else list(r["stops"])
                for n, site in enumerate(order, start=1):
                    rows.append({"Stop": n, "Site": site, "What happened": SHORT_STATUS.get(r["stops"].get(site), "")})
                st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
                if r.get("summary"):
                    st.markdown(f"> {r['summary']}")
            else:
                person = contacts.get(str(team_id), {})
                link = RP.link(ss.get("base_url", app_base_url()), plan_id, team_id)
                st.link_button("Send end of day link on WhatsApp",
                               N.whatsapp_link(N.report_message(team_id, person.get("name", ""), link),
                                               person.get("phone")))
                st.text_area("Or paste the team's WhatsApp reply here", key=f"debrief_{team_id}", height=80)

    general = st.text_area("Notes from the coordinator", key="debrief_general", height=70)
    if st.button("Save today's debrief", type="primary"):
        DEBRIEF_DIR.mkdir(parents=True, exist_ok=True)
        record = {"date": date.today().isoformat(), "plan_id": plan_id, "reports": received,
                  "pasted": {str(t["team_id"]): ss.get(f"debrief_{t['team_id']}", "") for t in team_list},
                  "coordinator": general, "plan_settings": saved}
        (DEBRIEF_DIR / f"{date.today().isoformat()}.json").write_text(json.dumps(record, indent=2, ensure_ascii=False))
        st.success("Saved. Next: the AI agent turns this into a daily report and suggested changes.")

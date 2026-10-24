"""Dengai dashboard. Run with: streamlit run app.py (after python run_pipeline.py)"""

import json
from pathlib import Path

import folium
import geopandas as gpd
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

import sys
sys.path.append(str(Path(__file__).resolve().parent / "engine"))
import config as C  # noqa: E402
import navigation as N  # noqa: E402
import plan_day as D  # noqa: E402
import route_paths as R  # noqa: E402

AREA_FILE = Path("data/raw/tallo_area.gpkg")
SITES_FILE = Path("data/processed/sites_scored.csv")
RAW_SITES_FILE = Path("data/processed/sites.csv")
START_FILE = Path("data/processed/start_point.csv")
OUTPUTS = Path("outputs")

TYPE_COLORS = {"tire": "#d7301f", "container": "#fc8d59", "drain": "#4575b4", "trash": "#7b3294"}
TEAM_COLORS = ["#1b9e77", "#d95f02", "#7570b3", "#e7298a", "#66a61e", "#e6ab02", "#a6761d", "#666666"]
METHOD_LABELS = {
    "nearest": "Baseline 1: nearest site next",
    "priority": "Baseline 2: highest priority next",
    "optimized": "Dengai optimizer",
}

st.set_page_config(page_title="Dengai", layout="wide")
st.title("Dengai: daily inspection plan for Tallo, Makassar")
st.caption("Sites are predicted, not confirmed, breeding sites. Numbers show inspection value, not health outcomes.")


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


@st.cache_resource
def street_network():
    """Load the street network once per app session (a few seconds)."""
    return R.load_network()


CONTACTS_FILE = OUTPUTS / "team_contacts.json"  # local only (outputs/ is not on GitHub)


def load_contacts():
    try:
        return json.loads(CONTACTS_FILE.read_text())
    except Exception:
        return {}


def save_contacts(contacts):
    OUTPUTS.mkdir(exist_ok=True)
    CONTACTS_FILE.write_text(json.dumps(contacts, indent=2))


def available_plans():
    """Methods that have a plan file in outputs/."""
    return [m for m in METHOD_LABELS if (OUTPUTS / f"plan_{m}.csv").exists()]


sites = load_csv(SITES_FILE)
if sites is None:
    sites = load_csv(RAW_SITES_FILE)
if sites is None:
    st.warning("No sites yet. Run: python engine/make_fake_sites.py, then python run_pipeline.py")
    st.stop()

boundary = load_layer("boundary")
health = load_layer("health_centers")
start = load_csv(START_FILE)
plans = available_plans()

# Sidebar: the organizer plans the day
cfg = C.load_assumptions()
settings = D.load_settings(cfg)
st.sidebar.header("Plan the day")
can_plan = SITES_FILE.exists() and C.MATRIX_FILE.exists()
with st.sidebar.form("plan_form"):
    n_teams = st.number_input("Number of teams", 1, 12, int(settings["n_teams"]))
    mode_keys = list(D.MODES)
    mode = st.selectbox("Teams travel by", mode_keys,
                        index=mode_keys.index(settings["travel_mode"]) if settings["travel_mode"] in mode_keys else 0,
                        format_func=lambda k: D.MODES[k][0])
    hours = st.slider("Hours in the field", 2.0, 10.0, float(settings["hours_per_day"]), 0.5)
    try:
        default_start = pd.to_datetime(settings["day_start"], format="%H:%M").time()
    except Exception:
        default_start = pd.to_datetime("08:00", format="%H:%M").time()
    day_start = st.time_input("Teams leave the puskesmas at", default_start, step=900)
    with st.expander("Advanced"):
        seconds = st.slider("Optimizer search time (seconds)", 5, 60, int(settings["solver_seconds"]), 5,
                            help="Longer can find slightly better routes.")
    create = st.form_submit_button("Create routes", type="primary", disabled=not can_plan,
                                   use_container_width=True)
if not can_plan:
    st.sidebar.info("Run python run_pipeline.py once to prepare sites and travel times.")
if create:
    with st.spinner(f"Planning routes for {n_teams} teams (about {seconds + 5} seconds)..."):
        D.plan_day(int(n_teams), mode, float(hours), day_start.strftime("%H:%M"), int(seconds),
                   net=street_network(), start=load_csv(START_FILE).iloc[0])
    st.cache_data.clear()
    st.session_state["method"] = "optimized"
    st.rerun()

method = None
if plans:
    if st.session_state.get("method") not in plans:
        st.session_state["method"] = "optimized" if "optimized" in plans else plans[0]
    method = st.sidebar.radio("Show routes for", plans, format_func=lambda m: METHOD_LABELS[m], key="method")

st.sidebar.header("Sites")
color_by = st.sidebar.radio("Color sites by", ["priority", "site type"]) if "priority" in sites else "site type"
chosen_types = st.sidebar.multiselect("Site types", sorted(sites["site_type"].unique()),
                                      default=sorted(sites["site_type"].unique()))
min_conf = st.sidebar.slider("Minimum confidence", 0.0, 1.0, 0.0, 0.05)
show_health = st.sidebar.checkbox("All health facilities", value=False)

shown = sites[sites["site_type"].isin(chosen_types) & (sites["confidence"] >= min_conf)]

# Comparison table across plans
if plans:
    rows = []
    for m in plans:
        with open(OUTPUTS / f"summary_{m}.json") as f:
            s = json.load(f)
        rows.append({
            "Method": METHOD_LABELS[m],
            "Sites inspected": s["sites_visited"],
            "High priority reached": f"{s['high_priority_visited']} of {s['high_priority_total']}",
            "Total priority": s["total_priority"],
            "Expected real sites": s["expected_real_sites"],
            "Walking minutes": s["travel_minutes"],
        })
    st.subheader("Plans compared (same teams, hours, and start point)")
    st.caption(f"{settings['n_teams']} teams, {D.MODES.get(settings['travel_mode'], ('walking',))[0].lower()}, "
               f"{settings['hours_per_day']:g} hours from {settings['day_start']}.")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

# Map
center = [sites["lat"].mean(), sites["lon"].mean()]
m = folium.Map(location=center, zoom_start=15, tiles="OpenStreetMap")

if boundary is not None:
    folium.GeoJson(boundary, name="Tallo boundary",
                   style_function=lambda _: {"color": "#333", "weight": 2, "fill": False}).add_to(m)

visited = set()
if method:
    plan = load_csv(OUTPUTS / f"plan_{method}.csv")
    visited = set(plan["site_id"])
    # Street paths from engine/route_paths.py; without them, draw straight lines.
    paths_file = OUTPUTS / f"paths_{method}.json"
    street_paths = json.loads(paths_file.read_text()) if paths_file.exists() else {}
    for team_id, team in plan.groupby("team_id"):
        team = team.sort_values("visit_order")
        path = street_paths.get(str(int(team_id)))
        if not path:
            path = [[start["lat"].iloc[0], start["lon"].iloc[0]]] if start is not None else []
            path += team[["lat", "lon"]].values.tolist()
            path += path[:1]  # back to start
        folium.PolyLine(path, color=TEAM_COLORS[(team_id - 1) % len(TEAM_COLORS)], weight=3,
                        opacity=0.8, tooltip=f"Team {team_id}: {len(team)} sites").add_to(m)

max_priority = shown["priority"].max() if "priority" in shown and len(shown) else 1
for _, row in shown.iterrows():
    if color_by == "priority":
        level = row["priority"] / max_priority
        color = "#b2182b" if level > 0.66 else "#ef8a62" if level > 0.33 else "#fddbc7"
    else:
        color = TYPE_COLORS.get(row["site_type"], "#555")
    is_visited = row["site_id"] in visited
    tip = f"{row['site_id']}: {row['site_type']}, confidence {row['confidence']:.2f}"
    if "priority" in row:
        tip += f", priority {row['priority']:.2f}"
    tip += " (visited)" if is_visited else (" (not visited)" if method else "")
    folium.CircleMarker(
        location=[row["lat"], row["lon"]],
        radius=4 + 4 * row["confidence"],
        color="#000" if is_visited else color, weight=2 if is_visited else 1,
        fill=True, fill_color=color, fill_opacity=0.85 if is_visited or not method else 0.35,
        tooltip=tip,
    ).add_to(m)

if start is not None:
    folium.Marker([start["lat"].iloc[0], start["lon"].iloc[0]], tooltip=f"Start: {start['name'].iloc[0]}",
                  icon=folium.Icon(color="green", icon="home")).add_to(m)

if health is not None:
    # Puskesmas (the teams' bases) always show; other health facilities only when ticked.
    for _, row in health.iterrows():
        if not (row.get("is_puskesmas") or show_health):
            continue
        label = row.get("name") or "Health facility"
        folium.Marker([row.geometry.y, row.geometry.x], tooltip=label,
                      icon=folium.Icon(color="blue" if row.get("is_puskesmas") else "lightgray",
                                       icon="plus")).add_to(m)

st_folium(m, height=600, use_container_width=True)

if color_by == "priority":
    st.caption("Dark red: highest priority, light: lowest. Black outline: inspected in this plan. "
               "Lines: each team's route along the streets. Green house: start. Blue cross: puskesmas.")
else:
    st.caption("Red tire, orange container, blue drain, purple trash. Black outline: inspected in this plan.")

# Field navigation: one message per team, shared on WhatsApp, opened in Google Maps (free links)
if method and start is not None:
    st.subheader("Send routes to the field teams")
    st.caption("Each team gets its stops in order, with a free Google Maps link per stop that navigates "
               "from where the inspector is. Whole route links are a preview, split into parts because "
               "a link holds at most 9 stops in between (3 in a phone browser).")
    msg_cfg = dict(cfg, travel_mode=settings["travel_mode"], day_start=settings["day_start"])
    contacts = load_contacts()
    site_info = sites.set_index("site_id")
    start_name = start["name"].iloc[0]
    start_latlon = (float(start["lat"].iloc[0]), float(start["lon"].iloc[0]))
    paths_file = OUTPUTS / f"paths_{method}.json"
    kml = N.plan_kml(plan, start_name, start_latlon, site_info,
                     json.loads(paths_file.read_text()) if paths_file.exists() else None, msg_cfg,
                     title=f"Dengai: {METHOD_LABELS[method]}")
    st.download_button("Download all teams for Google My Maps (.kml)", kml,
                       file_name=f"dengai_{method}.kml", mime="application/vnd.google-earth.kml+xml",
                       help="Free: go to mymaps.google.com, create a map, Import, choose this file.")
    for team_id, team in plan.groupby("team_id"):
        key = str(int(team_id))
        saved = contacts.get(key, {})
        label = f"Team {team_id}" + (f" ({saved['name']})" if saved.get("name") else "")
        with st.expander(f"{label}: {len(team)} sites"):
            c1, c2 = st.columns(2)
            name = c1.text_input("Team leader", saved.get("name", ""), key=f"name_{key}")
            phone = c2.text_input("WhatsApp number", saved.get("phone", ""), key=f"phone_{key}",
                                  placeholder="+62 812 3456 7890",
                                  help="Saved on this computer only, for the next time you plan.")
            if name != saved.get("name", "") or phone != saved.get("phone", ""):
                contacts[key] = {"name": name, "phone": phone}
                save_contacts(contacts)
            text, links = N.team_message(team_id, team, start_name, start_latlon, msg_cfg, site_info)
            if name:
                text = text.replace(f"*Dengai: Team {team_id}*", f"*Dengai: Team {team_id}*\nHi {name}!", 1)
            b1, b2, b3 = st.columns(3)
            b1.link_button(f"Send to {name or 'team'} on WhatsApp" if phone else "Share on WhatsApp",
                           N.whatsapp_link(text, phone), type="primary" if phone else "secondary",
                           use_container_width=True)
            b2.link_button("Preview whole route", links[0], use_container_width=True)
            b3.download_button("Download text", text, file_name=f"team_{team_id}.txt",
                               key=f"dl_{method}_{team_id}", use_container_width=True)
            st.code(text, language=None)

access = load_csv(Path("data/processed/site_access.csv"))
if access is not None and "hard_to_reach" in access and access["hard_to_reach"].any():
    hard = access[access["hard_to_reach"]].merge(sites, left_on="id", right_on="site_id")
    st.subheader("Sites that need a special visit")
    st.caption("These sites are far from any mapped street or path (fenced, on a roof, across water, "
               "or in unmapped alleys). They are left out of the walking routes for every method, "
               "so the coordinator can plan them separately, for example with the owner or a vehicle.")
    st.dataframe(hard[["site_id", "site_type", "priority", "meters_to_path"]]
                 .rename(columns={"meters_to_path": "Meters from nearest path"})
                 .sort_values("priority", ascending=False), hide_index=True)

robust_file, sens_file = OUTPUTS / "robustness.csv", OUTPUTS / "sensitivity.csv"
if robust_file.exists() or sens_file.exists():
    st.subheader("Robustness and sensitivity")
    if robust_file.exists():
        r = pd.read_csv(robust_file)
        st.caption("Computed by run_pipeline.py with the settings in assumptions.csv. "
                   "1,000 simulated realities: each site is real with the chance given by its confidence. "
                   "'Detector 25% worse' assumes the detector is overconfident. "
                   "Ranges are the 5th to 95th percentile.")
        show = pd.DataFrame({
            "Reality": r["reality"],
            "Method": r["method"].map(METHOD_LABELS),
            "Real sites reached": [f"{m} ({a} to {b})" for m, a, b in
                                   zip(r["real_sites_mean"], r["real_sites_p5"], r["real_sites_p95"])],
            "Real value reached": [f"{m} ({a} to {b})" for m, a, b in
                                   zip(r["real_value_mean"], r["real_value_p5"], r["real_value_p95"])],
        })
        st.dataframe(show, hide_index=True, width="stretch")
        opt = r[r["method"] == "optimized"]
        if "beats_nearest_pct" in opt:
            st.caption("Dengai beats both baselines in "
                       f"{opt['beats_nearest_pct'].min():.0f}% and {opt['beats_priority_pct'].min():.0f}% "
                       "of simulated realities.")
    if sens_file.exists():
        s = pd.read_csv(sens_file)
        st.caption("Each row changes one assumption and replans with every method.")
        st.dataframe(s.rename(columns={
            "assumption": "Assumption changed", "case": "Case",
            "nearest_priority": "Nearest next", "priority_first_priority": "Priority next",
            "optimized_priority": "Dengai", "gain_vs_best_baseline_pct": "Gain vs best baseline (%)",
            "optimized_high_priority": "Dengai high priority reached"}),
            hide_index=True, width="stretch")

with st.expander("Top priority sites"):
    cols = [c for c in ["site_id", "site_type", "confidence", "buildings_nearby", "sites_nearby",
                        "exposure", "clustering", "priority"] if c in sites]
    st.dataframe(sites.sort_values("priority", ascending=False)[cols].head(20) if "priority" in sites
                 else sites[cols].head(20), hide_index=True)

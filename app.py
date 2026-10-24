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

# Sidebar
st.sidebar.header("Plan")
method = None
if plans:
    method = st.sidebar.radio("Show routes for", plans, format_func=lambda m: METHOD_LABELS[m])
else:
    st.sidebar.info("No plans yet. Run: python run_pipeline.py")

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
               "Lines: each team's walking route along the streets. Green house: start. Blue cross: puskesmas.")
else:
    st.caption("Red tire, orange container, blue drain, purple trash. Black outline: inspected in this plan.")

# Field navigation: one message per team, shared on WhatsApp, opened in Google Maps (free links)
if method and start is not None:
    st.subheader("Send routes to the field teams")
    st.caption("Each team gets its stops in order, with a free Google Maps link per stop that navigates "
               "from where the inspector is. Whole route links are a preview, split into parts because "
               "a link holds at most 9 stops in between (3 in a phone browser).")
    cfg = C.load_assumptions()
    site_info = sites.set_index("site_id")
    start_name = start["name"].iloc[0]
    start_latlon = (float(start["lat"].iloc[0]), float(start["lon"].iloc[0]))
    paths_file = OUTPUTS / f"paths_{method}.json"
    kml = N.plan_kml(plan, start_name, start_latlon, site_info,
                     json.loads(paths_file.read_text()) if paths_file.exists() else None, cfg,
                     title=f"Dengai: {METHOD_LABELS[method]}")
    st.download_button("Download all teams for Google My Maps (.kml)", kml,
                       file_name=f"dengai_{method}.kml", mime="application/vnd.google-earth.kml+xml",
                       help="Free: go to mymaps.google.com, create a map, Import, choose this file.")
    for team_id, team in plan.groupby("team_id"):
        text, links = N.team_message(team_id, team, start_name, start_latlon, cfg, site_info)
        with st.expander(f"Team {team_id}: {len(team)} sites, {len(links)} map link(s)"):
            cols = st.columns(len(links) + 2)
            for k, link in enumerate(links):
                cols[k].link_button(f"Open route part {k + 1}", link)
            cols[len(links)].link_button("Share on WhatsApp", N.whatsapp_link(text))
            cols[len(links) + 1].download_button("Download text", text, file_name=f"team_{team_id}.txt",
                                                 key=f"dl_{method}_{team_id}")
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
        st.caption("1,000 simulated realities: each site is real with the chance given by its confidence. "
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

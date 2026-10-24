"""Dengai dashboard. Run with: streamlit run app.py (after python run_pipeline.py)"""

import json
from pathlib import Path

import folium
import geopandas as gpd
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

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

with st.expander("Top priority sites"):
    cols = [c for c in ["site_id", "site_type", "confidence", "buildings_nearby", "sites_nearby",
                        "exposure", "clustering", "priority"] if c in sites]
    st.dataframe(sites.sort_values("priority", ascending=False)[cols].head(20) if "priority" in sites
                 else sites[cols].head(20), hide_index=True)

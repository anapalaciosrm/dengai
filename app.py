"""Dengai dashboard. Run with: streamlit run app.py"""

from pathlib import Path

import folium
import geopandas as gpd
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

AREA_FILE = Path("data/raw/tallo_area.gpkg")
SITES_FILE = Path("data/processed/sites.csv")

TYPE_COLORS = {"tire": "#d7301f", "container": "#fc8d59", "drain": "#4575b4", "trash": "#7b3294"}

st.set_page_config(page_title="Dengai", layout="wide")
st.title("Dengai: daily inspection plan for Tallo, Makassar")


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
def load_sites():
    """Read the sites table, or None if it does not exist yet."""
    return pd.read_csv(SITES_FILE) if SITES_FILE.exists() else None


sites = load_sites()
boundary = load_layer("boundary")
health = load_layer("health_centers")

if sites is None:
    st.warning("No sites yet. Run: python engine/make_fake_sites.py")
    st.stop()

# Sidebar: what to show
st.sidebar.header("Show")
chosen_types = st.sidebar.multiselect("Site types", sorted(sites["site_type"].unique()),
                                      default=sorted(sites["site_type"].unique()))
min_conf = st.sidebar.slider("Minimum confidence", 0.0, 1.0, 0.0, 0.05)
show_health = st.sidebar.checkbox("Health centers", value=True)

shown = sites[sites["site_type"].isin(chosen_types) & (sites["confidence"] >= min_conf)]

# Summary numbers
c1, c2, c3 = st.columns(3)
c1.metric("Sites shown", len(shown))
c2.metric("Tires", int((shown["site_type"] == "tire").sum()))
c3.metric("Average confidence", f"{shown['confidence'].mean():.2f}" if len(shown) else "n/a")

# Map
center = [sites["lat"].mean(), sites["lon"].mean()]
m = folium.Map(location=center, zoom_start=15, tiles="OpenStreetMap")

if boundary is not None:
    folium.GeoJson(boundary, name="Tallo boundary",
                   style_function=lambda _: {"color": "#333", "weight": 2, "fill": False}).add_to(m)

for _, row in shown.iterrows():
    folium.CircleMarker(
        location=[row["lat"], row["lon"]],
        radius=4 + 4 * row["confidence"],
        color=TYPE_COLORS.get(row["site_type"], "#555"),
        fill=True, fill_opacity=0.8, weight=1,
        tooltip=f"{row['site_id']}: {row['site_type']}, confidence {row['confidence']:.2f}",
    ).add_to(m)

if show_health and health is not None:
    for _, row in health.iterrows():
        label = row.get("name") or "Health facility"
        icon_color = "green" if row.get("is_puskesmas") else "gray"
        folium.Marker([row.geometry.y, row.geometry.x], tooltip=label,
                      icon=folium.Icon(color=icon_color, icon="plus")).add_to(m)

st_folium(m, height=600, use_container_width=True)

st.caption("Colors: red tire, orange container, blue drain, purple trash. "
           "Green markers are puskesmas. Sites are predicted, not confirmed, breeding sites.")

with st.expander("Health centers found"):
    if health is None:
        st.write("Run python engine/setup_area.py to download them.")
    else:
        st.dataframe(pd.DataFrame(health.drop(columns="geometry")))

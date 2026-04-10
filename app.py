"""
Streamlit live demo — Bike-Share Analytics Dashboard
Fetches live Berlin station data from the Citybikes API.
No database or API key required.

Run: streamlit run app.py
"""

import requests
from datetime import datetime

import pandas as pd
import streamlit as st
import pydeck as pdk

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

CITYBIKES_URL = "https://api.citybik.es/v2/networks/nextbike-berlin"
RISK_COLORS = {
    "Critical": [231, 76, 60, 200],   # red
    "Low":      [243, 156, 18, 200],  # amber
    "Medium":   [52, 152, 219, 200],  # blue
    "High":     [39, 174, 96, 200],   # green
}

st.set_page_config(
    page_title="Berlin Bike-Share Dashboard",
    page_icon="🚲",
    layout="wide",
)


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300)  # cache for 5 minutes
def fetch_stations() -> pd.DataFrame:
    """Fetch live station data from Citybikes API."""
    try:
        resp = requests.get(CITYBIKES_URL, timeout=10)
        resp.raise_for_status()
        stations_raw = resp.json()["network"]["stations"]
    except Exception as e:
        st.error(f"Could not reach Citybikes API: {e}")
        return pd.DataFrame()

    rows = []
    for s in stations_raw:
        extra = s.get("extra", {})
        capacity = extra.get("slots", 0) or 0
        free_bikes = s.get("free_bikes", 0) or 0
        empty_slots = s.get("empty_slots", 0) or 0

        if capacity == 0:
            capacity = free_bikes + empty_slots

        avail_pct = (free_bikes / capacity * 100) if capacity > 0 else 0

        rows.append({
            "name":       s.get("name", "Unknown"),
            "lat":        s.get("latitude"),
            "lon":        s.get("longitude"),
            "free_bikes": free_bikes,
            "empty_slots": empty_slots,
            "capacity":   capacity,
            "avail_pct":  round(avail_pct, 1),
        })

    df = pd.DataFrame(rows).dropna(subset=["lat", "lon"])
    df["risk"] = df["avail_pct"].apply(_classify_risk)
    df["color"] = df["risk"].map(RISK_COLORS)
    df["radius"] = 60
    return df


def _classify_risk(pct: float) -> str:
    if pct < 10:
        return "Critical"
    elif pct < 25:
        return "Low"
    elif pct < 60:
        return "Medium"
    return "High"


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

st.title("Berlin Bike-Share — Live Analytics Dashboard")
st.caption(
    f"Live data from Nextbike Berlin via Citybikes API · "
    f"Refreshed at {datetime.now().strftime('%H:%M:%S')} · "
    f"Auto-caches for 5 minutes"
)

df = fetch_stations()

if df.empty:
    st.warning("No station data available. Please try again in a moment.")
    st.stop()

# ---------------------------------------------------------------------------
# KPI row
# ---------------------------------------------------------------------------

total_stations   = len(df)
total_bikes      = int(df["free_bikes"].sum())
empty_stations   = int((df["free_bikes"] == 0).sum())
critical_stations = int((df["risk"] == "Critical").sum())
system_avail_pct = round(df["avail_pct"].mean(), 1)

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Stations", f"{total_stations:,}")
col2.metric("Available Bikes", f"{total_bikes:,}")
col3.metric("System Availability", f"{system_avail_pct}%")
col4.metric("Empty Stations", empty_stations, delta=None)
col5.metric("Critical Stations (<10%)", critical_stations, delta=None)

st.divider()

# ---------------------------------------------------------------------------
# Map + sidebar filters
# ---------------------------------------------------------------------------

col_map, col_table = st.columns([2, 1])

with col_map:
    st.subheader("Station Risk Map")
    st.caption("Colour: Green = High availability · Blue = Medium · Amber = Low · Red = Critical (<10%)")

    risk_filter = st.multiselect(
        "Filter by risk level",
        options=["Critical", "Low", "Medium", "High"],
        default=["Critical", "Low", "Medium", "High"],
    )
    df_map = df[df["risk"].isin(risk_filter)]

    layer = pdk.Layer(
        "ScatterplotLayer",
        data=df_map,
        get_position=["lon", "lat"],
        get_fill_color="color",
        get_radius="radius",
        pickable=True,
        opacity=0.85,
    )
    view = pdk.ViewState(
        latitude=52.52,
        longitude=13.405,
        zoom=11,
        pitch=0,
    )
    tooltip = {
        "html": "<b>{name}</b><br/>Free bikes: {free_bikes} / {capacity}<br/>Availability: {avail_pct}%<br/>Risk: {risk}",
        "style": {"backgroundColor": "#2c3e50", "color": "white", "fontSize": "13px"},
    }
    st.pydeck_chart(pdk.Deck(layers=[layer], initial_view_state=view, tooltip=tooltip))

with col_table:
    st.subheader("Alert Stations")
    st.caption("Stations below 25% availability")

    alert_df = (
        df[df["avail_pct"] < 25]
        .sort_values("avail_pct")
        [["name", "free_bikes", "capacity", "avail_pct", "risk"]]
        .rename(columns={
            "name": "Station",
            "free_bikes": "Bikes",
            "capacity": "Cap",
            "avail_pct": "Avail %",
            "risk": "Risk",
        })
        .reset_index(drop=True)
    )

    def _color_risk(val):
        colors = {"Critical": "background-color: #e74c3c; color: white",
                  "Low":      "background-color: #f39c12; color: white"}
        return colors.get(val, "")

    if alert_df.empty:
        st.success("No stations below 25% availability right now.")
    else:
        st.dataframe(
            alert_df.style.applymap(_color_risk, subset=["Risk"]),
            use_container_width=True,
            height=500,
        )

st.divider()

# ---------------------------------------------------------------------------
# Distribution chart
# ---------------------------------------------------------------------------

st.subheader("Availability Distribution Across All Stations")

hist_df = df["avail_pct"].value_counts(bins=20).reset_index()
hist_df.columns = ["availability_pct", "station_count"]
hist_df = hist_df.sort_values("availability_pct")

st.bar_chart(hist_df.set_index("availability_pct")["station_count"])

# ---------------------------------------------------------------------------
# Risk breakdown
# ---------------------------------------------------------------------------

st.subheader("Risk Level Breakdown")

risk_summary = (
    df.groupby("risk")
    .agg(stations=("name", "count"), avg_avail=("avail_pct", "mean"), total_bikes=("free_bikes", "sum"))
    .reset_index()
    .rename(columns={"risk": "Risk Level", "stations": "Stations", "avg_avail": "Avg Availability %", "total_bikes": "Total Bikes"})
)
risk_summary["Avg Availability %"] = risk_summary["Avg Availability %"].round(1)

order = ["Critical", "Low", "Medium", "High"]
risk_summary["Risk Level"] = pd.Categorical(risk_summary["Risk Level"], categories=order, ordered=True)
risk_summary = risk_summary.sort_values("Risk Level")

st.dataframe(risk_summary, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------

st.divider()
st.caption(
    "Data: [Citybikes API](https://api.citybik.es/v2/) · Nextbike Berlin · "
    "Part of the [Bike-Share Analytics Dashboard](https://github.com/azinghasemi/bikeshare-analytics-dashboard) project · "
    "Full system: MySQL + Tableau + XGBoost + Flask"
)

"""
AWD FARMER PROGRESS DASHBOARD — v4
Reads from two Google Sheets (Apps Script v9 schema):
  1. Master Analysis  — daily readings, one row per farmer per date (21 cols)
  2. Summary          — season totals, one row per farmer (49 cols)

To connect your sheets: find the two lines marked with ← PASTE YOUR URL HERE
and replace with your published CSV links.

The Programme Overview map needs the geo/ folder (farmer_points.geojson,
gp_boundary.geojson, command_area.geojson) to sit next to this file —
converted once from the shapefiles in "map generation/" via geopandas.

Field-type terminology: older Apps Script versions wrote "Experimental" for
AWD-protocol farmers; v9+ writes "Treatment" directly. Every page in this
dashboard displays that group as "Treatment" and every filter/comparison goes
through relabel_type() / to_group() below, so both raw spellings are accepted
without code changes if the sheet's wording changes again.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import numpy as np
import requests
import json
import difflib
from pathlib import Path
from io import StringIO
from datetime import datetime
import folium
from streamlit_folium import st_folium

GEO_DIR = Path(__file__).parent / "geo"

# ═══════════════════════════════════════════════════════════════════
# PAGE CONFIGURATION — must be the very first Streamlit command
# ═══════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="AWD Farmer Progress Monitor",
    page_icon="🌾",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ═══════════════════════════════════════════════════════════════════
# ★ STEP 1 — PASTE YOUR GOOGLE SHEETS CSV LINKS HERE ★
# ═══════════════════════════════════════════════════════════════════
MASTER_ANALYSIS_URL = (
    r"https://docs.google.com/spreadsheets/d/e/2PACX-1vRK8CYPjHB6tBB9H5HFxJ_rIy6Exj5CpH8q7elgAN7DTXlehdNYX1034etUT1H7Ip6rdOFrdX_2RnJw/pub?gid=2089695520&single=true&output=csv"
)

SUMMARY_URL = (
    r"https://docs.google.com/spreadsheets/d/e/2PACX-1vRK8CYPjHB6tBB9H5HFxJ_rIy6Exj5CpH8q7elgAN7DTXlehdNYX1034etUT1H7Ip6rdOFrdX_2RnJw/pub?gid=899102818&single=true&output=csv"
)

# ═══════════════════════════════════════════════════════════════════
# COLOUR PALETTE — single light theme (see .streamlit/config.toml)
# ═══════════════════════════════════════════════════════════════════
C = {
    "bg"          : "#FBF9F4",   # app background
    "surface"     : "#FFFFFF",   # cards / sidebar / chart plot area
    "border"      : "#E7E0D2",
    "text"        : "#26221C",   # primary text — dark on light, high contrast
    "text_muted"  : "#6B6153",
    "grid"        : "#EDE7D8",
    "safe_zone"   : "rgba(46,125,50,0.10)",
    "treatment"   : "#2E6F9E",   # AWD / Treatment group
    "control"     : "#C1592B",   # Control group
    "accent"      : "#2E7D32",   # brand accent (matches primaryColor)
    "phase" : {
        "FL-Flood"  : "#F4B942",
        "FL-Inter"  : "#E07B39",
        "FL-Soil"   : "#8B4513",
        "RL-Flood"  : "#9EC9E2",
        "RL-Inter"  : "#2E6F9E",
        "RL-Soil"   : "#1B4F72",
        "No change" : "#C9C2B3",
    },
    # Single-hue phase spectrums for the concentric "Hydrological Phase
    # Distribution" donut — outer ring (Treatment) in blues, inner ring
    # (Control) in reds. FL phases lighter, RL phases darker within each ring.
    "phase_treatment" : {
        "FL-Flood"  : "#BBDEFB",
        "FL-Inter"  : "#64B5F6",
        "FL-Soil"   : "#1E88E5",
        "RL-Flood"  : "#1565C0",
        "RL-Inter"  : "#0D47A1",
        "RL-Soil"   : "#082A60",
        "No change" : "#C9C2B3",
    },
    "phase_control" : {
        "FL-Flood"  : "#FFCDD2",
        "FL-Inter"  : "#E57373",
        "FL-Soil"   : "#D32F2F",
        "RL-Flood"  : "#B71C1C",
        "RL-Inter"  : "#7F1010",
        "RL-Soil"   : "#4A0A0A",
        "No change" : "#C9C2B3",
    },
}

# FL terms always grouped before RL terms in every chart that shows phases
PHASE_ORDER = ["FL-Flood", "FL-Inter", "FL-Soil", "RL-Flood", "RL-Inter", "RL-Soil", "No change"]

# Display-label mapping — normalises both old ("Experimental") and current
# ("Treatment") raw spellings to one display label. Any filter/comparison
# against Type should go through relabel_type()/to_group(), never a hardcoded
# literal, so it keeps working if the sheet's wording changes again.
LABEL = {"Experimental": "Treatment"}
GROUP_COLOR = {"Treatment": C["treatment"], "Control": C["control"]}


def relabel_type(val):
    """Map a raw Type value to its display label (Experimental/Treatment -> Treatment)."""
    return LABEL.get(val, val)


def to_group(series):
    """Return a display-label copy of a Type/Group column for charting & tables."""
    return series.map(relabel_type)


# Derived columns — not in the source sheet, calculated on load.
DAS_COL = "Days After Sowing (derived)"  # Date − Date of Sowing, computed ourselves

# ═══════════════════════════════════════════════════════════════════
# COLUMN NAMES — Master Analysis (21 columns) — Apps Script v9
# ═══════════════════════════════════════════════════════════════════
M = {
    "farmer"         : "Farmer Name",
    "village"        : "Village (Gram Panchayat)",
    "type"           : "Type",
    "method"         : "Method of Cultivation",
    "land_area"      : "Land Area (acres)",
    "sowing_date"    : "Date of Sowing",
    "crp"            : "CRP Incharge",
    "date"           : "Date",
    "monitoring_day" : "Monitoring Day",
    "das"            : DAS_COL,
    "pp_reading"     : "PP Reading (cm)",
    "duplicate"      : "Duplicate? (count)",
    "zero_repl"      : "Zero Replaced?",
    "bgl"            : "In ref to surface",
    "fl_rl"          : "FL / RL",
    "phase"          : "Phase",
    "change_wl"      : "Change in WL (cm)",
    "event"          : "Event",
    "gopal_cm"       : "Irrig. Depth (cm)",
    "irrigated"      : "Irrigation Reported",
    "irrig_calc"     : "Irrigation Calculated",
    "days_mon"       : "Days Monitored",
}

# ═══════════════════════════════════════════════════════════════════
# COLUMN NAMES — Summary (49 columns) — Apps Script v9
# ═══════════════════════════════════════════════════════════════════
S = {
    "serial"            : " ",  # header is a blank cell in the sheet ("Sl No" is the intent)
    "village"           : "Name of the Village (Gram Panchayat)",
    "farmer"            : "Name of the Farmer",
    "type"              : "Type of Monitoring Site",
    "land_area"         : "Size of Monitoring Field (acres)",
    "gps"               : "Location of Monitoring Sites - GPS",
    "method"            : "Method of Cultivation (Sowing)",
    "sowing_date"       : "Date of Sowing of Seeds in the Field",
    "cm_start"          : "Start Date of Continuous Monitoring",
    "cm_end"            : "End Date of Continuous Monitoring",
    "harvest_date"      : "Date of Harvest",
    "irrigations_a"     : "No. Irrigations (a) Reported",
    "irrigations_b"     : "No. Irrigations (b) Calculated",
    "days_monitored"    : "No. of Days Monitored",
    "duplicate_days"    : "No. of Duplicate Days",
    "missing_days"      : "No. of Missing Days",
    "error_margin"      : "Error Margin of Data Collection",
    "days_above"        : "No. of Days Water Level Stayed Above Surface",
    "days_below"        : "No. of Days Water Level Stayed Below Surface",
    "max_wl_events"     : "Days Water Level >10cm Above Surface (Deep Flood)",
    "min_wl_events"     : "Days Water Level >10cm Below Surface (Deep Dry)",
    "dry_days"          : "No. of Dry Days (Water Level >=25cm Below)",
    "drying_events"     : "No. of Field Drying Events (>=3 Consecutive Days Below Surface)",
    "max_dry_duration"  : "Max Dry Period Duration (days)",
    "avg_drying_overall": "Avg Drying Days (Overall)",
    "avg_drying_p1"     : "Avg Drying Days Phase 1 (0-30 DAS)",
    "avg_drying_p2"     : "Avg Drying Days Phase 2 (30-60 DAS)",
    "avg_drying_p3"     : "Avg Drying Days Phase 3 (60-90 DAS)",
    "avg_drying_p4"     : "Avg Drying Days Phase 4 (90+ DAS)",
    "rl_flood_mm"       : "RL-Flood (mm)",
    "rl_inter_mm"       : "RL-Inter (mm)",
    "rl_soil_mm"        : "RL-Soil (mm)",
    "fl_flood_mm"       : "FL-Flood (mm)",
    "fl_inter_mm"       : "FL-Inter (mm)",
    "fl_soil_mm"        : "FL-Soil (mm)",
    "total_water_mm"    : "Total Irrigated Water Depth (mm)",
    "total_water_m3"    : "Total Volumetric Water Irrigated (m3)",
    "total_recharged_mm": "Total Water Recharged (mm)",
    "total_recharged_m3": "Total Volumetric Water Recharged (m3)",
    "savings_pct"       : "Actual Water Savings (%)",
    "savings_mm"        : "Actual Water Savings (mm)",
    "savings_m3"        : "Actual Vol. Water Saving (m3)",
    "rainfall"          : "Total Rainfall During Monitoring Period (mm)",
    # These columns were removed outright in the v10 rewrite (not renamed) —
    # every place that reads them already falls back to "—" when absent, so
    # these mappings are kept only so those fallbacks stay well-defined.
    "avg_gopal_cm"      : "Avg Irrig. Depth - Gopal (cm)",
    "avg_between_dry"   : "Avg Wet Days Between Dry Cycles",
    "min_between_dry"   : "Min Days Between Dry Periods",
    "max_between_dry"   : "Max Days Between Dry Periods",
    "avg_between_wet"   : "Avg Days Between Wet Events",
    "min_between_wet"   : "Min Days Between Wet Events",
    "max_between_wet"   : "Max Days Between Wet Events",
}

# ═══════════════════════════════════════════════════════════════════
# TOOLTIPS — plain-English definitions for every displayed variable
# Source: AWD_Explainer_Document.docx (Method Explainer & Data Dictionary)
# ═══════════════════════════════════════════════════════════════════
TIPS = {
    # Identity / setup
    "farmer"      : "The registered name of the farmer. Used as the unique ID linking every sheet.",
    "village"     : "The Gram Panchayat (village cluster) the farmer's field belongs to.",
    "type"        : "Treatment = farmer follows the AWD protocol (checks the Pani pipe daily, irrigates only when the safe threshold is crossed). Control = conventional continuous flooding, no AWD protocol.",
    "method"      : "How the crop was established in the field — Transplanted or Broadcasted.",
    "land_area"   : "Size of the farmer's monitored field, in acres. Used to scale every water-volume (m³) calculation.",
    "sowing_date" : "The date the paddy crop was sown or transplanted. Used to calculate Days Since Sowing.",
    "crp"         : "The field officer (Community Resource Person) responsible for this farmer.",
    "cm_start"    : "Date of the first valid Pani pipe reading recorded for this farmer.",
    "cm_end"      : "Date of the most recent reading recorded for this farmer.",
    "harvest_date": "The date the crop was harvested, once recorded.",
    "gps"         : "The farmer's field location as \"Latitude, Longitude\" — used to place the pin on the map.",
    # Daily readings
    "date"        : "The calendar date of this water-level reading.",
    "das"         : "Days After Sowing — how many days have passed since the crop was sown (Date − Date of Sowing).",
    "monitoring_day": "The sequence number of this reading for the farmer (1st reading, 2nd reading, …). Not the same as Days After Sowing — this just counts monitored days in order, regardless of any gaps.",
    "pp_reading"  : "Pani Pipe reading in centimetres — the distance from the top of the pipe down to the water surface inside it. Lower = more flooded, higher = drier. Formula: BGL = 15 − PP Reading.",
    "duplicate"   : "Flags dates where more than one raw reading was submitted for this farmer and the readings were averaged together.",
    "zero_repl"   : "Flags a reading of 0 (physically impossible) that was automatically replaced with the previous day's value.",
    "bgl"         : "Water level relative to the soil surface, in cm (15 − PP Reading). Positive = water above the surface (flooded). Negative = water below the surface (drying).",
    "fl_rl"       : "Falling Limb (FL) = field is drying (today's level lower than yesterday's). Rising Limb (RL) = field is being re-wetted. NC = no change.",
    "phase"       : "One of six AWD cycle phases — FL-Flood, FL-Inter, FL-Soil (drying), then RL-Soil, RL-Inter, RL-Flood (re-wetting) — showing exactly where the field sits in the wet/dry cycle.",
    "change_wl"   : "Day-on-day change in water level, in cm. Positive = rising, negative = falling.",
    "event"       : "Simple wet/dry label for the day — wet when BGL ≥ 0 (water at or above the surface), dry when BGL < 0.",
    "gopal_cm"    : "Advisor Gopal's normalised irrigation depth (cm) for this day, adjusted for soil porosity (7%) so it's directly comparable across farmers regardless of field size.",
    "irrigated"   : "Whether the enumerator recorded that the field was irrigated on this date — a ground-truth field observation (\"Irrigations Reported\").",
    "irrig_calc"  : "A day is counted as an irrigation here if the water level rose by more than 2cm compared to the previous day (or, on a farmer's very first monitored day, if the level was already above 1cm) — worked out purely from the readings, independent of what the enumerator reported. Comparing this to \"Reported\" flags possible data-entry gaps.",
    "days_mon"    : "Total number of days with a valid reading for this farmer.",
    # Monitoring quality
    "days_monitored" : "Count of unique dates with a valid Pani pipe reading, after removing duplicate same-day entries.",
    "duplicate_days" : "Number of dates with more than one raw entry that had to be averaged together. High values can mean an enumerator is double-submitting.",
    "missing_days"   : "Calendar days between the first and last reading with no data recorded at all.",
    "error_margin"   : "Share of calendar days missing a reading (Missing Days ÷ Total Days). Above 20% suggests unreliable monitoring for that farmer.",
    # Water level status
    "days_above"  : "Number of days the field was flooded — water at or above the soil surface (BGL ≥ 0). AWD aims to reduce these days.",
    "days_below"  : "Number of days the field was drying — water below the soil surface (BGL < 0). AWD aims to safely increase these days.",
    "dry_days"    : "Number of days the field reached a deep-dry condition (PP reading ≥ 25cm, i.e. BGL ≤ −10cm) — a potential crop-stress threshold.",
    # Drying events
    "drying_events"   : "Number of distinct AWD drying cycles — periods where the water stayed continuously below the soil surface for 3 or more consecutive days.",
    "avg_between_dry" : "Average number of wet days between consecutive drying events. Shorter gaps mean faster AWD cycling.",
    "min_between_dry" : "Shortest wet gap between any two consecutive drying events.",
    "max_between_dry" : "Longest wet gap between any two consecutive drying events (excludes the final, possibly-ongoing gap).",
    # Irrigation counts
    "irrigations_a" : "Number of days the enumerator marked the field as irrigated in the field app — the ground-truth count (\"Reported\").",
    "irrigations_b" : "Number of days the water level rose by more than 2cm from the previous day, worked out purely from the readings (\"Calculated\"). Large gaps between Reported and Calculated flag data-quality issues worth checking.",
    "avg_between_wet": "Average number of days between consecutive irrigation (re-flooding) events. Longer gaps generally mean better AWD practice.",
    "min_between_wet": "Shortest gap between any two consecutive irrigation (re-flooding) events.",
    "max_between_wet": "Longest gap between any two consecutive irrigation (re-flooding) events (excludes the final, possibly-ongoing gap).",
    # Drying duration by stage
    "avg_drying_overall": "Average duration, in days, of all drying events across the full season.",
    "avg_drying_p1" : "Average drying-event duration during 0–30 Days After Sowing — early vegetative stage, roots shallow, demand low.",
    "avg_drying_p2" : "Average drying-event duration during 30–60 Days After Sowing — active tillering, water demand increases.",
    "avg_drying_p3" : "Average drying-event duration during 60–90 Days After Sowing — panicle initiation, a critical reproductive stage.",
    "avg_drying_p4" : "Average drying-event duration during 90+ Days After Sowing — grain filling and maturity, longer dry spells are often fine here.",
    # Extremes
    "max_wl_events" : "Count of days the water level was more than 10cm above the soil surface — flags over-flooding / excess water input.",
    "min_wl_events" : "Count of days the water level was more than 10cm below the soil surface — flags deep drying / potential crop stress.",
    "max_dry_duration" : "The longest single drying event this season, in days.",
    "rainfall"         : "Total rainfall recorded during the monitoring period, in millimetres.",
    # Water volumes
    "total_water_mm"     : "Total irrigation water added across the season, in millimetres depth, using Gopal's normalised formula.",
    "total_water_m3"     : "Total irrigation water added across the season, in cubic metres — depth scaled by the field's land area.",
    "total_recharged_mm" : "Total water drained from the field across the season (Falling Limb / drying events), in millimetres depth.",
    "total_recharged_m3" : "Total water drained from the field across the season, in cubic metres.",
    "avg_gopal_cm"       : "Average of all per-irrigation-event Gopal depth values (cm) across the season — a field-size-independent metric, so it's fair to compare across farmers. (Removed from the current sheet — shown as \"—\" where it can't be found.)",
    "rl_flood_mm" : "Total irrigation depth (mm) accumulated on RL-Flood days this season — full depth counted, both above ground.",
    "rl_inter_mm" : "Total irrigation depth (mm) accumulated on RL-Inter days this season — split formula as water crosses the surface upward.",
    "rl_soil_mm"  : "Total irrigation depth (mm) accumulated on RL-Soil days this season — porosity-adjusted, both below ground.",
    "fl_flood_mm" : "Total depth (mm) drained on FL-Flood days this season (negative — water lost, both above ground).",
    "fl_inter_mm" : "Total depth (mm) drained on FL-Inter days this season (negative — split formula, crossing surface downward).",
    "fl_soil_mm"  : "Total depth (mm) drained on FL-Soil days this season (negative — porosity-adjusted, both below ground).",
    # App-level concepts
    "safe_zone"      : "The −5 to +10 cm BGL band shaded green on these charts — a water level considered a good balance between the drying benefits of AWD and the risk of crop stress.",
    "tnau_baseline"  : "The Tamil Nadu Agricultural University conventional irrigation benchmark: 1.1 metres of water depth per acre per season (≈4,451.5 m³/acre). Used as the reference point for calculating water savings.",
    "savings_pct"    : "How much less water was used than the 1,100mm conventional-flooding benchmark, as a percentage. (Baseline − Actual Water Added) ÷ Baseline × 100.",
    "savings_mm"     : "How much less water was used than the 1,100mm conventional-flooding benchmark, in millimetres depth.",
    "savings_m3"     : "How much less water was used than the conventional-flooding benchmark, in cubic metres — scaled by the field's land area.",
    "village_filter" : "Restrict every chart and table on this page to farmers in the selected village(s) (Gram Panchayats).",
    "type_filter"    : "Show All farmers, only Treatment (AWD protocol) farmers, or only Control (conventional flooding) farmers.",
    "date_filter"    : "Restrict every chart and table to readings within this date range.",
}


def H(key):
    """Shorthand accessor for a tooltip string."""
    return TIPS.get(key, "")


# ═══════════════════════════════════════════════════════════════════
# DATA LOADING
# ═══════════════════════════════════════════════════════════════════

@st.cache_data(ttl=3600)
def load_master(url):
    if "PASTE_YOUR" in url:
        return pd.DataFrame()
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        df = pd.read_csv(StringIO(r.text))
        for col in [M["date"], M["sowing_date"]]:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], dayfirst=True, errors="coerce")
        num_cols = [M["land_area"], M["monitoring_day"], M["pp_reading"], M["bgl"],
                    M["change_wl"], M["gopal_cm"], M["days_mon"]]
        for col in num_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        # Irrigation Reported / Calculated are written as YES/NO strings (v9)
        for col in [M["irrigated"], M["irrig_calc"]]:
            if col in df.columns:
                df[col] = df[col].astype(str).str.strip().str.upper() == "YES"
        for col in [M["farmer"], M["village"], M["type"], M["phase"], M["fl_rl"], M["event"]]:
            if col in df.columns:
                df[col] = df[col].astype(str).str.strip()
        df = df.sort_values([M["farmer"], M["date"]]).reset_index(drop=True)
        # Derived: real Days After Sowing (the sheet's own "Monitoring Day" column
        # is just a sequential reading count, not this) — used for the DAS-aligned trend.
        if M["date"] in df.columns and M["sowing_date"] in df.columns:
            df[DAS_COL] = (df[M["date"]] - df[M["sowing_date"]]).dt.days
        return df
    except Exception as e:
        st.error(f"Error loading Master Analysis: {e}")
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def load_summary(url):
    if "PASTE_YOUR" in url:
        return pd.DataFrame()
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        df = pd.read_csv(StringIO(r.text))
        for col in [S["sowing_date"], S["cm_start"], S["cm_end"], S["harvest_date"]]:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], dayfirst=True, errors="coerce")
        num_s = [v for k, v in S.items()
                 if k not in ["serial", "farmer", "village", "type", "method",
                              "sowing_date", "cm_start", "cm_end", "harvest_date", "gps",
                              "savings_pct"]]
        for col in num_s:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        # Actual Water Savings (%) is a Sheets custom text format ('0.00"%"'),
        # so it's exported as a literal string like "-40.69%" — strip the % first.
        if S["savings_pct"] in df.columns:
            df[S["savings_pct"]] = pd.to_numeric(
                df[S["savings_pct"]].astype(str).str.rstrip("%").str.strip(), errors="coerce")
        for col in [S["farmer"], S["village"], S["type"], S["gps"]]:
            if col in df.columns:
                df[col] = df[col].astype(str).str.strip()
        return df
    except Exception as e:
        st.error(f"Error loading Summary: {e}")
        return pd.DataFrame()


# ═══════════════════════════════════════════════════════════════════
# MAP — village boundaries + farmer locations (from bundled GeoJSON)
# ═══════════════════════════════════════════════════════════════════

@st.cache_data
def load_geojson(filename):
    path = GEO_DIR / filename
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def render_farmer_map(summary):
    """Boundary + pin-point map for every currently-filtered farmer, coloured by Type."""
    pts_geo = load_geojson("farmer_points.geojson")
    gp_geo = load_geojson("gp_boundary.geojson")
    cmd_geo = load_geojson("command_area.geojson")

    if pts_geo is None:
        st.info("Map data not found — expected a `geo/farmer_points.geojson` file next to app.py.")
        return

    # Farmer -> season info, from the currently filtered Summary (respects sidebar filters)
    farmers = []
    if not summary.empty:
        for _, row in summary.iterrows():
            name = str(row.get(S["farmer"], "")).strip()
            if not name or name.lower() == "nan":
                continue
            farmers.append((name, {
                "type": relabel_type(row.get(S["type"])),
                "village": row.get(S["village"], ""),
                "land_area": row.get(S["land_area"]),
                "irrig_mm": row.get(S["total_water_mm"]),
                "savings_mm": row.get(S["savings_mm"]),
            }))

    # Index geo points for lookup: exact name, name with word order/punctuation
    # normalised away, and grouped by village for a same-village fuzzy fallback
    # (Backend Data and the monitoring-sites shapefile don't always spell/order
    # a farmer's name identically — e.g. "G.Manikandan" vs "Manikandan.G").
    def _norm(n):
        return " ".join(sorted(str(n).replace(".", " ").split())).lower()

    geo_by_exact, geo_by_norm, geo_by_village = {}, {}, {}
    for feat in pts_geo["features"]:
        raw = str(feat["properties"].get("farmer", "")).strip()
        if not raw:
            continue
        village_key = str(feat["properties"].get("village", "")).strip().lower()
        geo_by_exact.setdefault(raw.lower(), feat)
        geo_by_norm.setdefault(_norm(raw), feat)
        geo_by_village.setdefault(village_key, []).append((_norm(raw), feat))

    plotted = []
    for name, info in farmers:
        feat = geo_by_exact.get(name.lower()) or geo_by_norm.get(_norm(name))
        if feat is None:
            village_key = str(info.get("village", "")).strip().lower()
            name_norm = _norm(name)
            best, best_ratio = None, 0.0
            for cand_norm, cand_feat in geo_by_village.get(village_key, []):
                ratio = difflib.SequenceMatcher(None, name_norm, cand_norm).ratio()
                if ratio > best_ratio:
                    best_ratio, best = ratio, cand_feat
            if best is not None and best_ratio >= 0.8:
                feat = best
        if feat is None:
            continue
        lon, lat = feat["geometry"]["coordinates"]
        plotted.append((name, lat, lon, info))

    if not plotted:
        st.info("None of the currently filtered farmers have a mapped location yet.")
        return

    lats = [p[1] for p in plotted]
    lons = [p[2] for p in plotted]
    m = folium.Map(location=[sum(lats) / len(lats), sum(lons) / len(lons)],
                    zoom_start=12, tiles="CartoDB positron")

    if gp_geo:
        folium.GeoJson(
            gp_geo, name="Village (GP) Boundaries",
            style_function=lambda f: {"fillColor": C["accent"], "color": C["accent"],
                                       "weight": 2, "fillOpacity": 0.04},
            tooltip=folium.GeoJsonTooltip(fields=["village"], aliases=["Village:"]),
        ).add_to(m)

    if cmd_geo:
        cmd_colors = {"Command": C["treatment"], "Non command": C["control"],
                      "Non Command area (Tail end)": "#8B4513"}
        folium.GeoJson(
            cmd_geo, name="Command Area Classification",
            style_function=lambda f: {
                "fillColor": cmd_colors.get(f["properties"].get("classification"), "#999"),
                "color": cmd_colors.get(f["properties"].get("classification"), "#999"),
                "weight": 1, "fillOpacity": 0.10},
            tooltip=folium.GeoJsonTooltip(fields=["classification", "detail"],
                                           aliases=["Classification:", "Detail:"]),
        ).add_to(m)

    for name, lat, lon, info in plotted:
        grp = info["type"]
        color = GROUP_COLOR.get(grp, "#999999")
        land = info.get("land_area")
        land_txt = f"{land:.2f} ac" if pd.notna(land) else "—"
        irrig = info.get("irrig_mm")
        irrig_txt = f"{irrig:,.0f} mm" if pd.notna(irrig) else "—"
        savings = info.get("savings_mm")
        savings_txt = f"{savings:,.0f} mm" if pd.notna(savings) else "—"
        popup_html = (f"<b>{name}</b><br>{info.get('village', '')}<br>"
                       f"{grp}<br>Land: {land_txt}<br>"
                       f"Irrigation Depth: {irrig_txt}<br>"
                       f"Actual Water Savings: {savings_txt}")
        folium.CircleMarker(
            location=[lat, lon], radius=6, color="white", weight=1,
            fill=True, fill_color=color, fill_opacity=0.9,
            popup=folium.Popup(popup_html, max_width=220), tooltip=name,
        ).add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    st_folium(m, use_container_width=True, height=460, returned_objects=[])
    st.caption(f"📍 {len(plotted)} of {len(farmers)} currently filtered farmers have a "
               f"mapped location. 🔵 Treatment · 🟠 Control")


# ═══════════════════════════════════════════════════════════════════
# HELPER — chart theming (single light theme, consistent across all charts)
# ═══════════════════════════════════════════════════════════════════

def style_fig(fig, height=300, legend=True):
    fig.update_layout(
        height=height,
        margin=dict(l=10, r=10, t=10, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=C["surface"],
        font=dict(color=C["text"]),
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                     font=dict(size=10)) if legend else None,
    )
    fig.update_xaxes(showgrid=True, gridcolor=C["grid"])
    fig.update_yaxes(showgrid=True, gridcolor=C["grid"])
    return fig


def metric_card(col, label, value, sub, tip_key, accent):
    with col:
        with st.container(border=True):
            st.markdown(
                f"<div style='height:4px;background:{accent};border-radius:3px;"
                f"margin:-1rem -1rem 0.6rem -1rem;'></div>",
                unsafe_allow_html=True,
            )
            st.metric(label, value, sub, help=H(tip_key), delta_color="off")


# Safe column access — the Google Sheet can occasionally serve a partial CSV
# snapshot (e.g. fetched mid-rewrite while the Apps Script rebuilds it), or a
# column can be renamed upstream. These helpers keep a stale/incomplete fetch
# from crashing the whole page — missing data shows as "—" instead of an error.

def safe_mean(df, col):
    return df[col].mean() if (not df.empty and col in df.columns) else None


def safe_sum(df, col):
    return df[col].sum() if (not df.empty and col in df.columns) else None


def safe_nunique(df, col):
    return df[col].nunique() if (not df.empty and col in df.columns) else 0


def fmt_or_dash(val, fmt_str="{:.1f}"):
    return fmt_str.format(val) if val is not None and pd.notna(val) else "—"


# ═══════════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════════

def render_sidebar(master, summary):
    with st.sidebar:
        st.markdown(
            f"<div style='text-align:center;padding:12px;"
            f"background:{C['accent']};border-radius:10px;margin-bottom:12px;'>"
            f"<div style='font-size:36px;'>🌾</div>"
            f"<div style='color:#FFFFFF;font-weight:700;font-size:15px;'>"
            f"AWD Dashboard</div></div>",
            unsafe_allow_html=True,
        )

        fm, fs = master.copy(), summary.copy()

        if not master.empty and M["date"] in master.columns:
            st.markdown("**📅 Date Range**")
            mn, mx = master[M["date"]].min(), master[M["date"]].max()
            dr = st.date_input("range", value=(mn, mx),
                               min_value=mn, max_value=mx,
                               label_visibility="collapsed",
                               help=H("date_filter"))
            if len(dr) == 2:
                fm = fm[(fm[M["date"]] >= pd.Timestamp(dr[0])) &
                        (fm[M["date"]] <= pd.Timestamp(dr[1]))]

        st.divider()
        st.markdown("**🏘️ Village**")
        if not master.empty:
            all_v = sorted(master[M["village"]].dropna().unique())
            sel_v = st.multiselect("v", all_v, default=all_v,
                                   label_visibility="collapsed",
                                   placeholder="All villages",
                                   help=H("village_filter"))
            if sel_v:
                fm = fm[fm[M["village"]].isin(sel_v)]
                fs = fs[fs[S["village"]].isin(sel_v)]

        st.divider()
        st.markdown("**🌱 Field Type**")
        sel_t = st.radio("t", ["All", "Treatment", "Control"],
                         label_visibility="collapsed", help=H("type_filter"))
        if sel_t == "Treatment":
            fm = fm[to_group(fm[M["type"]]) == "Treatment"]
            fs = fs[to_group(fs[S["type"]]) == "Treatment"]
        elif sel_t == "Control":
            fm = fm[to_group(fm[M["type"]]) == "Control"]
            fs = fs[to_group(fs[S["type"]]) == "Control"]

        st.divider()
        if not fm.empty:
            st.markdown(
                f"<div style='background:{C['surface']};border:1px solid {C['border']};"
                f"border-radius:8px;padding:10px;font-size:12px;color:{C['text']};'>"
                f"👤 <b>{fm[M['farmer']].nunique()}</b> farmers<br>"
                f"🏘️ <b>{fm[M['village']].nunique()}</b> villages<br>"
                f"📋 <b>{len(fm):,}</b> readings</div>",
                unsafe_allow_html=True,
            )
        st.markdown("")
        if st.button("🔄 Refresh Data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
        st.caption("Auto-refreshes every hour.")

    return fm, fs


# ═══════════════════════════════════════════════════════════════════
# HEADER
# ═══════════════════════════════════════════════════════════════════

def render_header(master):
    c1, c2 = st.columns([3, 1])
    with c1:
        st.markdown(
            f"<h1 style='color:{C['text']};font-size:24px;margin:0;'>"
            "🌾 Evaluation of the Alternate Wetting and Drying (AWD) of Paddy</h1>",
            unsafe_allow_html=True,
        )
    with c2:
        if not master.empty and M["date"] in master.columns:
            mn = master[M["date"]].min()
            mx = master[M["date"]].max()
            if pd.notna(mn) and pd.notna(mx):
                st.markdown(
                    f"<div style='text-align:right;padding-top:12px;'>"
                    f"<span style='background:{C['surface']};border:1px solid {C['border']};"
                    f"border-radius:6px;padding:5px 10px;font-size:12px;color:{C['text']};font-weight:600;'>"
                    f"📅 {mn.strftime('%d %b %Y')} → {mx.strftime('%d %b %Y')}"
                    f"</span></div>",
                    unsafe_allow_html=True,
                )
    st.divider()


# ═══════════════════════════════════════════════════════════════════
# TAB 1 — RESULTS OVERVIEW
# ═══════════════════════════════════════════════════════════════════

def tab_results_overview(master_f, summary_f, master, summary):
    """master_f/summary_f = sidebar-filtered (used by the two Row-2 charts).
    master/summary = full unfiltered cohort (used by every box/table/map —
    this tab is a fixed headline summary of the whole n=100 study)."""
    if summary.empty and master.empty:
        st.info("No data loaded.")
        return

    # ── Subtitle + conceptual diagram ────────────────────────────────
    csub, cimg = st.columns([2, 1])
    with csub:
        st.markdown(
            "This dashboard presents the key findings from an impact evaluation study "
            "conducted by WELL Labs, assessing the Alternate Wetting and Drying (AWD) "
            "intervention promoted by the M. S. Swaminathan Research Foundation (MSSRF) "
            "in Theni district, Tamil Nadu. The initiative was implemented under a "
            "Corporate Social Responsibility (CSR) project aimed at addressing water "
            "scarcity in the region.\n\n"
            "To quantify the effectiveness of the AWD practice, WELL Labs designed a "
            "robust comparative study. From a total cohort of 700 farmers across 7 "
            "villages, a representative sample of 100 farmers was selected using a "
            "stratified random sampling technique. This rigorous approach ensures that "
            "the results accurately reflect the diverse conditions across the "
            "intervention area.\n\n"
            "The core objective of this evaluation is to measure tangible water savings "
            "achieved through the adoption of AWD. Daily water levels were "
            "systematically monitored using the \"Pani Pipe\" method across both "
            "Treatment (AWD-adopting) and Control (conventional practice) fields. The "
            "resulting data has been analyzed to determine the differential in water "
            "consumption between the two groups.\n\n"
            "For a detailed understanding of the data collection process, please refer "
            "to the <a href=\"#\">Playbook for Measuring Water Level Using Pani "
            "Pipes</a>."
        , unsafe_allow_html=True)
    with cimg:
        img_path = Path(__file__).parent / "assets" / "awd_conceptual_diagram.png"
        if img_path.exists():
            st.image(str(img_path),
                caption="AWD Conceptual diagram: Water savings from AWD occurs by "
                        "reducing the total number of irrigations, thereby reducing "
                        "evaporative losses from standing water.",
                use_container_width=True)
    st.divider()

    # ── Map + farmer-distribution table ──────────────────────────────
    cmap, ctable = st.columns([1, 1])
    with cmap:
        st.subheader("Farmer Locations & Village Boundaries", help=H("gps"))
        st.caption("Every farmer in the study (n=100), pinned by GPS location. Toggle boundary layers with the control in the top-right of the map.")
        render_farmer_map(summary)
    with ctable:
        st.subheader("Distribution of Farmers Identified for This Evaluation (n=100)")
        if not summary.empty:
            sm = summary.copy()
            sm["Group"] = to_group(sm[S["type"]])
            dist = pd.crosstab(sm[S["village"]], sm["Group"])
            for grp in ["Treatment", "Control"]:
                if grp not in dist.columns:
                    dist[grp] = 0
            dist = dist[["Treatment", "Control"]]
            dist["Total"] = dist["Treatment"] + dist["Control"]
            dist.loc["Total"] = dist.sum()
            st.dataframe(dist, use_container_width=True, height=320)

    st.divider()

    # ── Key performance results ──────────────────────────────────────
    sv_t = summary[to_group(summary[S["type"]]) == "Treatment"] if not summary.empty else summary
    sv_c = summary[to_group(summary[S["type"]]) == "Control"] if not summary.empty else summary

    ckpi, cbaseline = st.columns([4, 1])
    with ckpi:
        st.markdown("**Key Performance Results**")
        n_awd    = safe_nunique(sv_t, S["farmer"])
        n_pos    = int((sv_t[S["savings_pct"]] > 0).sum()) if S["savings_pct"] in sv_t.columns else 0
        n_neg    = int((sv_t[S["savings_pct"]] < 0).sum()) if S["savings_pct"] in sv_t.columns else 0
        avg_pct  = safe_mean(sv_t, S["savings_pct"])
        avg_mm   = safe_mean(sv_t, S["savings_mm"])
        total_m3 = safe_sum(sv_t, S["savings_m3"])

        k1, k2, k3 = st.columns(3)
        metric_card(k1, "No. of AWD Farmers", f"{n_awd:,}", "Treatment only", "type", C["treatment"])
        metric_card(k2, "Farmers with +ve Savings", f"{n_pos:,}", "Treatment only", "savings_pct", C["accent"])
        metric_card(k3, "Farmers with -ve Savings", f"{n_neg:,}", "Treatment only", "savings_pct", C["control"])
        k4, k5, k6 = st.columns(3)
        metric_card(k4, "Avg Actual Savings", fmt_or_dash(avg_pct, "{:.1f}%"), "Treatment only", "savings_pct", C["accent"])
        metric_card(k5, "Avg Actual Savings", fmt_or_dash(avg_mm, "{:,.0f} mm"), "Treatment only", "savings_mm", C["accent"])
        metric_card(k6, "Total Volumetric Savings", fmt_or_dash(total_m3, "{:,.0f} m³"), "Treatment only, aggregate", "savings_m3", C["accent"])
    with cbaseline:
        st.markdown("**Baseline**")
        with st.container(border=True):
            st.markdown(
                "The baseline irrigation depth used is <b>1100mm</b> irrigated water "
                "depth for paddy in Tamil Nadu based on "
                "<a href=\"http://www.agritech.tnau.ac.in/agriculture/agri_cropproduction_cereals_rice_tranpudlow_mainfield_water_mgmt.html\" "
                "target=\"_blank\"><b>TNAU</b></a> standards.",
                unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Irrigation count boxes (Treatment only, Calculated) ──────────
    st.markdown("**Irrigations (Treatment only)**")
    i1, i2, i3 = st.columns(3)
    irr_avg = safe_mean(sv_t, S["irrigations_b"])
    irr_max = sv_t[S["irrigations_b"]].max() if S["irrigations_b"] in sv_t.columns and not sv_t.empty else None
    irr_min = sv_t[S["irrigations_b"]].min() if S["irrigations_b"] in sv_t.columns and not sv_t.empty else None
    metric_card(i1, "Average No. of Irrigations", fmt_or_dash(irr_avg, "{:.1f}"), "", "irrigations_b", C["treatment"])
    metric_card(i2, "Max Irrigations", fmt_or_dash(irr_max, "{:.0f}"), "", "irrigations_b", C["treatment"])
    metric_card(i3, "Min Irrigations", fmt_or_dash(irr_min, "{:.0f}"), "", "irrigations_b", C["treatment"])

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Irrigation depth boxes — Treatment (blue) then Control (light red) ──
    st.markdown("**Irrigation Depth (mm) — Treatment**")
    dt1, dt2, dt3 = st.columns(3)
    t_max = sv_t[S["total_water_mm"]].max() if S["total_water_mm"] in sv_t.columns and not sv_t.empty else None
    t_min = sv_t[S["total_water_mm"]].min() if S["total_water_mm"] in sv_t.columns and not sv_t.empty else None
    t_avg = safe_mean(sv_t, S["total_water_mm"])
    metric_card(dt1, "Max Irrigation Depth", fmt_or_dash(t_max, "{:,.0f} mm"), "Treatment", "total_water_mm", C["treatment"])
    metric_card(dt2, "Min Irrigation Depth", fmt_or_dash(t_min, "{:,.0f} mm"), "Treatment", "total_water_mm", C["treatment"])
    metric_card(dt3, "Average Irrigation Depth", fmt_or_dash(t_avg, "{:,.0f} mm"), "Treatment", "total_water_mm", C["treatment"])

    st.markdown("**Irrigation Depth (mm) — Control**")
    dc1, dc2, dc3 = st.columns(3)
    c_max = sv_c[S["total_water_mm"]].max() if S["total_water_mm"] in sv_c.columns and not sv_c.empty else None
    c_min = sv_c[S["total_water_mm"]].min() if S["total_water_mm"] in sv_c.columns and not sv_c.empty else None
    c_avg = safe_mean(sv_c, S["total_water_mm"])
    metric_card(dc1, "Max Irrigation Depth", fmt_or_dash(c_max, "{:,.0f} mm"), "Control", "total_water_mm", C["control"])
    metric_card(dc2, "Min Irrigation Depth", fmt_or_dash(c_min, "{:,.0f} mm"), "Control", "total_water_mm", C["control"])
    metric_card(dc3, "Average Irrigation Depth", fmt_or_dash(c_avg, "{:,.0f} mm"), "Control", "total_water_mm", C["control"])

    st.divider()

    # ── Row 1 charts (sidebar-filtered) ──────────────────────────────
    cl, cr = st.columns([1.3, 1])

    with cl:
        st.subheader("Water Level Changes in the Field", help=H("das"))
        st.caption("Avg water level on field vs Days After Sowing · Treatment vs Control · green band = safe zone")
        if not master_f.empty and M["das"] in master_f.columns:
            mm = master_f.copy()
            mm["Group"] = to_group(mm[M["type"]])
            mm = mm[mm[M["das"]].notna() & (mm[M["das"]] >= 0)]
            mm["das_week"] = (mm[M["das"]] // 7) * 7
            wk = mm.groupby(["das_week", "Group"])[M["bgl"]].mean().reset_index()
            fig = go.Figure()
            fig.add_hrect(y0=-5, y1=10, fillcolor=C["safe_zone"],
                          line_width=0, annotation_text="Safe zone",
                          annotation_font_color=C["accent"],
                          annotation_position="top left")
            for grp in ["Treatment", "Control"]:
                sub = wk[wk["Group"] == grp].sort_values("das_week")
                if sub.empty: continue
                fig.add_trace(go.Scatter(x=sub["das_week"], y=sub[M["bgl"]],
                    name=grp, mode="lines+markers",
                    line=dict(color=GROUP_COLOR[grp], width=2.5), marker=dict(size=5),
                    hovertemplate=f"<b>{grp}</b><br>Day %{{x:.0f}}+ after sowing<br>Avg level: %{{y:.1f}} cm<extra></extra>"))
            fig.add_hline(y=0, line_dash="dash", line_color="#999", line_width=1)
            fig.update_layout(xaxis=dict(title="Days After Sowing"),
                               yaxis=dict(title="Water Level on Field (cm)"))
            style_fig(fig, height=340)
            st.plotly_chart(fig, use_container_width=True)

    with cr:
        st.subheader("Hydrological Phase Distribution (AWD vs. Continuous Flooding)", help=H("phase"))
        st.caption("Outer ring = Treatment (blue) · Inner ring = Control (red) · FL group then RL group")
        if not master_f.empty:
            def _phase_counts(df):
                pc = df[M["phase"]].value_counts().reset_index()
                pc.columns = ["phase", "count"]
                pc["phase"] = pd.Categorical(pc["phase"], categories=PHASE_ORDER, ordered=True)
                return pc.sort_values("phase").dropna(subset=["phase"])

            mm = master_f.copy()
            mm["Group"] = to_group(mm[M["type"]])
            pc_t = _phase_counts(mm[mm["Group"] == "Treatment"])
            pc_c = _phase_counts(mm[mm["Group"] == "Control"])

            fig_donut = go.Figure()
            if not pc_t.empty:
                fig_donut.add_trace(go.Pie(
                    labels=pc_t["phase"], values=pc_t["count"], sort=False,
                    hole=0.62, domain=dict(x=[0, 1], y=[0, 1]),
                    marker=dict(colors=[C["phase_treatment"].get(p, "#999") for p in pc_t["phase"]],
                                line=dict(color="white", width=1)),
                    textinfo="none", name="Treatment",
                    hovertemplate="<b>Treatment</b><br>%{label}: %{percent}<extra></extra>"))
            if not pc_c.empty:
                fig_donut.add_trace(go.Pie(
                    labels=pc_c["phase"], values=pc_c["count"], sort=False,
                    hole=0.35, domain=dict(x=[0.19, 0.81], y=[0.19, 0.81]),
                    marker=dict(colors=[C["phase_control"].get(p, "#999") for p in pc_c["phase"]],
                                line=dict(color="white", width=1)),
                    textinfo="none", name="Control",
                    hovertemplate="<b>Control</b><br>%{label}: %{percent}<extra></extra>"))
            fig_donut.update_layout(height=340, margin=dict(l=10, r=10, t=10, b=10),
                paper_bgcolor="rgba(0,0,0,0)", showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=-0.18, xanchor="center", x=0.5, font_size=9))
            st.plotly_chart(fig_donut, use_container_width=True)

    st.divider()

    # ── Row 2 charts (sidebar-filtered, grouped bar by village) ──────
    c9a, c9b = st.columns(2)
    with c9a:
        st.subheader("Irrigation Depth Distribution — Control and Treatment", help=H("total_water_mm"))
        if not summary_f.empty and S["total_water_mm"] in summary_f.columns:
            sm = summary_f.copy()
            sm["Group"] = to_group(sm[S["type"]])
            vw = (sm.groupby([S["village"], "Group"])[S["total_water_mm"]]
                  .mean().reset_index())
            fig9a = px.bar(vw, x=S["village"], y=S["total_water_mm"], color="Group",
                barmode="group", color_discrete_map=GROUP_COLOR,
                labels={S["total_water_mm"]: "Avg Irrigation Depth (mm)", S["village"]: ""}, height=300)
            style_fig(fig9a, height=300)
            st.plotly_chart(fig9a, use_container_width=True)

    with c9b:
        st.subheader("No. of Irrigations", help=H("irrigations_b"))
        if not summary_f.empty and S["irrigations_b"] in summary_f.columns:
            sm = summary_f.copy()
            sm["Group"] = to_group(sm[S["type"]])
            vi = (sm.groupby([S["village"], "Group"])[S["irrigations_b"]]
                  .mean().reset_index())
            fig9b = px.bar(vi, x=S["village"], y=S["irrigations_b"], color="Group",
                barmode="group", color_discrete_map=GROUP_COLOR,
                labels={S["irrigations_b"]: "Avg No. of Irrigations", S["village"]: ""}, height=300)
            style_fig(fig9b, height=300)
            st.plotly_chart(fig9b, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════
# TAB 3 — COMPARE FARMERS
# ═══════════════════════════════════════════════════════════════════

def tab_compare_farmers(master, summary):
    st.markdown("### Compare Farmers")
    st.caption("Pick one Treatment farmer and one Control farmer to compare their water-level trend and season metrics side by side.")

    if master.empty or summary.empty:
        st.warning("Both Master Analysis and Summary sheets are needed for this comparison.")
        return

    cL, cR = st.columns(2)
    with cL:
        st.markdown("**Treatment Farmer**")
        vt_pool = sorted(master[to_group(master[M["type"]]) == "Treatment"][M["village"]].dropna().unique())
        if not vt_pool:
            st.warning("No Treatment farmers found.")
            return
        village_t = st.selectbox("Village", vt_pool, key="cmp_village_t", help=H("village_filter"))
        ft_pool = sorted(master[(master[M["village"]] == village_t) &
                                 (to_group(master[M["type"]]) == "Treatment")][M["farmer"]].dropna().unique())
        if not ft_pool:
            st.warning("No Treatment farmers in this village.")
            return
        farmer_t = st.selectbox("Farmer", ft_pool, key="cmp_farmer_t", help=H("farmer"))
    with cR:
        st.markdown("**Control Farmer**")
        vc_pool = sorted(master[to_group(master[M["type"]]) == "Control"][M["village"]].dropna().unique())
        if not vc_pool:
            st.warning("No Control farmers found.")
            return
        village_c = st.selectbox("Village", vc_pool, key="cmp_village_c", help=H("village_filter"))
        fc_pool = sorted(master[(master[M["village"]] == village_c) &
                                 (to_group(master[M["type"]]) == "Control")][M["farmer"]].dropna().unique())
        if not fc_pool:
            st.warning("No Control farmers in this village.")
            return
        farmer_c = st.selectbox("Farmer", fc_pool, key="cmp_farmer_c", help=H("farmer"))

    fmt = master[master[M["farmer"]] == farmer_t].sort_values(M["date"])
    fmc = master[master[M["farmer"]] == farmer_c].sort_values(M["date"])
    fst = summary[summary[S["farmer"]] == farmer_t]
    fsc = summary[summary[S["farmer"]] == farmer_c]

    st.subheader(f"Water Level Trend — {farmer_t} vs {farmer_c}", help=H("bgl"))
    st.caption("Daily BGL (water level relative to soil surface). ▲ = irrigation reported.")
    fig2 = go.Figure()
    fig2.add_hrect(y0=-5, y1=10, fillcolor=C["safe_zone"], line_width=0)
    fig2.add_trace(go.Scatter(x=fmt[M["date"]], y=fmt[M["bgl"]], name=f"{farmer_t} (Treatment)",
        mode="lines", line=dict(color=C["treatment"], width=2.5),
        hovertemplate="%{x|%d %b}<br>BGL: %{y:+.1f} cm<extra></extra>"))
    fig2.add_trace(go.Scatter(x=fmc[M["date"]], y=fmc[M["bgl"]], name=f"{farmer_c} (Control)",
        mode="lines", line=dict(color=C["control"], width=2.5),
        hovertemplate="%{x|%d %b}<br>BGL: %{y:+.1f} cm<extra></extra>"))
    irt = fmt[fmt[M["irrigated"]] == True]
    irc = fmc[fmc[M["irrigated"]] == True]
    if not irt.empty:
        fig2.add_trace(go.Scatter(x=irt[M["date"]], y=irt[M["bgl"]], mode="markers",
            name="Irrigation (Treatment)",
            marker=dict(symbol="triangle-up", size=9, color=C["treatment"], line=dict(color="white", width=1))))
    if not irc.empty:
        fig2.add_trace(go.Scatter(x=irc[M["date"]], y=irc[M["bgl"]], mode="markers",
            name="Irrigation (Control)",
            marker=dict(symbol="triangle-up", size=9, color=C["control"], line=dict(color="white", width=1))))
    fig2.add_hline(y=0, line_dash="dash", line_color="#999", line_width=1)
    fig2.update_layout(yaxis=dict(title="BGL (cm)"))
    style_fig(fig2, height=340)
    st.plotly_chart(fig2, use_container_width=True)

    rowt = fst.iloc[0] if not fst.empty else None
    rowc = fsc.iloc[0] if not fsc.empty else None

    def _num(row, key):
        if row is None: return None
        v = row.get(S[key])
        return float(v) if pd.notna(v) else None

    st.divider()
    st.markdown("#### Key Performance Indicators")
    st.caption(f"{farmer_c} (Control) vs {farmer_t} (Treatment) — see the Playbook for Measuring Water Level Using Pani Pipes for the calculation method.")

    t_mm, c_mm = _num(rowt, "total_water_mm"), _num(rowc, "total_water_mm")
    t_m3, c_m3 = _num(rowt, "total_water_m3"), _num(rowc, "total_water_m3")
    pot_m3 = _num(rowt, "savings_m3")

    water_savings_mm  = (c_mm - t_mm) if t_mm is not None and c_mm is not None else None
    water_savings_pct = (water_savings_mm / c_mm * 100) if water_savings_mm is not None and c_mm else None
    actual_vol_savings = (c_m3 - t_m3) if t_m3 is not None and c_m3 is not None else None

    metric_card(st.container(), "Water Savings (mm)", fmt_or_dash(water_savings_mm, "{:+,.0f} mm"),
                f"{farmer_c} minus {farmer_t}", "savings_mm", C["accent"])
    metric_card(st.container(), "Water Savings (%)", fmt_or_dash(water_savings_pct, "{:+.1f}%"),
                f"{farmer_c} minus {farmer_t}", "savings_pct", C["accent"])
    metric_card(st.container(), "Actual Volumetric Savings (m³)", fmt_or_dash(actual_vol_savings, "{:+,.0f} m³"),
                f"{farmer_c} minus {farmer_t}", "savings_m3", C["accent"])
    metric_card(st.container(), "Potential Volumetric Savings (m³)", fmt_or_dash(pot_m3, "{:,.0f} m³"),
                f"{farmer_t} vs the 1100mm TNAU baseline", "savings_m3", C["treatment"])

    st.divider()
    st.markdown("#### Season Metrics — Side by Side")

    def fmt_val(row, key, fs="{:.1f}"):
        if row is None: return "—"
        v = row.get(S[key])
        return fs.format(v) if pd.notna(v) else "—"

    metrics = [
        ("Drying Events", "drying_events", "{:.0f}"),
        ("Irrigations (Reported)", "irrigations_a", "{:.0f}"),
        ("Irrigations (Calculated)", "irrigations_b", "{:.0f}"),
        ("Days Above Surface", "days_above", "{:.0f}"),
        ("Days Below Surface", "days_below", "{:.0f}"),
        ("Dry Days (>=25cm)", "dry_days", "{:.0f}"),
        ("Max Dry Period Duration (days)", "max_dry_duration", "{:.0f}"),
        ("Total Water Added (mm)", "total_water_mm", "{:,.0f}"),
        ("Total Water Recharged (mm)", "total_recharged_mm", "{:,.0f}"),
        ("Actual Water Savings (%)", "savings_pct", "{:.1f}"),
        ("Actual Water Savings (mm)", "savings_mm", "{:,.0f}"),
        ("Actual Vol. Water Saving (m³)", "savings_m3", "{:,.0f}"),
    ]
    for label, key, fs in metrics:
        cc1, cc2 = st.columns(2)
        with cc1:
            with st.container(border=True):
                st.markdown(f"<div style='height:4px;background:{C['treatment']};border-radius:3px;"
                             f"margin:-1rem -1rem 0.6rem -1rem;'></div>", unsafe_allow_html=True)
                st.metric(f"{label} — {farmer_t}", fmt_val(rowt, key, fs), help=H(key))
        with cc2:
            with st.container(border=True):
                st.markdown(f"<div style='height:4px;background:{C['control']};border-radius:3px;"
                             f"margin:-1rem -1rem 0.6rem -1rem;'></div>", unsafe_allow_html=True)
                st.metric(f"{label} — {farmer_c}", fmt_val(rowc, key, fs), help=H(key))

    st.divider()
    st.markdown("#### Performance Index")
    st.caption("Each metric is scaled 0–100 against the highest value seen among all farmers in the study, so the two farmers can be compared on one chart regardless of units. Negative values are floored at 0.")

    if rowt is not None and rowc is not None:
        radar_metrics = [
            ("Drying Events", "drying_events"),
            ("Days Below Surface", "days_below"),
            ("Irrigations Reported", "irrigations_a"),
            ("Water Savings %", "savings_pct"),
            ("Water Added (mm)", "total_water_mm"),
        ]
        cats, vt, vc = [], [], []
        for label, key in radar_metrics:
            col = S[key]
            if col not in summary.columns: continue
            mx = summary[col].max()
            if pd.isna(mx) or mx <= 0: continue
            tv = rowt.get(col)
            cv = rowc.get(col)
            cats.append(label)
            vt.append(max(0.0, float(tv) / mx * 100) if pd.notna(tv) else 0)
            vc.append(max(0.0, float(cv) / mx * 100) if pd.notna(cv) else 0)
        if cats:
            figr = go.Figure()
            figr.add_trace(go.Scatterpolar(r=vt + [vt[0]], theta=cats + [cats[0]],
                name=f"{farmer_t} (Treatment)", fill="toself",
                line=dict(color=C["treatment"]), opacity=0.8))
            figr.add_trace(go.Scatterpolar(r=vc + [vc[0]], theta=cats + [cats[0]],
                name=f"{farmer_c} (Control)", fill="toself",
                line=dict(color=C["control"]), opacity=0.8))
            figr.update_layout(
                polar=dict(bgcolor=C["surface"],
                           radialaxis=dict(visible=True, range=[0, 100], gridcolor=C["grid"])),
                height=420, paper_bgcolor="rgba(0,0,0,0)", font=dict(color=C["text"]),
                showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
            st.plotly_chart(figr, use_container_width=True)
        else:
            st.info("Not enough season data to build the performance index for this pair.")


# ═══════════════════════════════════════════════════════════════════
# TAB 3 — FARMER SUMMARY TABLE
# ═══════════════════════════════════════════════════════════════════

def tab_farmer_summary(summary):
    st.markdown("### Farmer Season Summary")
    if summary.empty:
        st.warning("Summary sheet not loaded.")
        return

    cs, cv, ct = st.columns(3)
    with cs: search = st.text_input("🔍 Search farmer", help=H("farmer"))
    with cv:
        vo = ["All"] + sorted(summary[S["village"]].dropna().unique())
        sv = st.selectbox("Village", vo, help=H("village_filter"))
    with ct:
        to = ["All", "Treatment", "Control"]
        st_t = st.selectbox("Type", to, help=H("type_filter"))

    ds = summary.copy()
    if search: ds = ds[ds[S["farmer"]].str.contains(search, case=False, na=False)]
    if sv != "All": ds = ds[ds[S["village"]] == sv]
    if st_t == "Treatment": ds = ds[to_group(ds[S["type"]]) == "Treatment"]
    elif st_t == "Control": ds = ds[to_group(ds[S["type"]]) == "Control"]

    st.info(f"Showing **{len(ds)}** farmers")

    disp = [S["farmer"], S["village"], S["type"], S["land_area"], S["days_monitored"],
            S["missing_days"], S["drying_events"], S["days_above"], S["days_below"],
            S["dry_days"], S["irrigations_a"], S["irrigations_b"],
            S["total_water_mm"], S["total_water_m3"], S["avg_gopal_cm"]]
    disp = [c for c in disp if c in ds.columns]

    ds_view = ds[disp].reset_index(drop=True).copy()
    ds_view[S["type"]] = ds_view[S["type"]].map(relabel_type)

    key_lookup = {v: k for k, v in S.items()}
    col_config = {}
    for c in disp:
        k = key_lookup.get(c)
        tip = H(k) if k else ""
        if c == S["total_water_m3"]:
            col_config[c] = st.column_config.NumberColumn("Water Added (m³)", format="%.1f", help=tip)
        elif c == S["avg_gopal_cm"]:
            col_config[c] = st.column_config.NumberColumn("Gopal (cm)", format="%.2f", help=tip)
        elif tip:
            col_config[c] = st.column_config.Column(help=tip)

    st.dataframe(ds_view, use_container_width=True, height=420, column_config=col_config)

    st.divider()

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Top 15 — Irrigation Depth (mm)", help=H("total_water_mm"))
        st.caption("Farmers with the deepest total irrigation this season")
        if S["total_water_mm"] in ds.columns:
            dsg = ds.copy()
            dsg["Group"] = to_group(dsg[S["type"]])
            top = (dsg[[S["farmer"], "Group", S["total_water_mm"]]].dropna()
                   .sort_values(S["total_water_mm"], ascending=True).tail(15))
            fig = px.bar(top, y=S["farmer"], x=S["total_water_mm"], color="Group",
                orientation="h", color_discrete_map=GROUP_COLOR,
                height=380, labels={S["total_water_mm"]: "Irrigation Depth (mm)", S["farmer"]: ""})
            style_fig(fig, height=380)
            fig.update_layout(yaxis=dict(tickfont=dict(size=9)))
            st.plotly_chart(fig, use_container_width=True)

    with c2:
        st.subheader("Bottom 15 — Irrigation Depth (mm)", help=H("total_water_mm"))
        st.caption("Farmers with the shallowest total irrigation this season")
        if S["total_water_mm"] in ds.columns:
            dsg = ds.copy()
            dsg["Group"] = to_group(dsg[S["type"]])
            bottom = (dsg[[S["farmer"], "Group", S["total_water_mm"]]].dropna()
                      .sort_values(S["total_water_mm"], ascending=True).head(15))
            fig2 = px.bar(bottom, y=S["farmer"], x=S["total_water_mm"], color="Group",
                orientation="h", color_discrete_map=GROUP_COLOR,
                height=380, labels={S["total_water_mm"]: "Irrigation Depth (mm)", S["farmer"]: ""})
            style_fig(fig2, height=380)
            fig2.update_layout(yaxis=dict(tickfont=dict(size=9)))
            st.plotly_chart(fig2, use_container_width=True)

    csv = ds.to_csv(index=False).encode("utf-8")
    st.download_button("📥 Download CSV", data=csv,
                       file_name="awd_summary.csv", mime="text/csv")


# ═══════════════════════════════════════════════════════════════════
# TAB 2 — INDIVIDUAL FARMER RESULTS
# ═══════════════════════════════════════════════════════════════════

def tab_individual_farmer(master, summary):
    st.markdown("### Individual Farmer Results")
    if master.empty:
        st.warning("Master Analysis not loaded.")
        return

    cv, ct, cf = st.columns(3)
    with cv: sv = st.selectbox("Village", sorted(master[M["village"]].dropna().unique()), help=H("village_filter"))
    with ct:
        type_opts_raw = sorted(master[master[M["village"]] == sv][M["type"]].dropna().unique())
        type_opts = sorted(set(relabel_type(t) for t in type_opts_raw))
        st_disp = st.selectbox("Type", type_opts, help=H("type_filter"))
    with cf:
        in_village = master[M["village"]] == sv
        in_type = to_group(master[M["type"]]) == st_disp
        fs = sorted(master[in_village & in_type][M["farmer"]].dropna().unique())
        sel = st.selectbox("Farmer", fs, help=H("farmer"))

    if not sel: return

    fm = master[master[M["farmer"]] == sel].copy()
    sm = summary[summary[S["farmer"]] == sel] if not summary.empty else pd.DataFrame()

    if not sm.empty:
        row = sm.iloc[0]
        st.markdown("#### Season Summary")
        with st.container(key="deep_dive_season_summary"):
            c1, c2, c3, c4, c5, c6, c7, c8 = st.columns(8)
            irr_a_val = row.get(S["irrigations_a"])
            irr_b_val = row.get(S["irrigations_b"])
            pairs = [
                (c1, "Village", str(row.get(S["village"], "—")), "", "village"),
                (c2, "Type", relabel_type(str(row.get(S["type"], "—"))), "", "type"),
                (c3, "Land (ac)", str(row.get(S["land_area"], "—")), "", "land_area"),
                (c4, "Days Mon.", str(int(row.get(S["days_monitored"], 0))) if pd.notna(row.get(S["days_monitored"])) else "—", "", "days_monitored"),
                (c5, "Dry Events", str(int(row.get(S["drying_events"], 0))) if pd.notna(row.get(S["drying_events"])) else "—", "≥3 days", "drying_events"),
                (c6, "Irrig. Reported", str(int(irr_a_val)) if pd.notna(irr_a_val) else "—", "field-observed", "irrigations_a"),
                (c7, "Irrig. Calculated", str(int(irr_b_val)) if pd.notna(irr_b_val) else "—", "from readings", "irrigations_b"),
                (c8, "Water (m³)", f"{row.get(S['total_water_m3'], 0):.1f}" if pd.notna(row.get(S["total_water_m3"])) else "—", "added", "total_water_m3"),
            ]
            for col, lab, val, sub, key in pairs:
                col.metric(lab, val, sub or None, help=H(key))
        st.divider()

    st.subheader(f"Daily Water Level — {sel}", help=H("pp_reading"))
    st.caption("PP Reading over time · ▲ = irrigation reported · ◇ = irrigation calculated (BGL rose >2cm) · phase bars below")

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.72, 0.28],
        subplot_titles=("PP Reading (cm)", "Phase"), vertical_spacing=0.05)
    fig.add_hrect(y0=5, y1=25, row=1, col=1, fillcolor=C["safe_zone"], line_width=0)
    fig.add_trace(go.Scatter(x=fm[M["date"]], y=fm[M["pp_reading"]], name="PP Reading",
        mode="lines+markers", line=dict(color=C["treatment"], width=2.5), marker=dict(size=4),
        hovertemplate="<b>%{x|%d %b %Y}</b><br>PP: %{y:.1f} cm<extra></extra>"), row=1, col=1)
    fig.add_hline(y=15, line_dash="dash", line_color=C["accent"], line_width=1.5, row=1, col=1,
        annotation_text="Surface", annotation_font_color=C["accent"], annotation_position="bottom right")
    fig.add_hline(y=25, line_dash="dot", line_color=C["control"], line_width=1, row=1, col=1,
        annotation_text="Dry (25cm)", annotation_font_color=C["control"], annotation_position="top right")

    ir = fm[fm[M["irrigated"]] == True]
    if not ir.empty:
        fig.add_trace(go.Scatter(x=ir[M["date"]], y=ir[M["pp_reading"]], name="Irrigation (Reported)",
            mode="markers", marker=dict(symbol="triangle-up", size=11, color=C["accent"],
            line=dict(color="white", width=1)),
            hovertemplate="<b>Irrigation (Reported)</b><br>%{x|%d %b}<br>PP: %{y:.1f}<extra></extra>"), row=1, col=1)

    if M["irrig_calc"] in fm.columns:
        irc = fm[fm[M["irrig_calc"]] == True]
        if not irc.empty:
            fig.add_trace(go.Scatter(x=irc[M["date"]], y=irc[M["pp_reading"]], name="Irrigation (Calculated)",
                mode="markers", marker=dict(symbol="diamond", size=8, color=C["treatment"],
                line=dict(color="white", width=1)),
                hovertemplate="<b>Irrigation (Calculated)</b><br>%{x|%d %b}<br>PP: %{y:.1f}<extra></extra>"), row=1, col=1)

    for ph in PHASE_ORDER:
        sub = fm[fm[M["phase"]] == ph]
        if sub.empty: continue
        fig.add_trace(go.Bar(x=sub[M["date"]], y=[1] * len(sub), name=ph,
            marker_color=C["phase"].get(ph, "#999"),
            hovertemplate=f"<b>{ph}</b><br>%{{x|%d %b}}<extra></extra>"), row=2, col=1)

    fig.update_layout(height=510, margin=dict(l=10, r=10, t=30, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor=C["surface"], font=dict(color=C["text"]),
        barmode="stack",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font_size=10),
        yaxis=dict(title="PP Reading (cm)", autorange="reversed", showgrid=True, gridcolor=C["grid"]),
        yaxis2=dict(showticklabels=False, showgrid=False),
        xaxis2=dict(showgrid=True, gridcolor=C["grid"]))
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    st.subheader("Phase Distribution", help=H("phase"))
    pc = fm[M["phase"]].value_counts().reset_index()
    pc.columns = ["phase", "count"]
    pc["phase"] = pd.Categorical(pc["phase"], categories=PHASE_ORDER, ordered=True)
    pc = pc.sort_values("phase").dropna(subset=["phase"])
    cols_l = [C["phase"].get(p, "#999") for p in pc["phase"]]
    fig_p = go.Figure(go.Pie(labels=pc["phase"], values=pc["count"], hole=0.5, sort=False,
        marker=dict(colors=cols_l, line=dict(color="white", width=2)),
        textinfo="label+percent", textfont_size=10))
    fig_p.update_layout(height=320, margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)", showlegend=False)
    st.plotly_chart(fig_p, use_container_width=True)

    with st.expander("📋 Raw daily data"):
        show = [c for c in [M["date"], M["das"], M["pp_reading"], M["bgl"],
                M["fl_rl"], M["phase"], M["change_wl"], M["event"],
                M["gopal_cm"], M["irrigated"], M["irrig_calc"],
                M["zero_repl"]] if c in fm.columns]
        col_config = {
            M["date"]: st.column_config.DateColumn(format="DD MMM YYYY", help=H("date")),
            M["das"]: st.column_config.Column("Days After Sowing", help=H("das")),
            M["pp_reading"]: st.column_config.Column(help=H("pp_reading")),
            M["bgl"]: st.column_config.NumberColumn("BGL", format="%+.1f", help=H("bgl")),
            M["fl_rl"]: st.column_config.Column(help=H("fl_rl")),
            M["phase"]: st.column_config.Column(help=H("phase")),
            M["change_wl"]: st.column_config.Column(help=H("change_wl")),
            M["event"]: st.column_config.Column(help=H("event")),
            M["gopal_cm"]: st.column_config.Column(help=H("gopal_cm")),
            M["irrigated"]: st.column_config.CheckboxColumn("Irrigated (Reported)?", help=H("irrigated")),
            M["irrig_calc"]: st.column_config.CheckboxColumn("Irrigated (Calculated)?", help=H("irrig_calc")),
            M["zero_repl"]: st.column_config.Column(help=H("zero_repl")),
        }
        st.dataframe(fm[show].reset_index(drop=True), use_container_width=True, height=300,
            column_config=col_config)


# ═══════════════════════════════════════════════════════════════════
# TAB 5 — DATA EXPLORER
# ═══════════════════════════════════════════════════════════════════

def tab_explorer(master, summary):
    st.markdown("### Data Explorer")
    st1, st2 = st.tabs(["📋 Master Analysis (Daily)", "📊 Summary (Season)"])

    with st1:
        if master.empty:
            st.warning("Master Analysis not loaded.")
        else:
            c1, c2, c3 = st.columns(3)
            with c1: srch = st.text_input("🔍 Farmer", key="ex_srch", help=H("farmer"))
            with c2:
                ph_opts = [p for p in PHASE_ORDER if p in master[M["phase"]].dropna().unique()]
                ph_f = st.multiselect("Phase", ph_opts, key="ex_ph", help=H("phase"))
            with c3: ir_f = st.selectbox("Irrigation", ["All", "TRUE only", "FALSE only"], key="ex_ir", help=H("irrigated"))
            df = master.copy()
            if srch: df = df[df[M["farmer"]].str.contains(srch, case=False, na=False)]
            if ph_f: df = df[df[M["phase"]].isin(ph_f)]
            if ir_f == "TRUE only": df = df[df[M["irrigated"]] == True]
            elif ir_f == "FALSE only": df = df[df[M["irrigated"]] == False]
            st.info(f"**{len(df):,}** rows · **{df[M['farmer']].nunique()}** farmers")
            df_view = df.reset_index(drop=True).copy()
            df_view[M["type"]] = df_view[M["type"]].map(relabel_type)
            key_lookup = {v: k for k, v in M.items()}
            col_config = {M["date"]: st.column_config.DateColumn(format="DD MMM YYYY", help=H("date")),
                          M["irrigated"]: st.column_config.CheckboxColumn("Irrigated?", help=H("irrigated")),
                          M["bgl"]: st.column_config.NumberColumn("BGL", format="%+.1f", help=H("bgl"))}
            if M["irrig_calc"] in df_view.columns:
                col_config[M["irrig_calc"]] = st.column_config.CheckboxColumn("Irrigated (Calc.)?", help=H("irrig_calc"))
            for c in df_view.columns:
                if c in col_config: continue
                k = key_lookup.get(c)
                if k and H(k):
                    col_config[c] = st.column_config.Column(help=H(k))
            st.dataframe(df_view, use_container_width=True, height=420, column_config=col_config)
            st.download_button("📥 Download", df.to_csv(index=False).encode(),
                "master_filtered.csv", "text/csv")

    with st2:
        if summary.empty:
            st.warning("Summary not loaded.")
        else:
            srch2 = st.text_input("🔍 Farmer", key="ex_srch2", help=H("farmer"))
            df2 = summary.copy()
            if srch2: df2 = df2[df2[S["farmer"]].str.contains(srch2, case=False, na=False)]
            st.info(f"**{len(df2)}** farmers")
            df2_view = df2.reset_index(drop=True).copy()
            df2_view[S["type"]] = df2_view[S["type"]].map(relabel_type)
            key_lookup = {v: k for k, v in S.items()}
            col_config = {}
            for c in df2_view.columns:
                k = key_lookup.get(c)
                if k and H(k):
                    col_config[c] = st.column_config.Column(help=H(k))
            st.dataframe(df2_view, use_container_width=True, height=420, column_config=col_config)
            st.download_button("📥 Download", df2.to_csv(index=False).encode(),
                "summary_filtered.csv", "text/csv")


# ═══════════════════════════════════════════════════════════════════
# SETUP NOTICE
# ═══════════════════════════════════════════════════════════════════

def show_setup_notice():
    st.info(
        "**Google Sheets not connected yet.**\n\n"
        "Open `app.py`, find lines 50–56, and paste your published CSV links.\n\n"
        "See `README.md` for full step-by-step instructions."
    )


# ═══════════════════════════════════════════════════════════════════
# CSS — single light theme, consistent contrast throughout
# ═══════════════════════════════════════════════════════════════════

def apply_css():
    st.markdown(f"""
        <style>
        .stApp {{ background-color:{C['bg']}; }}
        section[data-testid="stSidebar"] {{ background-color:{C['surface']};
            border-right:1px solid {C['border']}; }}
        section[data-testid="stSidebar"] * {{ color:{C['text']} !important; }}
        .stTabs [data-baseweb="tab"] {{ font-weight:600;color:{C['text_muted']};font-size:14px; }}
        .stTabs [aria-selected="true"] {{ color:{C['treatment']} !important;
            border-bottom-color:{C['treatment']} !important; }}
        div[data-testid="stMetric"] {{ background:{C['surface']};border-radius:8px; }}
        div[data-testid="stMetricLabel"] {{ color:{C['text_muted']}; }}
        div[data-testid="stExpander"] {{ background:{C['surface']};border-radius:8px;
            border:1px solid {C['border']}; }}
        h1,h2,h3,h4 {{ color:{C['text']}; }}
        .st-key-deep_dive_season_summary div[data-testid="stMetricValue"] {{ font-size:16px; }}
        .st-key-deep_dive_season_summary div[data-testid="stMetricLabel"] {{ font-size:12px; }}
        </style>
    """, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

def main():
    apply_css()
    with st.spinner("Loading data..."):
        master  = load_master(MASTER_ANALYSIS_URL)
        summary = load_summary(SUMMARY_URL)

    render_header(master)

    if "PASTE_YOUR" in MASTER_ANALYSIS_URL or "PASTE_YOUR" in SUMMARY_URL:
        show_setup_notice()
        return

    master_f, summary_f = render_sidebar(master, summary)

    t1, t2, t3, t4, t5 = st.tabs([
        "📊 Results Overview",
        "👤 Individual Farmer Results",
        "⚖️ Compare Farmers",
        "📋 Summary",
        "🔍 Get Data",
    ])
    with t1: tab_results_overview(master_f, summary_f, master, summary)
    with t2: tab_individual_farmer(master_f, summary_f)
    with t3: tab_compare_farmers(master_f, summary_f)
    with t4: tab_farmer_summary(summary_f)
    with t5: tab_explorer(master_f, summary_f)


if __name__ == "__main__":
    main()

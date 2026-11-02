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
    page_icon=" ",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ═══════════════════════════════════════════════════════════════════
# ★ STEP 1 — PASTE YOUR GOOGLE SHEETS CSV LINKS HERE ★
# ═══════════════════════════════════════════════════════════════════
MASTER_ANALYSIS_URL = (
    r"https://docs.google.com/spreadsheets/d/e/2PACX-1vQaWVUo90mF4Tw0iWwanxzTsk0y4sly3UKVfkch9azX0dM9jg1EYKhV5ABLW3Q7mN0E95o3snn9aZOS/pub?gid=931246469&single=true&output=csv"
)

SUMMARY_URL = (
    r"https://docs.google.com/spreadsheets/d/e/2PACX-1vQaWVUo90mF4Tw0iWwanxzTsk0y4sly3UKVfkch9azX0dM9jg1EYKhV5ABLW3Q7mN0E95o3snn9aZOS/pub?gid=594619847&single=true&output=csv"
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
# Apps Script v17 writes "Days Since Sowing" (Date − Date of Sowing) itself;
# load_master() only derives it as a fallback if the column is ever missing.
DAS_COL = "Days Since Sowing"

# ═══════════════════════════════════════════════════════════════════
# COLUMN NAMES — Master Analysis (27 columns) — Apps Script v17
# (also holds "Counterfactual" marker rows — load_master keeps Actual only)
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
    "cum_irrig"      : "Cumulative Irrig. Depth (cm)",
    "data_type"      : "Data Type",
    "rain"           : "Daily Rainfall (mm)",
    "cum_rain"       : "Cumulative Rainfall (mm)",
    "remarks"        : "Remarks and Comments",
    "images"         : "Images of the Field",
}

# ═══════════════════════════════════════════════════════════════════
# COLUMN NAMES — Summary (69 columns) — Apps Script v17
# ═══════════════════════════════════════════════════════════════════
S = {
    "serial"            : "Sl No",
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
    "max_wl_events"     : "No of days Water Level is more than 10cm above Surface (High Wet)",
    "min_wl_events"     : "No of days Water Level is less than 10cm Below Surface (Very Dry)",
    "drying_events"     : "No. of Field Drying Events (3 or more Consecutive Days Below Surface)",
    "max_dry_duration"  : "Max Dry Period Duration (days)",
    "last_drying"       : "Last drying before Harvest",
    "avg_drying_overall": "Avg Drying Days (Overall)",
    "avg_drying_p1"     : "Avg Drying Days Phase 1 (0-30 DAS)",
    "avg_drying_p2"     : "Avg Drying Days Phase 2 (30-60 DAS)",
    "avg_drying_p3"     : "Avg Drying Days Phase 3 (60-90 DAS)",
    "avg_drying_p4"     : "Avg Drying Days Phase 4 (90+ DAS)",
    "rl_flood_mm"       : "Irrigation depth in rising limb - Flood (mm)",
    "rl_inter_mm"       : "Irrigation depth in rising limb - Inter (mm)",
    "rl_soil_mm"        : "Irrigation depth in rising limb - Soil (mm)",
    "fl_flood_mm"       : "Water level drop in falling limb - Flood (mm)",
    "fl_inter_mm"       : "Water level drop in falling limb - Inter (mm)",
    "fl_soil_mm"        : "Water level drop in falling limb - Soil (mm)",
    "total_water_mm"    : "Total Irrigated Water Depth (mm)",
    "total_water_m3"    : "Total Volumetric Water Irrigated (m3)",
    "total_recharged_mm": "Total Water Recharged (mm)",
    "total_recharged_m3": "Total Volumetric Water Recharged (m3)",
    "savings_pct"       : "Actual Water Savings (%)",
    "savings_mm"        : "Actual Water Savings (mm)",
    "savings_m3"        : "Actual Vol. Water Saving (m3)",
    "rainfall"          : "Total Rainfall During Monitoring Period (mm)",
    "yield_kg"          : "Yield (kg)",
    "price_per_kg"      : "Price per kg (Rs)",
    "income"            : "Income (Rs)",
    "cwp"               : "Crop water productivity (CWP) Kg/m3",
    "ewp"               : "Economic water productivity (EWP) Rs/m3",
    "days_sow_to_mon"   : "No. of Days between Sowing and Monitoring",
    "days_growing"      : "No. of Days of Growing",
    "crp"               : "Monitoring CRP Incharge",
    "total_land"        : "Total Land Area (acres)",
    "project_area"      : "Project Area",
    "command_area"      : "Command Area / Non Command Area",
    "canal_pos"         : "Broad Canal Positioning",
    "subcanal_pos"      : "Positioning within Sub Canal System",
    "soil"              : "Soil Type",
    "irrig_mode"        : "Mode of Irrigation",
    "seed"              : "Seed Variety",
    "cm_backend"        : "Continuous Monitoring Start Date (Backend)",
    "default_pair"      : "Default Control Pairing",
    "confidence"        : "AWD Confidence (Good/Average/Bad)",
    "remark1"           : "Remark 1 - Observation at Start",
    "remark2"           : "Remark 2 - Observation after Completion",
    # These columns were removed outright (v10 / v17 rewrites, not renamed) —
    # every place that reads them already falls back to "—" when absent, so
    # these mappings are kept only so those fallbacks stay well-defined.
    "avg_gopal_cm"      : "Avg Irrig. Depth - Gopal (cm)",
    "dry_days"          : "No. of Dry Days (Water Level >=25cm Below)",
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
    "cum_irrig"   : "Running total of irrigation depth (cm) added so far this season for this farmer.",
    "data_type"   : "\"Actual\" rows are real readings. \"Counterfactual\" rows are modelled marker rows showing where the water level would have been without an irrigation — the dashboard uses Actual rows only.",
    "rain"        : "Rainfall recorded on this date, in millimetres.",
    "cum_rain"    : "Rainfall accumulated from the start of monitoring up to this date, in millimetres.",
    "remarks"     : "Enumerator remarks and comments recorded on this date.",
    "images"      : "Link to the photo of the field / Pani pipe taken on this date.",
    "last_drying" : "Number of days at the end of the season (after the last wet reading) when the field was left to dry before harvest. These days are excluded from the drying-event statistics.",
    "yield_kg"    : "Paddy yield reported by the farmer, in kilograms.",
    "price_per_kg": "Selling price per kilogram, in rupees.",
    "income"      : "Income from the crop, in rupees.",
    "cwp"         : "Crop Water Productivity — kilograms of yield produced per cubic metre of irrigation water (Yield ÷ Total Volumetric Water Irrigated).",
    "ewp"         : "Economic Water Productivity — rupees of income earned per cubic metre of irrigation water (Income ÷ Total Volumetric Water Irrigated).",
    "days_sow_to_mon": "Days between sowing and the start of continuous monitoring.",
    "days_growing": "Number of days the crop was growing (sowing to harvest).",
    "pp_reading"  : "Daily water level reading — the Pani Pipe reading in centimetres — the distance from the top of the pipe down to the water surface inside it. Lower = more flooded, higher = drier. Formula: BGL = 15 − PP Reading.",
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
    "dry_days"    : "Number of days the field reached a deep-dry condition (PP reading ≥ 25cm). No longer provided by the current sheet — shown as \"—\".",
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
        # v17 interleaves modelled "Counterfactual" marker rows between actual
        # readings. Every chart/KPI here is about what really happened, so drop them.
        if M["data_type"] in df.columns:
            df = df[df[M["data_type"]].astype(str).str.strip() != "Counterfactual"].copy()
        for col in [M["date"], M["sowing_date"]]:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], dayfirst=True, errors="coerce")
        num_cols = [M["land_area"], M["das"], M["pp_reading"], M["bgl"],
                    M["change_wl"], M["gopal_cm"], M["days_mon"],
                    M["cum_irrig"], M["rain"], M["cum_rain"]]
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
        # Days Since Sowing now comes from the sheet; derive it only if absent.
        if DAS_COL not in df.columns and M["date"] in df.columns and M["sowing_date"] in df.columns:
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
        for col in [S["sowing_date"], S["cm_start"], S["cm_end"], S["harvest_date"], S["cm_backend"]]:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], dayfirst=True, errors="coerce")
        num_s = [v for k, v in S.items()
                 if k not in ["serial", "farmer", "village", "type", "method",
                              "sowing_date", "cm_start", "cm_end", "harvest_date", "gps",
                              "savings_pct", "error_margin", "crp", "project_area",
                              "command_area", "canal_pos", "subcanal_pos", "soil",
                              "irrig_mode", "seed", "cm_backend", "default_pair",
                              "confidence", "remark1", "remark2"]]
        for col in num_s:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        # Actual Water Savings (%) and Error Margin are exported as literal text
        # with a "%" suffix (e.g. "-40.69%", "0.0%") — strip it before parsing.
        for key in ["savings_pct", "error_margin"]:
            if S[key] in df.columns:
                df[S[key]] = pd.to_numeric(
                    df[S[key]].astype(str).str.rstrip("%").str.strip(), errors="coerce")
        for col in [S["farmer"], S["village"], S["type"], S["gps"], S["default_pair"]]:
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
                "gps": row.get(S["gps"]),
            }))

    def _parse_gps(val):
        """'10.116542, 77.558435' -> (lat, lon), or None if missing/invalid."""
        try:
            lat, lon = [float(x) for x in str(val).split(",")]
        except (ValueError, TypeError):
            return None
        return (lat, lon) if 5 < lat < 40 and 60 < lon < 100 else None

    # Primary source: the GPS column on the Summary sheet itself (always in sync
    # with the farmer list). Fallback for any farmer without usable GPS: look the
    # name up in the bundled shapefile points — exact, then word-order/punctuation
    # normalised, then a same-village fuzzy match — never reusing a point that
    # already belongs to another farmer (that would stack two farmers on one pin).
    def _norm(n):
        return " ".join(sorted(str(n).replace(".", " ").split())).lower()

    located, pending = {}, []
    for name, info in farmers:
        pos = _parse_gps(info.get("gps"))
        if pos:
            located[name] = pos
        else:
            pending.append((name, info))

    if pending:
        taken = set()
        geo_by_exact, geo_by_norm, geo_by_village = {}, {}, {}
        for i, feat in enumerate(pts_geo["features"]):
            raw = str(feat["properties"].get("farmer", "")).strip()
            if not raw:
                continue
            village_key = str(feat["properties"].get("village", "")).strip().lower()
            geo_by_exact.setdefault(raw.lower(), i)
            geo_by_norm.setdefault(_norm(raw), i)
            geo_by_village.setdefault(village_key, []).append((_norm(raw), i))

        unresolved = []
        for name, info in pending:
            i = geo_by_exact.get(name.lower(), geo_by_norm.get(_norm(name)))
            if i is not None and i not in taken:
                taken.add(i)
                lon, lat = pts_geo["features"][i]["geometry"]["coordinates"]
                located[name] = (lat, lon)
            else:
                unresolved.append((name, info))
        for name, info in unresolved:
            village_key = str(info.get("village", "")).strip().lower()
            best, best_ratio = None, 0.0
            for cand_norm, i in geo_by_village.get(village_key, []):
                if i in taken:
                    continue
                ratio = difflib.SequenceMatcher(None, _norm(name), cand_norm).ratio()
                if ratio > best_ratio:
                    best_ratio, best = ratio, i
            if best is not None and best_ratio >= 0.8:
                taken.add(best)
                lon, lat = pts_geo["features"][best]["geometry"]["coordinates"]
                located[name] = (lat, lon)

    plotted = [(name, located[name][0], located[name][1], info)
               for name, info in farmers if name in located]

    if not plotted:
        st.info("None of the currently filtered farmers have a mapped location yet.")
        return

    lats = [p[1] for p in plotted]
    lons = [p[2] for p in plotted]
    # Two key-free basemaps, switchable from the layer control. The control lists
    # only meaningful, human-named layers (not the raw tile-provider name).
    m = folium.Map(location=[sum(lats) / len(lats), sum(lons) / len(lons)],
                    zoom_start=12, tiles=None)
    folium.TileLayer("OpenStreetMap", name="Street map", control=True).add_to(m)
    folium.TileLayer(
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles &copy; Esri", name="Satellite", control=True, show=False).add_to(m)

    if gp_geo:
        folium.GeoJson(
            gp_geo, name="Village (GP) boundaries",
            style_function=lambda f: {"fillColor": C["accent"], "color": C["accent"],
                                       "weight": 2, "fillOpacity": 0.04},
            tooltip=folium.GeoJsonTooltip(fields=["village"], aliases=["Village:"]),
        ).add_to(m)

    if cmd_geo:
        cmd_colors = {"Command": C["treatment"], "Non command": C["control"],
                      "Non Command area (Tail end)": "#8B4513"}
        folium.GeoJson(
            cmd_geo, name="Command area classification",
            style_function=lambda f: {
                "fillColor": cmd_colors.get(f["properties"].get("classification"), "#999"),
                "color": cmd_colors.get(f["properties"].get("classification"), "#999"),
                "weight": 1, "fillOpacity": 0.10},
            tooltip=folium.GeoJsonTooltip(fields=["classification", "detail"],
                                           aliases=["Classification:", "Detail:"]),
        ).add_to(m)

    def _label_html(text, size=11, color="#1B4F72"):
        return (f"<div style='font-size:{size}px;font-weight:700;color:{color};white-space:nowrap;"
                f"transform:translate(-50%,-50%);text-shadow:0 0 3px #fff,0 0 3px #fff,0 0 3px #fff;'>"
                f"{text}</div>")

    # Always-visible village names at the centre of each boundary polygon
    if gp_geo:
        village_labels = folium.FeatureGroup(name="Village names", show=True)
        for feat in gp_geo["features"]:
            geom = feat["geometry"]
            rings = ([geom["coordinates"][0]] if geom["type"] == "Polygon"
                     else [poly[0] for poly in geom["coordinates"]])
            pts = [pt for ring in rings for pt in ring]
            if not pts:
                continue
            clon = (min(p[0] for p in pts) + max(p[0] for p in pts)) / 2
            clat = (min(p[1] for p in pts) + max(p[1] for p in pts)) / 2
            vname = str(feat["properties"].get("village", "")).replace("_TP", "").replace("_", " ").title()
            # match the spelling used in the data sheets
            vname = {"Vadugapatti": "Vadugapatty", "A Vadipatti": "A.Vadipatty"}.get(vname, vname)
            folium.Marker([clat, clon], icon=folium.DivIcon(
                html=_label_html(vname, 12), icon_size=(0, 0))).add_to(village_labels)
        village_labels.add_to(m)

    # Farmer pins as one toggleable layer per group, with counts in the label
    group_layers = {}
    for grp in ["Treatment", "Control"]:
        n = sum(1 for p in plotted if p[3]["type"] == grp)
        group_layers[grp] = folium.FeatureGroup(name=f"{grp} farmers ({n})", show=True)
    other_layer = folium.FeatureGroup(name="Other farmers", show=True)
    name_layer = folium.FeatureGroup(name="Farmer names", show=False)

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
        ).add_to(group_layers.get(grp, other_layer))
        folium.Marker([lat, lon], icon=folium.DivIcon(
            html=_label_html(name, 9, color).replace("translate(-50%,-50%)", "translate(-50%,8px)"),
            icon_size=(0, 0))).add_to(name_layer)

    for layer in list(group_layers.values()) + [other_layer, name_layer]:
        if layer is other_layer and not any(p[3]["type"] not in group_layers for p in plotted):
            continue   # no farmers of an unrecognised type — keep it out of the control
        layer.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    st_folium(m, use_container_width=True, height=460, returned_objects=[])
    st.caption(f"📍 {len(plotted)} of {len(farmers)} currently filtered farmers have a "
               f"mapped location. 🔵 Treatment · 🟠 Control — use the layer control (top-right) to switch basemap, "
               "toggle farmer groups, village names and farmer names.")


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
# SHARED SCOREBOARD / TABLE SECTIONS
# One definition of each section (KPI, Productivity, Water Usage,
# Irrigation, Information) drives the Results Overview (group-level),
# Individual Farmer (one farmer) and Compare Farmers (two farmers) tabs.
# ═══════════════════════════════════════════════════════════════════

# (card label, S key, number format, aggregation across a group of farmers)
KPI_SPEC = [
    ("Actual Water Savings (%)",      "savings_pct", "{:,.1f}%", "mean"),
    ("Actual Water Savings (mm)",     "savings_mm",  "{:,.1f}",  "mean"),
    ("Actual Vol. Water Saving (m3)", "savings_m3",  "{:,.0f}",  "sum"),
]
PRODUCTIVITY_SPEC = [
    ("Yield (kg)",                                "yield_kg",     "{:,.0f}", "mean"),
    ("Price per kg (Rs)",                         "price_per_kg", "{:,.1f}", "mean"),
    ("Income (Rs)",                               "income",       "{:,.0f}", "mean"),
    ("Crop water productivity (CWP) Kg/m3",       "cwp",          "{:.2f}",  "mean"),
    ("Economic water productivity (EWP) Rs/m3",   "ewp",          "{:.2f}",  "mean"),
]
WATER_SPEC = [
    ("Total Irrigated Water Depth (mm)",        "total_water_mm",     "{:,.0f}", "mean"),
    ("Total Volumetric Water Irrigated (m3)",   "total_water_m3",     "{:,.0f}", "sum"),
    ("Total Water Recharged (mm)",              "total_recharged_mm", "{:,.0f}", "mean"),
    ("Total Volumetric Water Recharged (m3)",   "total_recharged_m3", "{:,.0f}", "sum"),
]
IRRIGATION_SPEC = [
    ("No. Irrigations (a) Reported",   "irrigations_a"),
    ("No. Irrigations (b) Calculated", "irrigations_b"),
    ("No. of Days Water Level Stayed Above Surface", "days_above"),
    ("No. of Days Water Level Stayed Below Surface", "days_below"),
    ("No of days Water Level is more than 10cm above Surface (High Wet)", "max_wl_events"),
    ("No of days Water Level is less than 10cm Below Surface (Very Dry)", "min_wl_events"),
    ("No. of Field Drying Events (3 or more Consecutive Days Below Surface)", "drying_events"),
    ("Max Dry Period Duration (days)", "max_dry_duration"),
    ("Avg Drying Days (Overall)",      "avg_drying_overall"),
    ("Avg Drying Days Phase 1 (0-30 DAS)",  "avg_drying_p1"),
    ("Avg Drying Days Phase 2 (30-60 DAS)", "avg_drying_p2"),
    ("Avg Drying Days Phase 3 (60-90 DAS)", "avg_drying_p3"),
    ("Avg Drying Days Phase 4 (90+ DAS)",   "avg_drying_p4"),
    ("Irrigation depth in rising limb - Flood (mm)", "rl_flood_mm"),
    ("Irrigation depth in rising limb - Inter (mm)", "rl_inter_mm"),
    ("Irrigation depth in rising limb - Soil (mm)",  "rl_soil_mm"),
    ("Water level drop in falling limb - Flood (mm)", "fl_flood_mm"),
    ("Water level drop in falling limb - Inter (mm)", "fl_inter_mm"),
    ("Water level drop in falling limb - Soil (mm)",  "fl_soil_mm"),
]
# (row label, S key, kind) — the Information table on Individual Farmer Results
INFO_SPEC = [
    ("Monitoring CRP Incharge",                     "crp",             "text"),
    ("Total Land Area (acres)",                     "total_land",      "num"),
    ("Size of Monitoring Field (acres)",            "land_area",       "num"),
    ("Location of Monitoring Sites - GPS",          "gps",             "text"),
    ("Project Area",                                "project_area",    "text"),
    ("Command Area / Non Command Area",             "command_area",    "text"),
    ("Broad Canal Positioning",                     "canal_pos",       "text"),
    ("Positioning within Sub Canal System",         "subcanal_pos",    "text"),
    ("Soil Type",                                   "soil",            "text"),
    ("Method of Cultivation (Sowing)",              "method",          "text"),
    ("Mode of Irrigation",                          "irrig_mode",      "text"),
    ("Seed Variety",                                "seed",            "text"),
    ("Date of Sowing of Seeds in the Field",        "sowing_date",     "date"),
    ("Continuous Monitoring Start Date (Backend)",  "cm_backend",      "date"),
    ("No. of Days between Sowing and Monitoring",   "days_sow_to_mon", "num"),
    ("Start Date of Continuous Monitoring",         "cm_start",        "date"),
    ("End Date of Continuous Monitoring",           "cm_end",          "date"),
    ("No. of Days Monitored",                       "days_monitored",  "num"),
    ("Date of Harvest",                             "harvest_date",    "date"),
    ("No. of Days of Growing",                      "days_growing",    "num"),
    ("Total Rainfall During Monitoring Period (mm)", "rainfall",       "num"),
    ("Remark 1 - Observation at Start",             "remark1",         "text"),
    ("Remark 2 - Observation after Completion",     "remark2",         "text"),
]
REMARKS_SPEC = [
    ("Remark 1 - Observation at Start",         "remark1", "text"),
    ("Remark 2 - Observation after Completion", "remark2", "text"),
]
AGG_NOTE = {"mean": "avg per farmer", "sum": "group total"}


def _fmt_plain(v):
    """Table cell text: whole numbers without decimals, others to 2 dp, blanks as an em-dash."""
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return "—"
    if isinstance(v, (int, np.integer)):
        return f"{v:,}"
    if isinstance(v, (float, np.floating)):
        return f"{round(float(v), 2):,.2f}".rstrip("0").rstrip(".")
    return str(v)


def scoreboard(cards, accent, ncols=3):
    """cards = [(label, value text, sub text, tooltip key)] laid out ncols per row."""
    for i in range(0, len(cards), ncols):
        cols = st.columns(ncols)
        for col, (label, val, sub, tip) in zip(cols, cards[i:i + ncols]):
            metric_card(col, label, val, sub, tip, accent)


def kv_table(rows, value_label="Value"):
    """Metric/value table (text-wrapped, so long remarks stay readable)."""
    df = pd.DataFrame(rows, columns=["Metric", value_label]).set_index("Metric")
    st.table(df)


def _col_values(src, key):
    """Series of values for a group (DataFrame) or a one-element list for one farmer (Series)."""
    col = S[key]
    if isinstance(src, pd.DataFrame):
        return src[col].dropna() if col in src.columns else pd.Series(dtype=float)
    v = src.get(col) if src is not None else None
    return pd.Series([v]).dropna() if v is not None else pd.Series(dtype=float)


def section_cards(kind, src, tag=""):
    """Scoreboard cards for one section. src = DataFrame (a group of farmers, aggregated)
    or a Series (one farmer's Summary row). tag = e.g. 'Treatment only' for group cards."""
    is_group = isinstance(src, pd.DataFrame)
    spec = {"kpi": KPI_SPEC, "productivity": PRODUCTIVITY_SPEC, "water": WATER_SPEC}[kind]
    cards = []
    if kind == "kpi" and is_group:
        pct = _col_values(src, "savings_pct")
        n_farmers = src[S["farmer"]].nunique() if (not src.empty and S["farmer"] in src.columns) else 0
        cards += [
            ("No. of AWD Farmers", f"{n_farmers:,}", tag, "type"),
            ("Farmers with +ve Savings", f"{int((pct > 0).sum()):,}", tag, "savings_pct"),
            ("Farmers with -ve Savings", f"{int((pct < 0).sum()):,}", tag, "savings_pct"),
        ]
    for label, key, fs, agg in spec:
        vals = _col_values(src, key)
        val = getattr(vals, agg)() if not vals.empty else None
        sub = f"{tag} · {AGG_NOTE[agg]}" if is_group else ""
        cards.append((label, fmt_or_dash(val, fs), sub, key))
    return cards


def irrigation_rows(src):
    """(label, text) rows — group mean across farmers, or one farmer's value."""
    is_group = isinstance(src, pd.DataFrame)
    rows = []
    for label, key in IRRIGATION_SPEC:
        vals = _col_values(src, key)
        if vals.empty:
            rows.append((label, "—"))
        else:
            rows.append((label, _fmt_plain(float(vals.mean() if is_group else vals.iloc[0]))))
    return rows


def info_rows(row, spec=INFO_SPEC):
    """Rows for the Information / Remarks tables. Fields absent from the sheet are skipped."""
    rows = []
    for label, key, kind in spec:
        col = S[key]
        if row is None or col not in row.index:
            continue
        v = row.get(col)
        if pd.isna(v) or str(v).strip() in ("", "nan"):
            rows.append((label, "—"))
        elif kind == "date":
            rows.append((label, pd.Timestamp(v).strftime("%d %b %Y")))
        elif kind == "num":
            rows.append((label, _fmt_plain(float(v))))
        else:
            rows.append((label, str(v).strip()))
    return rows


def render_section(kind, src, accent, tag="", ncols=2):
    """Body of one collapsible section (scoreboard cards, or a table for Irrigation)."""
    if kind == "irrigation":
        is_group = isinstance(src, pd.DataFrame)
        kv_table(irrigation_rows(src), "Avg per farmer" if is_group else "Value")
        if is_group and tag:
            st.caption(f"{tag} · mean across farmers")
    else:
        scoreboard(section_cards(kind, src, tag), accent, ncols)


SECTION_TITLES = {
    "kpi": "Key Performance Index",
    "productivity": "Productivity",
    "water": "Water Usage",
    "irrigation": "Irrigation",
}


# ═══════════════════════════════════════════════════════════════════
# BUILD-YOUR-OWN CHART — shared by Individual Farmer and Compare Farmers
# The user picks chart type, X, Y, colour, aggregation and filters; it opens
# pre-filled with a sensible default graph rather than a blank canvas.
# ═══════════════════════════════════════════════════════════════════

CHART_TYPES = ["Line", "Bar", "Stacked bar", "Box plot", "Pie"]
AGG_CHOICES = {"None (raw values)": None, "Mean": "mean", "Sum": "sum", "Median": "median",
               "Count": "count", "Max": "max", "Min": "min"}
PALETTE = [C["treatment"], C["control"], C["accent"], "#8E6BB0", "#E0A030", "#3A9E9E", "#B24C6B", "#7A7A52"]
LBL_DWL = "Daily Water Level Reading (cm)"
LBL_BGL = "Water Level vs Surface (cm)"
DAILY_RENAME = {
    M["pp_reading"]: LBL_DWL,
    M["bgl"]: LBL_BGL,
    M["irrigated"]: "Irrigation Reported (1 = yes)",
    M["irrig_calc"]: "Irrigation Calculated (1 = yes)",
}


def builder_daily(df):
    """Dataset spec for the chart builder from Master Analysis rows."""
    d = df.copy()
    d["Group"] = to_group(d[M["type"]])
    for c in (M["irrigated"], M["irrig_calc"]):
        if c in d.columns:
            d[c] = d[c].astype(int)
    d = d.rename(columns=DAILY_RENAME)
    cats = [c for c in [M["farmer"], M["village"], "Group", M["phase"], M["fl_rl"], M["event"]] if c in d.columns]
    nums = [c for c in [DAS_COL, LBL_DWL, LBL_BGL, M["change_wl"], M["gopal_cm"], M["cum_irrig"],
                        DAILY_RENAME[M["irrigated"]], DAILY_RENAME[M["irrig_calc"]],
                        M["rain"], M["cum_rain"]] if c in d.columns]
    return dict(df=d, x=[M["date"]] + nums + cats, y=nums, color=cats, filters=[M["phase"], "Group"])


def builder_summary(df):
    """Dataset spec for the chart builder from Summary rows."""
    d = df.copy()
    d["Group"] = to_group(d[S["type"]])
    skip = {"serial", "gps", "type", "farmer", "village", "method", "sowing_date", "cm_start", "cm_end",
            "harvest_date", "crp", "project_area", "command_area", "canal_pos", "subcanal_pos", "soil",
            "irrig_mode", "seed", "remark1", "remark2", "default_pair", "confidence", "farmer_id", "cm_backend"}
    nums = [S[k] for k in S if k not in skip and S[k] in d.columns and d[S[k]].notna().any()
            and pd.api.types.is_numeric_dtype(d[S[k]])]
    cats = [c for c in [S["farmer"], S["village"], "Group", S["method"]] if c in d.columns]
    return dict(df=d, x=cats + nums, y=nums, color=cats, filters=[S["village"], "Group"])


def chart_builder(key, datasets):
    """datasets = {name: spec} where spec = builder_*() output plus a 'default' dict
    (chart, x, y, color, agg). Renders the controls and the chart."""
    names = list(datasets)
    ds_name = st.radio("Data", names, horizontal=True, key=f"{key}_ds") if len(names) > 1 else names[0]
    ds = datasets[ds_name]
    df, dflt = ds["df"], ds["default"]
    k = f"{key}_{ds_name}"

    def _idx(opts, val):
        return opts.index(val) if val in opts else 0

    c1, c2, c3, c4, c5 = st.columns([1, 1.5, 1.5, 1.2, 1.1])
    chart = c1.selectbox("Chart type", CHART_TYPES, index=_idx(CHART_TYPES, dflt["chart"]), key=f"{k}_chart")
    x_opts = ds["x"] + (["(none)"] if chart == "Box plot" else [])
    x = c2.selectbox("Slices (category)" if chart == "Pie" else "X-axis", x_opts,
                     index=_idx(x_opts, dflt["x"]), key=f"{k}_x")
    y = c3.selectbox("Values" if chart == "Pie" else "Y-axis", ds["y"],
                     index=_idx(ds["y"], dflt["y"]), key=f"{k}_y")
    c_opts = ["(none)"] + ds["color"]
    color = c4.selectbox("Colour by", c_opts, index=_idx(c_opts, dflt.get("color", "(none)")),
                         key=f"{k}_color", disabled=(chart == "Pie"))
    a_opts = list(AGG_CHOICES)
    agg_label = c5.selectbox("Aggregate", a_opts, index=_idx(a_opts, dflt.get("agg", a_opts[0])), key=f"{k}_agg")

    flt_cols = st.columns(max(len(ds["filters"]), 1))
    d = df
    for col, fcol in zip(flt_cols, [f for f in ds["filters"] if f in df.columns]):
        opts = sorted(df[fcol].dropna().astype(str).unique())
        sel = col.multiselect(f"Filter: {fcol}", opts, key=f"{k}_f_{fcol}", placeholder="All")
        if sel:
            d = d[d[fcol].astype(str).isin(sel)]
    if d.empty:
        st.info("No rows match these filters.")
        return

    colour = None if (color == "(none)" or chart == "Pie") else color
    xcol = None if x == "(none)" else x
    agg = AGG_CHOICES[agg_label]
    if chart == "Pie":
        agg = agg or "sum"
    plot_df = d
    if agg and xcol and chart != "Box plot":
        gkeys = [xcol] + ([colour] if colour and colour != xcol else [])
        plot_df = d.groupby(gkeys, dropna=True, observed=True)[y].agg(agg).reset_index()

    def _cmap(col):
        if col == "Group":
            return GROUP_COLOR
        if col == M["phase"]:
            return C["phase"]
        return None

    kw = dict(color_discrete_sequence=PALETTE)
    if chart == "Line":
        pdf = plot_df.sort_values(xcol) if xcol else plot_df
        fig = px.line(pdf, x=xcol, y=y, color=colour, markers=len(pdf) < 80,
                      color_discrete_map=_cmap(colour) if colour else None, **kw)
    elif chart in ("Bar", "Stacked bar"):
        fig = px.bar(plot_df, x=xcol, y=y, color=colour,
                     barmode="stack" if chart == "Stacked bar" else "group",
                     color_discrete_map=_cmap(colour) if colour else None, **kw)
    elif chart == "Box plot":
        fig = px.box(plot_df, x=xcol, y=y, color=colour,
                     color_discrete_map=_cmap(colour) if colour else None, **kw)
    else:
        if plot_df[y].lt(0).any():
            st.warning("A pie chart can't show negative values — negatives are shown as zero-size slices.")
            plot_df = plot_df.assign(**{y: plot_df[y].clip(lower=0)})
        fig = px.pie(plot_df, names=xcol, values=y, hole=0.45, color=xcol,
                     color_discrete_map=_cmap(xcol) or {}, **kw)
        if plot_df[xcol].nunique() > 20:
            st.info("This pie has many slices — pick a category with fewer values (e.g. Group, Village, Phase) for a clearer chart.")

    style_fig(fig, height=400, legend=True)
    fig.update_layout(margin=dict(l=10, r=10, t=30, b=10))
    if chart in ("Line", "Bar", "Stacked bar"):
        fig.update_layout(hovermode="x unified")
    how = f"{agg_label.lower()} of " if agg else ""
    st.caption(f"{chart}: {how}**{y}**" + (f" by **{xcol}**" if xcol else "") +
               (f", coloured by **{colour}**" if colour else "") + f" · {len(d):,} rows used")
    st.plotly_chart(fig, use_container_width=True)
    st.download_button("📥 Download chart data", plot_df.to_csv(index=False).encode(),
                       f"{key}_chart_data.csv", "text/csv", key=f"{k}_dl")


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

    sv_t = summary[to_group(summary[S["type"]]) == "Treatment"] if not summary.empty else summary
    sv_c = summary[to_group(summary[S["type"]]) == "Control"] if not summary.empty else summary

    # ── Subsection 1 — description + conceptual diagram ──────────────
    with st.expander("About this evaluation", expanded=True):
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
                "to the [playbook](https://docs.google.com/document/d/1tYzi1q7qTdXfrmkkpZsCLf_xfqBKXx_DOKIcrXsM4jA/edit?tab=t.8agzb0o7q1dh) "
            , unsafe_allow_html=True)
        with cimg:
            img_path = Path(__file__).parent / "assets" / "awd_conceptual_diagram.png"
            if img_path.exists():
                st.image(str(img_path),
                    caption="AWD Conceptual diagram: Water savings from AWD occurs by "
                            "reducing the total number of irrigations, thereby reducing "
                            "evaporative losses from standing water.",
                    use_container_width=True)

    # ── Subsection 2 — map + farmer-distribution table ───────────────
    with st.expander("Farmer Locations & Village Boundaries · Distribution of Farmers (n=100)", expanded=True):
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

    # ── Subsection 3 — scoreboards: Treatment (left) | Control (right) ─
    # Always the full n=100 cohort (not the sidebar filters).
    st.markdown("### Results — Treatment vs Control")
    st.caption("Savings are measured against the 1100 mm TNAU baseline — "
               "[TNAU standard](http://www.agritech.tnau.ac.in/agriculture/agri_cropproduction_cereals_rice_tranpudlow_mainfield_water_mgmt.html).")
    hl, hr = st.columns(2)
    hl.markdown(f"<div style='border-bottom:3px solid {C['treatment']};font-weight:700;"
                f"color:{C['treatment']};padding-bottom:2px;'>Treatment (AWD)</div>", unsafe_allow_html=True)
    hr.markdown(f"<div style='border-bottom:3px solid {C['control']};font-weight:700;"
                f"color:{C['control']};padding-bottom:2px;'>Control (conventional)</div>", unsafe_allow_html=True)
    for kind in ["kpi", "productivity", "water", "irrigation"]:
        left, right = st.columns(2)
        opened = kind in ("kpi", "productivity")
        for col, grp, df_g, accent in [(left, "Treatment", sv_t, C["treatment"]),
                                       (right, "Control", sv_c, C["control"])]:
            with col:
                with st.expander(f"{SECTION_TITLES[kind]} — {grp} only", expanded=opened):
                    render_section(kind, df_g, accent, tag=f"{grp} only")

    # ── Row 1 charts (sidebar-filtered) ──────────────────────────────
    #cl, cr = st.columns([1.3, 1])
    #with cl:
        #st.subheader("Water Level Changes in the Field", help=H("das"))
        #st.caption("Avg water level on field vs Days After Sowing · Treatment vs Control · green band = safe zone")
        #if not master_f.empty and M["das"] in master_f.columns:
            #mm = master_f.copy()
            #mm["Group"] = to_group(mm[M["type"]])
            #mm = mm[mm[M["das"]].notna() & (mm[M["das"]] >= 0)]
            #mm["das_week"] = (mm[M["das"]] // 7) * 7
            #wk = mm.groupby(["das_week", "Group"])[M["bgl"]].mean().reset_index()
            #fig = go.Figure()
            #fig.add_hrect(y0=-5, y1=10, fillcolor=C["safe_zone"],
                          #line_width=0, annotation_text="Safe zone",
                          #annotation_font_color=C["accent"],
                          #annotation_position="top left")
            #for grp in ["Treatment", "Control"]:
                #sub = wk[wk["Group"] == grp].sort_values("das_week")
                #if sub.empty: continue
                #fig.add_trace(go.Scatter(x=sub["das_week"], y=sub[M["bgl"]],
                    #name=grp, mode="lines+markers",
                    #line=dict(color=GROUP_COLOR[grp], width=2.5), marker=dict(size=5),
                    #hovertemplate=f"<b>{grp}</b><br>Day %{{x:.0f}}+ after sowing<br>Avg level: %{{y:.1f}} cm<extra></extra>"))
            #fig.add_hline(y=0, line_dash="dash", line_color="#999", line_width=1)
            #fig.update_layout(xaxis=dict(title="Days After Sowing"),
                               #yaxis=dict(title="Water Level on Field (cm)"))
            #style_fig(fig, height=340)
            #st.plotly_chart(fig, use_container_width=True)    
    #with cr:
        #st.subheader("Hydrological Phase Distribution (Control)", help=H("phase"))
        #st.caption("Outer ring = Treatment (blue) · Inner ring = Control (red) · FL group then RL group")
        #if not master_f.empty:
            #def _phase_counts(df):
                #pc = df[M["phase"]].value_counts().reset_index()
                #pc.columns = ["phase", "count"]
                #pc["phase"] = pd.Categorical(pc["phase"], categories=PHASE_ORDER, ordered=True)
                #return pc.sort_values("phase").dropna(subset=["phase"])

            #mm = master_f.copy()
            #mm["Group"] = to_group(mm[M["type"]])
            #pc_t = _phase_counts(mm[mm["Group"] == "Treatment"])
            #pc_c = _phase_counts(mm[mm["Group"] == "Control"])

            #fig_donut = go.Figure()
            #if not pc_t.empty:
                #fig_donut.add_trace(go.Pie(
                    #labels=pc_t["phase"], values=pc_t["count"], sort=False,
                    #hole=0.62, domain=dict(x=[0, 1], y=[0, 1]),
                    #marker=dict(colors=[C["phase_treatment"].get(p, "#999") for p in pc_t["phase"]],
                                #line=dict(color="white", width=1)),
                    #textinfo="none", name="Treatment",
                    #hovertemplate="<b>Treatment</b><br>%{label}: %{percent}<extra></extra>"))
            #if not pc_c.empty:
                #fig_donut.add_trace(go.Pie(
                    #labels=pc_c["phase"], values=pc_c["count"], sort=False,
                    #hole=0.35, domain=dict(x=[0.19, 0.81], y=[0.19, 0.81]),
                    #marker=dict(colors=[C["phase_control"].get(p, "#999") for p in pc_c["phase"]],
                                #line=dict(color="white", width=1)),
                    #textinfo="none", name="Control",
                    #hovertemplate="<b>Control</b><br>%{label}: %{percent}<extra></extra>"))
            #fig_donut.update_layout(height=340, margin=dict(l=10, r=10, t=10, b=10),
                #paper_bgcolor="rgba(0,0,0,0)", showlegend=True,
                #legend=dict(orientation="h", yanchor="bottom", y=-0.18, xanchor="center", x=0.5, font_size=9))
            #st.plotly_chart(fig_donut, use_container_width=True)

    # ── Extra charts (sidebar-filtered) — collapsed to keep the page clean ──
    with st.expander("Hydrological Phase Distribution", expanded=False):
        cl, cr = st.columns([1, 1])

        if not master_f.empty:

            def _phase_counts(df):
                pc = df[M["phase"]].value_counts().reset_index()
                pc.columns = ["phase", "count"]
                pc["phase"] = pd.Categorical(
                    pc["phase"],
                    categories=PHASE_ORDER,
                    ordered=True
                )
                return pc.sort_values("phase").dropna(subset=["phase"])

            mm = master_f.copy()
            mm["Group"] = to_group(mm[M["type"]])

        # Treatment
            pc_t = _phase_counts(
                mm[mm["Group"] == "Treatment"]
            )

        # Control
            pc_c = _phase_counts(
                mm[mm["Group"] == "Control"]
            )

        # --------------------------------------------------
        # Treatment chart
        # --------------------------------------------------
            with cl:
                st.subheader(
                    "Hydrological Phase Distribution (Treatment)",
                    help=H("phase")
                )

                st.caption(
                    "Treatment · FL group then RL group"
                )

                fig_treatment = go.Figure()

                if not pc_t.empty:
                    fig_treatment.add_trace(go.Pie(
                        labels=pc_t["phase"],
                        values=pc_t["count"],
                        sort=False,
                        hole=0.62,
                        domain=dict(x=[0, 1], y=[0, 1]),
                        marker=dict(
                            colors=[
                                C["phase_treatment"].get(p, "#999")
                                for p in pc_t["phase"]
                            ],
                            line=dict(color="white", width=1)
                        ),
                        textinfo="none",
                        name="Treatment",
                        hovertemplate=(
                            "<b>Treatment</b><br>"
                            "%{label}: %{percent}"
                            "<extra></extra>"
                        )
                    ))

                fig_treatment.update_layout(
                    height=340,
                    margin=dict(l=10, r=10, t=10, b=10),
                    paper_bgcolor="rgba(0,0,0,0)",
                    showlegend=True,
                    legend=dict(
                        orientation="h",
                        yanchor="bottom",
                        y=-0.18,
                        xanchor="center",
                        x=0.5,
                        font_size=9
                    )
                )

                st.plotly_chart(
                    fig_treatment,
                    use_container_width=True
                )

        # --------------------------------------------------
        # Control chart
        # --------------------------------------------------
            with cr:
                st.subheader(
                    "Hydrological Phase Distribution (Control)",
                    help=H("phase")
                )

                st.caption(
                    "Control · FL group then RL group"
                )

                fig_control = go.Figure()

                if not pc_c.empty:
                    fig_control.add_trace(go.Pie(
                        labels=pc_c["phase"],
                        values=pc_c["count"],
                        sort=False,
                        hole=0.62,
                        domain=dict(x=[0, 1], y=[0, 1]),
                        marker=dict(
                            colors=[
                                C["phase_control"].get(p, "#999")
                                for p in pc_c["phase"]
                            ],
                            line=dict(color="white", width=1)
                        ),
                        textinfo="none",
                        name="Control",
                        hovertemplate=(
                            "<b>Control</b><br>"
                            "%{label}: %{percent}"
                            "<extra></extra>"
                        )
                    ))

                fig_control.update_layout(
                    height=340,
                    margin=dict(l=10, r=10, t=10, b=10),
                    paper_bgcolor="rgba(0,0,0,0)",
                    showlegend=True,
                    legend=dict(
                        orientation="h",
                        yanchor="bottom",
                        y=-0.18,
                        xanchor="center",
                        x=0.5,
                        font_size=9
                    )
                )

                st.plotly_chart(
                    fig_control,
                    use_container_width=True
                )

    with st.expander("Irrigation Depth and No. of Irrigations by Village", expanded=False):
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
    """Uses the full cohort (not the sidebar filters): a pair needs one farmer from each group."""
    st.markdown("### Compare Farmers")
    st.caption("Pick a Treatment farmer")

    if master.empty or summary.empty:
        st.warning("Both Master Analysis and Summary sheets are needed for this comparison.")
        return

    is_t = to_group(master[M["type"]]) == "Treatment"
    is_c = to_group(master[M["type"]]) == "Control"
    if not is_t.any() or not is_c.any():
        st.warning("Both Treatment and Control farmers are needed for this comparison.")
        return

    def _farmers(group_mask, village):
        return sorted(master[group_mask & (master[M["village"]] == village)][M["farmer"]].dropna().unique())

    vt_pool = sorted(master[is_t][M["village"]].dropna().unique())
    vc_pool = sorted(master[is_c][M["village"]].dropna().unique())
    c_home = master[is_c].drop_duplicates(M["farmer"]).set_index(M["farmer"])[M["village"]].to_dict()
    pair_map = {}
    if S["default_pair"] in summary.columns:
        pair_map = dict(zip(summary[S["farmer"]], summary[S["default_pair"]].astype(str).str.strip()))

    # Session-state plumbing for the default pairing. Callbacks run before the widgets are
    # redrawn, which is the only point where their keyed values may be overwritten.
    def _apply_pairing():
        pair = pair_map.get(st.session_state.get("cmp_farmer_t"))
        if pair in c_home:
            st.session_state["cmp_village_c"] = c_home[pair]
            st.session_state["cmp_farmer_c"] = pair

    def _on_village_t():
        pool = _farmers(is_t, st.session_state["cmp_village_t"])
        st.session_state["cmp_farmer_t"] = pool[0] if pool else None
        _apply_pairing()

    def _on_village_c():
        pool = _farmers(is_c, st.session_state["cmp_village_c"])
        st.session_state["cmp_farmer_c"] = pool[0] if pool else None

    if "cmp_village_t" not in st.session_state:
        st.session_state["cmp_village_t"] = vt_pool[0]
        st.session_state["cmp_farmer_t"] = (_farmers(is_t, vt_pool[0]) or [None])[0]
        _apply_pairing()
        st.session_state.setdefault("cmp_village_c", vc_pool[0])
        st.session_state.setdefault("cmp_farmer_c", (_farmers(is_c, vc_pool[0]) or [None])[0])

    # ── Subsection 1 — farmer pickers ────────────────────────────────
    cL, cR = st.columns(2)
    with cL:
        st.markdown("**Treatment Farmer**")
        village_t = st.selectbox("Village", vt_pool, key="cmp_village_t",
                                 on_change=_on_village_t, help=H("village_filter"))
        farmer_t = st.selectbox("Farmer", _farmers(is_t, village_t), key="cmp_farmer_t",
                                on_change=_apply_pairing, help=H("farmer"))
    with cR:
        st.markdown("**Control Farmer**")
        village_c = st.selectbox("Village", vc_pool, key="cmp_village_c",
                                 on_change=_on_village_c, help=H("village_filter"))
        farmer_c = st.selectbox("Farmer", _farmers(is_c, village_c), key="cmp_farmer_c", help=H("farmer"))

    default_c = pair_map.get(farmer_t)
    if default_c in c_home:
        if farmer_c == default_c:
            st.caption(f" {farmer_c} is the default Control pairing for {farmer_t}.")
        else:
            st.caption(f" Custom pairing — the default Control farmer for {farmer_t} is {default_c}.")

    fmt = master[master[M["farmer"]] == farmer_t].sort_values(M["date"])
    fmc = master[master[M["farmer"]] == farmer_c].sort_values(M["date"])
    fst = summary[summary[S["farmer"]] == farmer_t]
    fsc = summary[summary[S["farmer"]] == farmer_c]
    rowt = fst.iloc[0] if not fst.empty else None
    rowc = fsc.iloc[0] if not fsc.empty else None

    # ── Subsection 2 — water level trend ─────────────────────────────
    with st.expander(f"Water Level Trend — {farmer_t} vs {farmer_c}", expanded=True):
        st.caption("Daily water level relative to soil surface. ▲ = irrigation reported.")
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
        fig2.update_layout(yaxis=dict(title="Daily water level vs surface (cm)"))
        style_fig(fig2, height=340)
        st.plotly_chart(fig2, use_container_width=True)

    # ── Subsection 3 — build-your-own chart (opens on a default graph) ─
    with st.expander("Build your own chart", expanded=True):
        st.caption(f"Explore {farmer_t} (Treatment) and {farmer_c} (Control) — daily readings or season totals.")
        pair_master = pd.concat([fmt, fmc])
        pair_summary = pd.concat([fst, fsc])
        chart_builder("cmp_chart", {
            "Daily readings": dict(
                builder_daily(pair_master),
                default=dict(chart="Line", x=DAS_COL, y=M["cum_irrig"], color="Group", agg="None (raw values)")),
            "Season summary": dict(
                builder_summary(pair_summary),
                default=dict(chart="Bar", x=S["farmer"], y=S["total_water_mm"], color="Group", agg="None (raw values)")),
        })

    # ── Subsection 4 — pair KPIs (Control vs Treatment) ──────────────
    def _num(row, key):
        if row is None: return None
        v = row.get(S[key])
        return float(v) if pd.notna(v) else None

    t_mm, c_mm = _num(rowt, "total_water_mm"), _num(rowc, "total_water_mm")
    t_pct, c_pct = _num(rowt, "savings_pct"), _num(rowc, "savings_pct")
    t_ac, c_ac = _num(rowt, "land_area"), _num(rowc, "land_area")

    diff_mm = (c_mm - t_mm) if t_mm is not None and c_mm is not None else None
    sav_pct = ((c_pct - t_pct) / c_pct * 100) if t_pct is not None and c_pct else None
    actual_m3 = (diff_mm * t_ac * 4046 / 1000) if diff_mm is not None and t_ac is not None else None
    potential_m3 = (diff_mm * c_ac * 4046 / 1000) if diff_mm is not None and c_ac is not None else None

    with st.expander("Key Performance Indicators — Control vs Treatment", expanded=True):
        st.caption(f"{farmer_c} (Control) compared with {farmer_t} (Treatment). "
                   "")
        k1, k2, k3, k4 = st.columns(4)
        metric_card(k1, "Water Savings (mm)", fmt_or_dash(diff_mm, "{:+,.0f} mm"),
                    "", "savings_mm", C["accent"])
        metric_card(k2, "Water Savings (%)", fmt_or_dash(sav_pct, "{:+.1f}%"),
                    "", "savings_pct", C["accent"])
        metric_card(k3, "Actual Volumetric Saving (m³)", fmt_or_dash(actual_m3, "{:+,.0f} m³"),
                    "", "savings_m3", C["accent"])
        metric_card(k4, "Potential Volumetric Savings (m³)", fmt_or_dash(potential_m3, "{:+,.0f} m³"),
                    "", "savings_m3", C["treatment"])

    # ── Subsection 5 — side-by-side scoreboards / tables ─────────────
    st.markdown("### Side by Side")
    hl, hr = st.columns(2)
    hl.markdown(f"<div style='border-bottom:3px solid {C['treatment']};font-weight:700;"
                f"color:{C['treatment']};padding-bottom:2px;'>Treatment Farmer — {farmer_t}</div>",
                unsafe_allow_html=True)
    hr.markdown(f"<div style='border-bottom:3px solid {C['control']};font-weight:700;"
                f"color:{C['control']};padding-bottom:2px;'>Control Farmer — {farmer_c}</div>",
                unsafe_allow_html=True)
    for kind in ["kpi", "productivity", "water", "irrigation", "remarks"]:
        left, right = st.columns(2)
        title = "Remarks" if kind == "remarks" else SECTION_TITLES[kind]
        opened = kind in ("kpi", "productivity")
        for col, who, row, accent in [(left, "Treatment Farmer", rowt, C["treatment"]),
                                      (right, "Control Farmer", rowc, C["control"])]:
            with col:
                with st.expander(f"{title} — {who}", expanded=opened):
                    if row is None:
                        st.info("No Summary row for this farmer.")
                    elif kind == "remarks":
                        kv_table(info_rows(row, REMARKS_SPEC))
                    else:
                        render_section(kind, row, accent)

    # ── Performance index (radar) ────────────────────────────────────
    with st.expander("Performance Index", expanded=False):
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
    row = sm.iloc[0] if not sm.empty else None
    accent = GROUP_COLOR.get(st_disp, C["accent"])

    # ── Subsection 1 — season summary + scoreboards ──────────────────
    with st.expander(f"Season Summary — {sel}", expanded=True):
        if row is None:
            st.info("No Summary row found for this farmer.")
        else:
            with st.container(key="deep_dive_season_summary"):
                c1, c2, c3, c4, c5 = st.columns(5)
                days_mon = row.get(S["days_monitored"])
                dry_ev = row.get(S["drying_events"])
                pairs = [
                    (c1, "Village", str(row.get(S["village"], "—")), "village"),
                    (c2, "Type", relabel_type(str(row.get(S["type"], "—"))), "type"),
                    (c3, "Land (ac)", str(row.get(S["land_area"], "—")), "land_area"),
                    (c4, "Days Monitored", str(int(days_mon)) if pd.notna(days_mon) else "—", "days_monitored"),
                    (c5, "Dry Events", str(int(dry_ev)) if pd.notna(dry_ev) else "—", "drying_events"),
                ]
                for col, lab, val, key in pairs:
                    col.metric(lab, val, help=H(key))

    if row is not None:
        with st.expander("Key Performance Index", expanded=True):
            render_section("kpi", row, accent, ncols=3)
        with st.expander("Productivity", expanded=True):
            render_section("productivity", row, accent, ncols=5)
        with st.expander("Information", expanded=False):
            kv_table(info_rows(row))
        with st.expander("Water Usage", expanded=True):
            render_section("water", row, accent, ncols=4)
        with st.expander("Irrigation", expanded=False):
            render_section("irrigation", row, accent)

    # ── Subsection 2 — daily water level chart ───────────────────────
    with st.expander(f"Daily Water Level — {sel}", expanded=True):
        st.caption("Daily water level reading over time · ▲ = irrigation reported · ◇ = irrigation calculated (water level rose >2cm) · phase bars below")

        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.72, 0.28],
            subplot_titles=(LBL_DWL, "Phase"), vertical_spacing=0.05)
        fig.add_hrect(y0=5, y1=25, row=1, col=1, fillcolor=C["safe_zone"], line_width=0)
        fig.add_trace(go.Scatter(x=fm[M["date"]], y=fm[M["pp_reading"]], name="Daily water level reading",
            mode="lines+markers", line=dict(color=C["treatment"], width=2.5), marker=dict(size=4),
            hovertemplate="<b>%{x|%d %b %Y}</b><br>Water level reading: %{y:.1f} cm<extra></extra>"), row=1, col=1)
        fig.add_hline(y=15, line_dash="dash", line_color=C["accent"], line_width=1.5, row=1, col=1,
            annotation_text="Surface", annotation_font_color=C["accent"], annotation_position="bottom right")
        fig.add_hline(y=25, line_dash="dot", line_color=C["control"], line_width=1, row=1, col=1,
            annotation_text="Dry (25cm)", annotation_font_color=C["control"], annotation_position="top right")

        ir = fm[fm[M["irrigated"]] == True]
        if not ir.empty:
            fig.add_trace(go.Scatter(x=ir[M["date"]], y=ir[M["pp_reading"]], name="Irrigation (Reported)",
                mode="markers", marker=dict(symbol="triangle-up", size=11, color=C["accent"],
                line=dict(color="white", width=1)),
                hovertemplate="<b>Irrigation (Reported)</b><br>%{x|%d %b}<br>Level: %{y:.1f}<extra></extra>"), row=1, col=1)

        if M["irrig_calc"] in fm.columns:
            irc = fm[fm[M["irrig_calc"]] == True]
            if not irc.empty:
                fig.add_trace(go.Scatter(x=irc[M["date"]], y=irc[M["pp_reading"]], name="Irrigation (Calculated)",
                    mode="markers", marker=dict(symbol="diamond", size=8, color=C["treatment"],
                    line=dict(color="white", width=1)),
                    hovertemplate="<b>Irrigation (Calculated)</b><br>%{x|%d %b}<br>Level: %{y:.1f}<extra></extra>"), row=1, col=1)

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
            yaxis=dict(title=LBL_DWL, autorange="reversed", showgrid=True, gridcolor=C["grid"]),
            yaxis2=dict(showticklabels=False, showgrid=False),
            xaxis2=dict(showgrid=True, gridcolor=C["grid"]))
        st.plotly_chart(fig, use_container_width=True)

    # ── Subsection 3 — build-your-own chart (opens on a default graph) ─
    with st.expander("Build your own chart", expanded=True):
        st.caption(f"Pick a chart type, axes, colour and filters to explore {sel}'s daily readings.")
        chart_builder("ind_chart", {"Daily readings": dict(
            builder_daily(fm),
            default=dict(chart="Line", x=M["date"], y=M["cum_irrig"], color="(none)", agg="None (raw values)"))})

    # ── Extras kept from the earlier layout (collapsed to keep the page clean) ──
    with st.expander("Phase Distribution", expanded=False):
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

    with st.expander("📋 Raw daily data", expanded=False):
        show = [c for c in [M["date"], M["das"], M["pp_reading"], M["bgl"],
                M["fl_rl"], M["phase"], M["change_wl"], M["event"],
                M["gopal_cm"], M["cum_irrig"], M["irrigated"], M["irrig_calc"],
                M["rain"], M["cum_rain"], M["zero_repl"], M["remarks"]] if c in fm.columns]
        col_config = {
            M["date"]: st.column_config.DateColumn(format="DD MMM YYYY", help=H("date")),
            M["das"]: st.column_config.Column("Days After Sowing", help=H("das")),
            M["pp_reading"]: st.column_config.Column(LBL_DWL, help=H("pp_reading")),
            M["bgl"]: st.column_config.NumberColumn("BGL", format="%+.1f", help=H("bgl")),
            M["fl_rl"]: st.column_config.Column(help=H("fl_rl")),
            M["phase"]: st.column_config.Column(help=H("phase")),
            M["change_wl"]: st.column_config.Column(help=H("change_wl")),
            M["event"]: st.column_config.Column(help=H("event")),
            M["gopal_cm"]: st.column_config.Column(help=H("gopal_cm")),
            M["cum_irrig"]: st.column_config.Column(help=H("cum_irrig")),
            M["rain"]: st.column_config.Column(help=H("rain")),
            M["cum_rain"]: st.column_config.Column(help=H("cum_rain")),
            M["remarks"]: st.column_config.Column(help=H("remarks")),
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
        div[data-testid="stExpander"] [data-testid="stMetricLabel"] {{ min-height:2.6em;align-items:flex-start; }}
        div[data-testid="stExpander"] [data-testid="stMetricLabel"] * {{ white-space:normal !important;
            overflow:visible !important;text-overflow:clip !important;line-height:1.25; }}
        div[data-testid="stExpander"] [data-testid="stMetricValue"] {{ font-size:1.35rem; }}
        div[data-testid="stExpander"] [data-testid="stMetricDelta"] {{ font-size:0.72rem; }}
        div[data-testid="stExpander"] [data-testid="stMetricDelta"] svg {{ display:none; }}
        div[data-testid="stExpander"] [data-testid="stMetricDelta"] * {{ white-space:normal !important;overflow:visible !important; }}
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

    t1, t2, t3, t4 = st.tabs([
        " Results Overview",
        " Individual Farmer Results",
        " Compare Farmers",
        " Get Data",
    ])
    with t1: tab_results_overview(master_f, summary_f, master, summary)
    with t2: tab_individual_farmer(master_f, summary_f)
    with t3: tab_compare_farmers(master, summary)
    with t4: tab_explorer(master_f, summary_f)


if __name__ == "__main__":
    main()

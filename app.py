"""
AWD FARMER PROGRESS DASHBOARD — v3
Reads from two Google Sheets:
  1. Master Analysis  — daily readings, one row per farmer per date
  2. Summary          — season totals, one row per farmer

To connect your sheets: find the two lines marked with ← PASTE YOUR URL HERE
and replace with your published CSV links.

Field-type terminology: the source data (and Google Sheet) uses "Experimental"
for AWD-protocol farmers. Every page in this dashboard displays that group as
"Treatment" instead — see relabel_type() / to_group() below. Filtering logic
still matches on the raw "Experimental" value since that's what's in the data.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import numpy as np
import requests
from io import StringIO
from datetime import datetime

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
    r"https://docs.google.com/spreadsheets/d/e/2PACX-1vRK8CYPjHB6tBB9H5HFxJ_rIy6Exj5CpH8q7elgAN7DTXlehdNYX1034etUT1H7Ip6rdOFrdX_2RnJw/pub?gid=124140633&single=true&output=csv"
)

SUMMARY_URL = (
    r"https://docs.google.com/spreadsheets/d/e/2PACX-1vRK8CYPjHB6tBB9H5HFxJ_rIy6Exj5CpH8q7elgAN7DTXlehdNYX1034etUT1H7Ip6rdOFrdX_2RnJw/pub?gid=1264516221&single=true&output=csv"
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
}

# FL terms always grouped before RL terms in every chart that shows phases
PHASE_ORDER = ["FL-Flood", "FL-Inter", "FL-Soil", "RL-Flood", "RL-Inter", "RL-Soil", "No change"]

# Display-label mapping — "Experimental" (source data) shows as "Treatment" everywhere
LABEL = {"Experimental": "Treatment"}
GROUP_COLOR = {"Treatment": C["treatment"], "Control": C["control"]}


def relabel_type(val):
    """Map a raw Type value to its display label (Experimental -> Treatment)."""
    return LABEL.get(val, val)


def to_group(series):
    """Return a display-label copy of a Type/Group column for charting & tables."""
    return series.map(relabel_type)


# ═══════════════════════════════════════════════════════════════════
# COLUMN NAMES — Master Analysis (21 columns)
# ═══════════════════════════════════════════════════════════════════
M = {
    "farmer"      : "Farmer Name",
    "village"     : "Village (Gram Panchayat)",
    "type"        : "Type",
    "method"      : "Method of Cultivation",
    "land_area"   : "Land Area (acres)",
    "sowing_date" : "Date of Sowing",
    "crp"         : "CRP Incharge",
    "date"        : "Date",
    "das"         : "Days Since Sowing",
    "pp_reading"  : "PP Reading (cm)",
    "duplicate"   : "Duplicate? (count)",
    "zero_repl"   : "Zero Replaced?",
    "bgl"         : "In ref to surface",
    "fl_rl"       : "FL / RL",
    "phase"       : "Phase",
    "change_wl"   : "Change in WL (cm)",
    "irrig_cm"    : "Irrigated Water (cm)",
    "irrig_m3"    : "Irrigated Water (m3)",
    "gopal_cm"    : "Irrig. Depth Gopal (cm)",
    "irrigated"   : "Irrigation Reported",
    "days_mon"    : "Days Monitored",
}

# Derived column — not in the source sheet, calculated on load.
# Matches the Apps Script definition: BGL rose >2cm vs the previous day.
IRRIG_CALC_COL = "Irrigation Calculated (derived)"

# ═══════════════════════════════════════════════════════════════════
# COLUMN NAMES — Summary (45 columns)
# ═══════════════════════════════════════════════════════════════════
S = {
    "serial"            : "#",
    "farmer"            : "Farmer Name",
    "village"           : "Village (Gram Panchayat)",
    "type"              : "Type",
    "method"            : "Method of Cultivation",
    "land_area"         : "Land Area (acres)",
    "sowing_date"       : "Date of Sowing",
    "cm_start"          : "Date of CM Start",
    "cm_end"            : "Date of CM End",
    "days_monitored"    : "Days Monitored",
    "duplicate_days"    : "Duplicate Days",
    "missing_days"      : "Missing Days",
    "error_margin"      : "Error Margin",
    "days_above"        : "Days Water Above Surface",
    "days_below"        : "Days Water Below Surface",
    "dry_days"          : "Dry Days (>=25cm)",
    "drying_events"     : "No. of Drying Events",
    "avg_between_dry"   : "Avg Days Between Dry Periods",
    "min_between_dry"   : "Min Days Between Dry Periods",
    "max_between_dry"   : "Max Days Between Dry Periods",
    "irrigations_a"     : "No. Irrigations (a) Reported",
    "irrigations_b"     : "No. Irrigations (b) Calculated",
    "avg_between_wet"   : "Avg Days Between Wet Events",
    "avg_drying_overall": "Avg Drying Days (Overall)",
    "avg_drying_p1"     : "Avg Drying Days Phase 1 (0-30)",
    "avg_drying_p2"     : "Avg Drying Days Phase 2 (30-60)",
    "avg_drying_p3"     : "Avg Drying Days Phase 3 (60-90)",
    "avg_drying_p4"     : "Avg Drying Days Phase 4 (90+)",
    "max_wl_events"     : "Max WL Events (>10cm above)",
    "min_wl_events"     : "Min WL Events (>10cm below)",
    "total_water_mm"    : "Total Water Added (mm)",
    "total_water_m3"    : "Total Water Added (m3)",
    "total_recharged_mm": "Total Water Recharged (mm)",
    "total_recharged_m3": "Total Water Recharged (m3)",
    "rl_flood_cm"       : "RL-Flood (cm) ",
    "rl_inter_cm"       : "RL-Inter (cm) ",
    "rl_soil_cm"        : "RL-Soil (cm) ",
    "fl_flood_cm"       : "FL-Flood (cm) ",
    "fl_inter_cm"       : "FL-Inter (cm) ",
    "fl_soil_cm"        : "FL-Soil (cm) ",
    # This column has been removed from the Summary sheet (not renamed).
    # Every place that reads it already falls back to "—" when it's absent,
    # so this mapping is kept only so those fallbacks stay well-defined.
    "avg_gopal_cm"      : "Avg Irrig. Depth - Gopal (cm)",
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
    # Daily readings
    "date"        : "The calendar date of this water-level reading.",
    "das"         : "Days Since Sowing — how many days have passed since the crop was sown.",
    "pp_reading"  : "Pani Pipe reading in centimetres — the distance from the top of the pipe down to the water surface inside it. Lower = more flooded, higher = drier. Formula: BGL = 15 − PP Reading.",
    "duplicate"   : "Flags dates where more than one raw reading was submitted for this farmer and the readings were averaged together.",
    "zero_repl"   : "Flags a reading of 0 (physically impossible) that was automatically replaced with the previous day's value.",
    "bgl"         : "Water level relative to the soil surface, in cm (15 − PP Reading). Positive = water above the surface (flooded). Negative = water below the surface (drying).",
    "fl_rl"       : "Falling Limb (FL) = field is drying (today's level lower than yesterday's). Rising Limb (RL) = field is being re-wetted. NC = no change.",
    "phase"       : "One of six AWD cycle phases — FL-Flood, FL-Inter, FL-Soil (drying), then RL-Soil, RL-Inter, RL-Flood (re-wetting) — showing exactly where the field sits in the wet/dry cycle.",
    "change_wl"   : "Day-on-day change in water level, in cm. Positive = rising, negative = falling.",
    "irrig_cm"    : "Depth of water added on Rising Limb (re-wetting) days, in centimetres.",
    "irrig_m3"    : "Volume of water added, in cubic metres — irrigation depth scaled by the field's land area.",
    "gopal_cm"    : "Advisor Gopal's normalised irrigation depth (cm), adjusted for soil porosity (7%) so it's directly comparable across farmers regardless of field size.",
    "irrigated"   : "Whether the enumerator recorded that the field was irrigated on this date — a ground-truth field observation (\"Irrigations Reported\").",
    "irrig_calc"  : "A day is counted as an irrigation here if the water level rose by more than 2 cm compared to the previous day — calculated purely from the readings, independent of what the enumerator reported. Comparing this to \"Reported\" flags possible data-entry gaps.",
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
    # Drying duration by stage
    "avg_drying_overall": "Average duration, in days, of all drying events across the full season.",
    "avg_drying_p1" : "Average drying-event duration during 0–30 Days After Sowing — early vegetative stage, roots shallow, demand low.",
    "avg_drying_p2" : "Average drying-event duration during 30–60 Days After Sowing — active tillering, water demand increases.",
    "avg_drying_p3" : "Average drying-event duration during 60–90 Days After Sowing — panicle initiation, a critical reproductive stage.",
    "avg_drying_p4" : "Average drying-event duration during 90+ Days After Sowing — grain filling and maturity, longer dry spells are often fine here.",
    # Extremes
    "max_wl_events" : "Count of days the water level was more than 10cm above the soil surface — flags over-flooding / excess water input.",
    "min_wl_events" : "Count of days the water level was more than 10cm below the soil surface — flags deep drying / potential crop stress.",
    # Water volumes
    "total_water_mm"     : "Total irrigation water added across the season, in millimetres depth, using Gopal's normalised formula.",
    "total_water_m3"     : "Total irrigation water added across the season, in cubic metres — depth scaled by the field's land area.",
    "total_recharged_mm" : "Total water drained from the field across the season (Falling Limb / drying events), in millimetres depth.",
    "total_recharged_m3" : "Total water drained from the field across the season, in cubic metres.",
    "avg_gopal_cm"       : "Average of all per-irrigation-event Gopal depth values (cm) across the season — a field-size-independent metric, so it's fair to compare across farmers.",
    "rl_flood_cm" : "Total Gopal depth (cm) accumulated on RL-Flood days this season — full depth counted, both above ground.",
    "rl_inter_cm" : "Total Gopal depth (cm) accumulated on RL-Inter days this season — split formula as water crosses the surface upward.",
    "rl_soil_cm"  : "Total Gopal depth (cm) accumulated on RL-Soil days this season — porosity-adjusted, both below ground.",
    "fl_flood_cm" : "Total Gopal depth (cm) drained on FL-Flood days this season (negative — water lost, both above ground).",
    "fl_inter_cm" : "Total Gopal depth (cm) drained on FL-Inter days this season (negative — split formula, crossing surface downward).",
    "fl_soil_cm"  : "Total Gopal depth (cm) drained on FL-Soil days this season (negative — porosity-adjusted, both below ground).",
    # App-level concepts
    "safe_zone"      : "The −5 to +10 cm BGL band shaded green on these charts — a water level considered a good balance between the drying benefits of AWD and the risk of crop stress.",
    "tnau_baseline"  : "The Tamil Nadu Agricultural University conventional irrigation benchmark: 1.1 metres of water depth per acre per season (≈4,451.5 m³/acre). Used as the reference point for calculating water savings.",
    "savings_pct"    : "(TNAU Baseline − Actual Water Added) ÷ TNAU Baseline × 100 — the percentage of the conventional water benchmark this programme is saving.",
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
        num_cols = [M["land_area"], M["das"], M["pp_reading"], M["bgl"],
                    M["change_wl"], M["irrig_cm"], M["irrig_m3"],
                    M["gopal_cm"], M["days_mon"]]
        for col in num_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        if M["irrigated"] in df.columns:
            df[M["irrigated"]] = df[M["irrigated"]].astype(str).str.upper() == "TRUE"
        for col in [M["farmer"], M["village"], M["type"], M["phase"], M["fl_rl"]]:
            if col in df.columns:
                df[col] = df[col].astype(str).str.strip()
        df = df.sort_values([M["farmer"], M["date"]]).reset_index(drop=True)
        # Derived: calculated irrigation — BGL rose >2cm vs the previous day for that farmer
        if M["bgl"] in df.columns and M["farmer"] in df.columns:
            df[IRRIG_CALC_COL] = df.groupby(M["farmer"])[M["bgl"]].diff() > 2
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
        for col in [S["sowing_date"], S["cm_start"], S["cm_end"]]:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], dayfirst=True, errors="coerce")
        num_s = [v for k, v in S.items()
                 if k not in ["serial","farmer","village","type","method",
                              "sowing_date","cm_start","cm_end"]]
        for col in num_s:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        for col in [S["farmer"], S["village"], S["type"]]:
            if col in df.columns:
                df[col] = df[col].astype(str).str.strip()
        return df
    except Exception as e:
        st.error(f"Error loading Summary: {e}")
        return pd.DataFrame()


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
            fm = fm[fm[M["type"]] == "Experimental"]
            fs = fs[fs[S["type"]] == "Experimental"]
        elif sel_t == "Control":
            fm = fm[fm[M["type"]] == "Control"]
            fs = fs[fs[S["type"]] == "Control"]

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
            f"<h1 style='color:{C['text']};font-size:26px;margin:0;'>"
            "🌾 AWD Farmer Progress Monitor</h1>"
            f"<p style='color:{C['text_muted']};font-size:13px;margin:3px 0 0;'>"
            "Alternative Wetting &amp; Drying · Water Level Monitoring</p>",
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
# TAB 1 — PROGRAMME OVERVIEW
# ═══════════════════════════════════════════════════════════════════

def tab_overview(master, summary):
    if summary.empty and master.empty:
        st.info("No data loaded.")
        return

    st.markdown("### Key Programme Metrics")
    n_f  = safe_nunique(summary, S["farmer"])
    n_v  = safe_nunique(summary, S["village"])
    n_de = safe_mean(summary, S["drying_events"])
    treat_bgl = safe_mean(master[master[M["type"]] == "Experimental"], M["bgl"]) \
                if not master.empty and M["type"] in master.columns else None
    ctrl_bgl  = safe_mean(master[master[M["type"]] == "Control"], M["bgl"]) \
                if not master.empty and M["type"] in master.columns else None
    safe = 0
    if not master.empty and M["bgl"] in master.columns:
        s = master[(master[M["bgl"]] >= -5) & (master[M["bgl"]] <= 10)]
        safe = len(s) / len(master) * 100
    irr_a = safe_mean(summary, S["irrigations_a"])
    irr_b = safe_mean(summary, S["irrigations_b"])

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    metric_card(c1, "Farmers Enrolled", f"{n_f:,}", f"{n_v} villages", "farmer", C["treatment"])
    metric_card(c2, "Avg Drying Events", fmt_or_dash(n_de), "per farmer", "drying_events", C["accent"])
    metric_card(c3, "In Safe Zone", f"{safe:.0f}%", "BGL −5 to +10 cm", "safe_zone", C["accent"])
    metric_card(c4, "Treatment Avg BGL",
                fmt_or_dash(treat_bgl, "{:+.1f} cm"),
                "in ref to surface", "bgl", C["treatment"])
    metric_card(c5, "Control Avg BGL",
                fmt_or_dash(ctrl_bgl, "{:+.1f} cm"),
                "in ref to surface", "bgl", C["control"])
    with c6:
        with st.container(border=True):
            st.markdown(
                f"<div style='height:4px;background:{C['accent']};border-radius:3px;"
                f"margin:-1rem -1rem 0.6rem -1rem;'></div>", unsafe_allow_html=True)
            st.metric("Avg Irrigations (Calculated)", fmt_or_dash(irr_b),
                       f"{irr_a:.1f} reported" if irr_a is not None and pd.notna(irr_a) else None,
                       delta_color="off",
                       help=H("irrigations_a") + " " + H("irrigations_b"))

    st.markdown("<br>", unsafe_allow_html=True)
    st.divider()

    cl, cr = st.columns([1.3, 1])

    with cl:
        st.subheader("Weekly Water Level Trend", help=H("safe_zone"))
        st.caption("Avg BGL · Treatment vs Control · green band = safe zone")
        if not master.empty:
            mm = master.copy()
            mm["Group"] = to_group(mm[M["type"]])
            wk = (mm.assign(week=mm[M["date"]].dt.to_period("W").dt.start_time)
                  .groupby(["week", "Group"])[M["bgl"]].mean().reset_index())
            fig = go.Figure()
            fig.add_hrect(y0=-5, y1=10, fillcolor=C["safe_zone"],
                          line_width=0, annotation_text="Safe zone",
                          annotation_font_color=C["accent"],
                          annotation_position="top left")
            for grp in ["Treatment", "Control"]:
                sub = wk[wk["Group"] == grp]
                if sub.empty: continue
                fig.add_trace(go.Scatter(x=sub["week"], y=sub[M["bgl"]],
                    name=grp, mode="lines+markers",
                    line=dict(color=GROUP_COLOR[grp], width=2.5), marker=dict(size=5),
                    hovertemplate=f"<b>{grp}</b><br>Week: %{{x|%d %b}}<br>Avg BGL: %{{y:.1f}} cm<extra></extra>"))
            fig.add_hline(y=0, line_dash="dash", line_color="#999", line_width=1)
            fig.update_layout(yaxis=dict(title="BGL (cm)"))
            style_fig(fig, height=320)
            st.plotly_chart(fig, use_container_width=True)

    with cr:
        st.subheader("Phase Distribution", help=H("phase"))
        st.caption("Share of all readings by FL/RL phase — FL group then RL group")
        if not master.empty:
            pc = master[M["phase"]].value_counts().reset_index()
            pc.columns = ["phase", "count"]
            pc["phase"] = pd.Categorical(pc["phase"], categories=PHASE_ORDER, ordered=True)
            pc = pc.sort_values("phase").dropna(subset=["phase"])
            cols_list = [C["phase"].get(p, "#999") for p in pc["phase"]]
            fig2 = go.Figure(go.Pie(labels=pc["phase"], values=pc["count"], hole=0.55, sort=False,
                marker=dict(colors=cols_list, line=dict(color="white", width=2)),
                textinfo="label+percent", textfont_size=10))
            fig2.update_layout(height=320, margin=dict(l=0, r=0, t=0, b=0),
                paper_bgcolor="rgba(0,0,0,0)", showlegend=False)
            st.plotly_chart(fig2, use_container_width=True)

    st.divider()

    ca, cb = st.columns(2)
    with ca:
        st.markdown("#### Water relative to Soil Surface by Village", help=H("bgl"))
        if not master.empty:
            mm = master.copy()
            mm["Group"] = to_group(mm[M["type"]])
            vb = (mm.groupby([M["village"], "Group"])[M["bgl"]]
                  .mean().reset_index().rename(columns={M["bgl"]: "avg_bgl"}))
            fig3 = px.bar(vb, x=M["village"], y="avg_bgl", color="Group",
                barmode="group", color_discrete_map=GROUP_COLOR,
                labels={"avg_bgl": "Avg BGL (cm)", M["village"]: ""}, height=300)
            fig3.add_hline(y=0, line_dash="dash", line_color="#999", line_width=1)
            style_fig(fig3, height=300)
            st.plotly_chart(fig3, use_container_width=True)

    with cb:
        st.subheader("Avg Drying Events by Village", help=H("drying_events"))
        if not summary.empty and S["drying_events"] in summary.columns:
            sm = summary.copy()
            sm["Group"] = to_group(sm[S["type"]])
            vd = (sm.groupby([S["village"], "Group"])[S["drying_events"]]
                  .mean().reset_index().rename(columns={S["drying_events"]: "avg_de"}))
            fig4 = px.bar(vd, x=S["village"], y="avg_de", color="Group",
                barmode="group", color_discrete_map=GROUP_COLOR,
                labels={"avg_de": "Avg Drying Events", S["village"]: ""}, height=300)
            style_fig(fig4, height=300)
            st.plotly_chart(fig4, use_container_width=True)

    st.divider()

    st.subheader("Avg Drying Duration by Crop Growth Stage (DAS)", help=H("avg_drying_overall"))
    if not summary.empty:
        rows = []
        for label, col in [("0–30 DAS", S["avg_drying_p1"]), ("30–60 DAS", S["avg_drying_p2"]),
                            ("60–90 DAS", S["avg_drying_p3"]), ("90+ DAS", S["avg_drying_p4"])]:
            if col not in summary.columns: continue
            for grp_val in summary[S["type"]].unique():
                avg = summary[summary[S["type"]] == grp_val][col].mean()
                rows.append({"Stage": label, "Group": relabel_type(grp_val), "Avg Days": avg})
        if rows:
            pf = pd.DataFrame(rows).dropna()
            fig5 = px.bar(pf, x="Stage", y="Avg Days", color="Group", barmode="group",
                color_discrete_map=GROUP_COLOR, height=300)
            style_fig(fig5, height=300)
            st.plotly_chart(fig5, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════
# TAB 2 — TREATMENT VS CONTROL PERFORMANCE COMPARISON
# ═══════════════════════════════════════════════════════════════════

def tab_comparison(master, summary):
    st.markdown("### Treatment vs Control — Performance Comparison")
    st.caption("Compare water-level trends and season metrics across every farmer, or drill down into one Treatment and one Control farmer side by side.")

    if master.empty or summary.empty:
        st.warning("Both Master Analysis and Summary sheets are needed for this comparison.")
        return

    villages = sorted(master[M["village"]].dropna().unique())
    sel_v = st.multiselect("Villages", villages, default=villages, help=H("village_filter"))
    if not sel_v:
        st.info("Select at least one village to see the comparison.")
        return

    mv = master[master[M["village"]].isin(sel_v)].copy()
    sv = summary[summary[S["village"]].isin(sel_v)].copy()
    mv["Group"] = to_group(mv[M["type"]])
    sv["Group"] = to_group(sv[S["type"]])

    st.subheader("All Treatment vs All Control — Weekly Water Level Trend", help=H("safe_zone"))
    st.caption("Average BGL across every selected farmer, grouped by week.")
    if not mv.empty:
        wk = (mv.assign(week=mv[M["date"]].dt.to_period("W").dt.start_time)
              .groupby(["week", "Group"])[M["bgl"]].mean().reset_index())
        fig = go.Figure()
        fig.add_hrect(y0=-5, y1=10, fillcolor=C["safe_zone"], line_width=0)
        for grp in ["Treatment", "Control"]:
            sub = wk[wk["Group"] == grp]
            if sub.empty: continue
            fig.add_trace(go.Scatter(x=sub["week"], y=sub[M["bgl"]], name=grp,
                mode="lines+markers", line=dict(color=GROUP_COLOR[grp], width=2.5),
                marker=dict(size=5),
                hovertemplate=f"<b>{grp}</b><br>Week: %{{x|%d %b}}<br>Avg BGL: %{{y:.1f}} cm<extra></extra>"))
        fig.add_hline(y=0, line_dash="dash", line_color="#999", line_width=1)
        fig.update_layout(yaxis=dict(title="Avg BGL (cm)"))
        style_fig(fig, height=320)
        st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.markdown("#### Farmer-level Drill-down")

    c1, c2 = st.columns(2)
    with c1:
        t_pool = sorted(mv[mv[M["type"]] == "Experimental"][M["farmer"]].dropna().unique())
        if not t_pool:
            st.warning("No Treatment farmers in the selected villages.")
            return
        farmer_t = st.selectbox("Treatment farmer", t_pool, help=H("type"))
    with c2:
        c_pool = sorted(mv[mv[M["type"]] == "Control"][M["farmer"]].dropna().unique())
        if not c_pool:
            st.warning("No Control farmers in the selected villages.")
            return
        farmer_c = st.selectbox("Control farmer", c_pool, help=H("type"))

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

    st.divider()
    st.markdown("#### Season Metrics — Side by Side")

    rowt = fst.iloc[0] if not fst.empty else None
    rowc = fsc.iloc[0] if not fsc.empty else None

    def fmt_val(row, key, fs="{:.1f}"):
        if row is None: return "—"
        v = row.get(S[key])
        return fs.format(v) if pd.notna(v) else "—"

    metrics = [
        ("Drying Events", "drying_events", "{:.0f}"),
        ("Irrigations (Reported)", "irrigations_a", "{:.0f}"),
        ("Irrigations (Calculated)", "irrigations_b", "{:.0f}"),
        ("Days Below Surface", "days_below", "{:.0f}"),
        ("Total Water Added (m³)", "total_water_m3", "{:.1f}"),
        ("Avg Gopal Depth (cm)", "avg_gopal_cm", "{:.2f}"),
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
    st.caption("Each metric is scaled 0–100 against the highest value seen among farmers in the selected villages, so the two farmers can be compared on one chart regardless of units.")

    if rowt is not None and rowc is not None:
        radar_metrics = [
            ("Drying Events", "drying_events"),
            ("Days Below Surface", "days_below"),
            ("Irrigations Reported", "irrigations_a"),
            ("Avg Gopal Depth", "avg_gopal_cm"),
            ("Water Added (m³)", "total_water_m3"),
        ]
        cats, vt, vc = [], [], []
        for label, key in radar_metrics:
            col = S[key]
            if col not in sv.columns: continue
            mx = sv[col].max()
            if pd.isna(mx) or mx == 0: continue
            cats.append(label)
            tv = rowt.get(col)
            cv = rowc.get(col)
            vt.append(float(tv) / mx * 100 if pd.notna(tv) else 0)
            vc.append(float(cv) / mx * 100 if pd.notna(cv) else 0)
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
    if st_t == "Treatment": ds = ds[ds[S["type"]] == "Experimental"]
    elif st_t == "Control": ds = ds[ds[S["type"]] == "Control"]

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
        st.subheader("Top 15 — Irrigation Events", help=H("irrigations_a") + " " + H("irrigations_b"))
        st.caption("Reported (field-observed) vs Calculated (from water-level readings)")
        if S["irrigations_a"] in ds.columns and S["irrigations_b"] in ds.columns:
            top_names = (ds[[S["farmer"], S["irrigations_a"]]].dropna()
                         .sort_values(S["irrigations_a"], ascending=True).tail(15)[S["farmer"]])
            melt = ds[ds[S["farmer"]].isin(top_names)][[S["farmer"], S["irrigations_a"], S["irrigations_b"]]]
            melt = melt.melt(id_vars=S["farmer"], value_vars=[S["irrigations_a"], S["irrigations_b"]],
                              var_name="Metric", value_name="Count")
            melt["Metric"] = melt["Metric"].map({S["irrigations_a"]: "Reported", S["irrigations_b"]: "Calculated"})
            order = pd.CategoricalDtype(top_names, ordered=True)
            melt[S["farmer"]] = melt[S["farmer"]].astype(order)
            fig = px.bar(melt.sort_values(S["farmer"]), y=S["farmer"], x="Count", color="Metric",
                orientation="h", barmode="group",
                color_discrete_map={"Reported": C["treatment"], "Calculated": C["accent"]},
                height=380, labels={S["farmer"]: ""})
            style_fig(fig, height=380)
            fig.update_layout(yaxis=dict(tickfont=dict(size=9)))
            st.plotly_chart(fig, use_container_width=True)

    with c2:
        st.subheader("Top 15 — Drying Events", help=H("drying_events"))
        if S["drying_events"] in ds.columns:
            dsg = ds.copy()
            dsg["Group"] = to_group(dsg[S["type"]])
            top2 = (dsg[[S["farmer"], "Group", S["drying_events"]]].dropna()
                    .sort_values(S["drying_events"], ascending=True).tail(15))
            fig2 = px.bar(top2, y=S["farmer"], x=S["drying_events"], color="Group",
                orientation="h", color_discrete_map=GROUP_COLOR,
                height=380, labels={S["drying_events"]: "Drying Events", S["farmer"]: ""})
            style_fig(fig2, height=380)
            fig2.update_layout(showlegend=False, yaxis=dict(tickfont=dict(size=9)))
            st.plotly_chart(fig2, use_container_width=True)

    csv = ds.to_csv(index=False).encode("utf-8")
    st.download_button("📥 Download CSV", data=csv,
                       file_name="awd_summary.csv", mime="text/csv")


# ═══════════════════════════════════════════════════════════════════
# TAB 4 — FARMER DEEP DIVE
# ═══════════════════════════════════════════════════════════════════

def tab_deep_dive(master, summary):
    st.markdown("### Farmer Deep Dive")
    if master.empty:
        st.warning("Master Analysis not loaded.")
        return

    cv, ct, cf = st.columns(3)
    with cv: sv = st.selectbox("Village", sorted(master[M["village"]].dropna().unique()), help=H("village_filter"))
    with ct:
        type_opts_raw = sorted(master[master[M["village"]] == sv][M["type"]].dropna().unique())
        type_opts = [relabel_type(t) for t in type_opts_raw]
        st_disp = st.selectbox("Type", type_opts, help=H("type_filter"))
        st_t = {v: k for k, v in LABEL.items()}.get(st_disp, st_disp)
    with cf:
        fs = sorted(master[(master[M["village"]] == sv) & (master[M["type"]] == st_t)][M["farmer"]].dropna().unique())
        sel = st.selectbox("Farmer", fs, help=H("farmer"))

    if not sel: return

    fm = master[master[M["farmer"]] == sel].copy()
    sm = summary[summary[S["farmer"]] == sel] if not summary.empty else pd.DataFrame()

    if not sm.empty:
        row = sm.iloc[0]
        st.markdown("#### Season Summary")
        c1, c2, c3, c4, c5, c6, c7, c8, c9 = st.columns(9)
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
            (c9, "Gopal (cm)", f"{row.get(S['avg_gopal_cm'], 0):.2f}" if pd.notna(row.get(S["avg_gopal_cm"])) else "—", "avg depth", "avg_gopal_cm"),
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

    if IRRIG_CALC_COL in fm.columns:
        irc = fm[fm[IRRIG_CALC_COL] == True]
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

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("In Ref to Surface (BGL)", help=H("bgl"))
        fig_b = go.Figure()
        fig_b.add_hrect(y0=-5, y1=10, fillcolor=C["safe_zone"], line_width=0)
        fig_b.add_trace(go.Scatter(x=fm[M["date"]], y=fm[M["bgl"]], fill="tozeroy",
            mode="lines", line=dict(color=C["treatment"], width=2),
            fillcolor="rgba(46,111,158,0.15)",
            hovertemplate="%{x|%d %b}<br>BGL: %{y:+.1f} cm<extra></extra>"))
        fig_b.add_hline(y=0, line_dash="dash", line_color="#999", line_width=1)
        fig_b.update_layout(yaxis=dict(title="cm"))
        style_fig(fig_b, height=280, legend=False)
        st.plotly_chart(fig_b, use_container_width=True)

    with c2:
        st.subheader("Phase Distribution", help=H("phase"))
        pc = fm[M["phase"]].value_counts().reset_index()
        pc.columns = ["phase", "count"]
        pc["phase"] = pd.Categorical(pc["phase"], categories=PHASE_ORDER, ordered=True)
        pc = pc.sort_values("phase").dropna(subset=["phase"])
        cols_l = [C["phase"].get(p, "#999") for p in pc["phase"]]
        fig_p = go.Figure(go.Pie(labels=pc["phase"], values=pc["count"], hole=0.5, sort=False,
            marker=dict(colors=cols_l, line=dict(color="white", width=2)),
            textinfo="label+percent", textfont_size=10))
        fig_p.update_layout(height=280, margin=dict(l=0, r=0, t=0, b=0),
            paper_bgcolor="rgba(0,0,0,0)", showlegend=False)
        st.plotly_chart(fig_p, use_container_width=True)

    with st.expander("📋 Raw daily data"):
        show = [c for c in [M["date"], M["das"], M["pp_reading"], M["bgl"],
                M["fl_rl"], M["phase"], M["change_wl"], M["irrig_cm"],
                M["irrig_m3"], M["gopal_cm"], M["irrigated"], IRRIG_CALC_COL,
                M["zero_repl"]] if c in fm.columns]
        col_config = {
            M["date"]: st.column_config.DateColumn(format="DD MMM YYYY", help=H("date")),
            M["das"]: st.column_config.Column(help=H("das")),
            M["pp_reading"]: st.column_config.Column(help=H("pp_reading")),
            M["bgl"]: st.column_config.NumberColumn("BGL", format="%+.1f", help=H("bgl")),
            M["fl_rl"]: st.column_config.Column(help=H("fl_rl")),
            M["phase"]: st.column_config.Column(help=H("phase")),
            M["change_wl"]: st.column_config.Column(help=H("change_wl")),
            M["irrig_cm"]: st.column_config.Column(help=H("irrig_cm")),
            M["irrig_m3"]: st.column_config.Column(help=H("irrig_m3")),
            M["gopal_cm"]: st.column_config.Column(help=H("gopal_cm")),
            M["irrigated"]: st.column_config.CheckboxColumn("Irrigated (Reported)?", help=H("irrigated")),
            IRRIG_CALC_COL: st.column_config.CheckboxColumn("Irrigated (Calculated)?", help=H("irrig_calc")),
            M["zero_repl"]: st.column_config.Column(help=H("zero_repl")),
        }
        st.dataframe(fm[show].reset_index(drop=True), use_container_width=True, height=300,
            column_config=col_config)


# ═══════════════════════════════════════════════════════════════════
# TAB 5 — WATER & IRRIGATION
# ═══════════════════════════════════════════════════════════════════

def tab_water(master, summary):
    st.markdown("### Water & Irrigation Analysis")

    if not summary.empty:
        tw   = safe_sum(summary, S["total_water_m3"])
        tr   = safe_sum(summary, S["total_recharged_m3"])
        tl   = safe_sum(summary, S["land_area"])
        tnau = 1.1 * 4046.8 * tl if tl is not None else None
        sav  = (tnau - tw) / tnau * 100 if tnau and tw is not None and tnau > 0 else None

        c1, c2, c3, c4 = st.columns(4)
        metric_card(c1, "Total Water Added", fmt_or_dash(tw, "{:,.0f}"), "m³", "total_water_m3", C["treatment"])
        metric_card(c2, "Total Recharged", fmt_or_dash(tr, "{:,.0f}"), "m³", "total_recharged_m3", C["accent"])
        metric_card(c3, "TNAU Baseline", fmt_or_dash(tnau, "{:,.0f}"), "m³", "tnau_baseline", C["control"])
        metric_card(c4, "Est. Savings", fmt_or_dash(sav, "{:.1f}%"), "vs TNAU", "savings_pct", C["accent"])
        st.markdown("<br>", unsafe_allow_html=True)
        st.divider()

    ca, cb = st.columns(2)
    with ca:
        st.subheader("Water Added by Village (m³)", help=H("total_water_m3"))
        if not summary.empty and S["total_water_m3"] in summary.columns:
            sm = summary.copy()
            sm["Group"] = to_group(sm[S["type"]])
            vw = (sm.groupby([S["village"], "Group"])[S["total_water_m3"]]
                  .sum().reset_index().rename(columns={S["total_water_m3"]: "total"}))
            fig = px.bar(vw, x=S["village"], y="total", color="Group", barmode="group",
                color_discrete_map=GROUP_COLOR,
                height=300, labels={"total": "m³", S["village"]: ""})
            style_fig(fig, height=300)
            st.plotly_chart(fig, use_container_width=True)

    with cb:
        st.subheader("Gopal Depth Distribution (cm)", help=H("gopal_cm"))
        if not master.empty:
            gd = master[master[M["gopal_cm"]].notna() & (master[M["gopal_cm"]] > 0)].copy()
            gd["Group"] = to_group(gd[M["type"]])
            fig2 = go.Figure()
            for grp in ["Treatment", "Control"]:
                sub = gd[gd["Group"] == grp][M["gopal_cm"]]
                if sub.empty: continue
                fig2.add_trace(go.Histogram(x=sub, name=grp, nbinsx=30,
                    marker_color=GROUP_COLOR[grp], opacity=0.7))
            fig2.update_layout(barmode="overlay", xaxis=dict(title="Gopal Depth (cm)"), yaxis=dict(title="Events"))
            style_fig(fig2, height=300)
            st.plotly_chart(fig2, use_container_width=True)

    st.divider()

    st.subheader("Irrigations — Reported vs Calculated, by Village", help=H("irrigations_a") + " " + H("irrigations_b"))
    st.caption("Reported = enumerator field observation. Calculated = derived from water-level readings (BGL rose >2cm). Large gaps flag data-quality issues worth reviewing.")
    if not summary.empty and S["irrigations_a"] in summary.columns and S["irrigations_b"] in summary.columns:
        vi = (summary.groupby(S["village"])[[S["irrigations_a"], S["irrigations_b"]]]
              .sum().reset_index()
              .melt(id_vars=S["village"], value_vars=[S["irrigations_a"], S["irrigations_b"]],
                    var_name="Metric", value_name="Count"))
        vi["Metric"] = vi["Metric"].map({S["irrigations_a"]: "Reported", S["irrigations_b"]: "Calculated"})
        fig3 = px.bar(vi, x=S["village"], y="Count", color="Metric", barmode="group",
            color_discrete_map={"Reported": C["treatment"], "Calculated": C["accent"]},
            height=300, labels={S["village"]: ""})
        style_fig(fig3, height=300)
        st.plotly_chart(fig3, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════
# TAB 6 — DATA EXPLORER
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
            if IRRIG_CALC_COL in df_view.columns:
                col_config[IRRIG_CALC_COL] = st.column_config.CheckboxColumn("Irrigated (Calc.)?", help=H("irrig_calc"))
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
        "Open `app.py`, find lines 39–45, and paste your published CSV links.\n\n"
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

    t1, t2, t3, t4, t5, t6 = st.tabs([
        "📊 Programme Overview",
        "⚖️ Treatment vs Control",
        "📋 Farmer Summary",
        "👤 Farmer Deep Dive",
        "💧 Water & Irrigation",
        "🔍 Data Explorer",
    ])
    with t1: tab_overview(master_f, summary_f)
    with t2: tab_comparison(master_f, summary_f)
    with t3: tab_farmer_summary(summary_f)
    with t4: tab_deep_dive(master_f, summary_f)
    with t5: tab_water(master_f, summary_f)
    with t6: tab_explorer(master_f, summary_f)


if __name__ == "__main__":
    main()

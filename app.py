"""
AWD FARMER PROGRESS DASHBOARD — v2
Reads from two Google Sheets:
  1. Master Analysis  — daily readings, one row per farmer per date
  2. Summary          — season totals, one row per farmer

To connect your sheets: find the two lines marked with ← PASTE YOUR URL HERE
and replace with your published CSV links.
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
# COLOUR PALETTE
# ═══════════════════════════════════════════════════════════════════
C = {
    "soil"         : "#2C1810",
    "earth"        : "#030303",
    "terracotta"   : "#C4622D",
    "wheat"        : "#E8C170",
    "water_light"  : "#ADD8E6",
    "water"        : "#3A7CA5",
    "water_deep"   : "#1B4F72",
    "leaf"         : "#4A7C59",
    "leaf_light"   : "#82C09A",
    "cream"        : "#FAF6EE",
    "parchment"    : "#F2EAD3",
    "muted"        : "#8A7968",
    "experimental" : "#3A7CA5",
    "control"      : "#C4622D",
    "phase" : {
        "FL-Flood"  : "#FFD580",
        "FL-Inter"  : "#E8A030",
        "FL-Soil"   : "#8B4513",
        "RL-Flood"  : "#ADD8E6",
        "RL-Inter"  : "#3A7CA5",
        "RL-Soil"   : "#1B4F72",
        "No change" : "#CCCCCC",
    },
}

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
    "rl_flood_cm"       : "RL-Flood (cm) Gopal",
    "rl_inter_cm"       : "RL-Inter (cm) Gopal",
    "rl_soil_cm"        : "RL-Soil (cm) Gopal",
    "fl_flood_cm"       : "FL-Flood (cm) Gopal",
    "fl_inter_cm"       : "FL-Inter (cm) Gopal",
    "fl_soil_cm"        : "FL-Soil (cm) Gopal",
    "avg_gopal_cm"      : "Avg Irrig. Depth - Gopal (cm)",
}

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
        return df.sort_values([M["farmer"], M["date"]]).reset_index(drop=True)
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
# HELPER — coloured metric card
# ═══════════════════════════════════════════════════════════════════

def card(label, value, sub="", bg="#1B4F72", accent="#ADD8E6"):
    return (
        f"<div style='background:{bg};border-radius:10px;padding:16px 14px;"
        f"border-left:4px solid {accent};'>"
        f"<div style='font-size:10px;font-weight:700;color:{accent};"
        f"letter-spacing:1.5px;text-transform:uppercase;'>{label}</div>"
        f"<div style='font-size:24px;font-weight:700;color:white;"
        f"font-family:monospace;margin:5px 0 3px;'>{value}</div>"
        f"<div style='font-size:11px;color:{accent};opacity:0.8;'>{sub}</div>"
        f"</div>"
    )


# ═══════════════════════════════════════════════════════════════════
# SIDEBAR
# ═══════════════════════════════════════════════════════════════════

def render_sidebar(master, summary):
    with st.sidebar:
        st.markdown(
            f"<div style='text-align:center;padding:12px;"
            f"background:{C['earth']};border-radius:10px;margin-bottom:12px;'>"
            f"<div style='font-size:36px;'>🌾</div>"
            f"<div style='color:{C['wheat']};font-weight:700;font-size:15px;'>"
            f"AWD Dashboard</div></div>",
            unsafe_allow_html=True,
        )

        fm, fs = master.copy(), summary.copy()

        if not master.empty and M["date"] in master.columns:
            st.markdown("**📅 Date Range**")
            mn, mx = master[M["date"]].min(), master[M["date"]].max()
            dr = st.date_input("range", value=(mn, mx),
                               min_value=mn, max_value=mx,
                               label_visibility="collapsed")
            if len(dr) == 2:
                fm = fm[(fm[M["date"]] >= pd.Timestamp(dr[0])) &
                        (fm[M["date"]] <= pd.Timestamp(dr[1]))]

        st.divider()
        st.markdown("**🏘️ Village**")
        if not master.empty:
            all_v = sorted(master[M["village"]].dropna().unique())
            sel_v = st.multiselect("v", all_v, default=all_v,
                                   label_visibility="collapsed",
                                   placeholder="All villages")
            if sel_v:
                fm = fm[fm[M["village"]].isin(sel_v)]
                fs = fs[fs[S["village"]].isin(sel_v)]

        st.divider()
        st.markdown("**🌱 Field Type**")
        sel_t = st.radio("t", ["All","Experimental","Control"],
                         label_visibility="collapsed")
        if sel_t != "All":
            fm = fm[fm[M["type"]] == sel_t]
            fs = fs[fs[S["type"]] == sel_t]

        st.divider()
        if not fm.empty:
            st.markdown(
                f"<div style='background:{C['earth']};border-radius:8px;"
                f"padding:10px;font-size:12px;color:{C['cream']};'>"
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
    c1, c2 = st.columns([3,1])
    with c1:
        st.markdown(
            f"<h1 style='color:{C['soil']};font-size:26px;margin:0;'>"
            "🌾 AWD Farmer Progress Monitor</h1>"
            f"<p style='color:{C['muted']};font-size:13px;margin:3px 0 0;'>"
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
                    f"<span style='background:{C['parchment']};border-radius:6px;"
                    f"padding:5px 10px;font-size:12px;color:{C['earth']};font-weight:600;'>"
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

    # KPIs
    st.markdown("### Key Programme Metrics")
    n_f  = summary[S["farmer"]].nunique() if not summary.empty else 0
    n_v  = summary[S["village"]].nunique() if not summary.empty else 0
    n_de = summary[S["drying_events"]].mean() if not summary.empty else 0
    exp_bgl = master[master[M["type"]]=="Experimental"][M["bgl"]].mean() \
              if not master.empty else None
    ctrl_bgl = master[master[M["type"]]=="Control"][M["bgl"]].mean() \
               if not master.empty else None
    safe = 0
    if not master.empty:
        s = master[(master[M["bgl"]] >= -5) & (master[M["bgl"]] <= 10)]
        safe = len(s)/len(master)*100
    irr_a = summary[S["irrigations_a"]].mean() if not summary.empty else 0

    c1,c2,c3,c4,c5,c6 = st.columns(6)
    c1.markdown(card("Farmers Enrolled", f"{n_f:,}", f"{n_v} villages",
                     C["water_deep"], C["water_light"]), unsafe_allow_html=True)
    c2.markdown(card("Avg Drying Events", f"{n_de:.1f}", "per farmer",
                     C["soil"], C["wheat"]), unsafe_allow_html=True)
    c3.markdown(card("In Safe Zone", f"{safe:.0f}%", "BGL −5 to +10 cm",
                     "#1A4A2E", C["leaf_light"]), unsafe_allow_html=True)
    c4.markdown(card("Exp. Avg BGL",
                     f"{exp_bgl:+.1f} cm" if exp_bgl is not None else "—",
                     "in ref to surface", C["water_deep"], C["water_light"]),
                unsafe_allow_html=True)
    c5.markdown(card("Ctrl Avg BGL",
                     f"{ctrl_bgl:+.1f} cm" if ctrl_bgl is not None else "—",
                     "in ref to surface", "#6B2D0C", C["wheat"]),
                unsafe_allow_html=True)
    c6.markdown(card("Avg Irrigations", f"{irr_a:.1f}", "per farmer",
                     C["earth"], C["wheat"]), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.divider()

    # Weekly trend + phase donut
    cl, cr = st.columns([1.3,1])

    with cl:
        st.markdown("#### Weekly Water Level Trend")
        st.caption("Avg BGL · Experimental vs Control · green band = safe zone")
        if not master.empty:
            wk = (master.assign(week=master[M["date"]].dt.to_period("W").dt.start_time)
                  .groupby(["week", M["type"]])[M["bgl"]].mean().reset_index())
            fig = go.Figure()
            fig.add_hrect(y0=-5, y1=10, fillcolor="rgba(74,124,89,0.12)",
                          line_width=0, annotation_text="Safe zone",
                          annotation_font_color=C["leaf"],
                          annotation_position="top left")
            for ft, col_h in [("Experimental",C["experimental"]),("Control",C["control"])]:
                sub = wk[wk[M["type"]]==ft]
                if sub.empty: continue
                fig.add_trace(go.Scatter(x=sub["week"], y=sub[M["bgl"]],
                    name=ft, mode="lines+markers",
                    line=dict(color=col_h,width=2.5), marker=dict(size=5),
                    hovertemplate=f"<b>{ft}</b><br>Week: %{{x|%d %b}}<br>Avg BGL: %{{y:.1f}} cm<extra></extra>"))
            fig.add_hline(y=0, line_dash="dash", line_color="grey", line_width=1)
            fig.update_layout(height=320, margin=dict(l=10,r=10,t=10,b=10),
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(242,234,211,0.4)",
                legend=dict(orientation="h",yanchor="bottom",y=1.02,xanchor="right",x=1),
                xaxis=dict(showgrid=True,gridcolor="#E5DDD0"),
                yaxis=dict(title="BGL (cm)",showgrid=True,gridcolor="#E5DDD0"))
            st.plotly_chart(fig, use_container_width=True)

    with cr:
        st.markdown("#### Phase Distribution")
        st.caption("Share of all readings by FL/RL phase")
        if not master.empty:
            pc = master[M["phase"]].value_counts().reset_index()
            pc.columns = ["phase","count"]
            order = ["FL-Flood","FL-Inter","FL-Soil","RL-Flood","RL-Inter","RL-Soil","No change"]
            pc["phase"] = pd.Categorical(pc["phase"],categories=order,ordered=True)
            pc = pc.sort_values("phase").dropna(subset=["phase"])
            cols_list = [C["phase"].get(p,"#999") for p in pc["phase"]]
            fig2 = go.Figure(go.Pie(labels=pc["phase"],values=pc["count"],hole=0.55,
                marker=dict(colors=cols_list,line=dict(color="white",width=2)),
                textinfo="label+percent",textfont_size=10))
            fig2.update_layout(height=320,margin=dict(l=0,r=0,t=0,b=0),
                paper_bgcolor="rgba(0,0,0,0)",showlegend=False)
            st.plotly_chart(fig2, use_container_width=True)

    st.divider()

    # Village comparison
    ca, cb = st.columns(2)
    with ca:
        st.markdown("#### Avg water level to soil surf by Village")
        if not master.empty:
            vb = (master.groupby([M["village"],M["type"]])[M["bgl"]]
                  .mean().reset_index().rename(columns={M["bgl"]:"avg_bgl"}))
            fig3 = px.bar(vb, x=M["village"], y="avg_bgl", color=M["type"],
                barmode="group",
                color_discrete_map={"Experimental":C["experimental"],"Control":C["control"]},
                labels={"avg_bgl":"Avg BGL (cm)",M["village"]:""}, height=300)
            fig3.add_hline(y=0,line_dash="dash",line_color="grey",line_width=1)
            fig3.update_layout(margin=dict(l=10,r=10,t=10,b=10),
                paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(242,234,211,0.4)",
                legend=dict(orientation="h",yanchor="bottom",y=1.02,xanchor="right",x=1,font_size=10))
            st.plotly_chart(fig3, use_container_width=True)

    with cb:
        st.markdown("#### Avg Drying Events by Village")
        if not summary.empty and S["drying_events"] in summary.columns:
            vd = (summary.groupby([S["village"],S["type"]])[S["drying_events"]]
                  .mean().reset_index().rename(columns={S["drying_events"]:"avg_de"}))
            fig4 = px.bar(vd, x=S["village"], y="avg_de", color=S["type"],
                barmode="group",
                color_discrete_map={"Experimental":C["experimental"],"Control":C["control"]},
                labels={"avg_de":"Avg Drying Events",S["village"]:""}, height=300)
            fig4.update_layout(margin=dict(l=10,r=10,t=10,b=10),
                paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(242,234,211,0.4)",
                legend=dict(orientation="h",yanchor="bottom",y=1.02,xanchor="right",x=1,font_size=10))
            st.plotly_chart(fig4, use_container_width=True)

    st.divider()

    # Drying phase durations
    st.markdown("#### Avg Drying Duration by Crop Growth Stage (DAS)")
    if not summary.empty:
        rows = []
        for label, col in [("0–30 DAS",S["avg_drying_p1"]),("30–60 DAS",S["avg_drying_p2"]),
                            ("60–90 DAS",S["avg_drying_p3"]),("90+ DAS",S["avg_drying_p4"])]:
            if col not in summary.columns: continue
            for ft in summary[S["type"]].unique():
                avg = summary[summary[S["type"]]==ft][col].mean()
                rows.append({"Stage":label,"Type":ft,"Avg Days":avg})
        if rows:
            pf = pd.DataFrame(rows).dropna()
            fig5 = px.bar(pf, x="Stage", y="Avg Days", color="Type", barmode="group",
                color_discrete_map={"Experimental":C["experimental"],"Control":C["control"]},
                height=300)
            fig5.update_layout(margin=dict(l=10,r=10,t=10,b=10),
                paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(242,234,211,0.4)",
                legend=dict(orientation="h",yanchor="bottom",y=1.02,xanchor="right",x=1))
            st.plotly_chart(fig5, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════
# TAB 2 — FARMER SUMMARY TABLE
# ═══════════════════════════════════════════════════════════════════

def tab_farmer_summary(summary):
    st.markdown("### Farmer Season Summary")
    if summary.empty:
        st.warning("Summary sheet not loaded.")
        return

    cs, cv, ct = st.columns(3)
    with cs: search = st.text_input("🔍 Search farmer")
    with cv:
        vo = ["All"]+sorted(summary[S["village"]].dropna().unique())
        sv = st.selectbox("Village", vo)
    with ct:
        to = ["All"]+sorted(summary[S["type"]].dropna().unique())
        st_t = st.selectbox("Type", to)

    ds = summary.copy()
    if search: ds = ds[ds[S["farmer"]].str.contains(search,case=False,na=False)]
    if sv!="All": ds = ds[ds[S["village"]]==sv]
    if st_t!="All": ds = ds[ds[S["type"]]==st_t]

    st.info(f"Showing **{len(ds)}** farmers")

    disp = [S["farmer"],S["village"],S["type"],S["land_area"],S["days_monitored"],
            S["missing_days"],S["drying_events"],S["days_above"],S["days_below"],
            S["dry_days"],S["irrigations_a"],S["irrigations_b"],
            S["total_water_mm"],S["total_water_m3"],S["avg_gopal_cm"]]
    disp = [c for c in disp if c in ds.columns]

    st.dataframe(ds[disp].reset_index(drop=True), use_container_width=True, height=420,
        column_config={
            S["total_water_m3"]: st.column_config.NumberColumn("Water Added (m³)", format="%.1f"),
            S["avg_gopal_cm"]  : st.column_config.NumberColumn("Gopal (cm)", format="%.2f"),
        })

    st.divider()

    # Rankings
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Top 15 — Irrigation Events**")
        if S["irrigations_a"] in ds.columns:
            top = (ds[[S["farmer"],S["type"],S["irrigations_a"]]].dropna()
                   .sort_values(S["irrigations_a"],ascending=True).tail(15))
            fig = px.bar(top, y=S["farmer"], x=S["irrigations_a"], color=S["type"],
                orientation="h",
                color_discrete_map={"Experimental":C["experimental"],"Control":C["control"]},
                height=360, labels={S["irrigations_a"]:"Irrigations",S["farmer"]:""})
            fig.update_layout(margin=dict(l=10,r=10,t=10,b=10),
                paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(242,234,211,0.4)",
                showlegend=False,yaxis=dict(tickfont=dict(size=9)))
            st.plotly_chart(fig, use_container_width=True)

    with c2:
        st.markdown("**Top 15 — Drying Events**")
        if S["drying_events"] in ds.columns:
            top2 = (ds[[S["farmer"],S["type"],S["drying_events"]]].dropna()
                    .sort_values(S["drying_events"],ascending=True).tail(15))
            fig2 = px.bar(top2, y=S["farmer"], x=S["drying_events"], color=S["type"],
                orientation="h",
                color_discrete_map={"Experimental":C["experimental"],"Control":C["control"]},
                height=360, labels={S["drying_events"]:"Drying Events",S["farmer"]:""})
            fig2.update_layout(margin=dict(l=10,r=10,t=10,b=10),
                paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(242,234,211,0.4)",
                showlegend=False,yaxis=dict(tickfont=dict(size=9)))
            st.plotly_chart(fig2, use_container_width=True)

    csv = ds.to_csv(index=False).encode("utf-8")
    st.download_button("📥 Download CSV", data=csv,
                       file_name="awd_summary.csv", mime="text/csv")


# ═══════════════════════════════════════════════════════════════════
# TAB 3 — FARMER DEEP DIVE
# ═══════════════════════════════════════════════════════════════════

def tab_deep_dive(master, summary):
    st.markdown("### Farmer Deep Dive")
    if master.empty:
        st.warning("Master Analysis not loaded.")
        return

    cv, ct, cf = st.columns(3)
    with cv: sv = st.selectbox("Village", sorted(master[M["village"]].dropna().unique()))
    with ct: st_t = st.selectbox("Type", sorted(master[master[M["village"]]==sv][M["type"]].dropna().unique()))
    with cf:
        fs = sorted(master[(master[M["village"]]==sv)&(master[M["type"]]==st_t)][M["farmer"]].dropna().unique())
        sel = st.selectbox("Farmer", fs)

    if not sel: return

    fm = master[master[M["farmer"]]==sel].copy()
    sm = summary[summary[S["farmer"]]==sel] if not summary.empty else pd.DataFrame()

    if not sm.empty:
        row = sm.iloc[0]
        st.markdown("#### Season Summary")
        c1,c2,c3,c4,c5,c6,c7,c8 = st.columns(8)
        pairs = [
            (c1,"Village",    str(row.get(S["village"],"—")),""),
            (c2,"Type",       str(row.get(S["type"],"—")),""),
            (c3,"Land (ac)",  str(row.get(S["land_area"],"—")),""),
            (c4,"Days Mon.",  str(int(row.get(S["days_monitored"],0)) if pd.notna(row.get(S["days_monitored"])) else "—"),""),
            (c5,"Dry Events", str(int(row.get(S["drying_events"],0)) if pd.notna(row.get(S["drying_events"])) else "—"),"≥3 days"),
            (c6,"Irrigations",str(int(row.get(S["irrigations_a"],0)) if pd.notna(row.get(S["irrigations_a"])) else "—"),"reported"),
            (c7,"Water (m³)", f"{row.get(S['total_water_m3'],0):.1f}" if pd.notna(row.get(S["total_water_m3"])) else "—","added"),
            (c8,"Gopal (cm)", f"{row.get(S['avg_gopal_cm'],0):.2f}" if pd.notna(row.get(S["avg_gopal_cm"])) else "—","avg depth"),
        ]
        for col,lab,val,sub in pairs: col.metric(lab, val, sub or None)
        st.divider()

    st.markdown(f"#### Daily Water Level — {sel}")
    st.caption("PP Reading over time · ▲ = irrigation reported · phase bars below")

    fig = make_subplots(rows=2,cols=1,shared_xaxes=True,row_heights=[0.72,0.28],
        subplot_titles=("PP Reading (cm)","Phase"),vertical_spacing=0.05)
    fig.add_hrect(y0=5,y1=25,row=1,col=1,fillcolor="rgba(74,124,89,0.10)",line_width=0)
    fig.add_trace(go.Scatter(x=fm[M["date"]],y=fm[M["pp_reading"]],name="PP Reading",
        mode="lines+markers",line=dict(color=C["water"],width=2.5),marker=dict(size=4),
        hovertemplate="<b>%{x|%d %b %Y}</b><br>PP: %{y:.1f} cm<extra></extra>"),row=1,col=1)
    fig.add_hline(y=15,line_dash="dash",line_color=C["leaf"],line_width=1.5,row=1,col=1,
        annotation_text="Surface",annotation_font_color=C["leaf"],annotation_position="bottom right")
    fig.add_hline(y=25,line_dash="dot",line_color=C["terracotta"],line_width=1,row=1,col=1,
        annotation_text="Dry (25cm)",annotation_font_color=C["terracotta"],annotation_position="top right")

    ir = fm[fm[M["irrigated"]]==True]
    if not ir.empty:
        fig.add_trace(go.Scatter(x=ir[M["date"]],y=ir[M["pp_reading"]],name="Irrigation",
            mode="markers",marker=dict(symbol="triangle-up",size=11,color=C["leaf"],
            line=dict(color="white",width=1)),
            hovertemplate="<b>Irrigation</b><br>%{x|%d %b}<br>PP: %{y:.1f}<extra></extra>"),row=1,col=1)

    for ph, ph_c in C["phase"].items():
        sub = fm[fm[M["phase"]]==ph]
        if sub.empty: continue
        fig.add_trace(go.Bar(x=sub[M["date"]],y=[1]*len(sub),name=ph,
            marker_color=ph_c,
            hovertemplate=f"<b>{ph}</b><br>%{{x|%d %b}}<extra></extra>"),row=2,col=1)

    fig.update_layout(height=510,margin=dict(l=10,r=10,t=30,b=10),
        paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(242,234,211,0.4)",
        barmode="stack",
        legend=dict(orientation="h",yanchor="bottom",y=1.02,xanchor="right",x=1,font_size=10),
        yaxis=dict(title="PP Reading (cm)",autorange="reversed",showgrid=True,gridcolor="#E5DDD0"),
        yaxis2=dict(showticklabels=False,showgrid=False),
        xaxis2=dict(showgrid=True,gridcolor="#E5DDD0"))
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### In Ref to Surface (BGL)")
        fig_b = go.Figure()
        fig_b.add_hrect(y0=-5,y1=10,fillcolor="rgba(74,124,89,0.10)",line_width=0)
        fig_b.add_trace(go.Scatter(x=fm[M["date"]],y=fm[M["bgl"]],fill="tozeroy",
            mode="lines",line=dict(color=C["water"],width=2),
            fillcolor="rgba(58,124,165,0.15)",
            hovertemplate="%{x|%d %b}<br>BGL: %{y:+.1f} cm<extra></extra>"))
        fig_b.add_hline(y=0,line_dash="dash",line_color="grey",line_width=1)
        fig_b.update_layout(height=280,margin=dict(l=10,r=10,t=10,b=10),
            paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(242,234,211,0.4)",
            showlegend=False,
            yaxis=dict(title="cm",showgrid=True,gridcolor="#E5DDD0"),
            xaxis=dict(showgrid=True,gridcolor="#E5DDD0"))
        st.plotly_chart(fig_b, use_container_width=True)

    with c2:
        st.markdown("#### Phase Distribution")
        pc = fm[M["phase"]].value_counts().reset_index()
        pc.columns = ["phase","count"]
        cols_l = [C["phase"].get(p,"#999") for p in pc["phase"]]
        fig_p = go.Figure(go.Pie(labels=pc["phase"],values=pc["count"],hole=0.5,
            marker=dict(colors=cols_l,line=dict(color="white",width=2)),
            textinfo="label+percent",textfont_size=10))
        fig_p.update_layout(height=280,margin=dict(l=0,r=0,t=0,b=0),
            paper_bgcolor="rgba(0,0,0,0)",showlegend=False)
        st.plotly_chart(fig_p, use_container_width=True)

    with st.expander("📋 Raw daily data"):
        show = [c for c in [M["date"],M["das"],M["pp_reading"],M["bgl"],
                M["fl_rl"],M["phase"],M["change_wl"],M["irrig_cm"],
                M["irrig_m3"],M["gopal_cm"],M["irrigated"],M["zero_repl"]] if c in fm.columns]
        st.dataframe(fm[show].reset_index(drop=True), use_container_width=True, height=300,
            column_config={
                M["date"]     : st.column_config.DateColumn(format="DD MMM YYYY"),
                M["irrigated"]: st.column_config.CheckboxColumn("Irrigated?"),
                M["bgl"]      : st.column_config.NumberColumn("BGL",format="%+.1f"),
            })


# ═══════════════════════════════════════════════════════════════════
# TAB 4 — WATER & IRRIGATION
# ═══════════════════════════════════════════════════════════════════

def tab_water(master, summary):
    st.markdown("### Water & Irrigation Analysis")

    if not summary.empty:
        tw   = summary[S["total_water_m3"]].sum()
        tr   = summary[S["total_recharged_m3"]].sum()
        tl   = summary[S["land_area"]].sum()
        tnau = 1.1 * 4046.8 * tl
        sav  = (tnau - tw) / tnau * 100 if tnau > 0 else 0

        c1,c2,c3,c4 = st.columns(4)
        c1.markdown(card("Total Water Added",f"{tw:,.0f}","m³",C["water_deep"],C["water_light"]),unsafe_allow_html=True)
        c2.markdown(card("Total Recharged",f"{tr:,.0f}","m³",C["soil"],C["wheat"]),unsafe_allow_html=True)
        c3.markdown(card("TNAU Baseline",f"{tnau:,.0f}","m³",C["earth"],C["wheat"]),unsafe_allow_html=True)
        c4.markdown(card("Est. Savings",f"{sav:.1f}%","vs TNAU","#1A4A2E",C["leaf_light"]),unsafe_allow_html=True)
        st.markdown("<br>",unsafe_allow_html=True)
        st.divider()

    ca, cb = st.columns(2)
    with ca:
        st.markdown("#### Water Added by Village (m³)")
        if not summary.empty and S["total_water_m3"] in summary.columns:
            vw = (summary.groupby([S["village"],S["type"]])[S["total_water_m3"]]
                  .sum().reset_index().rename(columns={S["total_water_m3"]:"total"}))
            fig = px.bar(vw,x=S["village"],y="total",color=S["type"],barmode="group",
                color_discrete_map={"Experimental":C["experimental"],"Control":C["control"]},
                height=300,labels={"total":"m³",S["village"]:""})
            fig.update_layout(margin=dict(l=10,r=10,t=10,b=10),
                paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(242,234,211,0.4)",
                legend=dict(orientation="h",yanchor="bottom",y=1.02,xanchor="right",x=1,font_size=10))
            st.plotly_chart(fig,use_container_width=True)

    with cb:
        st.markdown("#### Gopal Depth Distribution (cm)")
        if not master.empty:
            gd = master[master[M["gopal_cm"]].notna()&(master[M["gopal_cm"]]>0)]
            fig2 = go.Figure()
            for ft,col_h in [("Experimental",C["experimental"]),("Control",C["control"])]:
                sub = gd[gd[M["type"]]==ft][M["gopal_cm"]]
                if sub.empty: continue
                fig2.add_trace(go.Histogram(x=sub,name=ft,nbinsx=30,
                    marker_color=col_h,opacity=0.7))
            fig2.update_layout(barmode="overlay",height=300,
                margin=dict(l=10,r=10,t=10,b=10),
                paper_bgcolor="rgba(0,0,0,0)",plot_bgcolor="rgba(242,234,211,0.4)",
                xaxis=dict(title="Gopal Depth (cm)"),yaxis=dict(title="Events"),
                legend=dict(orientation="h",yanchor="bottom",y=1.02,xanchor="right",x=1))
            st.plotly_chart(fig2,use_container_width=True)


# ═══════════════════════════════════════════════════════════════════
# TAB 5 — DATA EXPLORER
# ═══════════════════════════════════════════════════════════════════

def tab_explorer(master, summary):
    st.markdown("### Data Explorer")
    st1, st2 = st.tabs(["📋 Master Analysis (Daily)","📊 Summary (Season)"])

    with st1:
        if master.empty:
            st.warning("Master Analysis not loaded.")
        else:
            c1,c2,c3 = st.columns(3)
            with c1: srch = st.text_input("🔍 Farmer",key="ex_srch")
            with c2: ph_f = st.multiselect("Phase",master[M["phase"]].dropna().unique(),key="ex_ph")
            with c3: ir_f = st.selectbox("Irrigation",["All","TRUE only","FALSE only"],key="ex_ir")
            df = master.copy()
            if srch: df = df[df[M["farmer"]].str.contains(srch,case=False,na=False)]
            if ph_f: df = df[df[M["phase"]].isin(ph_f)]
            if ir_f=="TRUE only": df = df[df[M["irrigated"]]==True]
            elif ir_f=="FALSE only": df = df[df[M["irrigated"]]==False]
            st.info(f"**{len(df):,}** rows · **{df[M['farmer']].nunique()}** farmers")
            st.dataframe(df.reset_index(drop=True),use_container_width=True,height=420,
                column_config={
                    M["date"]     : st.column_config.DateColumn(format="DD MMM YYYY"),
                    M["irrigated"]: st.column_config.CheckboxColumn("Irrigated?"),
                    M["bgl"]      : st.column_config.NumberColumn("BGL",format="%+.1f"),
                })
            st.download_button("📥 Download",df.to_csv(index=False).encode(),
                "master_filtered.csv","text/csv")

    with st2:
        if summary.empty:
            st.warning("Summary not loaded.")
        else:
            srch2 = st.text_input("🔍 Farmer",key="ex_srch2")
            df2 = summary.copy()
            if srch2: df2 = df2[df2[S["farmer"]].str.contains(srch2,case=False,na=False)]
            st.info(f"**{len(df2)}** farmers")
            st.dataframe(df2.reset_index(drop=True),use_container_width=True,height=420)
            st.download_button("📥 Download",df2.to_csv(index=False).encode(),
                "summary_filtered.csv","text/csv")


# ═══════════════════════════════════════════════════════════════════
# SETUP NOTICE
# ═══════════════════════════════════════════════════════════════════

def show_setup_notice():
    st.info(
        "**Google Sheets not connected yet.**\n\n"
        "Open `app.py`, find lines 30–31, and paste your published CSV links.\n\n"
        "See `README.md` for full step-by-step instructions."
    )


# ═══════════════════════════════════════════════════════════════════
# CSS
# ═══════════════════════════════════════════════════════════════════

def apply_css():
    st.markdown(f"""
        <style>
        .stApp {{ background-color:{C['cream']}; }}
        section[data-testid="stSidebar"] {{ background-color:{C['soil']}; }}
        section[data-testid="stSidebar"] * {{ color:{C['cream']} !important; }}
        section[data-testid="stSidebar"] .stSelectbox>div>div,
        section[data-testid="stSidebar"] .stMultiSelect>div>div
            {{ color:{C['soil']} !important; }}
        .stTabs [data-baseweb="tab"] {{ font-weight:600;color:{C['earth']};font-size:14px; }}
        .stTabs [aria-selected="true"] {{ color:{C['terracotta']} !important;
            border-bottom-color:{C['terracotta']} !important; }}
        div[data-testid="metric-container"] {{ background:white;border-radius:8px;
            padding:12px 16px;border-left:3px solid {C['terracotta']}; }}
        h1,h2,h3 {{ color:{C['soil']}; }}
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

    t1,t2,t3,t4,t5 = st.tabs([
        "📊 Programme Overview",
        "📋 Farmer Summary",
        "👤 Farmer Deep Dive",
        "💧 Water & Irrigation",
        "🔍 Data Explorer",
    ])
    with t1: tab_overview(master_f, summary_f)
    with t2: tab_farmer_summary(summary_f)
    with t3: tab_deep_dive(master_f, summary_f)
    with t4: tab_water(master_f, summary_f)
    with t5: tab_explorer(master_f, summary_f)


if __name__ == "__main__":
    main()

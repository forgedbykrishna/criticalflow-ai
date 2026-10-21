import json
import logging
from collections.abc import Mapping
from datetime import datetime, timezone

import altair as alt
import pandas as pd
import streamlit as st

from db import load_incidents


# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="CriticalFlow AI",
    page_icon="🚨",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# CUSTOM CSS — Dark-mode glassmorphism design system
# ============================================================

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

    /* ---- Base ---- */
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    .stApp {
        background: linear-gradient(135deg, #090d12 0%, #0b1118 50%, #0d1420 100%);
        min-height: 100vh;
    }
    .main .block-container {
        padding-top: 1.5rem;
        padding-bottom: 3rem;
        max-width: 1600px;
    }

    /* ---- Sidebar ---- */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0d1420 0%, #111820 100%);
        border-right: 1px solid rgba(99, 179, 237, 0.12);
    }
    section[data-testid="stSidebar"] .stRadio > label {
        color: #94a3b8;
        font-size: 13px;
        font-weight: 500;
        letter-spacing: 0.05em;
        text-transform: uppercase;
    }

    /* ---- Typography ---- */
    h1 {
        background: linear-gradient(90deg, #60a5fa, #a78bfa);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        font-size: 2.4rem !important;
        font-weight: 800 !important;
        letter-spacing: -0.04em;
        line-height: 1.15;
        margin-bottom: 0.25rem !important;
    }
    h2, h3 {
        color: #e2e8f0 !important;
        font-weight: 700 !important;
        letter-spacing: -0.02em;
    }
    .page-subtitle {
        color: #64748b;
        font-size: 15px;
        font-weight: 400;
        margin-bottom: 1.5rem;
    }

    /* ---- Metric Cards ---- */
    div[data-testid="stMetric"] {
        background: linear-gradient(135deg, rgba(15, 23, 42, 0.9), rgba(17, 24, 39, 0.95));
        border: 1px solid rgba(99, 179, 237, 0.15);
        padding: 20px 22px;
        border-radius: 16px;
        backdrop-filter: blur(12px);
        box-shadow: 0 4px 24px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(255,255,255,0.05);
        transition: border-color 0.2s, box-shadow 0.2s;
    }
    div[data-testid="stMetric"]:hover {
        border-color: rgba(99, 179, 237, 0.35);
        box-shadow: 0 8px 32px rgba(99, 179, 237, 0.12), inset 0 1px 0 rgba(255,255,255,0.05);
    }
    div[data-testid="stMetricLabel"] > div {
        color: #64748b !important;
        font-size: 12px !important;
        font-weight: 600 !important;
        letter-spacing: 0.06em;
        text-transform: uppercase;
    }
    div[data-testid="stMetricValue"] > div {
        color: #f1f5f9 !important;
        font-size: 2rem !important;
        font-weight: 700 !important;
        letter-spacing: -0.03em;
    }
    div[data-testid="stMetricDelta"] > div {
        font-size: 13px !important;
    }

    /* ---- DataFrames ---- */
    div[data-testid="stDataFrame"] {
        border: 1px solid rgba(99, 179, 237, 0.12);
        border-radius: 14px;
        overflow: hidden;
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
    }

    /* ---- Buttons ---- */
    .stButton > button {
        border-radius: 10px;
        font-weight: 600;
        font-size: 13px;
        border: 1px solid rgba(99, 179, 237, 0.25);
        background: rgba(99, 179, 237, 0.08);
        color: #93c5fd;
        transition: all 0.2s;
    }
    .stButton > button:hover {
        background: rgba(99, 179, 237, 0.18);
        border-color: rgba(99, 179, 237, 0.45);
        color: #bfdbfe;
    }

    /* ---- Selectbox / Radio ---- */
    .stSelectbox > div > div {
        background: rgba(15, 23, 42, 0.85) !important;
        border: 1px solid rgba(99, 179, 237, 0.2) !important;
        border-radius: 10px !important;
        color: #e2e8f0 !important;
    }
    .stRadio > div > label {
        color: #94a3b8 !important;
    }

    /* ---- Section title ---- */
    .section-header {
        display: flex;
        align-items: center;
        gap: 10px;
        margin: 1.8rem 0 0.9rem 0;
    }
    .section-header-line {
        flex: 1;
        height: 1px;
        background: linear-gradient(90deg, rgba(99,179,237,0.2), transparent);
    }
    .section-title {
        color: #94a3b8;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.12em;
        text-transform: uppercase;
    }

    /* ---- Status pills ---- */
    .status-pill {
        display: inline-flex;
        align-items: center;
        gap: 5px;
        padding: 4px 10px;
        border-radius: 20px;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.05em;
    }
    .pill-live {
        background: rgba(34, 197, 94, 0.12);
        color: #4ade80;
        border: 1px solid rgba(34, 197, 94, 0.25);
    }
    .pill-critical {
        background: rgba(239, 68, 68, 0.15);
        color: #f87171;
        border: 1px solid rgba(239, 68, 68, 0.3);
    }
    .pill-high {
        background: rgba(249, 115, 22, 0.15);
        color: #fb923c;
        border: 1px solid rgba(249, 115, 22, 0.3);
    }
    .pill-medium {
        background: rgba(234, 179, 8, 0.15);
        color: #facc15;
        border: 1px solid rgba(234, 179, 8, 0.3);
    }
    .pill-low {
        background: rgba(34, 197, 94, 0.12);
        color: #4ade80;
        border: 1px solid rgba(34, 197, 94, 0.25);
    }

    /* ---- Info boxes ---- */
    .stInfo, .stSuccess, .stWarning, .stError {
        border-radius: 12px !important;
    }

    /* ---- Data source banner ---- */
    .data-banner {
        background: linear-gradient(90deg, rgba(96,165,250,0.08), rgba(167,139,250,0.05));
        border: 1px solid rgba(96,165,250,0.2);
        border-radius: 12px;
        padding: 10px 16px;
        margin-bottom: 1.5rem;
        color: #93c5fd;
        font-size: 13px;
        font-weight: 500;
        display: flex;
        align-items: center;
        gap: 8px;
    }

    /* ---- Sidebar branding ---- */
    .sidebar-brand {
        padding: 0.5rem 0 1rem 0;
    }
    .sidebar-brand h2 {
        font-size: 1.15rem !important;
        font-weight: 800 !important;
        background: linear-gradient(90deg, #60a5fa, #a78bfa);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        margin: 0 !important;
    }
    .sidebar-brand p {
        color: #475569;
        font-size: 11px;
        font-weight: 500;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        margin: 2px 0 0 0;
    }

    /* ---- Expander ---- */
    .streamlit-expanderHeader {
        background: rgba(15, 23, 42, 0.6) !important;
        border-radius: 10px !important;
        border: 1px solid rgba(99, 179, 237, 0.1) !important;
        color: #94a3b8 !important;
        font-weight: 600 !important;
    }

    /* ---- Altair chart container ---- */
    .element-container:has(canvas) {
        border-radius: 14px;
        overflow: hidden;
    }

    /* ---- Code blocks ---- */
    .stCodeBlock {
        border-radius: 12px !important;
        border: 1px solid rgba(99, 179, 237, 0.12) !important;
    }

    /* ---- Progress bars ---- */
    .stProgress > div > div {
        border-radius: 4px;
    }

    /* ---- Divider ---- */
    hr {
        border-color: rgba(99, 179, 237, 0.1) !important;
        margin: 1rem 0 !important;
    }

    /* ---- Tabs ---- */
    .stTabs [data-baseweb="tab-list"] {
        background: rgba(15, 23, 42, 0.5);
        border-radius: 12px;
        border: 1px solid rgba(99, 179, 237, 0.12);
        padding: 4px;
        gap: 4px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px;
        color: #64748b;
        font-weight: 600;
        font-size: 13px;
    }
    .stTabs [aria-selected="true"] {
        background: rgba(99, 179, 237, 0.15) !important;
        color: #93c5fd !important;
    }

    /* ---- Incident detail card ---- */
    .detail-card {
        background: rgba(15, 23, 42, 0.7);
        border: 1px solid rgba(99, 179, 237, 0.12);
        border-radius: 14px;
        padding: 18px 20px;
        margin-bottom: 12px;
        backdrop-filter: blur(8px);
    }
    .detail-card-label {
        color: #64748b;
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        margin-bottom: 4px;
    }
    .detail-card-value {
        color: #e2e8f0;
        font-size: 14px;
        font-weight: 500;
        word-break: break-word;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# ALTAIR DARK THEME
# ============================================================

DARK_CHART_CONFIG = {
    "background": "transparent",
    "view": {"stroke": "transparent"},
    "axis": {
        "domainColor": "#1e293b",
        "gridColor": "#1e293b",
        "tickColor": "#1e293b",
        "labelColor": "#64748b",
        "titleColor": "#94a3b8",
        "labelFont": "Inter",
        "titleFont": "Inter",
        "labelFontSize": 11,
        "titleFontSize": 12,
    },
    "legend": {
        "labelColor": "#94a3b8",
        "titleColor": "#94a3b8",
        "labelFont": "Inter",
        "titleFont": "Inter",
    },
    "title": {
        "color": "#e2e8f0",
        "font": "Inter",
        "fontSize": 13,
        "fontWeight": 600,
    },
    "mark": {"font": "Inter"},
}

RISK_COLOR_SCALE = alt.Scale(
    domain=["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"],
    range=["#ef4444", "#f97316", "#eab308", "#22c55e", "#64748b"],
)


# ============================================================
# DATA HELPERS
# ============================================================

def _as_mapping(value):
    """Return a dictionary for JSON/dict values, otherwise an empty dict."""
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return dict(parsed) if isinstance(parsed, Mapping) else {}
        except (json.JSONDecodeError, TypeError):
            return {}
    return {}


def _first_non_null(*values):
    for value in values:
        if value is not None and not (isinstance(value, float) and pd.isna(value)):
            if not (isinstance(value, str) and not value.strip()):
                return value
    return None


def _nested_value(row, column, *path):
    value = row.get(column)
    for key in path:
        value = _as_mapping(value).get(key)
    return value


def normalize_incidents(source_df):
    """
    Map the hosted Neon incident_overview schema to the field names
    used by the existing dashboard. Original columns are preserved.
    """
    df = source_df.copy()

    # Safely parse JSON-like columns. Psycopg may already return dicts.
    for column in ("prediction", "features", "incident_data"):
        if column in df.columns:
            df[column] = df[column].apply(_as_mapping)

    def get_value(row, *candidates):
        for candidate in candidates:
            if "." in candidate:
                column, *path = candidate.split(".")
                value = _nested_value(row, column, *path)
            else:
                value = row.get(candidate)
            value = _first_non_null(value)
            if value is not None:
                return value
        return None

    def extract(row, *candidates):
        return get_value(row, *candidates)

    # Compatibility columns that let existing dashboard sections work
    # while keeping every original Neon column intact.
    aliases = {
        "timestamp": lambda r: extract(r, "event_time", "created_at", "timestamp"),
        "system_id": lambda r: extract(r, "system", "system_id"),
        "risk_label": lambda r: extract(
            r, "severity", "prediction.raw.severity", "risk_label"
        ),
        "risk_score": lambda r: extract(
            r, "prediction.raw.risk_score", "anomaly_score", "risk_score"
        ),
        "incident_type": lambda r: extract(
            r, "prediction.raw.incident_type", "event_type", "incident_type"
        ),
        "completion_status": lambda r: extract(
            r, "incident_data.completion_status", "pipeline_status",
            "incident_status", "event_type", "completion_status"
        ),
        "return_code": lambda r: extract(
            r, "incident_data.return_code", "features.return_code", "return_code"
        ),
        "abend_code": lambda r: extract(
            r, "incident_data.abend_code", "abend_code"
        ),
        "job_id": lambda r: extract(r, "incident_data.job_id", "job_id"),
        "step_name": lambda r: extract(r, "incident_data.step_name", "step_name"),
        "primary_message_id": lambda r: extract(
            r, "incident_data.primary_message_id", "primary_message_id"
        ),
        "cpu_utilization_pct": lambda r: extract(
            r, "features.cpu_utilization_pct",
            "incident_data.cpu_utilization_pct", "cpu_utilization_pct"
        ),
        "error_rate_pct": lambda r: extract(
            r, "features.error_rate_pct", "incident_data.error_rate_pct", "error_rate_pct"
        ),
        "transaction_volume_per_hr": lambda r: extract(
            r, "features.transaction_volume_per_hr",
            "incident_data.transaction_volume_per_hr", "transaction_volume_per_hr"
        ),
        "model_version": lambda r: extract(r, "prediction.raw.model_version", "model_version"),
        "recent_deployment_flag": lambda r: extract(
            r, "features.recent_deployment",
            "incident_data.recent_deployment_flag", "recent_deployment_flag"
        ),
        "evidence": lambda r: extract(
            r, "incident_data.raw_log_snippet", "pipeline_error", "evidence"
        ),
        "raw_log_snippet": lambda r: extract(
            r, "incident_data.raw_log_snippet", "pipeline_error", "raw_log_snippet"
        ),
        "remediation": lambda r: extract(
            r, "recommended_action", "prediction.raw.recommended_action", "remediation"
        ),
    }

    for target, function in aliases.items():
        df[target] = df.apply(function, axis=1)

    # Normalized categorical type for dashboard charts.
    df["incident_type"] = (
        df["incident_type"].fillna("UNKNOWN").astype(str).str.upper()
    )
    df["risk_label"] = (
        df["risk_label"].fillna("UNKNOWN").astype(str).str.upper()
    )

    # Use event_time as a sortable timestamp where available.
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)

    # Numeric coercion for metric columns
    for col in ("risk_score", "anomaly_score", "cpu_utilization_pct", "error_rate_pct"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    return df


@st.cache_data(ttl=30)
def get_incidents():
    raw_df = load_incidents()
    return normalize_incidents(raw_df)


def risk_count(label):
    if "risk_label" not in df.columns:
        return 0
    return int((df["risk_label"] == label).sum())


def format_value(value):
    if value is None:
        return "Not available"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2, default=str)
    try:
        if pd.isna(value):
            return "Not available"
    except (TypeError, ValueError):
        pass
    return value


def get_selected_incident(incident_id):
    rows = df[df["incident_id"].astype(str) == str(incident_id)]
    if rows.empty:
        return None
    return rows.iloc[0]


def available_columns(frame, columns):
    return [column for column in columns if column in frame.columns]


def section_header(title: str, icon: str = ""):
    st.markdown(
        f"""
        <div class="section-header">
            <span class="section-title">{icon}&nbsp;{title}</span>
            <div class="section-header-line"></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def risk_pill(label: str) -> str:
    cls_map = {
        "CRITICAL": "pill-critical",
        "HIGH": "pill-high",
        "MEDIUM": "pill-medium",
        "LOW": "pill-low",
    }
    icon_map = {
        "CRITICAL": "🔴",
        "HIGH": "🟠",
        "MEDIUM": "🟡",
        "LOW": "🟢",
    }
    cls = cls_map.get(label.upper(), "pill-low")
    icon = icon_map.get(label.upper(), "⚪")
    return f'<span class="status-pill {cls}">{icon} {label}</span>'


# ============================================================
# LOAD DATA
# ============================================================

df = pd.DataFrame()
try:
    df = get_incidents()
except Exception as exc:
    logging.getLogger("m6_dashboard").error("incident load failed: %s", type(exc).__name__)
    st.error("⚠️ Unable to load incident data. Please check database connectivity and try again.")
    st.stop()

if df.empty:
    st.warning("📭 No incidents are currently available in the database.")
    st.stop()

incidents = df.to_dict("records")


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.markdown(
        """
        <div class="sidebar-brand">
            <h2>🚨 CriticalFlow AI</h2>
            <p>Incident Intelligence Platform</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.divider()

    page = st.radio(
        "Navigation",
        [
            "📊  Overview",
            "📋  Incidents",
            "🔍  Incident Detail",
            "🖥️  System Health",
            "🎯  Demo Scenarios",
        ],
        label_visibility="collapsed",
    )

    st.divider()

    # Data source status
    st.markdown(
        """
        <div style="margin-bottom:8px;">
            <span class="status-pill pill-live">● NEON POSTGRESQL</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption(f"Records loaded: **{len(df):,}**")
    st.caption(f"Last refresh: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")

    st.divider()

    # Auto-refresh control
    auto_refresh = st.toggle("Auto-refresh (30s)", value=False)
    if auto_refresh:
        st.caption("🔄 Page refreshes every 30 seconds")

# Strip icon prefixes from page name
page_key = page.split("  ", 1)[-1].strip()


# ============================================================
# AUTO REFRESH
# ============================================================

if auto_refresh:
    import time
    # Use session_state to track refresh timing
    now_ts = time.time()
    if "last_refresh" not in st.session_state:
        st.session_state.last_refresh = now_ts
    elif now_ts - st.session_state.last_refresh > 30:
        st.session_state.last_refresh = now_ts
        st.cache_data.clear()
        st.rerun()


# ============================================================
# OVERVIEW PAGE
# ============================================================

if page_key == "Overview":
    st.title("CriticalFlow AI")
    st.markdown(
        '<p class="page-subtitle">AI-powered incident intelligence and operational risk monitoring for IBM Z® / LinuxONE</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="data-banner">
            🟢&nbsp;<strong>LIVE — NEON POSTGRESQL</strong>&nbsp;·&nbsp;
            Dashboard is reading incident data directly from the hosted PostgreSQL view.
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ---- KPI Metrics ----
    total_incidents = len(df)
    high_risk = int(df["risk_label"].isin(["HIGH", "CRITICAL"]).sum())
    critical = risk_count("CRITICAL")
    normal = int(
        df["incident_type"].isin(["NORMAL", "JOB_SUCCESS", "SUCCESS"]).sum()
    )
    avg_risk = df["risk_score"].mean() if "risk_score" in df.columns else 0

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Total Incidents", f"{total_incidents:,}")
    col2.metric("High Risk", f"{high_risk:,}", delta=None)
    col3.metric("Critical", f"{critical:,}", delta=None)
    col4.metric("Normal / Success", f"{normal:,}")
    col5.metric("Avg Risk Score", f"{avg_risk:.3f}" if avg_risk else "N/A")

    st.divider()

    # ---- Charts Row ----
    chart_col1, chart_col2 = st.columns([1, 1])

    with chart_col1:
        section_header("Risk Distribution", "🎯")
        risk_dist = (
            df["risk_label"]
            .value_counts()
            .reindex(["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"], fill_value=0)
            .reset_index()
        )
        risk_dist.columns = ["Risk Level", "Count"]

        chart_risk = (
            alt.Chart(risk_dist)
            .mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6, size=38)
            .encode(
                x=alt.X(
                    "Risk Level:N",
                    sort=["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"],
                    axis=alt.Axis(labelAngle=0),
                ),
                y=alt.Y("Count:Q", axis=alt.Axis(grid=True)),
                color=alt.Color("Risk Level:N", scale=RISK_COLOR_SCALE, legend=None),
                tooltip=["Risk Level:N", "Count:Q"],
            )
            .configure(**DARK_CHART_CONFIG)
            .properties(height=280)
        )
        st.altair_chart(chart_risk, use_container_width=True)

    with chart_col2:
        section_header("Incident Types", "📂")
        type_dist = df["incident_type"].value_counts().head(10).reset_index()
        type_dist.columns = ["Incident Type", "Count"]

        chart_type = (
            alt.Chart(type_dist)
            .mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6, size=28, color="#60a5fa")
            .encode(
                x=alt.X("Count:Q", axis=alt.Axis(grid=True)),
                y=alt.Y("Incident Type:N", sort="-x"),
                tooltip=["Incident Type:N", "Count:Q"],
                opacity=alt.value(0.85),
            )
            .configure(**DARK_CHART_CONFIG)
            .properties(height=280)
        )
        st.altair_chart(chart_type, use_container_width=True)

    # ---- Incident Timeline ----
    section_header("Incident Timeline", "📈")
    if "timestamp" in df.columns and df["timestamp"].notna().any():
        ts_df = df[["timestamp", "risk_label"]].copy().dropna(subset=["timestamp"])
        ts_df["date"] = ts_df["timestamp"].dt.floor("D")
        timeline = (
            ts_df.groupby(["date", "risk_label"])
            .size()
            .reset_index(name="count")
        )
        timeline["date"] = pd.to_datetime(timeline["date"])

        chart_timeline = (
            alt.Chart(timeline)
            .mark_area(opacity=0.6, interpolate="monotone")
            .encode(
                x=alt.X("date:T", axis=alt.Axis(format="%b %d", labelAngle=-30)),
                y=alt.Y("count:Q", stack="zero", axis=alt.Axis(grid=True)),
                color=alt.Color("risk_label:N", scale=RISK_COLOR_SCALE),
                tooltip=[
                    alt.Tooltip("date:T", format="%Y-%m-%d"),
                    "risk_label:N",
                    "count:Q",
                ],
            )
            .configure(**DARK_CHART_CONFIG)
            .properties(height=220)
        )
        st.altair_chart(chart_timeline, use_container_width=True)
    else:
        st.info("Timeline unavailable — no timestamp data found.")

    # ---- Risk Score Distribution (Histogram) ----
    if "risk_score" in df.columns and df["risk_score"].notna().any():
        section_header("Risk Score Distribution", "📉")
        rs_data = df[["risk_score", "risk_label"]].dropna(subset=["risk_score"])

        chart_hist = (
            alt.Chart(rs_data)
            .mark_bar(opacity=0.75, cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
            .encode(
                x=alt.X("risk_score:Q", bin=alt.Bin(maxbins=30), title="Risk Score"),
                y=alt.Y("count():Q", title="Count"),
                color=alt.Color("risk_label:N", scale=RISK_COLOR_SCALE),
                tooltip=["risk_label:N", "count():Q"],
            )
            .configure(**DARK_CHART_CONFIG)
            .properties(height=200)
        )
        st.altair_chart(chart_hist, use_container_width=True)

    # ---- Recent Incidents Table ----
    section_header("Recent Incidents", "🕐")
    recent_columns = [
        "incident_id", "timestamp", "system_id", "job_name",
        "completion_status", "risk_label", "risk_score",
    ]
    recent_df = (
        df.sort_values("timestamp", ascending=False, na_position="last")
        if "timestamp" in df.columns
        else df
    )
    st.dataframe(
        recent_df[available_columns(recent_df, recent_columns)].head(25),
        use_container_width=True,
        hide_index=True,
        column_config={
            "risk_score": st.column_config.ProgressColumn(
                "Risk Score", min_value=0.0, max_value=1.0, format="%.3f"
            ),
            "timestamp": st.column_config.DatetimeColumn("Timestamp", format="YYYY-MM-DD HH:mm"),
            "risk_label": st.column_config.TextColumn("Severity"),
        },
    )


# ============================================================
# INCIDENTS PAGE
# ============================================================

elif page_key == "Incidents":
    st.title("Incidents")
    st.markdown(
        '<p class="page-subtitle">All incidents currently available in the PostgreSQL database.</p>',
        unsafe_allow_html=True,
    )

    # Filters row
    col1, col2, col3 = st.columns(3)
    risk_options = ["ALL"] + sorted(df["risk_label"].dropna().astype(str).unique().tolist())
    system_values = df["system_id"].dropna().astype(str).unique().tolist()
    systems = ["ALL"] + sorted(system_values)
    type_values = df["incident_type"].dropna().astype(str).unique().tolist()
    incident_type_options = ["ALL"] + sorted(type_values)

    with col1:
        selected_risk = st.selectbox("🎯 Severity", risk_options)
    with col2:
        selected_system = st.selectbox("🖥️ System", systems)
    with col3:
        selected_type = st.selectbox("📂 Event Type", incident_type_options)

    filtered_df = df.copy()
    if selected_risk != "ALL":
        filtered_df = filtered_df[filtered_df["risk_label"] == selected_risk]
    if selected_system != "ALL":
        filtered_df = filtered_df[filtered_df["system_id"].astype(str) == selected_system]
    if selected_type != "ALL":
        filtered_df = filtered_df[filtered_df["incident_type"] == selected_type]

    # Summary metrics for the filtered view
    f_total = len(filtered_df)
    f_critical = int((filtered_df["risk_label"] == "CRITICAL").sum()) if "risk_label" in filtered_df.columns else 0
    f_high = int((filtered_df["risk_label"] == "HIGH").sum()) if "risk_label" in filtered_df.columns else 0
    f_avg_rs = filtered_df["risk_score"].mean() if "risk_score" in filtered_df.columns else 0

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Matching Incidents", f"{f_total:,}")
    m2.metric("Critical", f"{f_critical:,}")
    m3.metric("High", f"{f_high:,}")
    m4.metric("Avg Risk Score", f"{f_avg_rs:.3f}" if f_avg_rs else "N/A")

    section_header("Incident List", "📋")

    display_columns = [
        "incident_id", "timestamp", "system_id", "subsystem", "job_name",
        "event_type", "incident_status", "pipeline_status", "completion_status",
        "return_code", "abend_code", "risk_label", "risk_score", "anomaly_score",
        "incident_type",
    ]
    display_df = (
        filtered_df.sort_values("timestamp", ascending=False, na_position="last")
        if "timestamp" in filtered_df.columns
        else filtered_df
    )
    st.dataframe(
        display_df[available_columns(display_df, display_columns)],
        use_container_width=True,
        hide_index=True,
        column_config={
            "risk_score": st.column_config.ProgressColumn(
                "Risk Score", min_value=0.0, max_value=1.0, format="%.3f"
            ),
            "anomaly_score": st.column_config.ProgressColumn(
                "Anomaly Score", min_value=0.0, max_value=1.0, format="%.3f"
            ),
            "timestamp": st.column_config.DatetimeColumn("Timestamp", format="YYYY-MM-DD HH:mm"),
        },
    )

    # Filtered risk breakdown chart
    if not filtered_df.empty and "risk_label" in filtered_df.columns:
        section_header("Risk Breakdown (Filtered)", "🎯")
        filt_risk = filtered_df["risk_label"].value_counts().reset_index()
        filt_risk.columns = ["Risk Level", "Count"]
        chart_filt = (
            alt.Chart(filt_risk)
            .mark_arc(innerRadius=55, outerRadius=110)
            .encode(
                theta=alt.Theta("Count:Q", stack=True),
                color=alt.Color("Risk Level:N", scale=RISK_COLOR_SCALE),
                tooltip=["Risk Level:N", "Count:Q"],
            )
            .configure(**DARK_CHART_CONFIG)
            .properties(height=260)
        )
        _, donut_col, _ = st.columns([1, 1, 1])
        with donut_col:
            st.altair_chart(chart_filt, use_container_width=True)


# ============================================================
# INCIDENT DETAIL PAGE
# ============================================================

elif page_key == "Incident Detail":
    st.title("Incident Detail")
    st.markdown(
        '<p class="page-subtitle">Deep-dive into a specific incident with AI risk assessment and operational context.</p>',
        unsafe_allow_html=True,
    )

    incident_ids = df["incident_id"].dropna().astype(str).tolist()
    selected_incident_id = st.selectbox(
        "Select Incident ID",
        incident_ids,
        help="Choose an incident to inspect in detail",
    )
    incident = get_selected_incident(selected_incident_id)

    if incident is not None:
        risk_lbl = format_value(incident.get("risk_label"))
        pill_html = risk_pill(risk_lbl) if risk_lbl not in ("Not available", "UNKNOWN") else risk_lbl

        st.markdown(
            f"""
            <div style="display:flex; align-items:center; gap:12px; margin-bottom:4px;">
                <span style="font-size:1.6rem; font-weight:800; color:#e2e8f0;">
                    {incident.get('incident_id', 'Unknown')}
                </span>
                {pill_html}
            </div>
            <p style="color:#64748b; font-size:13px; margin-bottom:1rem;">
                {format_value(incident.get('job_name'))} &nbsp;·&nbsp;
                System: {format_value(incident.get('system_id'))} &nbsp;·&nbsp;
                Subsystem: {format_value(incident.get('subsystem'))}
            </p>
            """,
            unsafe_allow_html=True,
        )

        tab1, tab2, tab3 = st.tabs(["📊 Assessment", "⚙️ Execution", "📝 Root Cause & Logs"])

        # ---- Tab 1: Assessment ----
        with tab1:
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Severity", format_value(incident.get("risk_label")))
            col2.metric("Risk Score", format_value(incident.get("risk_score")))
            col3.metric("Incident Status", format_value(incident.get("incident_status")))
            col4.metric("Event Type", format_value(incident.get("event_type")))

            st.divider()

            section_header("Operational Metrics", "📡")
            col1, col2, col3, col4 = st.columns(4)
            cpu = incident.get("cpu_utilization_pct")
            error_rate = incident.get("error_rate_pct")
            txn = incident.get("transaction_volume_per_hr")
            col1.metric("CPU Utilization", f"{cpu:.1f}%" if cpu is not None and pd.notna(cpu) else "N/A")
            col2.metric("Error Rate", f"{error_rate:.1f}%" if error_rate is not None and pd.notna(error_rate) else "N/A")
            col3.metric("Transactions / Hr", f"{int(txn):,}" if txn is not None and pd.notna(txn) else "N/A")
            col4.metric("Return Code", format_value(incident.get("return_code")))

            # Metric gauges (if data available)
            if cpu is not None and pd.notna(cpu):
                st.divider()
                section_header("Resource Pressure Gauges", "🌡️")
                g1, g2, g3 = st.columns(3)
                with g1:
                    st.markdown("**CPU Utilization**")
                    st.progress(min(float(cpu) / 100.0, 1.0), text=f"{cpu:.1f}%")
                with g2:
                    if error_rate is not None and pd.notna(error_rate):
                        st.markdown("**Error Rate**")
                        st.progress(min(float(error_rate) / 100.0, 1.0), text=f"{error_rate:.1f}%")
                with g3:
                    rs = incident.get("risk_score")
                    if rs is not None and pd.notna(rs):
                        st.markdown("**Risk Score**")
                        st.progress(min(float(rs), 1.0), text=f"{float(rs):.3f}")

            section_header("AI Risk Assessment", "🤖")
            ai_col1, ai_col2 = st.columns(2)
            with ai_col1:
                st.write(f"**Severity:** {format_value(incident.get('risk_label'))}")
                st.write(f"**Risk Score:** {format_value(incident.get('risk_score'))}")
                st.write(f"**Anomaly Score:** {format_value(incident.get('anomaly_score'))}")
                st.write(f"**Model Version:** {format_value(incident.get('model_version'))}")
                st.write(f"**RCA Confidence:** {format_value(incident.get('rca_confidence'))}")
            with ai_col2:
                st.write(f"**Event Type:** {format_value(incident.get('event_type'))}")
                st.write(f"**Recent Deployment:** {format_value(incident.get('recent_deployment_flag'))}")
                st.write(f"**Pipeline Status:** {format_value(incident.get('pipeline_status'))}")
                st.write(f"**Pipeline Error:** {format_value(incident.get('pipeline_error'))}")

        # ---- Tab 2: Execution ----
        with tab2:
            section_header("Execution Information", "⚙️")
            execution_fields = [
                ("Incident ID", "incident_id"),
                ("Timestamp", "timestamp"),
                ("System", "system"),
                ("Subsystem", "subsystem"),
                ("Job Name", "job_name"),
                ("Job ID", "job_id"),
                ("Step Name", "step_name"),
                ("Event Type", "event_type"),
                ("Incident Status", "incident_status"),
                ("Pipeline Status", "pipeline_status"),
                ("Return Code", "return_code"),
                ("ABEND Code", "abend_code"),
                ("Primary Message ID", "primary_message_id"),
            ]
            execution_data = [
                {"Field": label, "Value": str(format_value(incident.get(column)))}
                for label, column in execution_fields
                if column in df.columns or column in incident.index
            ]
            st.dataframe(
                pd.DataFrame(execution_data),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Field": st.column_config.TextColumn("Field", width="small"),
                    "Value": st.column_config.TextColumn("Value", width="large"),
                },
            )

        # ---- Tab 3: Root Cause & Logs ----
        with tab3:
            section_header("Root Cause Analysis", "🧠")
            root_cause = format_value(incident.get("root_cause"))
            if root_cause != "Not available":
                st.info(f"🔍 {root_cause}")
            else:
                st.warning("Root cause analysis not yet available for this incident.")

            section_header("Explanation", "💡")
            explanation = format_value(incident.get("explanation"))
            if explanation != "Not available":
                st.write(explanation)
            else:
                st.caption("No explanation available.")

            section_header("Recommended Remediation", "🛠️")
            remediation = format_value(incident.get("recommended_action", incident.get("remediation")))
            if remediation != "Not available":
                st.success(f"✅ {remediation}")
            else:
                st.warning("No remediation recommendation available.")

            section_header("Raw Log / Incident Data", "📄")
            raw_log = incident.get("raw_log_snippet")
            if raw_log is not None and not pd.isna(raw_log):
                st.code(str(raw_log), language="text")
            else:
                st.caption("No raw log snippet available.")

            with st.expander("📦 View Structured Incident Data"):
                st.json(_as_mapping(incident.get("incident_data")) or {"message": "No structured data"})


# ============================================================
# SYSTEM HEALTH PAGE
# ============================================================

elif page_key == "System Health":
    st.title("System Health")
    st.markdown(
        '<p class="page-subtitle">Operational health overview derived from the incident database.</p>',
        unsafe_allow_html=True,
    )

    system_column = "system_id" if "system_id" in df.columns else "system"
    system_summary = (
        df.groupby(system_column, dropna=False)
        .agg(
            incidents=("incident_id", "count"),
            high_risk=("risk_label", lambda values: values.isin(["HIGH", "CRITICAL"]).sum()),
            avg_risk_score=("risk_score", "mean"),
            avg_anomaly_score=("anomaly_score", "mean"),
        )
        .reset_index()
        .rename(columns={system_column: "system"})
    )
    system_summary["avg_risk_score"] = system_summary["avg_risk_score"].round(3)
    system_summary["avg_anomaly_score"] = system_summary["avg_anomaly_score"].round(3)
    system_summary["high_risk_pct"] = (
        system_summary["high_risk"] / system_summary["incidents"].replace(0, 1) * 100
    ).round(1)

    section_header("System Summary", "🖥️")
    st.dataframe(
        system_summary,
        use_container_width=True,
        hide_index=True,
        column_config={
            "avg_risk_score": st.column_config.ProgressColumn(
                "Avg Risk Score", min_value=0.0, max_value=1.0, format="%.3f"
            ),
            "avg_anomaly_score": st.column_config.ProgressColumn(
                "Avg Anomaly Score", min_value=0.0, max_value=1.0, format="%.3f"
            ),
            "high_risk_pct": st.column_config.NumberColumn("High Risk %", format="%.1f%%"),
        },
    )

    # ---- System Incident Bar Chart ----
    if not system_summary.empty:
        section_header("Incidents by System", "📊")
        sys_chart = (
            alt.Chart(system_summary)
            .mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6)
            .encode(
                x=alt.X("system:N", axis=alt.Axis(labelAngle=-20)),
                y=alt.Y("incidents:Q", title="Incident Count"),
                color=alt.Color(
                    "avg_risk_score:Q",
                    scale=alt.Scale(scheme="reds"),
                    legend=alt.Legend(title="Avg Risk"),
                ),
                tooltip=["system:N", "incidents:Q", "high_risk:Q", "avg_risk_score:Q"],
            )
            .configure(**DARK_CHART_CONFIG)
            .properties(height=280)
        )
        st.altair_chart(sys_chart, use_container_width=True)

    st.divider()

    # Metric charts
    chart_col1, chart_col2, chart_col3 = st.columns(3)

    with chart_col1:
        section_header("Anomaly Scores", "⚡")
        anomaly_df = df[["incident_id", "anomaly_score"]].copy()
        anomaly_df["anomaly_score"] = pd.to_numeric(anomaly_df["anomaly_score"], errors="coerce")
        anomaly_df = anomaly_df.dropna().head(80)
        if not anomaly_df.empty:
            a_chart = (
                alt.Chart(anomaly_df)
                .mark_point(filled=True, color="#a78bfa", size=60, opacity=0.7)
                .encode(
                    x=alt.X("incident_id:N", axis=None),
                    y=alt.Y("anomaly_score:Q", scale=alt.Scale(domain=[0, 1])),
                    tooltip=["incident_id:N", "anomaly_score:Q"],
                )
                .configure(**DARK_CHART_CONFIG)
                .properties(height=200)
            )
            st.altair_chart(a_chart, use_container_width=True)
        else:
            st.info("Anomaly score data not available.")

    with chart_col2:
        section_header("CPU Utilization", "💻")
        cpu_df = df[["incident_id", "cpu_utilization_pct"]].copy()
        cpu_df["cpu_utilization_pct"] = pd.to_numeric(cpu_df["cpu_utilization_pct"], errors="coerce")
        cpu_df = cpu_df.dropna().head(80)
        if not cpu_df.empty:
            cpu_chart = (
                alt.Chart(cpu_df)
                .mark_point(filled=True, color="#60a5fa", size=60, opacity=0.7)
                .encode(
                    x=alt.X("incident_id:N", axis=None),
                    y=alt.Y("cpu_utilization_pct:Q", scale=alt.Scale(domain=[0, 100])),
                    tooltip=["incident_id:N", "cpu_utilization_pct:Q"],
                )
                .configure(**DARK_CHART_CONFIG)
                .properties(height=200)
            )
            st.altair_chart(cpu_chart, use_container_width=True)
        else:
            st.info("CPU utilization data not available.")

    with chart_col3:
        section_header("Error Rate", "🚨")
        error_df = df[["incident_id", "error_rate_pct"]].copy()
        error_df["error_rate_pct"] = pd.to_numeric(error_df["error_rate_pct"], errors="coerce")
        error_df = error_df.dropna().head(80)
        if not error_df.empty:
            err_chart = (
                alt.Chart(error_df)
                .mark_point(filled=True, color="#f87171", size=60, opacity=0.7)
                .encode(
                    x=alt.X("incident_id:N", axis=None),
                    y=alt.Y("error_rate_pct:Q", scale=alt.Scale(domain=[0, 100])),
                    tooltip=["incident_id:N", "error_rate_pct:Q"],
                )
                .configure(**DARK_CHART_CONFIG)
                .properties(height=200)
            )
            st.altair_chart(err_chart, use_container_width=True)
        else:
            st.info("Error rate data not available.")


# ============================================================
# DEMO SCENARIOS PAGE
# ============================================================

elif page_key == "Demo Scenarios":
    st.title("Demo Scenarios")
    st.markdown(
        '<p class="page-subtitle">Incident scenarios available in the current hosted dataset.</p>',
        unsafe_allow_html=True,
    )

    # Search / filter
    search_query = st.text_input(
        "🔎 Search incidents (ID, job name, root cause…)",
        placeholder="e.g. S0C4, PAYAUTH, JCL_ERROR",
    )

    scenario_columns = [
        "incident_id", "incident_type", "event_type", "completion_status",
        "abend_code", "risk_label", "risk_score", "root_cause",
        "recommended_action",
    ]

    scenario_df = df[available_columns(df, scenario_columns)].copy()
    if search_query:
        mask = scenario_df.astype(str).apply(
            lambda col: col.str.contains(search_query, case=False, na=False)
        ).any(axis=1)
        scenario_df = scenario_df[mask]

    st.markdown(f"**Showing {len(scenario_df):,} scenario(s)**")
    st.dataframe(
        scenario_df.head(500),
        use_container_width=True,
        hide_index=True,
        column_config={
            "risk_score": st.column_config.ProgressColumn(
                "Risk Score", min_value=0.0, max_value=1.0, format="%.3f"
            ),
        },
    )

    section_header("Scenario Cards", "🎯")
    display_rows = df if not search_query else df[df["incident_id"].isin(scenario_df.get("incident_id", pd.Series()).values)]
    for _, row in display_rows.head(50).iterrows():
        risk = str(row.get("risk_label", "UNKNOWN")).upper()
        pill = risk_pill(risk)
        with st.expander(
            f"{row.get('incident_id', 'Unknown')}  ·  "
            f"{row.get('incident_type', 'UNKNOWN')}  ·  "
            f"{risk}"
        ):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"**Job:** {format_value(row.get('job_name'))}")
                st.markdown(f"**System:** {format_value(row.get('system_id'))}")
                st.markdown(f"**Event Type:** {format_value(row.get('event_type'))}")
                st.markdown(f"**Incident Status:** {format_value(row.get('incident_status'))}")
            with c2:
                st.markdown(f"**Severity:** {format_value(row.get('risk_label'))}")
                st.markdown(f"**Risk Score:** {format_value(row.get('risk_score'))}")
                rc = row.get("root_cause")
                if rc and str(rc) != "nan":
                    st.info(f"🔍 **Root Cause:** {rc}")
                rem = row.get("recommended_action", row.get("remediation"))
                if rem and str(rem) != "nan":
                    st.success(f"✅ **Action:** {rem}")

    if len(df) > 50:
        st.caption("Showing the first 50 scenario cards to keep the page responsive.")


# ============================================================
# FOOTER
# ============================================================

st.divider()
st.markdown(
    '<p style="color:#334155; font-size:12px; text-align:center;">'
    "CriticalFlow AI &nbsp;·&nbsp; IBM Z® Incident Intelligence Platform &nbsp;·&nbsp; "
    "Data source: Neon PostgreSQL"
    "</p>",
    unsafe_allow_html=True,
)

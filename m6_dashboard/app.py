import json
import logging
from collections.abc import Mapping

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
# CUSTOM CSS
# ============================================================

st.markdown(
    """
    <style>
    .stApp {
        background-color: #0b0f14;
    }
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 3rem;
        max-width: 1500px;
    }
    section[data-testid="stSidebar"] {
        background-color: #111720;
        border-right: 1px solid #27303a;
    }
    h1, h2, h3 {
        letter-spacing: -0.5px;
    }
    .mock-banner {
        background: linear-gradient(
            90deg,
            rgba(34, 197, 94, 0.15),
            rgba(34, 197, 94, 0.05)
        );
        border: 1px solid rgba(34, 197, 94, 0.35);
        border-radius: 12px;
        padding: 12px 16px;
        margin-bottom: 20px;
        color: #86efac;
        font-size: 14px;
    }
    .section-title {
        font-size: 20px;
        font-weight: 700;
        margin-top: 20px;
        margin-bottom: 10px;
    }
    div[data-testid="stMetric"] {
        background: #111720;
        border: 1px solid #27303a;
        padding: 18px;
        border-radius: 14px;
    }
    div[data-testid="stMetricLabel"] {
        color: #9ca8b5;
    }
    div[data-testid="stDataFrame"] {
        border: 1px solid #27303a;
        border-radius: 12px;
    }
    .stButton > button {
        border-radius: 10px;
        font-weight: 600;
    }
    .status-pill {
        display: inline-block;
        padding: 5px 10px;
        border-radius: 20px;
        font-size: 12px;
        font-weight: 700;
    }
    .live-pill {
        background: rgba(34, 197, 94, 0.15);
        color: #4ade80;
        border: 1px solid rgba(34, 197, 94, 0.3);
    }
    </style>
    """,
    unsafe_allow_html=True,
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

    # These compatibility columns let existing dashboard sections work
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

    # A normalized categorical type is useful for dashboard charts.
    df["incident_type"] = (
        df["incident_type"].fillna("UNKNOWN").astype(str).str.upper()
    )
    df["risk_label"] = (
        df["risk_label"].fillna("UNKNOWN").astype(str).str.upper()
    )

    # Use event_time as a sortable timestamp where available.
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)

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


# ============================================================
# LOAD DATA
# ============================================================

df = pd.DataFrame()
try:
    df = get_incidents()
except Exception as exc:
    # Show a generic message to viewers; keep details (without secrets) in server logs only.
    logging.getLogger("m6_dashboard").error("incident load failed: %s", type(exc).__name__)
    st.error("Unable to load incident data. Please contact the administrator.")
    st.stop()

if df.empty:
    st.warning("No incidents are currently available.")
    st.stop()

incidents = df.to_dict("records")


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:
    st.markdown(
        """
        <h1 style="margin-bottom:0;">CriticalFlow AI</h1>
        <p style="color:#9ca8b5; margin-top:5px;">
            Incident Intelligence Platform
        </p>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("---")

    page = st.radio(
        "Navigation",
        [
            "Overview",
            "Incidents",
            "Incident Detail",
            "System Health",
            "Demo Scenarios",
        ],
    )

    st.markdown("---")
    st.markdown(
        """
        <div class="status-pill live-pill">
            ● NEON POSTGRESQL
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption("Data source: hosted PostgreSQL")
    st.caption(f"Records loaded: {len(df):,}")


# ============================================================
# OVERVIEW PAGE
# ============================================================

if page == "Overview":
    st.title("CriticalFlow AI")
    st.markdown(
        """
        <p style="color:#9ca8b5; font-size:16px;">
            AI-powered incident intelligence and operational risk monitoring.
        </p>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class="mock-banner">
            🟢 <b>NEON POSTGRESQL DATA MODE</b> — Dashboard is reading
            incident data directly from the hosted PostgreSQL view.
        </div>
        """,
        unsafe_allow_html=True,
    )

    total_incidents = len(df)
    high_risk = int(df["risk_label"].isin(["HIGH", "CRITICAL"]).sum())
    critical = risk_count("CRITICAL")
    normal = int(
        df["incident_type"].isin(["NORMAL", "JOB_SUCCESS", "SUCCESS"]).sum()
    )

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Incidents", f"{total_incidents:,}")
    col2.metric("High Risk", f"{high_risk:,}")
    col3.metric("Critical", f"{critical:,}")
    col4.metric("Normal / Successful", f"{normal:,}")

    st.markdown('<div class="section-title">Risk Distribution</div>', unsafe_allow_html=True)
    risk_distribution = (
        df["risk_label"]
        .value_counts()
        .reindex(["LOW", "MEDIUM", "HIGH", "CRITICAL", "UNKNOWN"], fill_value=0)
    )
    st.bar_chart(risk_distribution)

    st.markdown('<div class="section-title">Incident Types</div>', unsafe_allow_html=True)
    st.bar_chart(df["incident_type"].value_counts().head(15))

    st.markdown('<div class="section-title">Recent Incidents</div>', unsafe_allow_html=True)
    recent_columns = [
        "incident_id", "timestamp", "system_id", "job_name",
        "completion_status", "risk_label", "risk_score",
    ]
    recent_df = df.sort_values("timestamp", ascending=False, na_position="last") if "timestamp" in df else df
    st.dataframe(
        recent_df[available_columns(recent_df, recent_columns)].head(25),
        use_container_width=True,
        hide_index=True,
    )


# ============================================================
# INCIDENTS PAGE
# ============================================================

elif page == "Incidents":
    st.title("Incidents")
    st.markdown(
        '<p style="color:#9ca8b5;">All incidents currently available in Neon PostgreSQL.</p>',
        unsafe_allow_html=True,
    )

    col1, col2, col3 = st.columns(3)
    risk_options = ["ALL"] + sorted(df["risk_label"].dropna().astype(str).unique().tolist())
    system_values = df["system_id"].dropna().astype(str).unique().tolist()
    systems = ["ALL"] + sorted(system_values)
    type_values = df["incident_type"].dropna().astype(str).unique().tolist()
    incident_type_options = ["ALL"] + sorted(type_values)

    with col1:
        selected_risk = st.selectbox("Severity", risk_options)
    with col2:
        selected_system = st.selectbox("System", systems)
    with col3:
        selected_type = st.selectbox("Event Type", incident_type_options)

    filtered_df = df.copy()
    if selected_risk != "ALL":
        filtered_df = filtered_df[filtered_df["risk_label"] == selected_risk]
    if selected_system != "ALL":
        filtered_df = filtered_df[filtered_df["system_id"].astype(str) == selected_system]
    if selected_type != "ALL":
        filtered_df = filtered_df[filtered_df["incident_type"] == selected_type]

    st.markdown(f"**Showing {len(filtered_df):,} incident(s)**")

    display_columns = [
        "incident_id", "timestamp", "system_id", "subsystem", "job_name",
        "event_type", "incident_status", "pipeline_status", "completion_status",
        "return_code", "abend_code", "risk_label", "risk_score", "anomaly_score",
        "incident_type",
    ]
    display_df = filtered_df.sort_values("timestamp", ascending=False, na_position="last") if "timestamp" in filtered_df else filtered_df
    st.dataframe(
        display_df[available_columns(display_df, display_columns)],
        use_container_width=True,
        hide_index=True,
    )


# ============================================================
# INCIDENT DETAIL PAGE
# ============================================================

elif page == "Incident Detail":
    st.title("Incident Detail")

    incident_ids = df["incident_id"].dropna().astype(str).tolist()
    selected_incident_id = st.selectbox("Select Incident", incident_ids)
    incident = get_selected_incident(selected_incident_id)

    if incident is not None:
        st.subheader(f"{incident['incident_id']} — {format_value(incident.get('job_name'))}")
        st.caption(
            f"System: {format_value(incident.get('system_id'))} | "
            f"Subsystem: {format_value(incident.get('subsystem'))}"
        )

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Severity", format_value(incident.get("risk_label")))
        col2.metric("Risk Score", format_value(incident.get("risk_score")))
        col3.metric("Incident Status", format_value(incident.get("incident_status")))
        col4.metric("Event Type", format_value(incident.get("event_type")))

        st.markdown('<div class="section-title">Operational Metrics</div>', unsafe_allow_html=True)
        col1, col2, col3, col4 = st.columns(4)
        cpu = incident.get("cpu_utilization_pct")
        error_rate = incident.get("error_rate_pct")
        col1.metric("CPU Utilization", f"{cpu}%" if pd.notna(cpu) else "Not available")
        col2.metric("Error Rate", f"{error_rate}%" if pd.notna(error_rate) else "Not available")
        col3.metric("Transactions / Hr", format_value(incident.get("transaction_volume_per_hr")))
        col4.metric("Return Code", format_value(incident.get("return_code")))

        st.markdown('<div class="section-title">Execution Information</div>', unsafe_allow_html=True)
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
            {"Field": label, "Value": format_value(incident.get(column))}
            for label, column in execution_fields
            if column in df.columns or column in incident.index
        ]
        st.dataframe(pd.DataFrame(execution_data), use_container_width=True, hide_index=True)

        st.markdown('<div class="section-title">AI Investigation</div>', unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("### Risk Assessment")
            st.write(f"**Severity:** {format_value(incident.get('risk_label'))}")
            st.write(f"**Risk Score:** {format_value(incident.get('risk_score'))}")
            st.write(f"**Anomaly Score:** {format_value(incident.get('anomaly_score'))}")
            st.write(f"**Model Version:** {format_value(incident.get('model_version'))}")
            st.write(f"**RCA Confidence:** {format_value(incident.get('rca_confidence'))}")
        with col2:
            st.markdown("### Investigation")
            st.write(f"**Event Type:** {format_value(incident.get('event_type'))}")
            st.write(f"**Recent Deployment:** {format_value(incident.get('recent_deployment_flag'))}")
            st.write(f"**Pipeline Status:** {format_value(incident.get('pipeline_status'))}")
            st.write(f"**Pipeline Error:** {format_value(incident.get('pipeline_error'))}")

        st.markdown('<div class="section-title">Root Cause</div>', unsafe_allow_html=True)
        st.info(format_value(incident.get("root_cause")))

        st.markdown('<div class="section-title">Explanation</div>', unsafe_allow_html=True)
        st.write(format_value(incident.get("explanation")))

        st.markdown('<div class="section-title">Recommended Remediation</div>', unsafe_allow_html=True)
        st.success(format_value(incident.get("recommended_action", incident.get("remediation"))))

        st.markdown('<div class="section-title">Raw Log / Incident Data</div>', unsafe_allow_html=True)
        raw_log = incident.get("raw_log_snippet")
        if raw_log is not None and not pd.isna(raw_log):
            st.code(str(raw_log), language="text")
        with st.expander("View structured incident data"):
            st.json(_as_mapping(incident.get("incident_data")))


# ============================================================
# SYSTEM HEALTH PAGE
# ============================================================

elif page == "System Health":
    st.title("System Health")
    st.markdown(
        '<p style="color:#9ca8b5;">Operational health overview based on hosted incident data.</p>',
        unsafe_allow_html=True,
    )

    system_column = "system_id" if "system_id" in df.columns else "system"
    system_summary = (
        df.groupby(system_column, dropna=False)
        .agg(
            incidents=("incident_id", "count"),
            high_risk=("risk_label", lambda values: values.isin(["HIGH", "CRITICAL"]).sum()),
            avg_risk_score=("risk_score", "mean"),
        )
        .reset_index()
        .rename(columns={system_column: "system"})
    )
    system_summary["avg_risk_score"] = system_summary["avg_risk_score"].round(3)
    st.dataframe(system_summary, use_container_width=True, hide_index=True)

    st.markdown('<div class="section-title">Anomaly Score by Incident</div>', unsafe_allow_html=True)
    anomaly_df = df[["incident_id", "anomaly_score"]].copy()
    anomaly_df["anomaly_score"] = pd.to_numeric(anomaly_df["anomaly_score"], errors="coerce")
    anomaly_df = anomaly_df.dropna().head(100).set_index("incident_id")
    if not anomaly_df.empty:
        st.bar_chart(anomaly_df)
    else:
        st.info("Anomaly score data is not available.")

    st.markdown('<div class="section-title">CPU Utilization</div>', unsafe_allow_html=True)
    cpu_df = df[["incident_id", "cpu_utilization_pct"]].copy()
    cpu_df["cpu_utilization_pct"] = pd.to_numeric(cpu_df["cpu_utilization_pct"], errors="coerce")
    cpu_df = cpu_df.dropna().head(100).set_index("incident_id")
    if not cpu_df.empty:
        st.bar_chart(cpu_df)
    else:
        st.info("CPU utilization data is not available.")

    st.markdown('<div class="section-title">Error Rate</div>', unsafe_allow_html=True)
    error_df = df[["incident_id", "error_rate_pct"]].copy()
    error_df["error_rate_pct"] = pd.to_numeric(error_df["error_rate_pct"], errors="coerce")
    error_df = error_df.dropna().head(100).set_index("incident_id")
    if not error_df.empty:
        st.bar_chart(error_df)
    else:
        st.info("Error rate data is not available.")


# ============================================================
# DEMO SCENARIOS PAGE
# ============================================================

elif page == "Demo Scenarios":
    st.title("Demo Scenarios")
    st.markdown(
        '<p style="color:#9ca8b5;">Incident scenarios available in the current hosted dataset.</p>',
        unsafe_allow_html=True,
    )

    scenario_columns = [
        "incident_id", "incident_type", "event_type", "completion_status",
        "abend_code", "risk_label", "risk_score", "root_cause",
        "recommended_action",
    ]
    st.dataframe(
        df[available_columns(df, scenario_columns)].head(500),
        use_container_width=True,
        hide_index=True,
    )

    st.markdown('<div class="section-title">Scenario Summary</div>', unsafe_allow_html=True)
    # Limit expanders to avoid rendering thousands of records at once.
    for _, row in df.head(50).iterrows():
        with st.expander(
            f"{row.get('incident_id', 'Unknown')} — "
            f"{row.get('incident_type', 'UNKNOWN')} — "
            f"{row.get('risk_label', 'UNKNOWN')}"
        ):
            st.write(f"**Job:** {format_value(row.get('job_name'))}")
            st.write(f"**System:** {format_value(row.get('system_id'))}")
            st.write(f"**Event Type:** {format_value(row.get('event_type'))}")
            st.write(f"**Incident Status:** {format_value(row.get('incident_status'))}")
            st.write(f"**Risk Score:** {format_value(row.get('risk_score'))}")
            st.write(f"**Root Cause:** {format_value(row.get('root_cause'))}")
            st.write(f"**Recommended Action:** {format_value(row.get('recommended_action'))}")

    if len(df) > 50:
        st.caption("Showing the first 50 scenario summaries to keep the page responsive.")


# ============================================================
# FOOTER
# ============================================================

st.markdown("---")
st.caption(
    "CriticalFlow AI • PostgreSQL-backed M6 Dashboard • "
    "Data source: Neon PostgreSQL"
)

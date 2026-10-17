import os
from unittest.mock import patch, MagicMock
import pandas as pd
import pytest

from db import get_connection

with patch("db.load_incidents", return_value=pd.DataFrame()):
    from app import normalize_incidents


def test_get_connection_fallback_when_unset():
    """Verify get_connection falls back to local postgres connection string when DASHBOARD_DATABASE_URL is unset."""
    with patch.dict(os.environ, {}, clear=True):
        with patch("psycopg.connect") as mock_connect:
            get_connection()
            mock_connect.assert_called_once()
            args, kwargs = mock_connect.call_args
            assert args[0] == "postgresql://postgres:postgres@localhost:5432/criticalflow"
            assert kwargs.get("sslmode") == "prefer"


def test_get_connection_fallback_with_custom_env():
    """Verify get_connection constructs fallback using custom POSTGRES_* environment variables."""
    custom_env = {
        "POSTGRES_USER": "myuser",
        "POSTGRES_PASSWORD": "mypassword",
        "POSTGRES_HOST": "dbhost",
        "POSTGRES_PORT": "5433",
        "POSTGRES_DB": "mydb",
    }
    with patch.dict(os.environ, custom_env, clear=True):
        with patch("psycopg.connect") as mock_connect:
            get_connection()
            mock_connect.assert_called_once()
            args, kwargs = mock_connect.call_args
            assert args[0] == "postgresql://myuser:mypassword@dbhost:5433/mydb"
            assert kwargs.get("sslmode") == "prefer"


def test_get_connection_default_sslmode_prefer():
    """Verify default sslmode is 'prefer' when not specified in connection URL."""
    with patch.dict(os.environ, {"DATABASE_URL": "postgresql://postgres:postgres@localhost:5432/criticalflow"}, clear=True):
        with patch("psycopg.connect") as mock_connect:
            get_connection()
            mock_connect.assert_called_once()
            args, kwargs = mock_connect.call_args
            assert args[0] == "postgresql://postgres:postgres@localhost:5432/criticalflow"
            assert kwargs.get("sslmode") == "prefer"


def test_get_connection_explicit_url_sslmode():
    """Verify explicit sslmode in query params is respected without override."""
    neon_url = "postgresql://user:pass@ep-cool-host.neon.tech/criticalflow?sslmode=require"
    with patch.dict(os.environ, {"DASHBOARD_DATABASE_URL": neon_url}, clear=True):
        with patch("psycopg.connect") as mock_connect:
            get_connection()
            mock_connect.assert_called_once()
            args, kwargs = mock_connect.call_args
            assert args[0] == neon_url
            assert "sslmode" not in kwargs  # Handled natively by psycopg via URL query parameter


def test_get_connection_custom_sslmode_env():
    """Verify DB_SSLMODE / PGSSLMODE environment variable override."""
    with patch.dict(os.environ, {"DATABASE_URL": "postgresql://postgres:postgres@postgres:5432/criticalflow", "DB_SSLMODE": "disable"}, clear=True):
        with patch("psycopg.connect") as mock_connect:
            get_connection()
            mock_connect.assert_called_once()
            args, kwargs = mock_connect.call_args
            assert kwargs.get("sslmode") == "disable"


def test_normalize_incidents_structure():
    """Verify normalize_incidents maps incident_overview columns to dashboard aliases."""
    raw_sample = pd.DataFrame([{
        "incident_id": "INC-20260930-JOB06340-PAYGATE4",
        "event_type": "JOB_FAILURE",
        "error_code": "RC_8",
        "system": "SYSB",
        "subsystem": "PAYMENT-API",
        "job_name": "PAYGATE4",
        "event_time": "2026-09-30T10:00:00Z",
        "incident_status": "OPEN",
        "pipeline_status": "COMPLETE",
        "pipeline_error": None,
        "severity": "CRITICAL",
        "anomaly_score": 0.915,
        "prediction": {"raw": {"severity": "CRITICAL", "risk_score": 0.963, "incident_type": "exhaustion"}},
        "root_cause": "Resource exhaustion on JVM",
        "recommended_action": "Increase heap space",
        "rca_confidence": None,
        "explanation": {"raw": {}},
        "features": {"cpu_utilization_pct": 94.1, "error_rate_pct": 42.0},
        "incident_data": {"job_id": "JOB06340", "step_name": "STEP01"},
        "created_at": "2026-09-30T10:00:05Z",
    }])

    normalized = normalize_incidents(raw_sample)

    assert "risk_label" in normalized.columns
    assert normalized.iloc[0]["risk_label"] == "CRITICAL"
    assert normalized.iloc[0]["system_id"] == "SYSB"
    assert normalized.iloc[0]["incident_type"] == "EXHAUSTION"
    assert normalized.iloc[0]["remediation"] == "Increase heap space"

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_CSV = ROOT / "data" / "samples" / "training_data.csv"


@pytest.fixture
def good_event():
    return {
        "schema_version": "1.0.0", "incident_id": "INC-20260901-JOB10644-GLPOST7",
        "timestamp": "2026-09-01T01:21:05Z", "system_id": "SYSC", "subsystem": "GL-BATCH",
        "job_name": "GLPOST7", "job_id": "JOB10644", "step_name": "STEP020", "completion_status": "CC",
        "return_code": 0, "abend_code": None, "primary_message_id": "IEF142I", "cpu_utilization_pct": 59.4,
        "error_rate_pct": 0.2, "transaction_volume_per_hr": 32082, "recent_deployment_flag": False,
        "raw_log_snippet": "01.21.05 JOB10644  $HASP395 GLPOST7 ENDED - RC=0000"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    """API against a throw-away SQLite DB (set TEST_DATABASE_URL to run the same tests on Postgres)."""
    import os
    monkeypatch.setenv("DATABASE_URL", os.getenv("TEST_DATABASE_URL", f"sqlite:///{tmp_path/'t.db'}"))
    monkeypatch.delenv("API_KEY", raising=False)
    from config.settings import get_settings
    from db import session
    get_settings.cache_clear(); session.get_engine.cache_clear(); session._factory.cache_clear()
    from sqlalchemy import text
    from db.models import Base
    eng = session.get_engine()
    with eng.begin() as conn:                      # clean slate even on a persistent Postgres test DB
        conn.execute(text("DROP VIEW IF EXISTS incident_overview"))
    Base.metadata.drop_all(eng)
    from fastapi.testclient import TestClient
    from api.main import app
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear(); session.get_engine.cache_clear(); session._factory.cache_clear()

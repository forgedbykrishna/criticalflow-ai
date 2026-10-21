from __future__ import annotations

from functools import lru_cache
from typing import Iterator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from config.settings import get_settings
from db.models import Base


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True, future=True)


@lru_cache
def _factory() -> sessionmaker[Session]:
    return sessionmaker(get_engine(), expire_on_commit=False)


# One flat row per incident for M6 (dashboard reads PostgreSQL directly): event + M4 + M5 + pipeline status.
OVERVIEW_VIEW_SQL = """
SELECT p.event_id AS incident_id, p.event_type, p.error_code, p.system, p.subsystem, p.job_name,
       p.event_time, p.status AS incident_status, pl.status AS pipeline_status, pl.error AS pipeline_error,
       i.severity, i.anomaly_score, i.extra AS prediction,
       r.root_cause, r.recommended_action, r.confidence AS rca_confidence, r.extra AS explanation,
       p.features, p.context AS incident_data, p.processed_at AS created_at
FROM processed_events p
LEFT JOIN incident_results i ON i.event_id = p.event_id
LEFT JOIN rca_results r ON r.event_id = p.event_id
LEFT JOIN incident_pipeline pl ON pl.event_id = p.event_id
"""


def init_db(engine: Engine | None = None) -> None:
    engine = engine or get_engine()
    Base.metadata.create_all(engine)                 # creates missing tables only; never touches existing data
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            conn.execute(text(f"CREATE OR REPLACE VIEW incident_overview AS {OVERVIEW_VIEW_SQL}"))
        else:                                        # sqlite (tests) has no CREATE OR REPLACE VIEW
            conn.execute(text("DROP VIEW IF EXISTS incident_overview"))
            conn.execute(text(f"CREATE VIEW incident_overview AS {OVERVIEW_VIEW_SQL}"))


def get_session_factory() -> sessionmaker[Session]:
    """Return the shared session factory (use this instead of the private _factory)."""
    return _factory()


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    with _factory()() as s:
        yield s

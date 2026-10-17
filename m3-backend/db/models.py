"""PostgreSQL schema. JSONB on Postgres (indexable), plain JSON elsewhere (SQLite for quick local tests)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class IngestBatch(Base):
    """One row per ingest call/file: the data-quality log (what came in, what was kept, what was rejected)."""
    __tablename__ = "ingest_batches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source: Mapped[str] = mapped_column(String(255))
    received: Mapped[int] = mapped_column(Integer)
    accepted: Mapped[int] = mapped_column(Integer)
    quarantined: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RawEvent(Base):
    """Untouched payload as received (replay / audit)."""
    __tablename__ = "raw_events"
    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(36), index=True)
    payload: Mapped[dict] = mapped_column(JSONType)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProcessedEvent(Base):
    """Output of M3 -> consumed by M4 (risk model / priority) and M5 (RAG context)."""
    __tablename__ = "processed_events"
    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    batch_id: Mapped[str] = mapped_column(String(36), index=True)
    system: Mapped[str] = mapped_column(String(8), index=True)
    subsystem: Mapped[str] = mapped_column(String(32), index=True)
    job_name: Mapped[str] = mapped_column(String(8))
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    error_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="OPEN", index=True)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    features: Mapped[dict] = mapped_column(JSONType)
    context: Mapped[dict] = mapped_column(JSONType)
    labels: Mapped[dict | None] = mapped_column(JSONType, nullable=True)   # training only (risk_score, split, ...)
    split: Mapped[str | None] = mapped_column(String(8), nullable=True, index=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QuarantineEvent(Base):
    """Rejected records + why. Nothing is silently dropped."""
    __tablename__ = "quarantine_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[str] = mapped_column(String(36), index=True)
    stage: Mapped[str] = mapped_column(String(16))
    incident_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    errors: Mapped[list] = mapped_column(JSONType)
    payload: Mapped[dict] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IncidentResult(Base):
    """M4 output (guide 8.3): anomaly detection + severity for one event."""
    __tablename__ = "incident_results"
    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    incident_type: Mapped[str] = mapped_column(String(32), index=True)
    anomaly_score: Mapped[float] = mapped_column(Float)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    extra: Mapped[dict | None] = mapped_column(JSONType, nullable=True)      # any extra M4 fields (risk_score, model version...)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RcaResult(Base):
    """M5 output (guide 8.4): root cause, evidence, impact, recommendation, confidence."""
    __tablename__ = "rca_results"
    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    root_cause: Mapped[str] = mapped_column(Text)
    evidence: Mapped[list] = mapped_column(JSONType)
    impact: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommended_action: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IncidentPipeline(Base):
    """Where each incident is in the M3 -> M4 -> M5 chain. Lets us retry failures without losing the event."""
    __tablename__ = "incident_pipeline"
    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(16), index=True)      # RECEIVED PROCESSING M4_FAILED M5_FAILED COMPLETE
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


Index("ix_processed_type_time", ProcessedEvent.event_type, ProcessedEvent.event_time)

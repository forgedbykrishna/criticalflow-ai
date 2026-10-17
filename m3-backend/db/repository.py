"""Persistence. Idempotent: re-sending the same event_id updates the row instead of duplicating it."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Iterable

from sqlalchemy import insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from db.models import IngestBatch, ProcessedEvent, QuarantineEvent, RawEvent, utcnow
from processing.pipeline import PipelineResult

CHUNK = 1000


def _upsert(session: Session, model, rows: list[dict[str, Any]], pk: str) -> None:
    if not rows:
        return
    dialect = session.get_bind().dialect.name
    ins = {"postgresql": pg_insert, "sqlite": sqlite_insert}.get(dialect)
    for i in range(0, len(rows), CHUNK):
        chunk = rows[i:i + CHUNK]
        if ins is None:                                   # generic fallback
            for r in chunk:
                session.merge(model(**r))
            continue
        stmt = ins(model).values(chunk)
        update = {c: stmt.excluded[c] for c in chunk[0] if c != pk}
        session.execute(stmt.on_conflict_do_update(index_elements=[pk], set_=update))


def save_result(session: Session, res: PipelineResult, source: str) -> str:
    """Store raw + processed + quarantine + batch log in ONE transaction."""
    batch_id = str(uuid.uuid4())
    now = utcnow()
    session.add(IngestBatch(id=batch_id, source=source[:255], received=res.received,
                            accepted=len(res.processed), quarantined=len(res.rejected), created_at=now))
    _upsert(session, RawEvent, [
        {"event_id": p.event_id, "batch_id": batch_id, "payload": p.raw, "ingested_at": now}
        for p in res.processed], "event_id")
    _upsert(session, ProcessedEvent, [
        {"event_id": p.event_id, "batch_id": batch_id, "system": p.system, "subsystem": p.subsystem,
         "job_name": p.job_name, "event_type": p.event_type, "error_code": p.error_code, "status": p.status,
         "event_time": datetime.fromisoformat(p.timestamp.replace("Z", "+00:00")),
         "features": p.features, "context": p.context, "labels": p.labels,
         "split": (p.labels or {}).get("split"), "processed_at": now}
        for p in res.processed], "event_id")
    for i in range(0, len(res.rejected), CHUNK):
        session.execute(insert(QuarantineEvent), [
            {"batch_id": batch_id, "stage": r.stage, "incident_id": r.incident_id, "errors": r.errors,
             "payload": r.payload, "created_at": now} for r in res.rejected[i:i + CHUNK]])
    session.commit()
    return batch_id


def query_processed(session: Session, *, limit: int = 100, offset: int = 0, status: str | None = None,
                    event_type: str | None = None, system: str | None = None, split: str | None = None,
                    since: datetime | None = None) -> list[ProcessedEvent]:
    q = select(ProcessedEvent).order_by(ProcessedEvent.event_time.desc(), ProcessedEvent.event_id)
    for col, val in ((ProcessedEvent.status, status), (ProcessedEvent.event_type, event_type),
                     (ProcessedEvent.system, system), (ProcessedEvent.split, split)):
        if val:
            q = q.where(col == val)
    if since:
        q = q.where(ProcessedEvent.event_time >= since)
    return list(session.scalars(q.limit(limit).offset(offset)))


def to_contract(p: ProcessedEvent) -> dict[str, Any]:
    return {"event_id": p.event_id, "system": p.system, "event_type": p.event_type, "error_code": p.error_code,
            "features": p.features, "status": p.status, "timestamp": p.event_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "subsystem": p.subsystem, "job_name": p.job_name, "context": p.context}

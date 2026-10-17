"""The M3 orchestration loop for ONE incident (leader's diagram steps 2-6):
   processed event -> M4 predict -> save -> M5 explain -> save -> status COMPLETE.
A failure at any stage keeps everything saved so far and records WHY, so it can be retried (reprocess)."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from db.models import IncidentPipeline, IncidentResult, ProcessedEvent, RcaResult, utcnow
from db.repository import to_contract
from orchestration.clients import AIServiceError, explain, predict

log = logging.getLogger("cf.orchestrator")


def _upsert(session: Session, model, event_id: str, **cols: Any) -> None:
    now = utcnow()
    row = session.get(model, event_id)
    if row is None:
        session.add(model(event_id=event_id, created_at=now, updated_at=now, **cols))
    else:
        for k, v in cols.items():
            setattr(row, k, v)
        row.updated_at = now


def mark_received(session: Session, event_id: str) -> None:
    now = utcnow()
    row = session.get(IncidentPipeline, event_id)
    if row is None:
        session.add(IncidentPipeline(event_id=event_id, status="RECEIVED", attempts=0, created_at=now, updated_at=now))
    else:
        row.status, row.error, row.updated_at = "RECEIVED", None, now
    session.commit()


def _set(session: Session, event_id: str, status: str, error: str | None = None) -> None:
    row = session.get(IncidentPipeline, event_id)
    row.status, row.error, row.updated_at = status, (error or None), utcnow()
    session.commit()


def run_orchestration(session: Session, event_id: str) -> str:
    """Returns the final pipeline status."""
    ev = session.get(ProcessedEvent, event_id)
    if ev is None:
        raise LookupError(f"event {event_id} not found")
    if session.get(IncidentPipeline, event_id) is None:
        mark_received(session, event_id)
    row = session.get(IncidentPipeline, event_id)
    row.status, row.error, row.attempts, row.updated_at = "PROCESSING", None, (row.attempts or 0) + 1, utcnow()
    # every run replaces the previous M4/M5 answers, so a stale prediction is never shown next to a new explanation
    session.execute(delete(IncidentResult).where(IncidentResult.event_id == event_id))
    session.execute(delete(RcaResult).where(RcaResult.event_id == event_id))
    session.commit()
    event = to_contract(ev)

    try:
        pred = predict(event)
        _upsert(session, IncidentResult, event_id, incident_type=pred["incident_type"],
                anomaly_score=pred["anomaly_score"], severity=pred["severity"], extra=pred["extra"])
        session.commit()
    except Exception as exc:                                   # noqa: BLE001 - never lose the event, record why
        return _fail(session, event_id, "M4_FAILED", exc)

    try:
        expl = explain(event, pred)
        _upsert(session, RcaResult, event_id, root_cause=expl["root_cause"], evidence=expl["evidence"],
                impact=expl["impact"], recommended_action=expl["recommended_action"],
                confidence=expl["confidence"], extra=expl["extra"])
        session.commit()
    except Exception as exc:                                   # noqa: BLE001
        return _fail(session, event_id, "M5_FAILED", exc)

    _set(session, event_id, "COMPLETE")
    log.info("incident %s COMPLETE (severity=%s)", event_id, pred["severity"])
    return "COMPLETE"


def _fail(session: Session, event_id: str, status: str, exc: Exception) -> str:
    session.rollback()
    msg = str(exc) if isinstance(exc, AIServiceError) else f"unexpected {type(exc).__name__}: {exc}"
    log.error("incident %s %s: %s", event_id, status, msg)
    _set(session, event_id, status, msg[:1000])
    return status

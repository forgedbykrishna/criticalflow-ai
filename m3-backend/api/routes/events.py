from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.deps import require_api_key
from db.models import IncidentPipeline, ProcessedEvent, QuarantineEvent
from db.repository import query_processed, to_contract
from db.session import get_session

router = APIRouter(prefix="/api/v1", tags=["events"], dependencies=[Depends(require_api_key)])


@router.get("/events/processed", summary="Processed events for M4/M5 (filters + paging)")
def list_processed(limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
                   status: str | None = None, event_type: str | None = None, system: str | None = None,
                   split: str | None = None, since: datetime | None = None,
                   session: Session = Depends(get_session)):
    rows = query_processed(session, limit=limit, offset=offset, status=status, event_type=event_type,
                           system=system, split=split, since=since)
    return {"count": len(rows), "events": [to_contract(r) for r in rows]}


@router.get("/events/processed/{event_id}")
def get_processed(event_id: str, session: Session = Depends(get_session)):
    row = session.get(ProcessedEvent, event_id)
    if not row:
        raise HTTPException(404, "event not found")
    return {**to_contract(row), "labels": row.labels}


@router.get("/events/quarantine", summary="Rejected records and why")
def list_quarantine(limit: int = Query(100, ge=1, le=1000), session: Session = Depends(get_session)):
    rows = session.scalars(select(QuarantineEvent).order_by(QuarantineEvent.id.desc()).limit(limit))
    return [{"id": r.id, "batch_id": r.batch_id, "stage": r.stage, "incident_id": r.incident_id,
             "errors": r.errors, "created_at": r.created_at} for r in rows]


@router.get("/stats", summary="Counts for a quick data-quality check")
def stats(session: Session = Depends(get_session)):
    by_type = dict(session.execute(select(ProcessedEvent.event_type, func.count()).group_by(ProcessedEvent.event_type)).all())
    by_pipeline = dict(session.execute(select(IncidentPipeline.status, func.count()).group_by(IncidentPipeline.status)).all())
    return {"processed": sum(by_type.values()), "by_event_type": by_type, "by_pipeline_status": by_pipeline,
            "quarantined": session.scalar(select(func.count()).select_from(QuarantineEvent))}

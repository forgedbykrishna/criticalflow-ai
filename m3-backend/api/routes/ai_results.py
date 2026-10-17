"""Store and serve M4 (incident) and M5 (RCA) results in PostgreSQL. Upsert on event_id (re-send = update)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import require_api_key
from api.schemas.ai_results import IncidentResultIn, RcaResultIn
from db.models import IncidentPipeline, IncidentResult, ProcessedEvent, RcaResult, utcnow
from db.repository import to_contract
from db.session import get_session

router = APIRouter(prefix="/api/v1", tags=["ai-results"], dependencies=[Depends(require_api_key)])

INCIDENT_COLS = {"event_id", "incident_type", "anomaly_score", "severity"}
RCA_COLS = {"event_id", "root_cause", "evidence", "impact", "recommended_action", "confidence"}


def _split(model_in, cols: set[str]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    data = model_in.model_dump()
    core = {k: v for k, v in data.items() if k in cols}
    extra = {k: v for k, v in data.items() if k not in cols} or None
    return core, extra


def _save(session: Session, model, items: list, cols: set[str]) -> dict[str, Any]:
    ids = [i.event_id for i in items]
    known = set(session.scalars(select(ProcessedEvent.event_id).where(ProcessedEvent.event_id.in_(ids))))
    saved, unknown = 0, []
    now = utcnow()
    for item in items:
        if item.event_id not in known:           # keeps DB consistent: result must belong to a processed event
            unknown.append(item.event_id)
            continue
        core, extra = _split(item, cols)
        row = session.get(model, item.event_id)
        if row is None:
            session.add(model(**core, extra=extra, created_at=now, updated_at=now))
        else:
            for k, v in core.items():
                setattr(row, k, v)
            row.extra, row.updated_at = extra, now
        saved += 1
    session.commit()
    return {"received": len(items), "saved": saved, "unknown_event_ids": unknown}


def _as_list(body: Any, schema):
    items = body["results"] if isinstance(body, dict) and isinstance(body.get("results"), list) else \
        body if isinstance(body, list) else [body]
    try:
        return [schema.model_validate(i) for i in items]
    except Exception as exc:                      # pydantic ValidationError -> readable 422
        raise HTTPException(422, str(exc)) from exc


@router.post("/ai/incidents", summary="M4 posts anomaly score + severity (one, list, or {'results': [...]})")
def post_incidents(body: Any = Body(...), session: Session = Depends(get_session)):
    return _save(session, IncidentResult, _as_list(body, IncidentResultIn), INCIDENT_COLS)


@router.post("/rca", summary="M5 posts root cause / evidence / recommendation (one, list, or {'results': [...]})")
def post_rca(body: Any = Body(...), session: Session = Depends(get_session)):
    return _save(session, RcaResult, _as_list(body, RcaResultIn), RCA_COLS)


def _incident_dict(r: IncidentResult) -> dict[str, Any]:
    return {"event_id": r.event_id, "incident_type": r.incident_type, "anomaly_score": r.anomaly_score,
            "severity": r.severity, **(r.extra or {})}


def _rca_dict(r: RcaResult) -> dict[str, Any]:
    return {"event_id": r.event_id, "root_cause": r.root_cause, "evidence": r.evidence, "impact": r.impact,
            "recommended_action": r.recommended_action, "confidence": r.confidence, **(r.extra or {})}


@router.get("/ai/incidents", summary="List M4 results (filter by severity)")
def list_incidents(severity: str | None = None, limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
                   session: Session = Depends(get_session)):
    q = select(IncidentResult).order_by(IncidentResult.updated_at.desc())
    if severity:
        q = q.where(IncidentResult.severity == severity.upper())
    return [_incident_dict(r) for r in session.scalars(q.limit(limit).offset(offset))]


@router.get("/rca/{event_id}", summary="One M5 result")
def get_rca(event_id: str, session: Session = Depends(get_session)):
    row = session.get(RcaResult, event_id)
    if not row:
        raise HTTPException(404, "no RCA stored for this event")
    return _rca_dict(row)


@router.get("/incidents/{event_id}/full",
            summary="Everything for one event: processed data + M4 result + M5 RCA (for dashboard / M1 / M6)")
def full_incident(event_id: str, session: Session = Depends(get_session)):
    ev = session.get(ProcessedEvent, event_id)
    if not ev:
        raise HTTPException(404, "event not found")
    inc, rca = session.get(IncidentResult, event_id), session.get(RcaResult, event_id)
    pl = session.get(IncidentPipeline, event_id)
    return {"event": to_contract(ev), "incident": _incident_dict(inc) if inc else None,
            "rca": _rca_dict(rca) if rca else None,
            "pipeline": {"status": pl.status, "error": pl.error, "attempts": pl.attempts} if pl else None}

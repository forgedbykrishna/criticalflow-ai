"""Leader's flow:  M2 --POST /incident--> M3 (validate+clean+store) --> M4 /predict --> M5 /explain --> PostgreSQL."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import require_api_key
from api.routes.ai_results import _incident_dict, _rca_dict
from config.settings import get_settings
from db.models import IncidentPipeline, IncidentResult, ProcessedEvent, RcaResult
from db.repository import save_result
from db.session import get_session, get_session_factory
from ingestion.field_map import load_field_map
from orchestration.service import mark_received, run_orchestration
from processing.contract import load_contract
from processing.pipeline import Rejected, run_pipeline

log = logging.getLogger("cf.api")
router = APIRouter(dependencies=[Depends(require_api_key)], tags=["incident"])


def _extract(body: Any) -> dict[str, Any]:
    """Accepts the flat event contract OR the diagram's wrapper {"incident_id": "...", "data": {...}}."""
    if not isinstance(body, dict):
        raise HTTPException(422, "Body must be one JSON object (an incident)")
    data = body.get("data")
    if isinstance(data, dict) and "incident_id" in body:
        return {**data, "incident_id": body["incident_id"]}
    return body


def _background(event_id: str) -> None:
    try:
        with get_session_factory()() as session:
            run_orchestration(session, event_id)
    except Exception:                                  # noqa: BLE001
        log.exception("background orchestration crashed for %s", event_id)


def _result(session: Session, event_id: str, status: str) -> dict[str, Any]:
    pl = session.get(IncidentPipeline, event_id)
    inc, rca = session.get(IncidentResult, event_id), session.get(RcaResult, event_id)
    return {"incident_id": event_id, "pipeline_status": status, "error": pl.error if pl else None,
            "prediction": _incident_dict(inc) if inc else None, "explanation": _rca_dict(rca) if rca else None}


@router.post("/incident", status_code=202, summary="M2 sends an incident here (starts M3 -> M4 -> M5)")
@router.post("/api/v1/incident", status_code=202, include_in_schema=False)
def create_incident(response: Response, background: BackgroundTasks, body: Any = Body(...),
                    wait: bool = Query(False, description="true = wait for M4+M5 and return the full result"),
                    session: Session = Depends(get_session)):
    """Validates + cleans + stores the incident, then calls M4 and M5 and stores their answers.
    Default: answers 202 immediately and finishes M4/M5 in the background (poll GET /api/v1/incidents/{id}/full).
    Invalid incidents are quarantined and answered with 422 + the reasons."""
    s = get_settings()
    res = run_pipeline([_extract(body)], field_map=load_field_map(s.field_map_path))
    batch_id = save_result(session, res, "api:incident")
    if res.rejected:
        raise HTTPException(422, detail={"message": "incident rejected and quarantined", "batch_id": batch_id,
                                         "errors": res.rejected[0].errors})
    event_id = res.processed[0].event_id
    mark_received(session, event_id)
    if wait:
        status = run_orchestration(session, event_id)
        response.status_code = 200
        return _result(session, event_id, status)
    background.add_task(_background, event_id)
    return {"incident_id": event_id, "pipeline_status": "RECEIVED", "batch_id": batch_id}


@router.post("/api/v1/incidents", status_code=201, tags=["incident"],
             summary="M2 handoff endpoint: 201 new, 200 repeat (idempotent), 422 invalid, 401 bad token")
def m2_incident(response: Response, background: BackgroundTasks, body: Any = Body(...),
                session: Session = Depends(get_session)):
    """Same pipeline as POST /incident, with the status codes M2 agreed on (contract 1.0.0).
    A repeated incident_id is acknowledged with 200 and is NOT stored or sent to M4/M5 a second time."""
    s = get_settings()
    raw = _extract(body)
    res = run_pipeline([raw], field_map=load_field_map(s.field_map_path))
    unknown = sorted(set(raw) - set(load_contract().fields)) if not res.rejected else []
    if unknown:                                        # contract 1.0.0 is strict (no unknown fields); the generic pipeline just drops them
        res.processed = []
        res.rejected.append(Rejected(0, "validation", [{"field": k, "message": "unknown field not allowed by contract 1.0.0"}
                                                       for k in unknown], raw, raw.get("incident_id")))
    if res.rejected:
        batch_id = save_result(session, res, "api:m2")
        raise HTTPException(422, detail={"message": "incident rejected and quarantined", "batch_id": batch_id,
                                         "errors": res.rejected[0].errors})
    event_id = res.processed[0].event_id
    if session.get(ProcessedEvent, event_id) is not None:
        response.status_code = 200
        return {"incident_id": event_id, "created": False}
    batch_id = save_result(session, res, "api:m2")
    mark_received(session, event_id)
    background.add_task(_background, event_id)
    return {"incident_id": event_id, "created": True, "pipeline_status": "RECEIVED", "batch_id": batch_id}


@router.post("/api/v1/incidents/{event_id}/reprocess", tags=["incident"],
             summary="Re-run M4 + M5 for one incident (e.g. after M4/M5 was down)")
def reprocess(event_id: str, session: Session = Depends(get_session)):
    try:
        status = run_orchestration(session, event_id)
    except LookupError:
        raise HTTPException(404, "event not found") from None
    return _result(session, event_id, status)


@router.post("/api/v1/incidents/reprocess-failed", tags=["incident"],
             summary="Retry every incident stuck in M4_FAILED / M5_FAILED (max 50 per call)")
def reprocess_failed(session: Session = Depends(get_session)):
    ids = list(session.scalars(select(IncidentPipeline.event_id)
                               .where(IncidentPipeline.status.in_(["M4_FAILED", "M5_FAILED"])).limit(50)))
    out = {i: run_orchestration(session, i) for i in ids}
    return {"retried": len(ids), "results": out}

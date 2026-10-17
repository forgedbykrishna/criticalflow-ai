from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from api.deps import require_api_key
from api.schemas.responses import IngestResponse, RejectedItem
from config.settings import get_settings
from db.repository import save_result
from db.session import get_session
from ingestion.field_map import load_field_map
from ingestion.readers import read_records, supported_formats
from processing.pipeline import PipelineResult, run_pipeline

router = APIRouter(prefix="/api/v1/ingest", tags=["ingest"], dependencies=[Depends(require_api_key)])
ECHO_LIMIT = 100          # echo processed events back only for small requests


def _respond(session: Session, res: PipelineResult, source: str) -> IngestResponse:
    batch_id = save_result(session, res, source)
    return IngestResponse(
        batch_id=batch_id, received=res.received, accepted=len(res.processed), quarantined=len(res.rejected),
        duplicates_in_batch=res.duplicates,
        processed=[p.as_contract() for p in res.processed] if len(res.processed) <= ECHO_LIMIT else None,
        rejected=[RejectedItem(index=r.index, stage=r.stage, incident_id=r.incident_id, errors=r.errors)
                  for r in res.rejected[:ECHO_LIMIT]])


@router.post("/events", response_model=IngestResponse,
             summary="Receive one event, a list of events, or {\"events\": [...]} (JSON)")
def ingest_events(body: Any = Body(...), session: Session = Depends(get_session)) -> IngestResponse:
    """M2 posts events here. Malformed records do NOT fail the request: they are quarantined and reported."""
    s = get_settings()
    if isinstance(body, dict) and isinstance(body.get("events"), list):
        records = body["events"]
    elif isinstance(body, dict):
        records = [body]
    elif isinstance(body, list):
        records = body
    else:
        raise HTTPException(422, "Body must be an event object, a list of events, or {'events': [...]}")
    if not records:
        raise HTTPException(422, "No events supplied")
    if len(records) > s.max_batch_size:
        raise HTTPException(413, f"Batch too large (max {s.max_batch_size}); use /file or split the request")
    res = run_pipeline(records, field_map=load_field_map(s.field_map_path))
    return _respond(session, res, "api:json")


@router.post("/file", response_model=IngestResponse,
             summary=f"Upload a dataset file (formats: {', '.join(supported_formats())}; .gz ok)")
def ingest_file(file: UploadFile = File(...), format: str | None = Query(default=None, description="override auto-detect"),
                session: Session = Depends(get_session)) -> IngestResponse:
    s = get_settings()
    try:
        res = run_pipeline(read_records(file.file, format, filename=file.filename or ""),
                           field_map=load_field_map(s.field_map_path))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return _respond(session, res, f"file:{file.filename}")

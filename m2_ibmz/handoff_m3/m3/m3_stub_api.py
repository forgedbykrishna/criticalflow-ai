"""In-memory stand-in for M3's FastAPI service (same contract + status codes) for local testing.
   uvicorn m3_handoff.m3_stub_api:app --port 8000"""
from __future__ import annotations

import os

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status

from m3.models import IBMZEventPayload

app = FastAPI(title="CriticalFlow AI API (stub)")
STORE: dict[str, dict] = {}
API_TOKEN = os.environ.get("API_TOKEN")


def check_token(authorization: str | None = Header(default=None)) -> None:
    if API_TOKEN and authorization != f"Bearer {API_TOKEN}":
        raise HTTPException(status_code=401, detail="invalid token")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "stored": len(STORE)}


@app.post("/api/v1/incidents", status_code=status.HTTP_201_CREATED, dependencies=[Depends(check_token)])
def create_incident(payload: IBMZEventPayload, response: Response) -> dict:
    if payload.incident_id in STORE:
        response.status_code = status.HTTP_200_OK
        return {"incident_id": payload.incident_id, "created": False}
    STORE[payload.incident_id] = payload.model_dump(mode="json")
    return {"incident_id": payload.incident_id, "created": True}


@app.get("/api/v1/incidents", dependencies=[Depends(check_token)])
def list_incidents() -> list[dict]:
    return list(STORE.values())

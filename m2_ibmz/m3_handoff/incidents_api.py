"""M3 production endpoint (PostgreSQL). Requires: sqlalchemy[asyncio], asyncpg, DATABASE_URL, incidents.sql applied."""
from __future__ import annotations

import os

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from m3_handoff.models import IBMZEventPayload

engine = create_async_engine(os.environ.get(
    "DATABASE_URL", "postgresql+asyncpg://criticalflow:criticalflow@localhost:5432/criticalflow"))
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
API_TOKEN = os.environ.get("API_TOKEN")


async def get_session():
    async with SessionLocal() as session:
        yield session


def check_token(authorization: str | None = Header(default=None)) -> None:
    if API_TOKEN and authorization != f"Bearer {API_TOKEN}":
        raise HTTPException(status_code=401, detail="invalid token")


app = FastAPI(title="CriticalFlow AI API")

INSERT_SQL = text("""
INSERT INTO incidents (incident_id, schema_version, event_ts, system_id, subsystem, job_name, job_id,
  step_name, completion_status, return_code, abend_code, primary_message_id, cpu_utilization_pct,
  error_rate_pct, transaction_volume_per_hr, recent_deployment_flag, raw_log_snippet)
VALUES (:incident_id, :schema_version, :timestamp, :system_id, :subsystem, :job_name, :job_id,
  :step_name, :completion_status, :return_code, :abend_code, :primary_message_id, :cpu_utilization_pct,
  :error_rate_pct, :transaction_volume_per_hr, :recent_deployment_flag, :raw_log_snippet)
ON CONFLICT (incident_id) DO NOTHING RETURNING id
""")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/v1/incidents", status_code=status.HTTP_201_CREATED, dependencies=[Depends(check_token)])
async def create_incident(payload: IBMZEventPayload, response: Response,
                          session: AsyncSession = Depends(get_session)) -> dict:
    row = (await session.execute(INSERT_SQL, payload.model_dump())).first()
    await session.commit()
    if row is None:
        response.status_code = status.HTTP_200_OK
        return {"incident_id": payload.incident_id, "created": False}
    return {"incident_id": payload.incident_id, "created": True, "id": row[0]}

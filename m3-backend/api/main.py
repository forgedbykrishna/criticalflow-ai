"""Run:  uvicorn api.main:app --reload      (docs at /docs)"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from config.settings import get_settings
from api.routes import ai_results, events, incident, ingest
from db.session import get_engine, init_db

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    st = get_settings()
    for name, url in (("M4", st.m4_url), ("M5", st.m5_url)):
        if not url:
            logging.getLogger("cf.api").warning("%s_URL not set -> using built-in MOCK %s (dev only)", name, name)
    yield


app = FastAPI(title="CriticalFlow AI - M3 Data Pipeline API", version="1.0.0", lifespan=lifespan)
app.include_router(ingest.router)
app.include_router(events.router)
app.include_router(ai_results.router)
app.include_router(incident.router)


@app.get("/health", tags=["ops"])
def health():
    with get_engine().connect() as c:
        c.execute(text("SELECT 1"))
    st = get_settings()
    return {"status": "ok", "m4": st.m4_url or "mock", "m5": st.m5_url or "mock"}

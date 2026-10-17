"""Stand-in M5 service for local tests:  uvicorn mocks.m5_mock:app --port 8002"""
from fastapi import Body, FastAPI

from orchestration.mock import mock_explain

app = FastAPI(title="MOCK M5 explanation")


@app.post("/explain")
def explain(payload: dict = Body(...)):
    return mock_explain(payload)

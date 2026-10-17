"""Stand-in M4 service for local tests:  uvicorn mocks.m4_mock:app --port 8001"""
from fastapi import Body, FastAPI

from orchestration.mock import mock_predict

app = FastAPI(title="MOCK M4 prediction")


@app.post("/predict")
def predict(payload: dict = Body(...)):
    return mock_predict(payload)

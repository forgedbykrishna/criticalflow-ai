from pathlib import Path
from typing import Optional

import joblib
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

# 1. FastAPI app setup
app = FastAPI(title="CriticalFlow M4 Risk Engine", version="1.0.0")

# 2. Model pipeline loading
MODEL_PATH = Path(__file__).resolve().parent / "models" / "m4_pipeline.joblib"
if not MODEL_PATH.exists():
    raise RuntimeError(f"M4 model artifact not found at {MODEL_PATH}")

artifacts = joblib.load(MODEL_PATH)
risk_model = artifacts.get("risk_model")
sev_model = artifacts.get("sev_model")
type_model = artifacts.get("type_model")

if risk_model is None or sev_model is None or type_model is None:
    raise RuntimeError("M4 model artifact is corrupted or missing expected estimators")


# 3. Input and Output Schemas
class IncidentRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    incident_id: str = Field(..., min_length=1, description="Unique incident identifier")
    system_id: Optional[str] = None
    subsystem: Optional[str] = None
    completion_status: Optional[str] = None
    return_code: Optional[float] = None
    abend_code: Optional[str] = None
    primary_message_id: Optional[str] = None
    cpu_utilization_pct: Optional[float] = None
    error_rate_pct: Optional[float] = None
    transaction_volume_per_hr: Optional[float] = None
    recent_deployment_flag: Optional[bool] = False


class PredictionResponse(BaseModel):
    incident_id: str
    anomaly_score: float
    risk_score: float
    severity: str
    incident_type: str
    model_version: str = "v1.0"


# 4. Prediction Logic
def run_prediction(data: dict) -> dict:
    incident_id = data.get("incident_id")
    if not incident_id or not str(incident_id).strip():
        raise HTTPException(status_code=422, detail="incident_id must be a non-empty string")

    row = {
        "system_id": data.get("system_id"),
        "subsystem": data.get("subsystem"),
        "completion_status": data.get("completion_status"),
        "return_code": data.get("return_code"),
        "abend_code": data.get("abend_code"),
        "primary_message_id": data.get("primary_message_id"),
        "cpu_utilization_pct": data.get("cpu_utilization_pct"),
        "error_rate_pct": data.get("error_rate_pct"),
        "transaction_volume_per_hr": data.get("transaction_volume_per_hr"),
        "recent_deployment_flag": 1.0 if data.get("recent_deployment_flag") else 0.0,
    }
    df_single = pd.DataFrame([row])

    try:
        risk_pred = float(risk_model.predict(df_single)[0])
        sev_pred = str(sev_model.predict(df_single)[0])
        type_pred = str(type_model.predict(df_single)[0])
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Model prediction failed: {exc}") from exc

    anomaly_score = round(min(max(risk_pred * 0.95, 0.0), 1.0), 3)

    return {
        "incident_id": str(incident_id).strip(),
        "anomaly_score": anomaly_score,
        "risk_score": round(risk_pred, 3),
        "severity": sev_pred,
        "incident_type": type_pred,
        "model_version": "v1.0",
    }


# 5. Routes
@app.get("/health")
def health():
    if risk_model is None or sev_model is None or type_model is None:
        raise HTTPException(status_code=503, detail="Models not loaded")
    return {"status": "healthy", "module": "M4", "model_version": "v1.0"}


@app.post("/predict", response_model=PredictionResponse)
def predict_incident_post(payload: IncidentRequest):
    return run_prediction(payload.model_dump())


@app.get("/predict", response_model=PredictionResponse)
def predict_incident_get(
    incident_id: str = Query(..., min_length=1),
    system_id: Optional[str] = None,
    subsystem: Optional[str] = None,
    completion_status: Optional[str] = None,
    return_code: Optional[float] = None,
    abend_code: Optional[str] = None,
    primary_message_id: Optional[str] = None,
    cpu_utilization_pct: Optional[float] = None,
    error_rate_pct: Optional[float] = None,
    transaction_volume_per_hr: Optional[float] = None,
    recent_deployment_flag: Optional[bool] = False,
):
    query_data = {
        "incident_id": incident_id,
        "system_id": system_id,
        "subsystem": subsystem,
        "completion_status": completion_status,
        "return_code": return_code,
        "abend_code": abend_code,
        "primary_message_id": primary_message_id,
        "cpu_utilization_pct": cpu_utilization_pct,
        "error_rate_pct": error_rate_pct,
        "transaction_volume_per_hr": transaction_volume_per_hr,
        "recent_deployment_flag": recent_deployment_flag,
    }
    return run_prediction(query_data)
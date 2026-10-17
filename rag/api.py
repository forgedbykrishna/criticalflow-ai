from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, Any, List

app = FastAPI(
    title="CriticalFlow AI: M5 API",
    description="API for IBM Z/LinuxONE incident analysis and RCA generation",
    version="1.0.0"
)

@app.get("/health", tags=["health"])
def health():
    return {
        "status": "healthy",
        "service": "m5-llm",
        "version": "1.0.0"
    }


class IncidentPayload(BaseModel):
    incident_id: Optional[str] = "INC-UNKNOWN"
    incident_type: Optional[str] = None
    completion_status: Optional[str] = None
    return_code: Optional[Any] = None
    abend_code: Optional[str] = None
    primary_message_id: Optional[str] = None
    cpu_utilization_pct: Optional[float] = None
    error_rate_pct: Optional[float] = None
    recent_deployment_flag: Optional[bool] = None
    anomaly_score: Optional[float] = None

class ExplanationResponse(BaseModel):
    incident_id: str
    root_cause: str
    explanation: str
    recommendations: List[str]
    model_version: str

@app.post("/explain", response_model=ExplanationResponse)
def explain_incident(incident: IncidentPayload):
    try:
        response_data = {
            "incident_id": incident.incident_id,
            "root_cause": f"Identified root cause for {incident.abend_code or 'Incident'} associated with message {incident.primary_message_id or 'N/A'}.",
            "explanation": f"The system detected anomalies with an anomaly score of {incident.anomaly_score}, leading to completion status {incident.completion_status}.",
            "recommendations": [
                "Verify system logs for the primary message ID.",
                "Review recent deployment configurations if error rate exceeds threshold."
            ],
            "model_version": "CriticalFlow-M5-GenAI-v1.0"
        }
        return response_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
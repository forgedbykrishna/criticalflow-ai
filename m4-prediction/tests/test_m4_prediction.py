from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient

from api import app, MODEL_PATH, artifacts, risk_model, sev_model, type_model
from inference import predict_incident

client = TestClient(app)

REPRESENTATIVE_PAYLOAD = {
    "incident_id": "INC-20260930-JOB06340-PAYGATE4",
    "system_id": "SYSB",
    "subsystem": "PAYMENT-API",
    "completion_status": "CC",
    "return_code": 8.0,
    "abend_code": None,
    "primary_message_id": "IEF142I",
    "cpu_utilization_pct": 94.1,
    "error_rate_pct": 42.0,
    "transaction_volume_per_hr": 97300.0,
    "recent_deployment_flag": False,
}

EXPECTED_SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
EXPECTED_SCENARIOS = {"normal", "warning", "exhaustion", "jcl_error", "abend"}


def test_model_artifact_loading():
    """Verify that the model artifact exists, loads properly, and contains all required models."""
    assert MODEL_PATH.exists(), f"Model artifact missing at {MODEL_PATH}"
    assert "risk_model" in artifacts
    assert "sev_model" in artifacts
    assert "type_model" in artifacts
    assert "features" in artifacts
    assert risk_model is not None
    assert sev_model is not None
    assert type_model is not None


def test_inference_module_prediction():
    """Verify the inference.py predict_incident function produces valid schema and score bounds."""
    result = predict_incident(REPRESENTATIVE_PAYLOAD)

    assert result["incident_id"] == "INC-20260930-JOB06340-PAYGATE4"
    assert isinstance(result["anomaly_score"], float)
    assert 0.0 <= result["anomaly_score"] <= 1.0
    assert isinstance(result["risk_score"], float)
    assert result["severity"] in EXPECTED_SEVERITIES
    assert result["incident_type"] in EXPECTED_SCENARIOS
    assert result["model_version"] == "v1.0"


def test_api_health():
    """Verify the /health endpoint returns healthy status and model version."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["module"] == "M4"
    assert data["model_version"] == "v1.0"


def test_api_predict_post_valid():
    """Verify POST /predict with a representative incident payload."""
    response = client.post("/predict", json=REPRESENTATIVE_PAYLOAD)
    assert response.status_code == 200
    data = response.json()

    assert data["incident_id"] == REPRESENTATIVE_PAYLOAD["incident_id"]
    assert isinstance(data["anomaly_score"], float)
    assert 0.0 <= data["anomaly_score"] <= 1.0
    assert isinstance(data["risk_score"], float)
    assert data["severity"] in EXPECTED_SEVERITIES
    assert data["incident_type"] in EXPECTED_SCENARIOS
    assert data["model_version"] == "v1.0"


def test_api_predict_post_with_extra_m3_fields():
    """Verify POST /predict succeeds when M3 sends extra envelope fields (event_type, context, etc.)."""
    extended_payload = {
        **REPRESENTATIVE_PAYLOAD,
        "event_type": "JOB_FAILURE",
        "error_code": "RC_8",
        "raw_log_snippet": "IEF142I STEP01 COND CODE 0008",
        "features": {"cpu_missing": False},
        "context": {"job_name": "PAYGATE4"},
    }
    response = client.post("/predict", json=extended_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["incident_id"] == extended_payload["incident_id"]
    assert data["severity"] in EXPECTED_SEVERITIES


def test_api_predict_post_minimal_payload():
    """Verify POST /predict handles missing optional fields via imputer pipeline without crashing."""
    minimal_payload = {"incident_id": "INC-MINIMAL-001"}
    response = client.post("/predict", json=minimal_payload)
    assert response.status_code == 200
    data = response.json()
    assert data["incident_id"] == "INC-MINIMAL-001"
    assert 0.0 <= data["anomaly_score"] <= 1.0
    assert data["severity"] in EXPECTED_SEVERITIES


def test_api_predict_get_valid():
    """Verify GET /predict endpoint with query parameters."""
    response = client.get(
        "/predict",
        params={
            "incident_id": "INC-20260930-GET-TEST",
            "system_id": "SYSA",
            "return_code": 0.0,
            "completion_status": "CC",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["incident_id"] == "INC-20260930-GET-TEST"
    assert data["severity"] in EXPECTED_SEVERITIES


def test_api_predict_missing_incident_id():
    """Verify validation error when incident_id is omitted or blank."""
    # Omitted incident_id
    res_missing = client.post("/predict", json={"system_id": "SYSB"})
    assert res_missing.status_code == 422

    # Blank incident_id
    res_blank = client.post("/predict", json={"incident_id": "   "})
    assert res_blank.status_code == 422

    # GET without incident_id
    res_get_missing = client.get("/predict")
    assert res_get_missing.status_code == 422


def test_api_predict_invalid_data_types():
    """Verify validation error when data types cannot be coerced."""
    bad_payload = {
        "incident_id": "INC-TEST-002",
        "cpu_utilization_pct": "not_a_number",
    }
    response = client.post("/predict", json=bad_payload)
    assert response.status_code == 422


def test_api_predict_internal_error_handling():
    """Verify model execution exceptions return HTTP 500 rather than misleading success."""
    with patch.object(risk_model, "predict", side_effect=RuntimeError("Simulated estimator error")):
        response = client.post("/predict", json=REPRESENTATIVE_PAYLOAD)
        assert response.status_code == 500
        assert "Model prediction failed" in response.json()["detail"]

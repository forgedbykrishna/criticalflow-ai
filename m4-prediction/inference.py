from pathlib import Path
import joblib
import pandas as pd
import numpy as np

# Model load
MODEL_PATH = Path(__file__).resolve().parent / "models" / "m4_pipeline.joblib"
if not MODEL_PATH.exists():
    raise FileNotFoundError(f"M4 model artifact not found at: {MODEL_PATH}")

artifacts = joblib.load(MODEL_PATH)

risk_model = artifacts['risk_model']
sev_model = artifacts['sev_model']
type_model = artifacts['type_model']

def predict_incident(incident_dict: dict) -> dict:
    row = {
        'system_id': incident_dict.get('system_id'),
        'subsystem': incident_dict.get('subsystem'),
        'completion_status': incident_dict.get('completion_status'),
        'return_code': incident_dict.get('return_code'),
        'abend_code': incident_dict.get('abend_code'),
        'primary_message_id': incident_dict.get('primary_message_id'),
        'cpu_utilization_pct': incident_dict.get('cpu_utilization_pct'),
        'error_rate_pct': incident_dict.get('error_rate_pct'),
        'transaction_volume_per_hr': incident_dict.get('transaction_volume_per_hr'),
        'recent_deployment_flag': 1.0 if incident_dict.get('recent_deployment_flag') else 0.0
    }
    df_single = pd.DataFrame([row])
    
    risk_pred = float(risk_model.predict(df_single)[0])
    sev_pred = str(sev_model.predict(df_single)[0])
    type_pred = str(type_model.predict(df_single)[0])
    
    anomaly_score = round(min(max(risk_pred * 0.95, 0.0), 1.0), 3)

    return {
        "incident_id": incident_dict.get("incident_id", "UNKNOWN"),
        "anomaly_score": anomaly_score,
        "risk_score": round(risk_pred, 3),
        "severity": sev_pred,
        "incident_type": type_pred,
        "model_version": "v1.0"
    }

if __name__ == '__main__':
    # Test sample: Scenario 4 (Resource Exhaustion)
    sample_incident = {
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
        "recent_deployment_flag": False
    }
    output = predict_incident(sample_incident)
    print("\n--- M4 INFERENCE OUTPUT TEST ---")
    print(output)
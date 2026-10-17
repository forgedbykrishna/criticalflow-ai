"""Rule-based stand-ins for M4 and M5 so M3 can be developed, demoed and tested before the real services exist
(team guide: 'mock first'). Results are tagged source=mock. NOT real ML / LLM output."""
from __future__ import annotations

from typing import Any


def mock_predict(payload: dict[str, Any]) -> dict[str, Any]:
    f = payload.get("features") or {}
    score = 0.05
    if f.get("is_jcl_error"):
        score = 0.8
    elif f.get("is_abend"):
        score = 0.9
    elif (f.get("return_code") or 0) >= 8:
        score = 0.85
    elif (f.get("return_code") or 0) > 0:
        score = 0.35
    if f.get("cpu_critical") or f.get("error_rate_critical"):
        score = max(score, 0.9)
    elif f.get("cpu_high") or f.get("error_rate_high"):
        score = max(score, 0.6)
    if f.get("deploy_and_failure"):
        score = min(0.99, score + 0.05)
    severity = "CRITICAL" if score >= 0.8 else "HIGH" if score >= 0.55 else "MEDIUM" if score >= 0.2 else "LOW"
    return {"anomaly": score >= 0.55, "severity": severity, "confidence": round(score, 2), "model": "mock-rules"}


def mock_explain(payload: dict[str, Any]) -> dict[str, Any]:
    ev = payload.get("event") or {}
    pred = payload.get("prediction") or {}
    ctx = ev.get("context") or {}
    code = ev.get("error_code") or "none"
    evidence = [f"event_type={ev.get('event_type')}", f"error_code={code}"]
    if ctx.get("return_code") is not None:
        evidence.append(f"return_code={ctx['return_code']}")
    if ctx.get("recent_deployment_flag"):
        evidence.append("recent deployment on this system")
    sev = pred.get("severity", "UNKNOWN")
    return {
        "explanation": f"[MOCK] {ev.get('job_name')} on {ev.get('system')} finished as {ev.get('event_type')} "
                       f"({code}); predicted severity {sev}.",
        "root_cause": f"[MOCK] {ev.get('event_type')} with {code}",
        "evidence": evidence,
        "recommendations": ["Check job log", "Verify recent deployment", "Check dependent services"],
        "confidence": 0.5,
        "model": "mock-template",
    }

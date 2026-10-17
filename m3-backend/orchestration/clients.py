"""Calls to M4 (/predict) and M5 (/explain) + normalisation of their answers into our DB shape.

M3 sends the processed event (guide 8.2 fields + `incident_id` alias). M4/M5 answers are accepted in the shapes the
team diagram shows AND the shapes in the team guide (anomaly_score / evidence / recommended_action), so a small
naming difference on their side does not break M3. Anything unusable raises AIServiceError -> stage marked FAILED."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from config.settings import get_settings
from orchestration.mock import mock_explain, mock_predict

log = logging.getLogger("cf.orchestrator")
SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


class AIServiceError(Exception):
    def __init__(self, service: str, message: str):
        super().__init__(f"{service}: {message}")
        self.service = service


def _http() -> httpx.Client:          # tests replace this with a client using httpx.MockTransport
    return httpx.Client()


def _post(service: str, base_url: str, path: str, payload: dict[str, Any], timeout: float, retries: int) -> dict:
    url = base_url.rstrip("/") + path
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with _http() as client:
                r = client.post(url, json=payload, timeout=timeout)
            r.raise_for_status()
            data = r.json()
            if not isinstance(data, dict):
                raise ValueError("response is not a JSON object")
            return data
        except (httpx.HTTPError, ValueError) as exc:
            last = exc
            log.warning("%s call failed (attempt %d/%d): %s: %s", service, attempt + 1, retries + 1,
                        type(exc).__name__, exc)
    raise AIServiceError(service, f"{type(last).__name__}: {last}")


def _to_bool(v: Any) -> bool | None:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        if v.strip().lower() in {"true", "1", "yes", "y"}:
            return True
        if v.strip().lower() in {"false", "0", "no", "n"}:
            return False
    return None


def _unit(service: str, name: str, v: Any) -> float | None:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise AIServiceError(service, f"{name}={v!r} is not a number") from None
    if not 0 <= x <= 1:
        raise AIServiceError(service, f"{name}={x} must be between 0 and 1")
    return x


def normalize_prediction(raw: dict[str, Any], event_type: str, source: str) -> dict[str, Any]:
    sev = str(raw.get("severity", "")).strip().upper()
    if sev not in SEVERITIES:
        raise AIServiceError("M4", f"severity={raw.get('severity')!r} must be one of {sorted(SEVERITIES)}")
    conf, score = _unit("M4", "confidence", raw.get("confidence")), _unit("M4", "anomaly_score", raw.get("anomaly_score"))
    if conf is None and score is None:
        raise AIServiceError("M4", "response needs `anomaly_score` or `confidence`")
    return {"incident_type": str(raw.get("incident_type") or event_type), "severity": sev,
            "anomaly_score": score if score is not None else conf,
            "extra": {"anomaly": _to_bool(raw.get("anomaly")), "confidence": conf, "source": source, "raw": raw}}


def _rec_text(r: Any) -> str:
    """A recommendation is a string, or M5's {"priority": "High", "action": "..."} object."""
    if isinstance(r, dict):
        action = str(r.get("action") or r.get("recommendation") or r.get("text") or "").strip()
        prio = str(r.get("priority") or "").strip()
        return f"[{prio}] {action}" if action and prio else action
    return str(r)


def normalize_explanation(raw: dict[str, Any], source: str) -> dict[str, Any]:
    root = raw.get("root_cause")
    if not isinstance(root, str) or not root.strip():
        raise AIServiceError("M5", "response needs a non-empty `root_cause`")
    recs = raw.get("recommendations", raw.get("recommended_action"))
    recs = [recs] if isinstance(recs, str) else [_rec_text(r) for r in recs] if isinstance(recs, list) else []
    recs = [r for r in recs if r.strip()]
    if not recs:
        raise AIServiceError("M5", "response needs `recommendations` (list) or `recommended_action`")
    evidence = raw.get("evidence")
    return {"root_cause": root.strip(), "evidence": evidence if isinstance(evidence, list) else [],
            "impact": raw.get("impact") if isinstance(raw.get("impact"), str) else None,
            "recommended_action": "; ".join(recs), "confidence": _unit("M5", "confidence", raw.get("confidence")),
            "extra": {"explanation": raw.get("explanation"), "recommendations": recs, "source": source, "raw": raw}}


def predict(event: dict[str, Any]) -> dict[str, Any]:
    s = get_settings()
    # M4 reads the raw incident fields at the top level (system_id, completion_status, cpu_utilization_pct, ...),
    # so flatten the cleaned incident next to the processed-event fields instead of burying it in `context`.
    payload = {"incident_id": event["event_id"], **event, **(event.get("context") or {}), "system_id": event["system"]}
    if s.m4_url:
        raw, source = _post("M4", s.m4_url, s.m4_path, payload, s.m4_timeout_s, s.ai_retries), "http"
    else:
        raw, source = mock_predict(payload), "mock"
    return normalize_prediction(raw, event["event_type"], source)


def explain(event: dict[str, Any], prediction: dict[str, Any]) -> dict[str, Any]:
    s = get_settings()
    pred = {"anomaly": prediction["extra"]["anomaly"], "severity": prediction["severity"],
            "confidence": prediction["extra"]["confidence"], "anomaly_score": prediction["anomaly_score"]}
    ctx = event.get("context") or {}
    raw_pred = (prediction.get("extra") or {}).get("raw") or {}
    desc = (f"Job {event.get('job_name')} on {event.get('system')} finished as {event.get('event_type')}"
            f"{' with ' + str(event['error_code']) if event.get('error_code') else ''}"
            f"{' after a recent deployment' if ctx.get('recent_deployment_flag') else ''}.")
    # M5's UI/API reads ONE flat incident (incident fields + M4 scores + description); the nested copies stay for other M5s.
    payload = {"incident_id": event["event_id"], **ctx, "incident_type": prediction.get("incident_type") or event.get("event_type"),
               "risk_score": raw_pred.get("risk_score"), **pred, "description": desc,
               "event": event, "prediction": pred}
    if s.m5_url:
        raw, source = _post("M5", s.m5_url, s.m5_path, payload, s.m5_timeout_s, s.ai_retries), "http"
    else:
        raw, source = mock_explain(payload), "mock"
    return normalize_explanation(raw, source)
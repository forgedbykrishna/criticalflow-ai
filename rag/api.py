"""M5 GenAI Root Cause Analysis API.

M3 calls POST /explain with a flat incident payload and expects back:
  - root_cause (str, non-empty)
  - recommendations (list[str]) OR recommended_action (str)
  - evidence (list)
  - confidence (float 0-1, optional)

When a live LLM / vector DB is available, this module delegates to app.py / m5_pipeline.py.
When running standalone (mock mode), it constructs a deterministic but informative response.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

log = logging.getLogger("m5.api")

app = FastAPI(
    title="CriticalFlow AI: M5 GenAI RCA API",
    description="Root Cause Analysis and runbook recommendation engine for IBM Z® / LinuxONE incidents.",
    version="1.0.0",
)


# ============================================================
# HEALTH
# ============================================================

@app.get("/health", tags=["health"])
def health():
    return {
        "status": "healthy",
        "service": "m5-llm",
        "version": "1.0.0",
    }


# ============================================================
# SCHEMAS
# ============================================================

class IncidentPayload(BaseModel):
    incident_id: Optional[str] = "INC-UNKNOWN"
    incident_type: Optional[str] = None
    completion_status: Optional[str] = None
    return_code: Optional[Any] = None
    abend_code: Optional[str] = None
    primary_message_id: Optional[str] = None
    cpu_utilization_pct: Optional[float] = None
    error_rate_pct: Optional[float] = None
    transaction_volume_per_hr: Optional[float] = None
    recent_deployment_flag: Optional[bool] = None
    anomaly_score: Optional[float] = None
    risk_score: Optional[float] = None
    severity: Optional[str] = None
    description: Optional[str] = None
    event_type: Optional[str] = None
    job_name: Optional[str] = None
    # Allow extra fields from M3 envelope without raising an error.
    model_config = {"extra": "ignore"}


class ExplanationResponse(BaseModel):
    incident_id: str
    root_cause: str
    explanation: str
    recommendations: List[str] = Field(default_factory=list)
    # recommended_action is the string form that M3's normalize_explanation also accepts.
    recommended_action: Optional[str] = None
    evidence: List[Any] = Field(default_factory=list)
    confidence: Optional[float] = None
    model_version: str


# ============================================================
# ROOT CAUSE LOGIC (deterministic mock — replace with LLM/RAG)
# ============================================================

# Known ABEND / return-code patterns
_ABEND_KNOWLEDGE: Dict[str, Dict[str, Any]] = {
    "S0C4": {
        "root_cause": "Storage Protection Exception (ABEND S0C4): the program attempted to access storage outside its authorised area, typically caused by a null pointer dereference, an array index out of bounds, or an application regression introduced by a recent code deployment.",
        "recommendations": [
            "Review the recent deployment that preceded the ABEND and back it out if confirmed as the cause.",
            "Run IPCS/SNAP dump analysis to identify the failing instruction and storage address.",
            "Check for initialisation defects, unresolved external references, or mismatched link-edit levels in the load module.",
            "Increase diagnostic SYSUDUMP/SYSABEND DD statements and rerun in test LPAR to reproduce.",
        ],
        "evidence_tags": ["ABEND S0C4", "storage protection", "protection exception"],
        "confidence": 0.88,
    },
    "S0C7": {
        "root_cause": "Data Exception (ABEND S0C7): invalid packed-decimal data was used in an arithmetic operation, typically caused by uninitialised working storage or corrupted input data.",
        "recommendations": [
            "Validate all packed-decimal fields are properly initialised before use.",
            "Trace the input dataset for malformed records that could have caused data corruption.",
            "Add COBOL/PL1 data validation routines or use ON ERROR handlers.",
        ],
        "evidence_tags": ["ABEND S0C7", "data exception", "packed decimal"],
        "confidence": 0.85,
    },
    "S806": {
        "root_cause": "Program Not Found (ABEND S806): the JCL or program attempted to LINK/LOAD/ATTACH a load module that could not be located in the STEPLIB, JOBLIB, or authorised libraries.",
        "recommendations": [
            "Verify the load module name in the JCL EXEC PROC= or PGM= statement.",
            "Check that the correct STEPLIB/JOBLIB DD concatenation is present and the module is in the library.",
            "Confirm the load module was successfully compiled and linked during the last build cycle.",
        ],
        "evidence_tags": ["ABEND S806", "module not found", "STEPLIB"],
        "confidence": 0.91,
    },
    "S222": {
        "root_cause": "Time Limit Exceeded / Job Cancelled (ABEND S222): the job was cancelled by an operator or exceeded the TIME= parameter. This is often caused by an infinite loop, resource wait, or unexpectedly high processing volume.",
        "recommendations": [
            "Review job CPU and elapsed time and compare against historical baselines.",
            "Check for lock/enqueue contention that may be causing the job to hang.",
            "Increase TIME= in the JOB card only after root cause is confirmed — do not mask the symptom.",
        ],
        "evidence_tags": ["ABEND S222", "time limit", "cancelled"],
        "confidence": 0.82,
    },
    "S322": {
        "root_cause": "CPU Time Limit Exceeded (ABEND S322): the job consumed more CPU time than allocated by the TIME= JCL parameter or installation limits, indicating runaway processing or regression.",
        "recommendations": [
            "Profile the job using SMF type-30 records to identify high-CPU steps.",
            "Check for algorithmic regressions in recently deployed load modules.",
            "Review DFSORT/utility performance — missing index or sort WORK DD shortage can drive CPU.",
        ],
        "evidence_tags": ["ABEND S322", "CPU time limit"],
        "confidence": 0.83,
    },
}

_COMPLETION_KNOWLEDGE: Dict[str, Dict[str, Any]] = {
    "JCL_ERROR": {
        "root_cause": "JCL Error: the job failed during JES2/JES3 interpretation before any program was executed. Common causes are a missing or misspelled dataset name, an invalid DD statement, or a JCLLIB/PROCLIB member that cannot be found.",
        "recommendations": [
            "Examine the JESMSGLG and JES2/JES3 messages for the specific IEF/IEC message code.",
            "Verify all DD DSN= references point to existing, catalogued datasets.",
            "Validate PROC and JCLLIB concatenation and ensure all INCLUDE members exist.",
            "Submit the JCL through SDSF in HELD class and review J status before releasing.",
        ],
        "evidence_tags": ["JCL_ERROR", "IEF", "JES2", "dataset not found"],
        "confidence": 0.90,
    },
    "ABEND": {
        "root_cause": "Job ABEND: the program terminated abnormally. Without a specific ABEND code, the most likely causes are storage violations, data exceptions, or external resource failures.",
        "recommendations": [
            "Capture the system dump (SYSUDUMP/SYSABEND) and run IPCS for detailed analysis.",
            "Look for the system completion code in JESMSGLG output.",
            "Check for recent changes to load modules, datasets, or RACF profiles.",
        ],
        "evidence_tags": ["ABEND", "abnormal termination"],
        "confidence": 0.70,
    },
    "CC": {
        "root_cause": "Condition Code completion: the job finished with a non-zero return code indicating a warning or error condition in one or more steps.",
        "recommendations": [
            "Review the return code against application-specific thresholds documented in the runbook.",
            "Inspect SYSPRINT and SYSOUT DD output for warning messages from the failing step.",
            "Evaluate whether downstream jobs that depend on this job's output have been affected.",
        ],
        "evidence_tags": ["condition code", "return code"],
        "confidence": 0.65,
    },
}


def _build_explanation(incident: IncidentPayload) -> dict[str, Any]:
    """Build a deterministic, knowledge-driven explanation from the incident fields."""
    abend = (incident.abend_code or "").upper().strip()
    completion = (incident.completion_status or "").upper().strip()
    event_type = (incident.event_type or incident.incident_type or "").upper().strip()
    job = incident.job_name or incident.incident_id or "the job"

    # Lookup in knowledge base
    knowledge = None
    matched_key = ""
    if abend in _ABEND_KNOWLEDGE:
        knowledge = _ABEND_KNOWLEDGE[abend]
        matched_key = abend
    elif completion in _COMPLETION_KNOWLEDGE:
        knowledge = _COMPLETION_KNOWLEDGE[completion]
        matched_key = completion

    # Build contextual suffix
    context_parts: list[str] = []
    if incident.cpu_utilization_pct is not None:
        context_parts.append(f"CPU utilization was {incident.cpu_utilization_pct:.1f}%")
    if incident.error_rate_pct is not None:
        context_parts.append(f"error rate was {incident.error_rate_pct:.1f}%")
    if incident.recent_deployment_flag:
        context_parts.append("a recent deployment was detected prior to the failure")
    if incident.anomaly_score is not None:
        context_parts.append(f"anomaly score was {incident.anomaly_score:.3f}")

    context_sentence = (
        (" Context: " + "; ".join(context_parts) + ".") if context_parts else ""
    )

    if knowledge:
        root_cause = knowledge["root_cause"] + context_sentence
        recommendations = knowledge["recommendations"].copy()
        if incident.recent_deployment_flag and "recent deployment" not in recommendations[0].lower():
            recommendations.insert(
                0,
                "A recent deployment was detected — prioritise rollback assessment before other remediation steps.",
            )
        evidence = knowledge["evidence_tags"].copy()
        confidence = knowledge.get("confidence", 0.75)
        explanation = (
            f"Incident {incident.incident_id} on job '{job}' terminated with "
            f"{'ABEND ' + abend if abend else 'status ' + (completion or event_type or 'UNKNOWN')}."
            f"{context_sentence} Anomaly score: {incident.anomaly_score or 'N/A'}."
        )
    else:
        # Generic fallback
        root_cause = (
            f"Incident {incident.incident_id} for job '{job}' encountered an unclassified operational failure "
            f"(status: {completion or event_type or 'UNKNOWN'}).{context_sentence}"
        )
        recommendations = [
            "Review the JES spool output (JESMSGLG, SYSPRINT) for the primary error message.",
            "Check recent changes to the job's datasets, load modules, and RACF permissions.",
            "Consult the IBM z/OS System Messages manual for any system completion codes reported.",
            f"Review the primary message ID ({incident.primary_message_id or 'N/A'}) in the IBM Knowledge Centre.",
        ]
        evidence = [completion, event_type, abend]
        evidence = [e for e in evidence if e]
        confidence = 0.60
        explanation = (
            f"The system detected anomalies for incident {incident.incident_id} with an anomaly score of "
            f"{incident.anomaly_score or 'N/A'}, leading to completion status {completion or event_type or 'UNKNOWN'}."
        )

    return {
        "incident_id": incident.incident_id,
        "root_cause": root_cause,
        "explanation": explanation,
        "recommendations": recommendations,
        "recommended_action": "; ".join(recommendations),
        "evidence": evidence,
        "confidence": confidence,
        "model_version": "CriticalFlow-M5-GenAI-v1.0",
    }


# ============================================================
# ENDPOINTS
# ============================================================

@app.post("/explain", response_model=ExplanationResponse)
def explain_incident(incident: IncidentPayload):
    """Generate a root cause explanation and remediation recommendations for one incident."""
    try:
        return _build_explanation(incident)
    except Exception as exc:
        log.exception("Explanation failed for %s", incident.incident_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
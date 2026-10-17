"""Maps a validated event to the team's processed-event contract (guide section 8.2) for M4/M5."""
from __future__ import annotations

from typing import Any

# Known message-id -> readable error code (extend as M2 discovers more sources).
MESSAGE_ERROR_CODES = {"IEF212I": "DATASET_NOT_FOUND"}


def derive_event_type(e: dict[str, Any]) -> str:
    s, rc = e["completion_status"], e["return_code"]
    if s == "ABEND":
        return "JOB_ABEND"
    if s == "JCL_ERROR":
        return "JCL_ERROR"
    if rc is None or rc <= 0:
        return "JOB_SUCCESS"
    return "JOB_WARNING" if rc <= 4 else "JOB_FAILURE"


def derive_error_code(e: dict[str, Any]) -> str | None:
    s = e["completion_status"]
    if s == "ABEND":
        return e["abend_code"]
    if s == "JCL_ERROR":
        return MESSAGE_ERROR_CODES.get(e["primary_message_id"] or "", e["primary_message_id"])
    rc = e["return_code"]
    return f"RC_{rc}" if rc else None


def build_context(e: dict[str, Any]) -> dict[str, Any]:
    """Evidence/context fields M5 (RAG) needs next to the model features."""
    keys = ("timestamp", "subsystem", "job_name", "job_id", "step_name", "completion_status", "return_code",
            "abend_code", "primary_message_id", "cpu_utilization_pct", "error_rate_pct",
            "transaction_volume_per_hr", "recent_deployment_flag", "raw_log_snippet")
    return {k: e[k] for k in keys}

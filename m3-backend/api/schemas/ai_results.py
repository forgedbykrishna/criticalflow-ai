from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Severity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


class IncidentResultIn(BaseModel):
    """M4 -> M3 DB. Unknown extra fields are kept in `extra` instead of being rejected."""
    model_config = ConfigDict(extra="allow")
    event_id: str = Field(min_length=1, max_length=64)
    incident_type: str
    anomaly_score: float = Field(ge=0, le=1)
    severity: Severity


class RcaResultIn(BaseModel):
    """M5 -> M3 DB."""
    model_config = ConfigDict(extra="allow")
    event_id: str = Field(min_length=1, max_length=64)
    root_cause: str
    evidence: list[Any]
    impact: str | None = None
    recommended_action: str
    confidence: float | None = Field(default=None, ge=0, le=1)

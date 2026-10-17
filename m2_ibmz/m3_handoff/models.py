"""IBMZEventPayload - Pydantic v2 mirror of criticalflow_event.schema.json (contract 1.0.0)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class IBMZEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal["1.0.0"]
    incident_id: str = Field(pattern=r"^INC-\d{8}-(JOB|STC|TSU)\d{5,8}-[A-Z#@$][A-Z0-9#@$]{0,7}$")
    timestamp: datetime
    system_id: str = Field(pattern=r"^[A-Z0-9#@$]{1,8}$")
    subsystem: str = Field(pattern=r"^[A-Z0-9-]{2,32}$")
    job_name: str = Field(pattern=r"^[A-Z#@$][A-Z0-9#@$]{0,7}$")
    job_id: str = Field(pattern=r"^(JOB|STC|TSU)\d{5,8}$")
    step_name: str = Field(pattern=r"^[A-Z#@$][A-Z0-9#@$]{0,7}$")
    completion_status: Literal["CC", "ABEND", "JCL_ERROR"]
    return_code: Optional[int] = Field(default=None, ge=0, le=4095)
    abend_code: Optional[str] = Field(default=None, pattern=r"^(S[0-9A-F]{3}|U\d{4})$")
    primary_message_id: Optional[str] = Field(default=None, pattern=r"^\$?[A-Z]{3,4}\d{3,5}[A-Z]?$")
    cpu_utilization_pct: Optional[float] = Field(default=None, ge=0, le=100)
    error_rate_pct: Optional[float] = Field(default=None, ge=0, le=100)
    transaction_volume_per_hr: Optional[int] = Field(default=None, ge=0)
    recent_deployment_flag: bool
    raw_log_snippet: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def _status_consistency(self) -> "IBMZEventPayload":
        cs = self.completion_status
        if cs == "CC" and (self.return_code is None or self.abend_code is not None):
            raise ValueError("CC requires return_code and forbids abend_code")
        if cs == "ABEND" and (self.abend_code is None or self.return_code is not None):
            raise ValueError("ABEND requires abend_code and forbids return_code")
        if cs == "JCL_ERROR" and (self.return_code is not None or self.abend_code is not None):
            raise ValueError("JCL_ERROR forbids return_code and abend_code")
        return self

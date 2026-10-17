from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class RejectedItem(BaseModel):
    index: int
    stage: str
    incident_id: str | None = None
    errors: list[dict[str, str]]


class IngestResponse(BaseModel):
    batch_id: str
    received: int
    accepted: int
    quarantined: int
    duplicates_in_batch: int
    processed: list[dict[str, Any]] | None = None   # echoed back for small requests only
    rejected: list[RejectedItem]

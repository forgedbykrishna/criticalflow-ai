"""Orchestrates  read-records -> map fields -> CLEAN -> VALIDATE -> FEATURES -> processed event.
Pure (no DB, no HTTP): the API and the CLI both call run_pipeline()."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Iterable

from config.settings import get_settings
from ingestion.field_map import apply_field_map
from ingestion.readers import UNPARSEABLE
from processing.cleaning import clean_event, clean_labels, parse_utc
from processing.contract import Contract, load_contract
from processing.features import DEFAULT_CONFIG, FeatureConfig, build_features
from processing.transform import build_context, derive_error_code, derive_event_type
from processing.validation import validate_event

log = logging.getLogger("cf.pipeline")


@dataclass
class ProcessedRecord:
    event_id: str
    system: str
    subsystem: str
    job_name: str
    timestamp: str
    event_type: str
    error_code: str | None
    status: str
    features: dict[str, Any]
    context: dict[str, Any]
    labels: dict[str, Any] | None
    raw: dict[str, Any]

    def as_contract(self) -> dict[str, Any]:
        """Processed-event JSON handed to M4/M5 (guide 8.2 fields + timestamp/subsystem/job_name/context)."""
        return {"event_id": self.event_id, "system": self.system, "event_type": self.event_type,
                "error_code": self.error_code, "features": self.features, "status": self.status,
                "timestamp": self.timestamp, "subsystem": self.subsystem, "job_name": self.job_name,
                "context": self.context}


@dataclass
class Rejected:
    index: int
    stage: str                      # parse | validation
    errors: list[dict[str, str]]
    payload: dict[str, Any]
    incident_id: str | None = None


@dataclass
class PipelineResult:
    received: int = 0
    processed: list[ProcessedRecord] = field(default_factory=list)
    rejected: list[Rejected] = field(default_factory=list)
    duplicates: int = 0


def _jsonable(obj: Any) -> Any:
    return json.loads(json.dumps(obj, default=str))


def run_pipeline(records: Iterable[dict[str, Any]], *, field_map: dict[str, str] | None = None,
                 contract: Contract | None = None, feature_cfg: FeatureConfig = DEFAULT_CONFIG,
                 label_columns: tuple[str, ...] | None = None) -> PipelineResult:
    contract = contract or load_contract()
    label_columns = label_columns if label_columns is not None else get_settings().label_columns
    res = PipelineResult()
    accepted: dict[str, ProcessedRecord] = {}

    for idx, rec in enumerate(records):
        res.received += 1
        if not isinstance(rec, dict) or UNPARSEABLE in rec:
            msg = rec.get(UNPARSEABLE) if isinstance(rec, dict) else "record is not an object"
            payload = rec if isinstance(rec, dict) else {"_raw": repr(rec)[:500]}
            res.rejected.append(Rejected(idx, "parse", [{"field": "<record>", "message": str(msg)}], _jsonable(payload)))
            continue

        mapped = apply_field_map(rec, field_map)
        event = clean_event(mapped, contract)
        errors = validate_event(event, contract)
        if errors:
            log.warning("record %d rejected: %s", idx, errors[:3])
            res.rejected.append(Rejected(idx, "validation", errors, _jsonable(rec), event.get("incident_id")))
            continue

        features = build_features(event, feature_cfg)
        rid = event["incident_id"]
        if rid in accepted:
            res.duplicates += 1                       # same incident twice in one batch: last one wins
        accepted[rid] = ProcessedRecord(
            event_id=rid, system=event["system_id"], subsystem=event["subsystem"], job_name=event["job_name"],
            timestamp=event["timestamp"], event_type=derive_event_type(event), error_code=derive_error_code(event),
            status="OPEN", features=features, context=build_context(event),
            labels=clean_labels(mapped, label_columns), raw=_jsonable(rec))
    res.processed = list(accepted.values())
    return res

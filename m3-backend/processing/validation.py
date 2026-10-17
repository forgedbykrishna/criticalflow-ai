"""Stage 2 - VALIDATE: JSON-Schema contract + semantic checks. Returns errors; never raises, never mutates."""
from __future__ import annotations

from typing import Any

from processing.cleaning import parse_utc
from processing.contract import Contract


def validate_event(event: dict[str, Any], contract: Contract) -> list[dict[str, str]]:
    errors = [
        {"field": "/".join(map(str, e.path)) or "<root>", "message": e.message}
        for e in sorted(contract.validator.iter_errors(event), key=lambda e: list(map(str, e.path)))
    ]
    ts = event.get("timestamp")
    if isinstance(ts, str) and not any(e["field"] == "timestamp" for e in errors) and parse_utc(ts) is None:
        errors.append({"field": "timestamp", "message": f"{ts!r} is not a real calendar date/time"})
    return errors

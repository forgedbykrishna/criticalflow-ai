"""Stage 1 - CLEAN: type conversion + normalisation. Never invents data: unparseable values are left as-is so the
validation stage can report them. Source-format agnostic (CSV gives strings, JSON gives typed values, etc.)."""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any

from processing.contract import Contract

NULL_TOKENS = {"", "null", "none", "nan", "n/a", "na"}
TRUE_TOKENS = {"true", "1", "y", "yes", "t"}
FALSE_TOKENS = {"false", "0", "n", "no", "f"}
NO_UPPER = {"raw_log_snippet", "timestamp", "schema_version"}
MAX_SNIPPET = 4000
RE_PAN = re.compile(r"\b\d{13,19}\b")            # 13-19 digit runs = possible card / account numbers


def to_py(value: Any) -> Any:
    """numpy/pandas scalars -> python; NaN -> None."""
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            value = value.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def coerce(value: Any, jtypes: tuple[str, ...]) -> Any:
    value = to_py(value)
    if isinstance(value, str):
        value = value.strip()
        if value.lower() in NULL_TOKENS:
            return None
    if value is None:
        return None
    try:
        if "boolean" in jtypes and not isinstance(value, bool):
            s = str(value).strip().lower()
            if s in TRUE_TOKENS:
                return True
            if s in FALSE_TOKENS:
                return False
            return value
        if "integer" in jtypes and not isinstance(value, bool):
            f = float(value)
            return int(f) if f.is_integer() else value      # "8.0" -> 8 ; "8.5" stays -> validation error
        if "number" in jtypes and not isinstance(value, bool):
            return float(value)
    except (ValueError, TypeError):
        return value
    return value


def normalize_timestamp(value: Any) -> Any:
    """Any ISO-8601 -> 'YYYY-MM-DDTHH:MM:SSZ' in UTC. Naive timestamps are assumed to already be UTC."""
    if not isinstance(value, str):
        return value
    try:
        dt = datetime.fromisoformat(value.strip().replace(" ", "T", 1))
    except ValueError:
        return value
    dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(ts: str) -> datetime | None:
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def mask_pii(text: str) -> str:
    return RE_PAN.sub(lambda m: "*" * (len(m.group(0)) - 4) + m.group(0)[-4:], text)


def normalize_snippet(s: Any) -> Any:
    if not isinstance(s, str):
        return s
    s = s.replace("\r\n", "\n").replace("\r", "\n").strip()
    if "\n" not in s and " | " in s:          # flat CSV export joins log lines with ' | '
        s = "\n".join(part.strip() for part in s.split(" | "))
    return mask_pii(s)[:MAX_SNIPPET]


def clean_event(rec: dict[str, Any], contract: Contract, *, fill_missing_nullable: bool = True) -> dict[str, Any]:
    """Return only the contract fields, cleaned. Missing nullable fields become None (JSON producers often omit
    nulls); missing required non-null fields stay missing so validation reports them."""
    out: dict[str, Any] = {}
    for field in contract.fields:
        jt = contract.types[field]
        if field not in rec:
            if fill_missing_nullable and "null" in jt:
                out[field] = None
            continue
        v = coerce(rec[field], jt)
        if isinstance(v, str):
            if field == "timestamp":
                v = normalize_timestamp(v)
            elif field == "raw_log_snippet":
                v = normalize_snippet(v)
            elif field not in NO_UPPER and "string" in jt:
                v = v.upper()
        out[field] = v
    return out


def clean_labels(rec: dict[str, Any], label_columns: tuple[str, ...]) -> dict[str, Any] | None:
    """Training labels (not part of the inference contract). None if the record carries no labels."""
    labels: dict[str, Any] = {}
    for col in label_columns:
        if col not in rec:
            continue
        v = to_py(rec[col])
        if isinstance(v, str):
            v = v.strip()
            v = None if v.lower() in NULL_TOKENS else v
        if v is not None:
            try:
                if col == "risk_score":
                    v = float(v)
                elif col == "is_high_risk":
                    v = int(float(v)) if not isinstance(v, bool) else int(v)
                elif col == "risk_label":
                    v = str(v).upper()
                elif col in ("scenario_type", "split"):
                    v = str(v).lower()
            except (ValueError, TypeError):
                pass
        labels[col] = v
    return labels or None

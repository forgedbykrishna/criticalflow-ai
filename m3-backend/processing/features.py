"""Stage 3 - FEATURES. Deliberately STATELESS (one event in -> features out), so the exact same function runs for a
3,000-row training file and for a single event arriving at the API. No cross-row leakage.

Nulls are meaningful (README): missing metrics stay None and get *_missing flags - never imputed as 0."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from processing.cleaning import parse_utc


@dataclass(frozen=True)
class FeatureConfig:
    cpu_high: float = 85.0
    cpu_critical: float = 95.0
    error_rate_high: float = 10.0
    error_rate_critical: float = 30.0
    business_hours: tuple[int, int] = (8, 18)      # UTC hours [start, end)


DEFAULT_CONFIG = FeatureConfig()
_RE_STEP = re.compile(r"(\d+)$")
_RE_FAMILY = re.compile(r"\d+$")


def rc_bucket(rc: int | None) -> str | None:
    if rc is None:
        return None
    return "OK" if rc <= 0 else "WARNING" if rc <= 4 else "ERROR" if rc <= 8 else "SEVERE"


def build_features(event: dict[str, Any], cfg: FeatureConfig = DEFAULT_CONFIG) -> dict[str, Any]:
    ts = parse_utc(event["timestamp"])
    status, rc, abend = event["completion_status"], event["return_code"], event["abend_code"]
    cpu, err, tph = event["cpu_utilization_pct"], event["error_rate_pct"], event["transaction_volume_per_hr"]
    deploy = bool(event["recent_deployment_flag"])
    is_abend, is_jcl = status == "ABEND", status == "JCL_ERROR"
    failed = is_abend or is_jcl or (rc is not None and rc > 4)
    step = _RE_STEP.search(event["step_name"])
    snippet = event["raw_log_snippet"]

    return {
        # time (UTC)
        "hour_of_day": ts.hour,
        "day_of_week": ts.weekday(),
        "is_weekend": ts.weekday() >= 5,
        "is_business_hours": cfg.business_hours[0] <= ts.hour < cfg.business_hours[1],
        # completion
        "is_abend": is_abend,
        "is_jcl_error": is_jcl,
        "return_code": rc,
        "rc_bucket": rc_bucket(rc),
        "abend_family": None if not abend else ("SYSTEM" if abend.startswith("S") else "USER"),
        # metrics (None = metric feed missing / job never ran)
        "cpu_utilization_pct": cpu,
        "error_rate_pct": err,
        "transaction_volume_per_hr": tph,
        "log_transaction_volume": None if tph is None else round(math.log1p(tph), 4),
        "cpu_missing": cpu is None,
        "error_rate_missing": err is None,
        "tph_missing": tph is None,
        "cpu_high": cpu is not None and cpu >= cfg.cpu_high,
        "cpu_critical": cpu is not None and cpu >= cfg.cpu_critical,
        "error_rate_high": err is not None and err >= cfg.error_rate_high,
        "error_rate_critical": err is not None and err >= cfg.error_rate_critical,
        # change context
        "recent_deployment": deploy,
        "deploy_and_failure": deploy and failed,
        # identity-derived
        "job_family": _RE_FAMILY.sub("", event["job_name"]) or event["job_name"],
        "step_number": int(step.group(1)) if step else None,
        "snippet_line_count": snippet.count("\n") + 1,
    }

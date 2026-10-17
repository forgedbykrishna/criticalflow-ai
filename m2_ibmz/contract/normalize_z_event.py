#!/usr/bin/env python3
"""
normalize_z_event.py - Parse raw JES/SYSLOG text into the CriticalFlow AI event contract.

Usage
  python normalize_z_event.py raw.txt [--out event.json] [--default-system-id SYSA] [--utc-offset 0]
  cat raw.txt | python normalize_z_event.py - 

Exit codes: 0 ok | 2 parse failure | 3 schema violation
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

log = logging.getLogger("cf.normalize")

SCHEMA_PATH = Path(__file__).with_name("criticalflow_event.schema.json")
SCHEMA_VERSION = "1.0.0"
MAX_SNIPPET = 4000
MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}

# ---------------------------------------------------------------- patterns
RE_DATE = re.compile(r"----\s+[A-Z]+DAY,\s+(\d{1,2})\s+([A-Z]{3})\s+(\d{4})\s+----")
RE_JOBID = re.compile(r"\b((?:JOB|STC|TSU)\d{5,8})\b")
RE_JOBNAME = re.compile(
    r"(?:\$HASP395|IEF403I|IEF142I|IEF450I|IEF212I|IEFC452I|IEF453I)\s+([A-Z0-9#@$]{1,8})\b")
RE_TIME = re.compile(r"TIME=(\d{2})\.(\d{2})\.(\d{2})")
RE_STEP_CC = re.compile(
    r"IEF142I\s+(\S+)\s+(\S+)(?:\s+(?!-)\S+)?\s+-\s+STEP WAS EXECUTED\s+-\s+COND CODE\s+(\d{4})")
RE_ABEND = re.compile(
    r"IEF450I\s+(\S+)\s+(\S+)(?:\s+(?!-)\S+)?\s+-\s+ABEND=(S[0-9A-F]{3})\s+(U\d{4})")
RE_ALLOC_FAIL = re.compile(r"IEF212I\s+(\S+)\s+(\S+)\s+(\S+)\s+-\s+DATA SET NOT FOUND")
RE_JCL_FAIL = re.compile(r"\b(IEFC452I|IEF453I)\b")
RE_METRIC = re.compile(r"CFMETRIC\s+(.*)$", re.M)
RE_KV = re.compile(r"([A-Z_]+)=(\S+)")
RE_SYS = re.compile(r"\bSYS\s+([A-Z0-9#@$]{1,8})\b")
RE_PAN = re.compile(r"\b\d{13,19}\b")
# --- compact JES log format (MSGLEVEL=(0,0)): no IEF403I/IEF142I lines, step table instead ---
RE_JOBINFO = re.compile(r"==== JOBINFO jobname=(\S+) jobid=(\S+) status=(\S+) retcode=(.*?) owner=")
RE_HASP395_TIME = re.compile(r"(\d{2})\.(\d{2})\.(\d{2})\s+(?:JOB|STC|TSU)\d+\s+\$HASP395")
RE_PREFIX_TIME = re.compile(r"^(\d{2})\.(\d{2})\.(\d{2})\s+(?:JOB|STC|TSU)\d+", re.M)
RE_STEP_TABLE_HDR = re.compile(r"^-(JOBNAME\s+)?STEPNAME\s+PROCSTEP\s+RC")
RE_LINE_PREFIX = re.compile(r"^\d{2}\.\d{2}\.\d{2}\s+(?:JOB|STC|TSU)\d+\s+")
RE_RETCODE_CC = re.compile(r"CC\s+(\d{4})")
RE_RETCODE_ABEND = re.compile(r"ABEND\s*=?\s*(S[0-9A-F]{3}|U\d{4})")
VALID_NAME = re.compile(r"[A-Z#@$][A-Z0-9#@$]{0,7}")
RE_SNIPPET = re.compile(
    r"(IEFC?\d{3}[A-Z]|IEC\d{3}[A-Z]|IEA\d{3}[A-Z]|IGD\d{5}[A-Z]|\$HASP\d{3}"
    r"|CFMETRIC|PAY\d{4}[EWI]|PSW AT TIME OF ERROR|ACTIVE LOAD MODULE"
    r"|SYSTEM COMPLETION CODE|DSN=|ICH408I|STEPNAME\s+PROCSTEP)")


class NormalizationError(ValueError):
    """Raw text is missing evidence needed to build an event."""


class SchemaViolation(ValueError):
    """Built event does not satisfy the JSON schema contract."""


# ---------------------------------------------------------------- helpers
def _mask_pii(s: str) -> str:
    """Mask 13-19 digit runs (potential PANs / account numbers), keep last 4."""
    return RE_PAN.sub(lambda m: "*" * (len(m.group(0)) - 4) + m.group(0)[-4:], s)


def _num(value: str | None, cast) -> Any:
    if value is None:
        return None
    try:
        return cast(value)
    except ValueError:
        log.warning("Ignoring non-numeric metric value %r", value)
        return None


def _timestamp(text: str, utc_offset_hours: float, date_hint: str | None) -> str:
    m = RE_DATE.search(text)
    if m:
        day, mon, year = int(m.group(1)), MONTHS[m.group(2)], int(m.group(3))
    elif date_hint:
        year, mon, day = (int(x) for x in date_hint.split("-"))
    else:
        raise NormalizationError("No JES date banner found and no --date-hint supplied")
    times = RE_TIME.findall(text) or RE_HASP395_TIME.findall(text) or RE_PREFIX_TIME.findall(text)
    if not times:
        raise NormalizationError("No time value found in job messages")
    hh, mm, ss = (int(x) for x in times[-1])
    local = datetime(year, mon, day, hh, mm, ss, tzinfo=timezone(timedelta(hours=utc_offset_hours)))
    return local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _step_rows(text: str) -> list[tuple[str, int]]:
    """Parse the compact step table: '-STEPNAME PROCSTEP RC EXCP ...' rows -> [(step, rc)]."""
    rows: list[tuple[str, int]] = []
    in_table, job_col, idx = False, False, 0
    for ln in text.splitlines():
        body = RE_LINE_PREFIX.sub("", ln.strip())
        hdr = RE_STEP_TABLE_HDR.match(body)
        if hdr:
            in_table, job_col = True, bool(hdr.group(1))
            continue
        if not in_table:
            continue
        if "ENDED." in body or body.startswith("$HASP"):
            in_table = False
            continue
        if not body.startswith("-"):
            continue
        toks = body[1:].split()
        rc_i = next((i for i, t in enumerate(toks) if re.fullmatch(r"\d{2,4}", t)), None)
        if rc_i is None:
            continue
        idx += 1
        name_i = 1 if job_col else 0
        name = toks[name_i] if rc_i > name_i else ""
        if not VALID_NAME.fullmatch(name):
            name = f"STEP{idx:03d}"
        rows.append((name, int(toks[rc_i])))
    return rows


def _snippet(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if RE_SNIPPET.search(ln)]
    out = _mask_pii("\n".join(lines))
    return out[:MAX_SNIPPET] if out else _mask_pii(text.strip())[:MAX_SNIPPET]


def _metrics(text: str) -> dict[str, str]:
    kv: dict[str, str] = {}
    for line in RE_METRIC.findall(text):       # last CFMETRIC line wins
        kv.update(dict(RE_KV.findall(line)))
    return kv


# ---------------------------------------------------------------- core
def normalize(raw: str, *, default_system_id: str = "UNKNOWN", default_subsystem: str = "UNKNOWN",
              utc_offset_hours: float = 0.0, date_hint: str | None = None) -> dict[str, Any]:
    jid = RE_JOBID.search(raw)
    jname = RE_JOBNAME.search(raw)
    info = RE_JOBINFO.search(raw)
    retcode_txt = info.group(4).strip() if info else ""
    if not jid and info:
        jid = re.search(r"((?:JOB|STC|TSU)\d{5,8})", info.group(2))
    job_name = jname.group(1) if jname else (info.group(1) if info else None)
    if not jid or not job_name:
        raise NormalizationError("Cannot determine job id / job name from raw text")
    job_id = jid.group(1)

    ts = _timestamp(raw, utc_offset_hours, date_hint)

    return_code: int | None = None
    abend_code: str | None = None
    primary: str | None = None

    abend = RE_ABEND.search(raw)
    alloc = RE_ALLOC_FAIL.search(raw)
    ra = RE_RETCODE_ABEND.search(retcode_txt)
    rows = _step_rows(raw)
    if abend:
        status = "ABEND"
        step = abend.group(2)
        sys_code, usr_code = abend.group(3), abend.group(4)
        abend_code = sys_code if sys_code != "S000" else usr_code
        primary = "IEF450I"
    elif ra:                                   # z/OSMF job status says ABEND (no IEF450I in the log)
        status, abend_code = "ABEND", ra.group(1)
        step = rows[-1][0] if rows else "STEP001"
        primary = None
    elif alloc or RE_JCL_FAIL.search(raw) or retcode_txt.startswith(("JCL ERROR", "SEC ERROR")):
        status = "JCL_ERROR"
        step = alloc.group(2) if alloc else "JCL"
        if alloc:
            primary = "IEF212I"
        elif RE_JCL_FAIL.search(raw):
            primary = RE_JCL_FAIL.search(raw).group(1)
        else:
            primary = "ICH408I" if "ICH408I" in raw else None
    else:
        steps = RE_STEP_CC.findall(raw)
        status, step, best = "CC", "", -1
        if steps:
            for _job, stp, cc in steps:        # highest RC; last step wins ties
                if int(cc) >= best:
                    best, step = int(cc), stp
            return_code = best
            primary = "IEF142I"
        else:
            m_cc = RE_RETCODE_CC.search(retcode_txt)
            if not rows and not m_cc:
                raise NormalizationError("No step completion evidence (job still running or truncated log)")
            for stp, rc in rows:
                if rc >= best:
                    best, step = rc, stp
            if not step:
                step = "STEP001"
            return_code = int(m_cc.group(1)) if m_cc else best
            primary = "$HASP395"

    kv = _metrics(raw)
    hasp = RE_SYS.search(raw)
    metric_sys = kv.get("SYSID")
    system_id = (metric_sys if metric_sys not in (None, "AUTO", "UNKNOWN") else None) \
        or (hasp.group(1) if hasp else default_system_id)

    event: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "incident_id": f"INC-{ts[:4]}{ts[5:7]}{ts[8:10]}-{job_id}-{job_name}",
        "timestamp": ts,
        "system_id": system_id,
        "subsystem": kv.get("SUBSYS", default_subsystem),
        "job_name": job_name,
        "job_id": job_id,
        "step_name": step,
        "completion_status": status,
        "return_code": return_code,
        "abend_code": abend_code,
        "primary_message_id": primary,
        "cpu_utilization_pct": _num(kv.get("CPU_PCT"), float),
        "error_rate_pct": _num(kv.get("ERR_PCT"), float),
        "transaction_volume_per_hr": _num(kv.get("TPH"), int),
        "recent_deployment_flag": kv.get("DEPLOY", "N").upper() == "Y",
        "raw_log_snippet": _snippet(raw),
    }
    validate(event)
    return event


def load_validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def validate(event: dict[str, Any]) -> None:
    errors = sorted(load_validator().iter_errors(event), key=lambda e: list(e.path))
    if errors:
        detail = "; ".join(f"{'/'.join(map(str, e.path)) or '<root>'}: {e.message}" for e in errors)
        raise SchemaViolation(detail)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help="raw log file, or '-' for stdin")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--default-system-id", default="UNKNOWN")
    ap.add_argument("--default-subsystem", default="UNKNOWN")
    ap.add_argument("--utc-offset", type=float, default=0.0, help="mainframe local time offset from UTC in hours")
    ap.add_argument("--date-hint", help="YYYY-MM-DD if the log lacks a JES date banner")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    raw = sys.stdin.read() if a.input == "-" else Path(a.input).read_text(encoding="utf-8", errors="replace")
    try:
        event = normalize(raw, default_system_id=a.default_system_id,
                          default_subsystem=a.default_subsystem,
                          utc_offset_hours=a.utc_offset, date_hint=a.date_hint)
    except NormalizationError as exc:
        log.error("Parse failure: %s", exc)
        return 2
    except SchemaViolation as exc:
        log.error("Schema violation: %s", exc)
        return 3
    text = json.dumps(event, indent=2)
    if a.out:
        a.out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())

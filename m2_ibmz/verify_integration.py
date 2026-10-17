#!/usr/bin/env python3
"""verify_integration.py - Smoke test: extract (mock|live) -> normalize -> POST -> assert 201.
  MOCK_MODE=True  python verify_integration.py --unique      # offline replay + golden comparison
  MOCK_MODE=False python verify_integration.py --unique      # live z/OSMF (read-only, no checkpoint)
"""
from __future__ import annotations

import argparse
import json
import random
import sys

import httpx

from contract.normalize_z_event import NormalizationError, SchemaViolation, normalize, validate
from pipeline_config import get_raw_logs, load_settings


def make_unique(ev: dict) -> dict:
    ev = dict(ev)
    ev["job_id"] = f"JOB9{random.randint(0, 9999):04d}"
    d = ev["timestamp"]
    ev["incident_id"] = f"INC-{d[:4]}{d[5:7]}{d[8:10]}-{ev['job_id']}-{ev['job_name']}"
    validate(ev)
    return ev


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--unique", action="store_true", help="fresh job_id so POST returns 201 on every run")
    ap.add_argument("--no-post", action="store_true")
    a = ap.parse_args()
    s = load_settings()
    failures: list[str] = []
    headers = {"Content-Type": "application/json"}
    if s.api_token:
        headers["Authorization"] = f"Bearer {s.api_token}"
    with httpx.Client(timeout=s.api_timeout_s, headers=headers) as api:
        if not a.no_post:
            h = api.get(f"{s.api_base_url}/health")
            if h.status_code != 200:
                print(f"FAIL  API health: HTTP {h.status_code}")
                return 1
            print(f"OK    API healthy at {s.api_base_url}")
        items = get_raw_logs(s)
        print(f"INFO  {len(items)} raw log(s) acquired (mock_mode={s.mock_mode})")
        if not items:
            print("FAIL  no jobs found (check CF_JOB_PREFIX / CF_JOB_OWNER)")
            return 1
        for label, raw in items:
            try:
                ev = normalize(raw, default_system_id=s.default_system_id,
                               default_subsystem=s.default_subsystem, utc_offset_hours=s.utc_offset_hours)
            except (NormalizationError, SchemaViolation) as exc:
                failures.append(f"{label}: {exc}")
                print(f"FAIL  {label}: {exc}")
                continue
            print(f"OK    {label}: {ev['incident_id']} [{ev['completion_status']}]")
            golden = s.expected_dir / f"{label}.json"
            if s.mock_mode and golden.exists():
                exp = json.loads(golden.read_text(encoding="utf-8"))
                diffs = [k for k in exp if exp[k] != ev.get(k)]
                if diffs:
                    failures.append(f"{label}: golden mismatch {diffs}")
                    print(f"FAIL  {label}: golden mismatch {diffs}")
                    continue
                print(f"OK    {label}: matches golden file")
            if a.no_post:
                continue
            r = api.post(f"{s.api_base_url}/api/v1/incidents", json=make_unique(ev) if a.unique else ev)
            if r.status_code != 201:
                failures.append(f"{label}: POST {r.status_code} {r.text[:200]}")
                print(f"FAIL  {label}: expected 201, got {r.status_code}")
            else:
                print(f"OK    {label}: 201 Created")
    print("\nSMOKE TEST " + ("FAILED:\n  - " + "\n  - ".join(failures) if failures else "PASSED"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

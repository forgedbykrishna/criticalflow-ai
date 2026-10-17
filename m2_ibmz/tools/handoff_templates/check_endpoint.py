#!/usr/bin/env python3
"""check_endpoint.py - acceptance test for M3's POST /api/v1/incidents endpoint.

  API_BASE_URL=http://localhost:8000 API_TOKEN=devtoken python3 check_endpoint.py
Needs: pip install httpx.   Exit code 0 only if every check passes.
Each run rewrites job_id/incident_id of the samples so a fresh database returns 201 every time.
"""
import copy
import json
import os
import random
import sys
from pathlib import Path

import httpx

BASE = os.environ.get("API_BASE_URL", "http://localhost:8000").rstrip("/")
TOKEN = os.environ.get("API_TOKEN")
HERE = Path(__file__).resolve().parent
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name} {detail}")


def fresh(ev):
    ev = copy.deepcopy(ev)
    ev["job_id"] = f"JOB9{random.randint(0, 9999):04d}"
    d = ev["timestamp"]
    ev["incident_id"] = f"INC-{d[:4]}{d[5:7]}{d[8:10]}-{ev['job_id']}-{ev['job_name']}"
    return ev


headers = {"Content-Type": "application/json"}
if TOKEN:
    headers["Authorization"] = f"Bearer {TOKEN}"

with httpx.Client(timeout=15, headers=headers) as c:
    r = c.get(f"{BASE}/health")
    check("GET /health returns 200", r.status_code == 200, f"(got {r.status_code})")

    samples = sorted((HERE / "samples").glob("*.json"))
    check("sample events found", len(samples) > 0, f"({len(samples)} files)")
    for p in samples:
        ev = fresh(json.loads(p.read_text()))
        r = c.post(f"{BASE}/api/v1/incidents", json=ev)
        check(f"POST {p.name} -> 201 Created", r.status_code == 201, f"(got {r.status_code} {r.text[:120]})")
        r2 = c.post(f"{BASE}/api/v1/incidents", json=ev)
        check(f"POST {p.name} again -> 200 (idempotent)", r2.status_code == 200, f"(got {r2.status_code})")

    if samples:
        bad = fresh(json.loads(samples[0].read_text()))
        bad.pop("incident_id")
        r = c.post(f"{BASE}/api/v1/incidents", json=bad)
        check("missing required field -> 422", r.status_code == 422, f"(got {r.status_code})")

        bad = fresh(json.loads(samples[0].read_text()))
        bad["completion_status"] = "ABEND" if bad["completion_status"] == "CC" else "CC"
        r = c.post(f"{BASE}/api/v1/incidents", json=bad)
        check("inconsistent status/return_code/abend_code -> 422", r.status_code == 422, f"(got {r.status_code})")

        bad = fresh(json.loads(samples[0].read_text()))
        bad["unexpected_field"] = 1
        r = c.post(f"{BASE}/api/v1/incidents", json=bad)
        check("unknown extra field -> 422", r.status_code == 422, f"(got {r.status_code})")

    if TOKEN and samples:
        r = httpx.post(f"{BASE}/api/v1/incidents", json=fresh(json.loads(samples[0].read_text())),
                       headers={"Content-Type": "application/json", "Authorization": "Bearer wrong"}, timeout=15)
        check("wrong token -> 401", r.status_code == 401, f"(got {r.status_code})")

print(f"\n{sum(results)}/{len(results)} checks passed")
sys.exit(0 if all(results) else 1)

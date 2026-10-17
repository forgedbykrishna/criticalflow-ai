#!/usr/bin/env python3
"""
run_pipeline.py - Production runner for Approach A:
  z/OSMF harvest -> normalize -> validate -> POST /api/v1/incidents

Delivery guarantee: at-least-once. A job's checkpoint is committed only after the API answers
200/201 (idempotent on incident_id) or the event is quarantined as permanently bad.

  python run_pipeline.py --once                 # one cycle (cron / scheduler)
  python run_pipeline.py --interval 10          # long-running poller
  python run_pipeline.py --once --dry-run --out-dir events/   # no API call, write JSON files

Exit codes: 0 ok | 1 some jobs deferred (retry next cycle) | 2 z/OSMF error | 3 API auth/config error
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path

import httpx

from contract.normalize_z_event import NormalizationError, SchemaViolation, normalize
from extract.extract_zosmf import ZosmfError, client_from_env, harvest, load_state, save_state
from pipeline_config import Settings, load_settings

log = logging.getLogger("cf.run")
_stop = False


def _quarantine(s: Settings, key: str, reason: str, raw: str) -> None:
    s.quarantine_dir.mkdir(parents=True, exist_ok=True)
    (s.quarantine_dir / (key.replace(":", "_") + ".json")).write_text(
        json.dumps({"key": key, "reason": reason, "raw": raw}, indent=2), encoding="utf-8")
    log.error("QUARANTINED %s: %s", key, reason)


def run_cycle(s: Settings, client, api: httpx.Client | None, *, dry_run: bool, out_dir: Path | None,
              purge: bool, max_rps: float) -> tuple[dict, int]:
    stats = {"harvested": 0, "created": 0, "duplicate": 0, "quarantined": 0, "deferred": 0, "written": 0}
    seen = load_state(s.state_file)
    rc = 0
    for prefix in s.job_prefixes:
        for jobname, jobid, key, raw in harvest(client, prefix, s.job_owner, seen,
                                                s.default_subsystem, s.default_system_id):
            stats["harvested"] += 1
            try:
                ev = normalize(raw, default_system_id=s.default_system_id,
                               default_subsystem=s.default_subsystem, utc_offset_hours=s.utc_offset_hours)
            except (NormalizationError, SchemaViolation) as exc:
                _quarantine(s, key, f"{type(exc).__name__}: {exc}", raw)
                stats["quarantined"] += 1
                seen.add(key); save_state(s.state_file, seen)   # permanent failure: do not retry forever
                continue

            if out_dir:
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / f"{ev['incident_id']}.json").write_text(json.dumps(ev, indent=2), encoding="utf-8")
                stats["written"] += 1
            if dry_run or api is None:
                seen.add(key); save_state(s.state_file, seen)
                continue

            try:
                r = api.post(f"{s.api_base_url}/api/v1/incidents", json=ev)
            except httpx.HTTPError as exc:
                log.error("API unreachable (%s); %s deferred, aborting cycle", exc, key)
                stats["deferred"] += 1
                return stats, 1
            if r.status_code in (200, 201):
                stats["created" if r.status_code == 201 else "duplicate"] += 1
                seen.add(key); save_state(s.state_file, seen)
                log.info("delivered %s -> %s", ev["incident_id"], r.status_code)
                if purge:
                    client.purge(jobname, jobid)
            elif r.status_code in (400, 422):
                _quarantine(s, key, f"API rejected payload: HTTP {r.status_code} {r.text[:300]}", raw)
                stats["quarantined"] += 1
                seen.add(key); save_state(s.state_file, seen)
            elif r.status_code in (401, 403):
                log.error("API auth failure HTTP %s: check API_TOKEN", r.status_code)
                return stats, 3
            else:
                log.error("API error HTTP %s for %s; will retry next cycle", r.status_code, key)
                stats["deferred"] += 1
                return stats, 1
            time.sleep(1.0 / max_rps)
        # prefix finished without error: still alive and making progress (long cycles stay healthy)
        write_heartbeat()
    return stats, rc


def write_heartbeat() -> None:
    """Touch CF_HEARTBEAT_FILE after a fully successful cycle (read by docker/healthcheck.py)."""
    path = os.environ.get("CF_HEARTBEAT_FILE")
    if not path:
        return
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(str(int(time.time())))
    except OSError as exc:
        log.warning("could not write heartbeat file %s: %s", path, exc)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=float, default=10.0, help="poll seconds (min 5)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out-dir", type=Path)
    ap.add_argument("--purge", action="store_true", help="purge spool of jobs after confirmed delivery")
    ap.add_argument("--max-rps", type=float, default=20.0, help="max API posts per second")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    s = load_settings()
    if s.mock_mode:
        log.error("MOCK_MODE is True; run_pipeline is the live runner. Set MOCK_MODE=False.")
        return 2
    signal.signal(signal.SIGTERM, lambda *_: globals().__setitem__("_stop", True))
    headers = {"Content-Type": "application/json"}
    if s.api_token:
        headers["Authorization"] = f"Bearer {s.api_token}"
    api = None if a.dry_run else httpx.Client(timeout=s.api_timeout_s, headers=headers)
    try:
        client = client_from_env()
    except (KeyError, ZosmfError) as exc:
        log.error("z/OSMF login failed: %s", exc)
        return 2
    worst = 0
    try:
        while not _stop:
            try:
                stats, rc = run_cycle(s, client, api, dry_run=a.dry_run, out_dir=a.out_dir,
                                      purge=a.purge, max_rps=a.max_rps)
            except ZosmfError as exc:
                log.error("z/OSMF error: %s", exc)
                stats, rc = {}, 2
            log.info("cycle done: %s rc=%s", stats, rc)
            if rc == 0:
                write_heartbeat()
            worst = max(worst, rc)
            if a.once or rc == 3:
                break
            time.sleep(max(5.0, a.interval))
    finally:
        client.close()
        if api:
            api.close()
    return worst


if __name__ == "__main__":
    sys.exit(main())

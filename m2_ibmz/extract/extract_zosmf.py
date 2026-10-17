#!/usr/bin/env python3
"""
extract_zosmf.py - CriticalFlow AI M2 extractor (Approach A: z/OSMF REST Jobs/Files API).

  * authenticate once (JWT/LTPA cookie), re-authenticate on 401, retry 5xx/transport errors
  * submit a job from a dataset member and wait for OUTPUT status
  * harvest finished jobs by prefix; checkpointing is explicit (commit only after delivery)
  * collect JESMSGLG / JESJCL / JESYSMSG / SYSPRINT / CFMETRIC into one raw text blob

Environment
  ZOSMF_URL          e.g. https://zos.example.com:443
  ZOSMF_USER / ZOSMF_PASSWORD
  ZOSMF_VERIFY_TLS   "true" (default) | "false" | path to CA bundle
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Iterable

import httpx

log = logging.getLogger("cf.extract.zosmf")

WANTED_DDS = ("JESMSGLG", "JESJCL", "JESYSMSG", "SYSPRINT", "CFMETRIC")
CTX_METRIC_FMT = "CFMETRIC SUBSYS={subsys} SYSID={sysid} DEPLOY=N"


class ZosmfError(RuntimeError):
    pass


class ZosmfClient:
    def __init__(self, base_url: str, user: str, password: str,
                 verify: bool | str = True, timeout: float = 30.0,
                 use_jwt: bool = True, max_retries: int = 3) -> None:
        self.base = base_url.rstrip("/")
        self._user, self._password = user, password
        self._use_jwt = use_jwt
        self._retries = max_retries
        self.http = httpx.Client(verify=verify, timeout=timeout,
                                 headers={"X-CSRF-ZOSMF-HEADER": "true"})
        if use_jwt:
            self._login()
        else:
            self.http.auth = (user, password)

    # ---- auth --------------------------------------------------------
    def _login(self) -> None:
        r = self.http.post(f"{self.base}/zosmf/services/authenticate",
                           auth=(self._user, self._password))
        if r.status_code not in (200, 204):
            raise ZosmfError(f"z/OSMF authentication failed: HTTP {r.status_code} {r.text[:200]}")
        names = {c.name for c in self.http.cookies.jar}
        if not names & {"jwtToken", "LtpaToken2"}:
            raise ZosmfError("Authenticated but no jwtToken/LtpaToken2 cookie returned")
        log.info("z/OSMF session established (%s)", ",".join(sorted(names)))

    # ---- request wrapper --------------------------------------------
    def request(self, method: str, path: str, **kw) -> httpx.Response:
        url = f"{self.base}{path}"
        delay = 1.0
        last_exc: Exception | None = None
        for attempt in range(1, self._retries + 1):
            try:
                r = self.http.request(method, url, **kw)
                if r.status_code == 401 and self._use_jwt and attempt < self._retries:
                    log.warning("401 from z/OSMF; re-authenticating")
                    self._login()
                    continue
                if r.status_code in (502, 503, 504) and attempt < self._retries:
                    log.warning("HTTP %s on %s; retry %d", r.status_code, path, attempt)
                    time.sleep(delay)
                    delay *= 2
                    continue
                return r
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                log.warning("Transport error on %s: %s (attempt %d)", path, exc, attempt)
                time.sleep(delay)
                delay *= 2
        raise ZosmfError(f"Request failed after {self._retries} attempts: {last_exc}")

    def _json(self, method: str, path: str, **kw):
        r = self.request(method, path, **kw)
        if r.status_code >= 400:
            raise ZosmfError(f"{method} {path} -> HTTP {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else {}

    # ---- jobs ---------------------------------------------------------
    def submit_dataset_job(self, dsn_member: str) -> dict:
        return self._json("PUT", "/zosmf/restjobs/jobs", json={"file": f"//'{dsn_member}'"},
                          headers={"Content-Type": "application/json"})

    def job_status(self, jobname: str, jobid: str) -> dict:
        return self._json("GET", f"/zosmf/restjobs/jobs/{jobname}/{jobid}")

    def list_jobs(self, prefix: str, owner: str, status: str | None = None) -> list[dict]:
        params = {"prefix": prefix, "owner": owner}
        if status:
            params["status"] = status
        return self._json("GET", "/zosmf/restjobs/jobs", params=params)

    def wait_for_output(self, jobname: str, jobid: str,
                        timeout_s: int = 900, poll_s: float = 5.0) -> dict:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            info = self.job_status(jobname, jobid)
            if info.get("status") == "OUTPUT":
                return info
            time.sleep(poll_s)
        raise ZosmfError(f"Timeout waiting for {jobname}({jobid}) to reach OUTPUT")

    def list_spool(self, jobname: str, jobid: str) -> list[dict]:
        return self._json("GET", f"/zosmf/restjobs/jobs/{jobname}/{jobid}/files")

    def spool_text(self, jobname: str, jobid: str, file_id: int) -> str:
        r = self.request("GET", f"/zosmf/restjobs/jobs/{jobname}/{jobid}/files/{file_id}/records",
                         headers={"X-IBM-Data-Type": "text"})
        if r.status_code == 403:
            raise ZosmfError(f"Spool access denied for {jobname}({jobid}) file {file_id}; "
                             "check JESSPOOL permissions for the service ID")
        if r.status_code >= 400:
            raise ZosmfError(f"Spool read failed: HTTP {r.status_code} {r.text[:200]}")
        return r.text

    def purge(self, jobname: str, jobid: str) -> None:
        r = self.request("DELETE", f"/zosmf/restjobs/jobs/{jobname}/{jobid}")
        if r.status_code >= 400:
            log.warning("Purge of %s(%s) failed: HTTP %s", jobname, jobid, r.status_code)

    # ---- datasets -----------------------------------------------------
    def read_dataset(self, dsn: str) -> str:
        r = self.request("GET", f"/zosmf/restfiles/ds/{dsn}", headers={"X-IBM-Data-Type": "text"})
        if r.status_code >= 400:
            raise ZosmfError(f"Dataset read failed for {dsn}: HTTP {r.status_code} {r.text[:200]}")
        return r.text

    def close(self) -> None:
        self.http.close()


# ------------------------------------------------------------------ collection
def collect_job_text(client: ZosmfClient, jobname: str, jobid: str,
                     default_subsys: str = "UNKNOWN", default_sysid: str = "UNKNOWN") -> str:
    """One raw text blob for a finished job, ready for normalize_z_event."""
    info = client.job_status(jobname, jobid)
    parts = [f"==== JOBINFO jobname={jobname} jobid={jobid} status={info.get('status')} "
             f"retcode={info.get('retcode')} owner={info.get('owner')} ===="]
    saw_cfmetric = False
    for f in client.list_spool(jobname, jobid):
        ddname = f.get("ddname", "")
        if ddname not in WANTED_DDS:
            continue
        text = client.spool_text(jobname, jobid, int(f["id"]))
        if "CFMETRIC" in text and ddname != "JESJCL":
            saw_cfmetric = True
        parts.append(f"---- DD {ddname} (step={f.get('stepname')}) ----")
        parts.append(text.rstrip())
    if not saw_cfmetric:   # job never produced metrics (e.g., JCL error)
        sysid_part = "" if default_sysid in ("", "AUTO", "UNKNOWN") else f" SYSID={default_sysid}"
        parts.append(f"CFMETRIC SUBSYS={default_subsys}{sysid_part} DEPLOY=N")
    return "\n".join(parts) + "\n"


# ------------------------------------------------------------------ checkpointing
def load_state(path: Path) -> set[str]:
    if path.exists():
        try:
            return set(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError) as exc:
            log.error("Checkpoint %s unreadable (%s); starting empty", path, exc)
    return set()


def save_state(path: Path, seen: set[str]) -> None:
    """Atomic write so a crash never leaves a half-written checkpoint."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(sorted(seen)), encoding="utf-8")
    os.replace(tmp, path)


def harvest(client: ZosmfClient, prefix: str, owner: str, seen: set[str],
            default_subsys: str, default_sysid: str) -> list[tuple[str, str, str, str]]:
    """Return [(jobname, jobid, key, raw_text)] for finished jobs not in `seen`.
    Does NOT modify the checkpoint: the caller commits after successful delivery."""
    out: list[tuple[str, str, str, str]] = []
    for job in client.list_jobs(prefix, owner, status="OUTPUT"):
        key = f"{job['jobname']}:{job['jobid']}"
        if key in seen:
            continue
        try:
            blob = collect_job_text(client, job["jobname"], job["jobid"], default_subsys, default_sysid)
        except ZosmfError as exc:
            log.error("Skipping %s: %s", key, exc)
            continue
        out.append((job["jobname"], job["jobid"], key, blob))
    return out


def client_from_env() -> ZosmfClient:
    v = os.environ.get("ZOSMF_VERIFY_TLS", "true")
    verify: bool | str = (v.lower() == "true") if v.lower() in ("true", "false") else v
    return ZosmfClient(os.environ["ZOSMF_URL"], os.environ["ZOSMF_USER"],
                       os.environ["ZOSMF_PASSWORD"], verify=verify)


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--submit", help="dataset(member) to submit, e.g. USER.CRITFLOW.JCL(RUNEXTR)")
    g.add_argument("--job", nargs=2, metavar=("JOBNAME", "JOBID"))
    g.add_argument("--dataset", help="read a sequential dataset, e.g. USER.CRITFLOW.EXTRACT.OUTPUT")
    g.add_argument("--harvest", metavar="PREFIX", help="save all new finished jobs matching prefix, e.g. 'PAY*'")
    ap.add_argument("--owner", default=os.environ.get("ZOSMF_USER", "*"))
    ap.add_argument("--subsys", default="PAYMENT-API")
    ap.add_argument("--sysid", default="SYSA")
    ap.add_argument("--out", type=Path, required=True, help="file (directory for --harvest)")
    ap.add_argument("--state", type=Path, default=Path(".cf_harvest_state.json"))
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        client = client_from_env()
    except (KeyError, ZosmfError) as exc:
        log.error("Cannot start: %s", exc)
        return 2
    try:
        if a.dataset:
            a.out.write_text(client.read_dataset(a.dataset), encoding="utf-8")
        elif a.harvest:
            a.out.mkdir(parents=True, exist_ok=True)
            seen = load_state(a.state)
            for _n, _i, key, blob in harvest(client, a.harvest, a.owner, seen, a.subsys, a.sysid):
                (a.out / (key.replace(":", "_") + ".txt")).write_text(blob, encoding="utf-8")
                seen.add(key)               # delivery here = file written
                save_state(a.state, seen)
                log.info("saved %s", key)
        else:
            if a.submit:
                sub = client.submit_dataset_job(a.submit)
                jobname, jobid = sub["jobname"], sub["jobid"]
                log.info("Submitted %s(%s)", jobname, jobid)
            else:
                jobname, jobid = a.job
            client.wait_for_output(jobname, jobid, poll_s=float(os.environ.get("CF_POLL_S", "5")))
            a.out.write_text(collect_job_text(client, jobname, jobid, a.subsys, a.sysid), encoding="utf-8")
        return 0
    except ZosmfError as exc:
        log.error("%s", exc)
        return 2
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())

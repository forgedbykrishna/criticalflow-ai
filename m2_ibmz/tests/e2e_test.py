#!/usr/bin/env python3
"""End-to-end test of Approach A against the local z/OSMF simulator and the M3 stub.
Run from the project root:  python tests/e2e_test.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ZP, AP = 18081, 18000
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name} {detail}")


def spawn(app: str, port: int, env: dict) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-m", "uvicorn", app, "--port", str(port), "--log-level", "warning"],
                            cwd=ROOT, env={**os.environ, **env, "PYTHONPATH": str(ROOT)})


def wait(url: str) -> None:
    for _ in range(60):
        try:
            if httpx.get(url, timeout=1).status_code < 500:
                return
        except httpx.HTTPError:
            time.sleep(0.25)
    raise RuntimeError(f"{url} did not start")


def run(cmd: list[str], env: dict) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *cmd], cwd=ROOT, text=True, capture_output=True,
                          env={**os.environ, "PYTHONPATH": str(ROOT), **env})


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    zmf = spawn("mock_zosmf.server:app", ZP, {"MOCK_USER": "CFSVC", "MOCK_PASS": "secret"})
    m3 = spawn("m3_handoff.m3_stub_api:app", AP, {"API_TOKEN": "t0ken"})
    try:
        wait(f"http://127.0.0.1:{ZP}/zosmf/info")
        wait(f"http://127.0.0.1:{AP}/health")
        base_env = {"ZOSMF_URL": f"http://127.0.0.1:{ZP}", "ZOSMF_USER": "CFSVC", "ZOSMF_PASSWORD": "secret",
                    "MOCK_MODE": "False", "CF_JOB_PREFIX": "PAY*,GL*", "API_BASE_URL": f"http://127.0.0.1:{AP}",
                    "API_TOKEN": "t0ken", "CF_STATE_FILE": str(tmp / "state.json"),
                    "CF_QUARANTINE_DIR": str(tmp / "q"), "CF_POLL_S": "0.2"}

        # 1. wrong password is rejected cleanly
        from extract.extract_zosmf import ZosmfClient, ZosmfError, collect_job_text, harvest
        try:
            ZosmfClient(base_env["ZOSMF_URL"], "CFSVC", "wrong")
            check("bad credentials rejected", False)
        except ZosmfError as e:
            check("bad credentials rejected", "authentication failed" in str(e))

        # 2. harvest + normalize equals golden files
        from contract.normalize_z_event import normalize
        c = ZosmfClient(base_env["ZOSMF_URL"], "CFSVC", "secret")
        got = []
        for p in ("PAY*", "GL*"):
            got += harvest(c, p, "CFSVC", set(), "PAYMENT-API", "SYSA")
        check("harvest returns 4 finished jobs", len(got) == 4, f"({[g[2] for g in got]})")
        exp = {json.loads(f.read_text())["job_id"]: json.loads(f.read_text())
               for f in (ROOT / "datasets" / "expected").glob("*.json")}
        ok = all(normalize(blob) == exp[jid] for _n, jid, _k, blob in got)
        check("live-path events identical to golden files", ok)

        # 3. submit + wait path
        sub = c.submit_dataset_job("USER.CRITFLOW.JCL(RUNEXTR)")
        info = c.wait_for_output(sub["jobname"], sub["jobid"], poll_s=0.1)
        ev = normalize(collect_job_text(c, sub["jobname"], sub["jobid"]))
        check("submit -> wait -> collect", info["status"] == "OUTPUT" and ev["job_name"] == "RUNEXTR")
        c.purge(sub["jobname"], sub["jobid"])
        c.close()

        # 4. API down: nothing committed, pipeline reports deferral
        r = run(["run_pipeline.py", "--once"], {**base_env, "API_BASE_URL": "http://127.0.0.1:1"})
        state = (tmp / "state.json")
        check("API down -> exit 1, checkpoint untouched", r.returncode == 1 and not state.exists(), r.stdout[-0:] or "")

        # 5. wrong API token -> exit 3
        r = run(["run_pipeline.py", "--once"], {**base_env, "API_TOKEN": "bad"})
        check("bad API token -> exit 3", r.returncode == 3)

        # 6. healthy run delivers all 4
        r = run(["run_pipeline.py", "--once"], base_env)
        stored = httpx.get(f"http://127.0.0.1:{AP}/api/v1/incidents", headers={"Authorization": "Bearer t0ken"}).json()
        check("pipeline delivered 4 incidents", r.returncode == 0 and len(stored) == 4, r.stderr[-300:])
        by_id = {e["incident_id"]: e for e in stored}
        check("stored S0C4 incident correct",
              by_id["INC-20260930-JOB05581-PAYAUTH2"]["abend_code"] == "S0C4")

        # 7. second run: checkpoint prevents re-delivery
        r = run(["run_pipeline.py", "--once"], base_env)
        check("second run harvests nothing new", "'harvested': 0" in r.stderr, "")

        # 8. smoke test in live mode
        r = run(["verify_integration.py", "--unique"], base_env)
        check("verify_integration.py (live) passes", r.returncode == 0, r.stdout[-200:] if r.returncode else "")
    finally:
        for p in (zmf, m3):
            p.terminate()
            p.wait(timeout=10)
    failed = [n for n, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

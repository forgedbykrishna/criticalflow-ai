#!/usr/bin/env python3
"""Submit the 4 sample JCL jobs to z/OS via z/OSMF and wait for each to finish.
   Env: ZOSMF_URL ZOSMF_USER ZOSMF_PASSWORD ZOSMF_VERIFY_TLS
        CF_JOB_CLASS (default 7 = IBM Z Xplore class used by CHKVSC)   CF_JOB_MSGCLASS (optional, default none)"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extract.extract_zosmf import ZosmfError, client_from_env  # noqa: E402

JCL_DIR = Path(__file__).resolve().parents[1] / "jcl_samples"
GOOD = ("CC ", "ABEND", "JCL ERROR")


def show_spool(c, jobname: str, jobid: str) -> None:
    """Print the key messages so a failure explains itself."""
    for f in c.list_spool(jobname, jobid):
        if f.get("ddname") in ("JESMSGLG", "JESJCL", "JESYSMSG"):
            text = c.spool_text(jobname, jobid, int(f["id"]))
            for line in text.splitlines():
                if any(k in line for k in ("ICH", "IEF", "$HASP", "SECURITY", "NOT AUTHORIZED", "CLASS")):
                    print("      |", line.strip()[:150])


def main() -> int:
    user = os.environ["ZOSMF_USER"].upper()
    jcl_class = os.environ.get("CF_JOB_CLASS", "7")
    msgclass = os.environ.get("CF_JOB_MSGCLASS", "")
    c = client_from_env()
    rc = 0
    try:
        for f in sorted(JCL_DIR.glob("*.jcl")):
            jcl = (f.read_text().replace("{USER}", user).replace("{CLASS}", jcl_class)
                   .replace("{MSGCLASS}", f",MSGCLASS={msgclass}" if msgclass else ""))
            r = c.request("PUT", "/zosmf/restjobs/jobs", content=jcl.encode(),
                          headers={"Content-Type": "text/plain"})
            if r.status_code >= 400:
                print(f"FAIL submit {f.name}: HTTP {r.status_code} {r.text[:300]}")
                rc = 1
                continue
            j = r.json()
            info = c.wait_for_output(j["jobname"], j["jobid"], timeout_s=300, poll_s=2)
            ret = info.get("retcode") or ""
            ok = ret.startswith(GOOD)
            print(f"{'OK  ' if ok else 'BAD '} {f.name}: {j['jobname']} {j['jobid']} -> {ret}")
            if not ok:
                rc = 1
                show_spool(c, j["jobname"], j["jobid"])
    except ZosmfError as exc:
        print(f"ERROR {exc}")
        rc = 2
    finally:
        c.close()
    return rc


if __name__ == "__main__":
    sys.exit(main())

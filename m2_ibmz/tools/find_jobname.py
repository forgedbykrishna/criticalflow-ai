#!/usr/bin/env python3
"""Find which job names Xplore's RACF lets your userid submit (ICH408I 'NOT AUTHORIZED TO SUBMIT JOB').
Submits a harmless IEFBR14 job under several candidate names and prints which ones run.
Env: ZOSMF_URL ZOSMF_USER ZOSMF_PASSWORD ZOSMF_VERIFY_TLS [CF_JOB_CLASS=7]"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extract.extract_zosmf import ZosmfError, client_from_env  # noqa: E402

user = os.environ["ZOSMF_USER"].upper()
cls = os.environ.get("CF_JOB_CLASS", "7")
CANDIDATES = ["@CFA", "@CF1", "@M2A", "@JCL9", "@CODE9", "@USS9", "@REXX9", "@CFTEST", "@" + user, "JCL9", user, "CFA"]
c = client_from_env()
found = []
try:
    for name in CANDIDATES:
        jcl = f"//{name:<8} JOB ,MSGLEVEL=(1,1),CLASS={cls}\n//STEP1    EXEC PGM=IEFBR14\n"
        r = c.request("PUT", "/zosmf/restjobs/jobs", content=jcl.encode(), headers={"Content-Type": "text/plain"})
        if r.status_code >= 400:
            print(f"{name:10} submit rejected: HTTP {r.status_code}")
            continue
        j = r.json()
        info = c.wait_for_output(j["jobname"], j["jobid"], timeout_s=120, poll_s=2)
        ok = (info.get("retcode") or "").startswith("CC ")
        print(f"{name:10} -> {info.get('retcode')}   {'ALLOWED' if ok else 'refused'}")
        if ok:
            found.append(name)
            if len(found) >= 2:
                break
except ZosmfError as exc:
    sys.exit(f"ERROR {exc}")
finally:
    c.close()
if found:
    base = found[0][:-1] if found[0][-1].isalnum() and len(found[0]) > 2 else found[0]
    print(f"\nUse:  export CF_JOBNAME_BASE='{base}'   (jobs become {base}A..D)")
    print(f"      export CF_JOB_PREFIX='{base}*'")
else:
    print("\nNo candidate worked. Open the JCL member from your JCL1/JCL3 challenge and copy its JOB name pattern.")

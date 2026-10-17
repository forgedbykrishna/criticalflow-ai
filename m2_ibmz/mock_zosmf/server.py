"""Local simulator of the z/OSMF REST endpoints used by Approach A (for offline development/CI).
Serves the four bundled scenarios as finished jobs owned by CFSVC.

  MOCK_USER=CFSVC MOCK_PASS=secret uvicorn mock_zosmf.server:app --port 8081
Implements: POST /zosmf/services/authenticate, GET /zosmf/info, GET/PUT/DELETE /zosmf/restjobs/jobs...,
            GET .../files, GET .../files/{id}/records, GET /zosmf/restfiles/ds/{dsn}
Not a security model: it checks the CSRF header and credentials only.
"""
from __future__ import annotations

import base64
import fnmatch
import os
from pathlib import Path

from fastapi import Cookie, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse

from contract.normalize_z_event import normalize

RAW_DIR = Path(os.environ.get("MOCK_RAW_DIR", Path(__file__).resolve().parents[1] / "datasets" / "raw"))
USER, PASSWORD = os.environ.get("MOCK_USER", "CFSVC"), os.environ.get("MOCK_PASS", "secret")
TOKEN = "mock.jwt.token"

app = FastAPI(title="Mock z/OSMF")
JOBS: dict[tuple[str, str], dict] = {}
_next_id = [7000]


def _retcode(ev: dict) -> str:
    if ev["completion_status"] == "CC":
        return f"CC {ev['return_code']:04d}"
    return f"ABEND {ev['abend_code']}" if ev["completion_status"] == "ABEND" else "JCL ERROR"


def _register(text: str, status: str = "OUTPUT", polls_to_output: int = 0) -> dict:
    ev = normalize(text)
    job = {"jobname": ev["job_name"], "jobid": ev["job_id"], "owner": USER, "status": status,
           "type": "JOB", "class": "A", "subsystem": "JES2", "retcode": _retcode(ev),
           "text": text, "polls": polls_to_output}
    JOBS[(job["jobname"], job["jobid"])] = job
    return job


for f in sorted(RAW_DIR.glob("scenario*.txt")):
    _register(f.read_text(encoding="utf-8"))


def _auth(authorization: str | None, jwt: str | None) -> None:
    if jwt == TOKEN:
        return
    if authorization and authorization.startswith("Basic "):
        u, _, p = base64.b64decode(authorization[6:]).decode().partition(":")
        if (u, p) == (USER, PASSWORD):
            return
    raise HTTPException(status_code=401, detail="unauthorized")


def _csrf(x_csrf: str | None) -> None:
    if x_csrf is None:
        raise HTTPException(status_code=403, detail="missing X-CSRF-ZOSMF-HEADER")


def _public(j: dict) -> dict:
    d = {k: j[k] for k in ("jobname", "jobid", "owner", "status", "type", "class", "subsystem", "retcode")}
    d["url"] = f"/zosmf/restjobs/jobs/{j['jobname']}/{j['jobid']}"
    d["files-url"] = d["url"] + "/files"
    return d


@app.get("/zosmf/info")
def info() -> dict:
    return {"zosmf_version": "mock-1.0", "zos_version": "04.30.00", "zosmf_hostname": "mock"}


@app.post("/zosmf/services/authenticate")
def authenticate(response: Response, authorization: str | None = Header(default=None),
                 x_csrf_zosmf_header: str | None = Header(default=None)):
    _csrf(x_csrf_zosmf_header)
    if not authorization:
        raise HTTPException(status_code=401, detail="no credentials")
    _auth(authorization, None)
    response.set_cookie("jwtToken", TOKEN, httponly=True)
    response.status_code = 200
    return {}


@app.get("/zosmf/restjobs/jobs")
def list_jobs(prefix: str = "*", owner: str = "*", status: str | None = None,
              authorization: str | None = Header(default=None), jwtToken: str | None = Cookie(default=None),
              x_csrf_zosmf_header: str | None = Header(default=None)):
    _auth(authorization, jwtToken)
    return [_public(j) for j in JOBS.values()
            if fnmatch.fnmatchcase(j["jobname"], prefix.upper())
            and owner in ("*", j["owner"]) and (status is None or j["status"] == status)]


@app.get("/zosmf/restjobs/jobs/{jobname}/{jobid}")
def job_status(jobname: str, jobid: str, authorization: str | None = Header(default=None),
               jwtToken: str | None = Cookie(default=None)):
    _auth(authorization, jwtToken)
    j = JOBS.get((jobname, jobid))
    if not j:
        raise HTTPException(status_code=404, detail="job not found")
    if j["status"] == "ACTIVE":
        j["polls"] -= 1
        if j["polls"] <= 0:
            j["status"] = "OUTPUT"
    return _public(j)


@app.get("/zosmf/restjobs/jobs/{jobname}/{jobid}/files")
def files(jobname: str, jobid: str, authorization: str | None = Header(default=None),
          jwtToken: str | None = Cookie(default=None)):
    _auth(authorization, jwtToken)
    if (jobname, jobid) not in JOBS:
        raise HTTPException(status_code=404, detail="job not found")
    return [{"id": 2, "ddname": "JESMSGLG", "stepname": "JES2", "class": "A", "recfm": "UA", "lrecl": 133},
            {"id": 3, "ddname": "JESJCL", "stepname": "JES2", "class": "A", "recfm": "V", "lrecl": 136}]


@app.get("/zosmf/restjobs/jobs/{jobname}/{jobid}/files/{file_id}/records", response_class=PlainTextResponse)
def records(jobname: str, jobid: str, file_id: int, authorization: str | None = Header(default=None),
            jwtToken: str | None = Cookie(default=None)):
    _auth(authorization, jwtToken)
    j = JOBS.get((jobname, jobid))
    if not j:
        raise HTTPException(status_code=404, detail="job not found")
    if file_id == 2:
        return j["text"]
    if file_id == 3:
        return f"//{jobname} JOB (ACCT01),'BATCH',CLASS=A,MSGCLASS=H\n"
    raise HTTPException(status_code=404, detail="file not found")


@app.put("/zosmf/restjobs/jobs")
async def submit(request: Request, authorization: str | None = Header(default=None),
                 jwtToken: str | None = Cookie(default=None), x_csrf_zosmf_header: str | None = Header(default=None)):
    _auth(authorization, jwtToken)
    _csrf(x_csrf_zosmf_header)
    body = await request.json()
    if "file" not in body:
        raise HTTPException(status_code=400, detail="file required")
    _next_id[0] += 1
    jid = f"JOB{_next_id[0]:05d}"
    base = (RAW_DIR / "scenario1_normal.txt").read_text(encoding="utf-8")
    text = base.replace("PAYSETL1", "RUNEXTR").replace("JOB04127", jid)
    job = _register(text, status="ACTIVE", polls_to_output=2)
    return _public(job)


@app.delete("/zosmf/restjobs/jobs/{jobname}/{jobid}")
def purge(jobname: str, jobid: str, authorization: str | None = Header(default=None),
          jwtToken: str | None = Cookie(default=None), x_csrf_zosmf_header: str | None = Header(default=None)):
    _auth(authorization, jwtToken)
    _csrf(x_csrf_zosmf_header)
    if JOBS.pop((jobname, jobid), None) is None:
        raise HTTPException(status_code=404, detail="job not found")
    return {"jobid": jobid, "jobname": jobname, "status": 0}


@app.get("/zosmf/restfiles/ds/{dsn}", response_class=PlainTextResponse)
def read_ds(dsn: str, authorization: str | None = Header(default=None), jwtToken: str | None = Cookie(default=None)):
    _auth(authorization, jwtToken)
    if dsn != "USER.CRITFLOW.EXTRACT.OUTPUT":
        raise HTTPException(status_code=404, detail="dataset not found")
    return "CFRC STEP=STEP010 STATUS=CC RC=0000\n"

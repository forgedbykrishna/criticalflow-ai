# CriticalFlow AI - M2 (IBM Z) to M3 (Backend) Handoff

Prepared 2026-10-11 by M2 (IBM Z Engineer). Contract version **1.0.0**. Package contains 12 real events
extracted from z/OS (IBM Z Xplore, system S0W1); samples are copied from the real run.

## 1. What M2 delivers
One JSON event per **finished z/OS batch job** (JES status OUTPUT), produced by: z/OSMF REST harvest ->
regex normalization -> JSON Schema validation -> `POST /api/v1/incidents`.

## 2. Endpoint M3 must provide
| Item | Value |
|---|---|
| Method / path | `POST /api/v1/incidents` |
| Health check | `GET /health` -> 200 |
| Content type | `application/json` |
| Auth | `Authorization: Bearer <token>` (401 when missing/wrong) |
| New incident | **201 Created** `{"incident_id": "...", "created": true}` |
| Same `incident_id` again | **200 OK** `{"created": false}` (idempotent, no second row) |
| Invalid payload | **422** (M2 quarantines the event and does not retry) |
| Auth failure | **401/403** (M2 stops and exits with code 3) |
| 5xx / 429 / timeout | M2 retries on the next cycle (nothing is lost) |

M2 delivery is **at-least-once**, so duplicates will happen; `incident_id` is the idempotency key
(`INC-YYYYMMDD-<JOBID>-<JOBNAME>`, UNIQUE in the database).

## 3. Payload example (real event)
```json
{
  "schema_version": "1.0.0",
  "incident_id": "INC-20261011-JOB03536-Z75376B",
  "timestamp": "2026-10-11T05:08:47Z",
  "system_id": "S0W1",
  "subsystem": "PAYMENT-API",
  "job_name": "Z75376B",
  "job_id": "JOB03536",
  "step_name": "STEP020",
  "completion_status": "ABEND",
  "return_code": null,
  "abend_code": "S806",
  "primary_message_id": "IEF450I",
  "cpu_utilization_pct": null,
  "error_rate_pct": null,
  "transaction_volume_per_hr": null,
  "recent_deployment_flag": false,
  "raw_log_snippet": "00.08.43 JOB03536  $HASP373 Z75376B  STARTED - INIT 2    - CLASS 7        - SYS S0W1\n00.08.43 JOB03536  -STEPNAME PROCSTEP    RC   EXCP   CONN       TCB       SRB  CLOCK          SERV  WORKLOAD  PAGE  SWAP   VIO SWAPS\n00.08.47 JOB03536  IEA848I NO DUMP WAS PRODUCED FOR THIS ABEND, DUE TO SYSTEM OR INSTALLATION REQUEST\n00.08.47 JOB03536  IEF450I Z75376B STEP020 - ABEND=S806 U0000 REASON=00000004\n00.08.47 JOB03536  $HASP395 Z75376B  ENDED - ABEND=S806\nIEF142I Z75376B STEP010 - STEP WAS EXECUTED - COND CODE 0000\nIEF373I STEP/STEP010 /START 2026284.0008\nIEF032I STEP/STEP010 /STOP  2026284.0008\nIEF285I   SYS26284.T000844.RA000.Z75376B.T7799954.H01  DELETED\nIEF237I DMY  ALLOCATED TO IDITRACE\nIEF237I 0D2F ALLOCATED TO SYS00003\nIEF285I   VENDOR.PARMLIB                               KEPT\nIEF285I   VOL SER NOS= VPMVSE.\nIEF237I 1005 ALLOCATED TO SYS00004\nIEF285I   SVTSC.PARMLIB                                KEPT\nIEF285I   VOL SER NOS= VTMVSG.\nIEF237I 100E ALLOCATED TO SYS00005\nIEF285I   LVL0.PARMLIB                                 KEPT\nIEF285I   VOL SER NOS= VTLVL0.\nIEF237I 1000 ALLOCATED TO SYS00006\nIEF285I   SYS1.PARMLIB                                 KEPT\nIEF285I   VOL SER NOS= VIMVSB.\nIEF237I 0D2F ALLOCATED TO SYS00007\nIEF285I   VENDOR.PARMLIB                               KEPT\nIEF285I   VOL SER NOS= VPMVSE.\nIEF237I 1005 ALLOCATED TO SYS00008\nIEF285I   SVTSC.PARMLIB                                KEPT\nIEF285I   VOL SER NOS= VTMVSG.\nIEF237I 100E ALLOCATED TO SYS00009\nIEF285I   LVL0.PARMLIB                                 KEPT\nIEF285I   VOL SER NOS= VTLVL0.\nIEF237I 1000 ALLOCATED TO SYS00010\nIEF285I   SYS1.PARMLIB                                 KEPT\nIEF285I   VOL SER NOS= VIMVSB.\nIEF237I 0D2F ALLOCATED TO SYS00011\nIEF285I   VENDOR.PARMLIB                               KEPT\nIEF285I   VOL SER NOS= VPMVSE.\nIEF237I 1005 ALLOCATED TO SYS00012\nIEF285I   SVTSC.PARMLIB                                KEPT\nIEF285I   VOL SER NOS= VTMVSG.\nIEF237I 1D70 ALLOCATED TO SYS00013\nIEF285I   ISM402.SIDIDOC1                              KEPT\nIEF285I   VOL SER NOS= VTISMH.\nIEF237I 1D72 ALLOCATED TO SYS00014\nIEF237I 1D70 ALLOCATED TO SYS00015\nIEF285I   ISM402.SIDIMAPS                              KEPT\nIEF285I   VOL SER NOS= VTISMH.\nIEF237I 1D72 ALLOCATED TO SYS00017\nIEF237I JES2 ALLOCATED TO IDIREPRT\nIEF237I 1D70 ALLOCATED TO SYS00018\nIEF237I 1D70 ALLOCATED TO SYS00019\nIEF237I 1D72 ALLOCATED TO SYS00020\nIEF237I 1D70 ALLOCATED TO SYS00021\nIEF237I 1D70 ALLOCATED TO SYS00022\nIEF237I 1D70 ALLOCATED TO SYS00023\nIEF285I   ISM402.SIDIDOC1                              KEPT\nIEF285I   VOL SER NOS= VTISMH.\nIEF237I DMY  ALLOCATED TO SYS00024\nIEF237I 1D70 ALLOCATED TO SYS00025\nIEF285I   ISM402.SIDIMAPS                              KEPT\nIEF285I   VOL SER NOS= VTISMH.\nIEF237I 1D72 ALLOCATED TO SYS00026\nIEF285I   ISM402.HIST                                  KEPT\nIEF285I   VOL SER NOS= VPISMH.\nIEF285I   ISM402.SIDIDOC1                              KEPT\nIEF285I   VOL SER NOS= VTISMH.\nIEF285I   ISM402.SIDIDOC1                              KEPT\nIEF285I   VOL SER NOS= VTISMH.\nIEF285I   ISM402.SIDIDOC1                              KEPT\nIEF285I   VOL SER NOS= VTISMH.\nIEF285I   ISM402.SIDIDOC1                              KEPT\nIEF285I   VOL SER NOS= VTISMH.\nIEF285I   Z75376.Z75376B.JOB03536.D0000101.?           SYSOUT\nIEA848I NO DUMP WAS PRODUCED FOR THIS ABEND, DUE TO SYSTEM OR INSTALLATION REQUEST\nIEF472I Z75376B STEP020 - COMPLETION CODE - SYSTEM=806 USER=0000 REASON=00000004\nIEF373I STEP/STEP020 /START 2026284.0008\nIEF032I STEP/STEP020 /STOP  2026284.0008\nIEF375I  JOB/Z75376B /START 2026284.0008\nIEF033I  JOB/Z75376B /STOP  2026284.0008\nCFMETRIC SUBSYS=PAYMENT-API DEPLOY=N"
}
```

## 4. Field dictionary
| Field | Type | Nullable | Meaning / rules | `incidents` column |
|---|---|---|---|---|
| `schema_version` | const "1.0.0" | no | reject other versions with 422 | `schema_version` |
| `incident_id` | string | no | idempotency key, `^INC-\d{8}-(JOB\|STC\|TSU)\d{5,8}-<jobname>$` | `incident_id` UNIQUE |
| `timestamp` | string `YYYY-MM-DDTHH:MM:SSZ` | no | job end time in **UTC** | `event_ts TIMESTAMPTZ` |
| `system_id` | string, 1-8 | no | z/OS system (e.g. `S0W1`) | `system_id` |
| `subsystem` | string | no | `PAYMENT-API`, `CICS-PROD`, `GL-BATCH`... | `subsystem` |
| `job_name` | string, 1-8 | no | may start with `@`, `#`, `$` | `job_name` |
| `job_id` | string | no | `JOBnnnnn` / `STCnnnnn` / `TSUnnnnn` | `job_id` |
| `step_name` | string | no | failing step, or highest-RC step; `JCL` when unknown | `step_name` |
| `completion_status` | enum | no | `CC`, `ABEND`, `JCL_ERROR` (see section 5) | `completion_status` |
| `return_code` | int 0-4095 | yes | non-null **only** when `CC` | `return_code` |
| `abend_code` | string | yes | `S0C4`, `S806`, `U4038`; non-null **only** when `ABEND` | `abend_code` |
| `primary_message_id` | string | yes | signature message (`IEF450I`, `IEF212I`, `$HASP395`, `ICH408I`) | `primary_message_id` |
| `cpu_utilization_pct` | number 0-100 | yes | null when the job reports no metrics | `cpu_utilization_pct NUMERIC(5,2)` |
| `error_rate_pct` | number 0-100 | yes | same | `error_rate_pct NUMERIC(5,2)` |
| `transaction_volume_per_hr` | int >= 0 | yes | same | `transaction_volume_per_hr INTEGER` |
| `recent_deployment_flag` | bool | no | false when unknown | `recent_deployment_flag` |
| `raw_log_snippet` | string 1-4000 | no | key JES message lines; long digit runs are masked | `raw_log_snippet TEXT` |

## 5. Status semantics (important for ML and the dashboard)
| `completion_status` | `return_code` | `abend_code` | Meaning |
|---|---|---|---|
| `CC` | integer (0 = success, 4 = warning, 8 = error, 12 = severe, 16 = terminal) | null | job ran to completion |
| `ABEND` | null | e.g. `S0C4`, `S806`, `U4038` | job terminated abnormally |
| `JCL_ERROR` | null | null | job never executed (JCL error, missing dataset, security refusal) - **this is a third enum value beyond CC/ABEND** |

**Null metrics are "missing", not zero.** Real Xplore jobs write no CPU/error-rate/throughput, so those three fields
are null in the real samples. In production they come from the application's `CFMETRIC` line or RMF/SMF.
The synthetic training dataset (separate zip) has all fields populated.

## 6. What is in this package
| Path | Purpose |
|---|---|
| `contract/criticalflow_event.schema.json` | JSON Schema (draft 2020-12) |
| `m3/models.py` | Pydantic v2 model `IBMZEventPayload` incl. status/return_code/abend_code consistency check |
| `m3/incidents.sql` | PostgreSQL DDL for `incidents` (CHECK constraints mirror the rules above) |
| `m3/incidents_api.py` | reference FastAPI + SQLAlchemy endpoint (PostgreSQL, `ON CONFLICT DO NOTHING`) |
| `m3/m3_stub_api.py` | in-memory stand-in with the same status codes - M2 tested against this |
| `samples/*.json` | real events: one success, one ABEND, one JCL_ERROR, one non-zero RC (when available) |
| `check_endpoint.py` | **acceptance test**: run it against your endpoint |

## 7. How M3 accepts the handoff (5 minutes)
```bash
pip install httpx fastapi pydantic "sqlalchemy[asyncio]" asyncpg uvicorn
psql -d criticalflow -f m3/incidents.sql
DATABASE_URL=postgresql+asyncpg://user:pw@localhost/criticalflow API_TOKEN=devtoken \
  python3 -m uvicorn m3.incidents_api:app --port 8000
API_BASE_URL=http://localhost:8000 API_TOKEN=devtoken python3 check_endpoint.py
```
Expected: `N/N checks passed` (201 for new, 200 for repeat, 422 for bad payloads, 401 for a wrong token).
If your endpoint differs from section 2, tell M2 which of the codes you want changed.

## 8. Known limits
1. Timestamps are converted to UTC using a configured mainframe offset (`CF_UTC_OFFSET`, currently -5 for US Central).
2. `step_name` is `JCL` for some JCL errors because the log does not name the failing step.
3. Real Xplore data has null metrics (see section 5).
4. Sample events contain only job-log message text (no dataset contents); long digit sequences are masked.

## 9. Open questions for M3
- Do you want `JCL_ERROR` mapped differently in your ML features (e.g. folded into ABEND)?
- Which token/auth scheme will production use (Bearer is assumed)?
- Preferred retry/backoff expectations when your service returns 429/503?

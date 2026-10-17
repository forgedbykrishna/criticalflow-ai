# CriticalFlow AI - M2 (IBM Z) to M3 (Backend) Handoff

Prepared {{DATE}} by M2 (IBM Z Engineer). Contract version **1.0.0**. Package contains {{EVENT_COUNT}} real events
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
{{SAMPLE_JSON}}
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

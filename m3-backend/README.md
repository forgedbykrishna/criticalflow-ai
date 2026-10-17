# CriticalFlow AI – M3 Backend / Orchestrator (Ingestion → Processing → M4 → M5 → PostgreSQL → FastAPI)

```
file (csv/tsv/jsonl/json/parquet/.gz) ─┐
POST /api/v1/ingest/events (JSON)  ────┼─► readers ─► field map ─► CLEAN ─► VALIDATE ─► FEATURES ─► PostgreSQL
POST /api/v1/ingest/file (upload)  ────┘                              │ bad records ─► quarantine_events (with reasons)
```

## Team flow (leader's diagram) – what M3 does
```
M2 --POST /incident--> M3: validate + clean + features + save
                        M3 --POST {M4_URL}/predict--> M4  -> save prediction  (incident_results)
                        M3 --POST {M5_URL}/explain--> M5  -> save explanation (rca_results)
                        status per incident in incident_pipeline: RECEIVED > PROCESSING > COMPLETE | M4_FAILED | M5_FAILED
M6 reads PostgreSQL view  incident_overview  (event + prediction + explanation + status in one row)
```
* `POST /incident` (also `/api/v1/incident`): body = event contract fields, or the diagram wrapper
  `{"incident_id": "...", "data": {...}}`. Default answers **202** and finishes M4/M5 in the background;
  `?wait=true` waits and returns everything. Invalid incident -> **422** + reasons (and it is quarantined).
* M4 receives `{incident_id, event_id, system, event_type, error_code, features{...}, context{...}, ...}`.
  Accepted answers: `{anomaly, severity, confidence}` (diagram) or `{incident_type, anomaly_score, severity}` (guide).
  `severity` any case -> stored as LOW/MEDIUM/HIGH/CRITICAL; needs `anomaly_score` or `confidence` (0-1).
* M5 receives `{incident_id, event{...}, prediction{anomaly, severity, confidence, anomaly_score}}`.
  Accepted answers: `{explanation, root_cause, recommendations[]}` (diagram) or `{root_cause, evidence[], impact,
  recommended_action, confidence}` (guide). Needs `root_cause` and recommendations.
* If M4/M5 is down or answers garbage, the incident stays saved with status `M4_FAILED`/`M5_FAILED` + the reason.
  Retry: `POST /api/v1/incidents/{id}/reprocess` or `POST /api/v1/incidents/reprocess-failed`.
  Every run replaces the previous M4/M5 answers for that incident (no stale prediction next to a new explanation).
* `M4_URL`/`M5_URL` empty = built-in MOCK (rule-based, tagged `source: mock`) so M3 works before M4/M5 exist.
  `GET /health` shows which URLs are active.
* Bulk loads (`/ingest/events`, `/ingest/file`, `scripts/run_pipeline`) clean + store only; they do NOT call M4/M5.

## Docker (M3 component)
```bash
docker build -t m3-backend . && docker run -p 8000:8000 --env-file .env m3-backend      # M3 alone
docker compose -f docker-compose.m3-dev.yml up --build                                   # M3 + Postgres + fake M4/M5
```
In the team compose use service names as hosts: `DATABASE_URL=postgresql+psycopg://postgres:PW@postgres:5432/criticalflow`,
`M4_URL=http://m4-prediction:8001`, `M5_URL=http://m5-llm:8002`. Fake M4/M5 for local tests:
`uvicorn mocks.m4_mock:app --port 8001`, `uvicorn mocks.m5_mock:app --port 8002`.

## Quick start
```bash
pip install -r requirements.txt
cp .env.example .env            # set DATABASE_URL (PostgreSQL)
python -m scripts.run_pipeline data/samples/training_data.csv      # batch load (tables auto-created)
uvicorn api.main:app --reload                                      # API + docs at http://localhost:8000/docs
pytest                                                             # 27 tests (SQLite by default)
TEST_DATABASE_URL=postgresql+psycopg://... pytest tests/integration   # same API tests on Postgres
```

## Endpoints (all under `/api/v1`, optional `X-API-Key` if `API_KEY` is set)
| Method | Path | Use |
|---|---|---|
| POST | `/ingest/events` | **M2 sends here.** One event, a list, or `{"events":[...]}`. Bad records never fail the request: they are quarantined and listed in the response |
| POST | `/ingest/file?format=` | Upload a dataset file (format auto-detected; `format` overrides) |
| GET | `/events/processed` | **M4/M5 read here.** Filters: `status, event_type, system, split, since, limit, offset` |
| GET | `/events/processed/{event_id}` | One event (includes training labels if present) |
| POST | `/incidents` | **M2 handoff endpoint** (full path `/api/v1/incidents`, `Authorization: Bearer <API_KEY>`): 201 new, 200 same incident_id again (nothing re-processed), 422 invalid or unknown field (quarantined), 401 bad token. Contract 1.0.0. Verified with M2's `check_endpoint.py` (14/14). Then M3 calls M4 + M5 in the background |
| POST | `/ai/incidents` | (optional push path, normally M3 calls M4 itself) **M4 results**: `{event_id, incident_type, anomaly_score 0-1, severity LOW/MEDIUM/HIGH/CRITICAL}` (one, list, or `{"results":[...]}`; extra fields kept) |
| POST | `/rca` | **M5 sends here**: `{event_id, root_cause, evidence[], impact, recommended_action, confidence}` |
| GET | `/ai/incidents`, `/rca/{event_id}` | Read back M4 / M5 results |
| GET | `/incidents/{event_id}/full` | Event + M4 result + M5 RCA in one JSON (for M1/M6 dashboard) |
| GET | `/events/quarantine`, `/stats`, `/health` | Data-quality / ops |

## Tables
`raw_events` (payload as received) · `processed_events` (event contract + `features`/`context`/`labels` as JSONB) ·
`incident_results` (M4) · `rca_results` (M5) · `quarantine_events` (rejected + errors) · `ingest_batches` (received/accepted/quarantined per call).
Writes are **idempotent** (upsert on `event_id`): re-running a file or re-sending an event never duplicates rows.

## Processed event handed to M4 / M5
```json
{"event_id":"INC-…","system":"SYSA","event_type":"JOB_FAILURE","error_code":"RC_12","status":"OPEN",
 "timestamp":"…Z","subsystem":"…","job_name":"…","features":{…25 model features…},"context":{…evidence incl. raw_log_snippet…}}
```
`event_type`: JOB_SUCCESS (RC 0) · JOB_WARNING (RC 1-4) · JOB_FAILURE (RC ≥ 8) · JOB_ABEND · JCL_ERROR
(rules in `processing/transform.py` – **confirm with M4/M5**; the team guide does not define the values).

## If the data format changes
* New file type → add one function with `@register_reader("ext")` in `ingestion/readers.py`.
* Renamed columns → map them in a JSON file (`config/field_map.example.json`), set `FIELD_MAP_PATH`.
* New/changed fields → edit `ingestion/schemas/criticalflow_event.schema.json`; cleaning and validation read it.
* Label columns (`risk_score, risk_label, is_high_risk, split, scenario_type`) are stored separately in `labels`
  and never mixed into the inference contract. Training must use the dataset's time-based `split` column (no shuffling).

## Design notes
* Features are **stateless** (same function for a training file and for one live event → no train/serve skew, no leakage).
* Missing metrics stay `null` + `*_missing` flags (README: "treat as missing, not zero").
* 13-19 digit runs in log snippets are masked (same rule as `normalize_z_event.py`).
* Synthetic data only – labels are rule-generated, so model scores are a pipeline test, not real accuracy.

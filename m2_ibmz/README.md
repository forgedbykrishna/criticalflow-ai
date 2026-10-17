# CriticalFlow AI - M2 IBM Z Pipeline (Approach A: z/OSMF REST)

```
z/OS JES spool --HTTPS--> extract_zosmf.py --> normalize_z_event.py --> POST /api/v1/incidents (M3)
                          (harvest, checkpoint)  (regex + JSON Schema)    (201 new / 200 duplicate)
```

## Quick start (no mainframe needed)
```bash
pip install -r requirements.txt
python tests/e2e_test.py                          # 10 checks against a local z/OSMF simulator + M3 stub
MOCK_MODE=True python verify_integration.py --no-post   # offline replay of the 4 scenarios vs golden files
```

## Run against a real LPAR
1. Complete the access checks (z/OSMF `GET /zosmf/info`, login, spool read) with the service ID.
2. `cp .env.example /etc/criticalflow/m2.env`, fill it in (secrets from a secret manager).
3. Dry run, no API: `set -a; . ./m2.env; set +a; python run_pipeline.py --once --dry-run --out-dir events/ -v`
4. Smoke test against M3: `python verify_integration.py --unique` (live, read-only, does not move the checkpoint)
5. Production: `python run_pipeline.py --interval 10 --purge` (systemd unit included) or `--once` from cron.

Jobs must expose a `CFMETRIC SUBSYS=.. SYSID=.. CPU_PCT=.. ERR_PCT=.. TPH=.. DEPLOY=Y|N` line in a spool DD
(JESMSGLG/SYSPRINT/CFMETRIC) to populate CPU, error rate and throughput; otherwise those fields are null.
If a job emits no CFMETRIC line, the extractor appends a context-only line using CF_DEFAULT_SUBSYSTEM/SYSTEM_ID.

## Delivery semantics
- At-least-once: a job's checkpoint (`CF_STATE_FILE`) moves only after the API returns 200/201.
- Idempotent: `incident_id = INC-<date>-<jobid>-<jobname>`; replays return 200, not duplicates.
- API down / 5xx / 429: cycle stops, nothing committed, retried next cycle. 401/403: exit 3 (fix token).
- Unparseable or API-rejected (400/422) jobs go to `CF_QUARANTINE_DIR` with the raw text and are not retried.
- `--purge` deletes a job's spool only after confirmed delivery.

## Layout
| Path | Role |
|---|---|
| `extract/extract_zosmf.py` | z/OSMF client: auth, retry, submit, spool read, harvest, atomic checkpoint |
| `contract/` | JSON Schema + `normalize_z_event.py` |
| `run_pipeline.py` | Production runner (poll, normalize, deliver, quarantine) |
| `pipeline_config.py`, `.env.example` | Mock/live switch and settings |
| `verify_integration.py` | Smoke test (asserts 201) |
| `m3_handoff/` | Pydantic model, PostgreSQL DDL, production endpoint, in-memory stub |
| `mock_zosmf/server.py` | z/OSMF simulator for dev/CI |
| `datasets/` | 4 raw scenarios + golden JSON |
| `criticalflow-m2.service` | systemd unit |

## Exit codes (run_pipeline.py)
0 ok | 1 deferred (API down/5xx) | 2 z/OSMF or startup error | 3 API auth error

## Not covered by the simulator
Real RACF/JESSPOOL permissions, TLS/AT-TLS behaviour, z/OSMF throttling, very large spool paging, and
site-specific `CFMETRIC` sources. Validate these once on your LPAR (see the troubleshooting matrix in the blueprint).

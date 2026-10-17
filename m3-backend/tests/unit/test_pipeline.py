import gzip
import json

from ingestion.readers import read_records, supported_formats
from processing.pipeline import run_pipeline
from tests.conftest import SAMPLE_CSV


def test_full_sample_dataset_is_clean():
    res = run_pipeline(read_records(SAMPLE_CSV))
    assert (res.received, len(res.processed), len(res.rejected)) == (3000, 3000, 0)
    assert all(p.labels and p.labels["split"] in {"train", "val", "test"} for p in res.processed)


def test_csv_jsonl_parquet_give_identical_output(tmp_path):
    csv_res = run_pipeline(read_records(SAMPLE_CSV))
    rows = [p.raw for p in csv_res.processed[:200]]
    jl = tmp_path / "e.jsonl"
    jl.write_text("\n".join(json.dumps(r) for r in rows))
    pq = tmp_path / "e.parquet"
    import pandas as pd
    pd.DataFrame(rows).to_parquet(pq)
    gz = tmp_path / "e.csv.gz"
    gz.write_bytes(gzip.compress(SAMPLE_CSV.read_bytes()))
    base = {p.event_id: p.as_contract() for p in csv_res.processed[:200]}
    for path in (jl, pq):
        out = {p.event_id: p.as_contract() for p in run_pipeline(read_records(path)).processed}
        assert out == base, path
    assert len(run_pipeline(read_records(gz)).processed) == 3000


def test_nulls_stay_null_not_zero(good_event):
    good_event.update(cpu_utilization_pct="", error_rate_pct=None)
    p = run_pipeline([good_event]).processed[0]
    f = p.features
    assert f["cpu_utilization_pct"] is None and f["cpu_missing"] and f["error_rate_missing"]
    assert not f["cpu_high"]


def test_bad_records_are_quarantined_not_dropped(good_event):
    bad_status = {**good_event, "incident_id": "INC-20260901-JOB10644-X1", "completion_status": "WEIRD"}
    bad_rule = {**good_event, "incident_id": "INC-20260901-JOB10644-X2", "completion_status": "ABEND"}  # needs abend_code
    bad_date = {**good_event, "incident_id": "INC-20260901-JOB10644-X3", "timestamp": "2026-02-31T01:00:00Z"}
    missing = {k: v for k, v in good_event.items() if k != "job_id"}
    res = run_pipeline([good_event, bad_status, bad_rule, bad_date, missing, "garbage"])
    assert len(res.processed) == 1 and len(res.rejected) == 5 and res.received == 6
    assert {r.stage for r in res.rejected} == {"validation", "parse"}


def test_duplicates_last_wins_and_pan_is_masked(good_event):
    dup = {**good_event, "raw_log_snippet": "card 4111111111111111 seen"}
    res = run_pipeline([good_event, dup])
    assert len(res.processed) == 1 and res.duplicates == 1
    assert "4111111111111111" not in res.processed[0].context["raw_log_snippet"]


def test_features_are_stateless_and_deterministic(good_event):
    a = run_pipeline([good_event]).processed[0].features
    b = run_pipeline([good_event]).processed[0].features
    assert a == b


def test_field_map_renames_columns(good_event):
    renamed = {("event_id" if k == "incident_id" else k): v for k, v in good_event.items()}
    assert len(run_pipeline([renamed], field_map={"event_id": "incident_id"}).processed) == 1
    assert len(run_pipeline([renamed]).processed) == 0


def test_formats_listed():
    assert {"csv", "jsonl", "json", "parquet", "tsv"} <= set(supported_formats())

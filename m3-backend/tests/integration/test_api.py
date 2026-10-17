from tests.conftest import SAMPLE_CSV


def test_post_single_and_idempotent(client, good_event):
    r = client.post("/api/v1/ingest/events", json=good_event)
    assert r.status_code == 200 and r.json()["accepted"] == 1
    assert r.json()["processed"][0]["event_type"] == "JOB_SUCCESS"
    client.post("/api/v1/ingest/events", json=good_event)               # re-send: no duplicate row
    assert client.get("/api/v1/stats").json()["processed"] == 1


def test_batch_with_bad_record_returns_200_and_quarantines(client, good_event):
    bad = {**good_event, "incident_id": "INC-20260901-JOB10644-BAD1", "completion_status": "NOPE"}
    r = client.post("/api/v1/ingest/events", json={"events": [good_event, bad]})
    body = r.json()
    assert r.status_code == 200 and body["accepted"] == 1 and body["quarantined"] == 1
    q = client.get("/api/v1/events/quarantine").json()
    assert q[0]["stage"] == "validation" and q[0]["incident_id"].endswith("BAD1")


def test_non_event_body_is_422(client):
    assert client.post("/api/v1/ingest/events", json="hello").status_code == 422
    assert client.post("/api/v1/ingest/events", json=[]).status_code == 422


def test_file_upload_and_query(client):
    with open(SAMPLE_CSV, "rb") as f:
        r = client.post("/api/v1/ingest/file", files={"file": ("training_data.csv", f)})
    assert r.json()["accepted"] == 3000 and r.json()["processed"] is None
    ev = client.get("/api/v1/events/processed", params={"event_type": "JOB_ABEND", "limit": 5}).json()
    assert ev["count"] == 5 and all(e["event_type"] == "JOB_ABEND" for e in ev["events"])
    one = client.get(f"/api/v1/events/processed/{ev['events'][0]['event_id']}")
    assert one.status_code == 200 and "risk_label" in one.json()["labels"]
    assert client.get("/api/v1/events/processed/NOPE").status_code == 404
    assert client.post("/api/v1/ingest/file?format=xml", files={"file": ("a.csv", b"x")}).status_code == 422


def test_api_key_enforced_when_configured(client, good_event, monkeypatch):
    from config.settings import get_settings
    monkeypatch.setenv("API_KEY", "secret"); get_settings.cache_clear()
    assert client.post("/api/v1/ingest/events", json=good_event).status_code == 401
    ok = client.post("/api/v1/ingest/events", json=good_event, headers={"X-API-Key": "secret"})
    assert ok.status_code == 200

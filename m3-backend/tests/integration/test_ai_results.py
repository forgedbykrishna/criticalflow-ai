def _seed(client, good_event):
    assert client.post("/api/v1/ingest/events", json=good_event).json()["accepted"] == 1
    return good_event["incident_id"]


def test_m4_and_m5_results_saved_and_joined(client, good_event):
    eid = _seed(client, good_event)
    r = client.post("/api/v1/ai/incidents", json={"event_id": eid, "incident_type": "JOB_FAILURE",
                                               "anomaly_score": 0.92, "severity": "HIGH", "model": "iforest-v1"})
    assert r.json() == {"received": 1, "saved": 1, "unknown_event_ids": []}
    r = client.post("/api/v1/rca", json={"event_id": eid, "root_cause": "Dataset unavailable",
                                         "evidence": ["Return code 8"], "impact": "Payroll delayed",
                                         "recommended_action": "Verify dataset", "confidence": 0.87})
    assert r.json()["saved"] == 1
    full = client.get(f"/api/v1/incidents/{eid}/full").json()
    assert full["incident"]["severity"] == "HIGH" and full["incident"]["model"] == "iforest-v1"
    assert full["rca"]["evidence"] == ["Return code 8"] and full["event"]["event_id"] == eid


def test_resend_updates_not_duplicates(client, good_event):
    eid = _seed(client, good_event)
    body = {"event_id": eid, "incident_type": "JOB_FAILURE", "anomaly_score": 0.5, "severity": "LOW"}
    client.post("/api/v1/ai/incidents", json=body)
    client.post("/api/v1/ai/incidents", json={**body, "severity": "CRITICAL"})
    rows = client.get("/api/v1/ai/incidents").json()
    assert len(rows) == 1 and rows[0]["severity"] == "CRITICAL"
    assert client.get("/api/v1/ai/incidents", params={"severity": "low"}).json() == []


def test_bad_or_unknown_input(client, good_event):
    _seed(client, good_event)
    bad = {"event_id": "X", "incident_type": "A", "anomaly_score": 1.7, "severity": "HIGH"}
    assert client.post("/api/v1/ai/incidents", json=bad).status_code == 422
    assert client.post("/api/v1/ai/incidents", json={**bad, "anomaly_score": 0.5, "severity": "SCARY"}).status_code == 422
    ok_shape = {**bad, "anomaly_score": 0.5}
    assert client.post("/api/v1/ai/incidents", json=ok_shape).json() == {"received": 1, "saved": 0, "unknown_event_ids": ["X"]}
    assert client.get("/api/v1/rca/NOPE").status_code == 404

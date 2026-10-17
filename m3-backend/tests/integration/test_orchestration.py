"""M2 -> POST /incident -> M3 -> M4 /predict -> M5 /explain -> PostgreSQL, with M4/M5 faked at the HTTP level."""
import json

import httpx
import pytest

LEADER_M4 = {"anomaly": "True", "severity": "High", "confidence": 0.87}                 # shape in the team diagram
LEADER_M5 = {"explanation": "Abnormal error rate after deployment", "root_cause": "Bad deployment",
             "recommendations": ["Check payment service logs", "Verify recent deployment"]}


@pytest.fixture
def ai(client, monkeypatch):
    """Point M3 at fake M4/M5 URLs. `ai.calls` records every request; `ai.m4` / `ai.m5` set the behaviour."""
    from config.settings import get_settings
    from orchestration import clients

    monkeypatch.setenv("M4_URL", "http://m4:8001"); monkeypatch.setenv("M5_URL", "http://m5:8002")
    get_settings.cache_clear()

    class AI:
        calls: list = []
        m4 = staticmethod(lambda req: httpx.Response(200, json=LEADER_M4))
        m5 = staticmethod(lambda req: httpx.Response(200, json=LEADER_M5))

    def handler(req: httpx.Request) -> httpx.Response:
        AI.calls.append((req.method, str(req.url), json.loads(req.content)))
        return (AI.m4 if req.url.path == "/predict" else AI.m5)(req)

    AI.calls = []
    monkeypatch.setattr(clients, "_http", lambda: httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setenv("AI_RETRIES", "0"); get_settings.cache_clear()
    AI.client = client
    return AI


def test_full_chain_success(ai, good_event):
    r = ai.client.post("/incident?wait=true", json=good_event)
    body = r.json()
    assert r.status_code == 200 and body["pipeline_status"] == "COMPLETE"
    assert body["prediction"]["severity"] == "HIGH" and body["prediction"]["confidence"] == 0.87
    assert body["explanation"]["root_cause"] == "Bad deployment"
    assert body["explanation"]["recommendations"] == ["Check payment service logs", "Verify recent deployment"]
    # what M3 actually sent
    (m4_call, m5_call) = ai.calls
    assert m4_call[0] == "POST" and m4_call[1] == "http://m4:8001/predict"
    assert m4_call[2]["incident_id"] == good_event["incident_id"] and "features" in m4_call[2]
    assert m5_call[2]["prediction"]["severity"] == "HIGH" and m5_call[2]["event"]["event_id"] == good_event["incident_id"]
    full = ai.client.get(f"/api/v1/incidents/{good_event['incident_id']}/full").json()
    assert full["pipeline"]["status"] == "COMPLETE" and full["incident"] and full["rca"]


def test_default_is_202_and_finishes_in_background(ai, good_event):
    r = ai.client.post("/incident", json=good_event)
    assert r.status_code == 202 and r.json()["pipeline_status"] == "RECEIVED"
    full = ai.client.get(f"/api/v1/incidents/{good_event['incident_id']}/full").json()
    assert full["pipeline"]["status"] == "COMPLETE"          # TestClient runs background tasks before returning


def test_wrapper_body_from_diagram(ai, good_event):
    wrapped = {"incident_id": good_event["incident_id"], "data": {k: v for k, v in good_event.items() if k != "incident_id"}}
    assert ai.client.post("/incident?wait=true", json=wrapped).json()["pipeline_status"] == "COMPLETE"


def test_m4_down_keeps_event_then_reprocess_recovers(ai, good_event):
    ai.m4 = staticmethod(lambda req: httpx.Response(503, text="down"))
    body = ai.client.post("/incident?wait=true", json=good_event).json()
    assert body["pipeline_status"] == "M4_FAILED" and "503" in body["error"] and body["prediction"] is None
    assert ai.client.get("/api/v1/stats").json()["processed"] == 1            # event itself is safe
    ai.m4 = staticmethod(lambda req: httpx.Response(200, json=LEADER_M4))
    assert ai.client.post("/api/v1/incidents/reprocess-failed").json()["results"] == {good_event["incident_id"]: "COMPLETE"}
    assert ai.client.get(f"/api/v1/incidents/{good_event['incident_id']}/full").json()["pipeline"]["attempts"] == 2


def test_m5_failure_keeps_m4_result(ai, good_event):
    ai.m5 = staticmethod(lambda req: httpx.Response(500, text="llm error"))
    body = ai.client.post("/incident?wait=true", json=good_event).json()
    assert body["pipeline_status"] == "M5_FAILED" and body["prediction"]["severity"] == "HIGH"
    assert body["explanation"] is None


def test_unusable_m4_answers_are_reported_not_stored(ai, good_event):
    for bad, needle in (({"anomaly": True, "severity": "SCARY", "confidence": 0.5}, "severity"),
                        ({"anomaly": True, "severity": "HIGH"}, "anomaly_score"),
                        ({"severity": "HIGH", "confidence": 7}, "between 0 and 1")):
        ai.m4 = staticmethod(lambda req, b=bad: httpx.Response(200, json=b))
        body = ai.client.post("/incident?wait=true", json=good_event).json()
        assert body["pipeline_status"] == "M4_FAILED" and needle in body["error"]
        assert body["prediction"] is None


def test_m5_needs_root_cause_and_recommendation(ai, good_event):
    ai.m5 = staticmethod(lambda req: httpx.Response(200, json={"explanation": "only text"}))
    body = ai.client.post("/incident?wait=true", json=good_event).json()
    assert body["pipeline_status"] == "M5_FAILED" and "root_cause" in body["error"]


def test_team_guide_shapes_also_accepted(ai, good_event):
    ai.m4 = staticmethod(lambda req: httpx.Response(200, json={"incident_type": "JOB_FAILURE", "anomaly_score": 0.92, "severity": "HIGH"}))
    ai.m5 = staticmethod(lambda req: httpx.Response(200, json={"root_cause": "r", "evidence": ["Return code 8"], "impact": "i",
                                                               "recommended_action": "Verify dataset", "confidence": 0.87}))
    body = ai.client.post("/incident?wait=true", json=good_event).json()
    assert body["pipeline_status"] == "COMPLETE" and body["prediction"]["anomaly_score"] == 0.92
    assert body["explanation"]["evidence"] == ["Return code 8"] and body["explanation"]["recommended_action"] == "Verify dataset"


def test_invalid_incident_is_422_and_quarantined(ai, good_event):
    r = ai.client.post("/incident", json={**good_event, "completion_status": "WEIRD"})
    assert r.status_code == 422 and r.json()["detail"]["errors"][0]["field"] == "completion_status"
    assert ai.calls == []                                         # M4/M5 never called for bad data
    assert ai.client.get("/api/v1/events/quarantine").json()[0]["stage"] == "validation"
    assert ai.client.post("/incident", json=[1, 2]).status_code == 422


def test_mock_mode_when_no_urls(client, good_event):
    body = client.post("/incident?wait=true", json=good_event).json()
    assert body["pipeline_status"] == "COMPLETE"
    assert body["prediction"]["source"] == "mock" and body["explanation"]["source"] == "mock"
    assert client.get("/health").json() == {"status": "ok", "m4": "mock", "m5": "mock"}


def test_overview_view_has_everything(ai, good_event):
    ai.client.post("/incident?wait=true", json=good_event)
    from sqlalchemy import text
    from db.session import get_engine
    with get_engine().connect() as c:
        row = c.execute(text("SELECT * FROM incident_overview")).mappings().one()
    assert row["incident_id"] == good_event["incident_id"] and row["pipeline_status"] == "COMPLETE"
    assert row["severity"] == "HIGH" and row["root_cause"] == "Bad deployment"

def test_m4_gets_raw_incident_fields_at_top_level(ai, good_event):
    """M4 (the real service) reads system_id, completion_status, cpu_utilization_pct... straight off the body."""
    assert ai.client.post("/incident?wait=true", json=good_event).status_code == 200
    sent = ai.calls[0][2]
    for k in ("system_id", "subsystem", "completion_status", "return_code", "abend_code", "primary_message_id",
              "cpu_utilization_pct", "error_rate_pct", "transaction_volume_per_hr", "recent_deployment_flag"):
        assert k in sent, k
    assert sent["system_id"] == good_event["system_id"]
    assert sent["completion_status"] == good_event["completion_status"]
    assert sent["cpu_utilization_pct"] == good_event["cpu_utilization_pct"]


def test_m2_endpoint_201_then_200_then_422(ai, good_event):
    r = ai.client.post("/api/v1/incidents", json=good_event)
    assert r.status_code == 201 and r.json()["created"] is True
    r2 = ai.client.post("/api/v1/incidents", json=good_event)
    assert r2.status_code == 200 and r2.json() == {"incident_id": good_event["incident_id"], "created": False}
    bad = {**good_event, "incident_id": "INC-20261005-JOB00001-NOPE", "unexpected": 1}
    assert ai.client.post("/api/v1/incidents", json=bad).status_code == 422


def test_bearer_token_accepted_and_wrong_rejected(ai, good_event, monkeypatch):
    from config.settings import get_settings
    monkeypatch.setenv("API_KEY", "devtoken")
    get_settings.cache_clear()
    try:
        assert ai.client.post("/api/v1/incidents", json=good_event).status_code == 401
        assert ai.client.post("/api/v1/incidents", json=good_event, headers={"Authorization": "Bearer wrong"}).status_code == 401
        ok = ai.client.post("/api/v1/incidents", json=good_event, headers={"Authorization": "Bearer devtoken"})
        assert ok.status_code == 201
        assert ai.client.get("/api/v1/stats", headers={"X-API-Key": "devtoken"}).status_code == 200
    finally:
        monkeypatch.delenv("API_KEY")
        get_settings.cache_clear()

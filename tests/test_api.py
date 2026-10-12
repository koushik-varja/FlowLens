import os

os.environ["DATABASE_URL"] = "sqlite:///./test_flowlens.db"
from fastapi.testclient import TestClient
from backend.app.main import app

c = TestClient(app)
DATA = b"case_id,activity,timestamp,priority,cost\n1,A,2026-01-01T00:00:00Z,normal,1\n1,B,2026-01-01T03:00:00Z,normal,2\n2,A,2026-01-01T00:00:00Z,high,1\n2,B,2026-01-03T03:00:00Z,high,2\n"


def test_upload_and_analytics():
    r = c.post("/datasets", files={"file": ("events.csv", DATA, "text/csv")})
    assert r.status_code == 201
    i = r.json()["id"]
    assert c.get(f"/processes/{i}/graph").status_code == 200
    assert c.get(f"/processes/{i}/variants").status_code == 200
    assert c.get(f"/processes/{i}/bottlenecks").status_code == 200
    assert c.get(f"/processes/{i}/sla").status_code == 200


def test_invalid_json():
    r = c.post("/datasets", files={"file": ("x.json", b"{bad", "application/json")})
    assert r.status_code in (400, 422)


def test_unsafe_filename_sanitized():
    r = c.post("/datasets", files={"file": ("../../evil.csv", DATA, "text/csv")})
    assert r.status_code == 201
    assert ".." not in r.json()["name"]


def test_privileged_delete_requires_key():
    r = c.post("/datasets", files={"file": ("x.csv", DATA, "text/csv")})
    i = r.json()["id"]
    assert c.delete(f"/datasets/{i}").status_code == 503


def test_sql_like_payload_safe():
    d = DATA.replace(b"1,A", b"1'; DROP TABLE datasets;--,A", 1)
    r = c.post("/datasets", files={"file": ("x.csv", d, "text/csv")})
    assert r.status_code == 201
    assert c.get("/datasets").status_code == 200


def test_mime_mismatch_rejected():
    r = c.post("/datasets", files={"file": ("x.csv", DATA, "image/png")})
    assert r.status_code == 415


def test_noop_simulation_api_zero_effect():
    r = c.post("/datasets", files={"file": ("noop.csv", DATA, "text/csv")})
    i = r.json()["id"]
    body = {"name": "noop", "actions": [], "runs": 20, "sla_hours": 48, "seed": 7}
    out = c.post(f"/processes/{i}/simulation", json=body)
    assert out.status_code == 200
    j = out.json()
    assert j["no_op_exact"] is True
    assert j["simulated_impact"]["median_cycle_reduction_pct"] == 0


def test_configured_activity_sla_api():
    r = c.post("/datasets", files={"file": ("sla.csv", DATA, "text/csv")})
    i = r.json()["id"]
    body = {
        "rules": [
            {"name": "B inbound", "scope": "activity", "activity": "B", "threshold_hours": 12, "severity": "high"}
        ]
    }
    out = c.post(f"/processes/{i}/sla/rules", json=body)
    assert out.status_code == 200
    assert out.json()["rules"][0]["violation_count"] == 1


def test_admin_key_when_configured(monkeypatch):
    monkeypatch.setenv("ADMIN_API_KEY", "secret-test-key")
    r = c.post("/datasets", files={"file": ("delete.csv", DATA, "text/csv")})
    i = r.json()["id"]
    assert c.delete(f"/datasets/{i}", headers={"X-Admin-Key": "wrong"}).status_code == 401
    assert c.delete(f"/datasets/{i}", headers={"X-Admin-Key": "secret-test-key"}).status_code == 204


def test_invalid_parallelization_returns_validation_error():
    r = c.post("/datasets", files={"file": ("parallel.csv", DATA, "text/csv")})
    i = r.json()["id"]
    body = {
        "name": "invalid parallel",
        "actions": [{"type": "parallelize_activities", "first_activity": "B", "second_activity": "A"}],
        "runs": 20,
        "sla_hours": 48,
        "seed": 7,
    }
    out = c.post(f"/processes/{i}/simulation", json=body)
    assert out.status_code == 422
    assert "observed adjacent activities" in out.json()["detail"]

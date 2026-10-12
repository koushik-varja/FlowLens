from datetime import datetime, timezone, timedelta
import pytest
from backend.app.core import (
    Scenario,
    ValidationError,
    bottlenecks,
    business_impact,
    conformance,
    discover,
    load_event_bytes,
    parse_ts,
    predict_snapshot,
    recommendations,
    rework,
    simulate,
    sla_analysis,
    train_models,
    variants,
)


def ev(cid, a, h, cost=1, priority="normal"):
    return {
        "case_id": cid,
        "activity": a,
        "timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=h),
        "cost": cost,
        "priority": priority,
        "department": "D",
    }


def sample():
    return [
        ev("1", "A", 0),
        ev("1", "B", 2),
        ev("1", "A", 5),
        ev("1", "C", 9),
        ev("2", "A", 0),
        ev("2", "B", 1),
        ev("2", "C", 3),
    ]


def test_order_and_quality():
    raw = b"case_id,activity,timestamp\n1,B,2026-01-02T00:00:00Z\n1,A,2026-01-01T00:00:00Z\n"
    events, q = load_event_bytes(raw, "x.csv")
    assert q["chronology_issues"] == 1
    assert events[0]["activity"] == "A"


def test_duplicate_detection():
    raw = b"case_id,activity,timestamp\n1,A,2026-01-01T00:00:00Z\n1,A,2026-01-01T00:00:00Z\n"
    _, q = load_event_bytes(raw, "x.csv")
    assert q["duplicates"] == 1


def test_bad_extension():
    with pytest.raises(ValidationError):
        load_event_bytes(b"x", "x.exe")


def test_graph():
    g = discover(sample())
    assert any(e["source"] == "A" and e["target"] == "B" for e in g["edges"])


def test_variants():
    v = variants(sample())
    assert len(v) == 2 and v[0]["case_count"] == 1


def test_rework():
    r = rework(sample())
    assert r["cases_affected"] == 1 and r["repeated_activities"]["A"] == 1


def test_sla():
    s = sla_analysis(sample(), process_hours=4)
    assert s["violation_count"] == 1


def test_bottleneck():
    b = bottlenecks(sample())
    assert b and "evidence" in b[0]


def test_conformance():
    c = conformance(sample(), ["A", "B", "C"])
    assert c["compliance_rate"] == 0.5


def test_simulation_deterministic():
    sc = Scenario({"B": 0.5}, set(), {}, False)
    a = simulate(sample(), sc, runs=60, seed=2)
    b = simulate(sample(), sc, runs=60, seed=2)
    assert a == b


def test_business_impact_formula():
    sim = {
        "baseline": {"mean_cycle_hours": 10, "sla_compliance": 0.8},
        "proposed": {"mean_cycle_hours": 8, "sla_compliance": 0.9},
    }
    x = business_impact(sim, 100, 10, 50)
    assert x["estimated_monthly_value"] == 500
    assert x["categories"]["labor_effort_savings"] == 0


def test_ml_training_and_prediction():
    from data.generator.generate import generate

    rows = generate(80, 7)
    for r in rows:
        r["timestamp"] = parse_ts(r["timestamp"])
    model = train_models(rows, 48)
    assert model["split"]["train_samples"] > 0 and "mae_hours" in model["remaining_metrics"]
    pred = predict_snapshot(
        model,
        {
            "elapsed_hours": 8,
            "current_activity": "Finance Review",
            "prior_count": 3,
            "rework_count": 0,
            "priority": "normal",
            "department": "Finance",
        },
    )
    assert 0 <= pred["sla_breach_probability"] <= 1 and pred["predicted_remaining_hours"] >= 0


def test_oversized_input(monkeypatch):
    import backend.app.core as core

    monkeypatch.setattr(core, "MAX_UPLOAD_BYTES", 10)
    with pytest.raises(ValidationError):
        core.load_event_bytes(b"a" * 11, "x.csv")


def test_lifecycle_timing_separates_wait_and_processing():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [
        {"case_id": "1", "activity": "A", "timestamp": base, "lifecycle": "complete"},
        {"case_id": "1", "activity": "B", "timestamp": base + timedelta(hours=2), "lifecycle": "start"},
        {"case_id": "1", "activity": "B", "timestamp": base + timedelta(hours=5), "lifecycle": "complete"},
    ]
    b = bottlenecks(rows)
    row = next(x for x in b if x["activity"] == "B")
    assert row["timing_basis"] == "lifecycle start/complete"
    assert row["median_wait_hours"] == 2 and row["median_processing_hours"] == 3


def test_recommendations_are_multi_option_and_explainable():
    from data.generator.generate import generate

    rows = generate(80, 13)
    for row in rows:
        row["timestamp"] = parse_ts(row["timestamp"])
    recs = recommendations(rows)
    assert len(recs) >= 3
    assert all(
        "why_this" in r and "simulated" in r and "implementation_effort" in r and "rank_score" in r for r in recs
    )

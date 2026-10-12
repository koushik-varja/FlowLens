from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.app.core import parse_ts
from backend.app.ml import (
    active_case_snapshots,
    load_persisted_models,
    persist_models,
    score_active_cases,
    split_case_ids,
    train_models,
)
from backend.app.scenario_models import Condition
from backend.app.sla import SlaRule, evaluate_sla_rules
from data.generator.generate import generate


def generated(n=100):
    rows = generate(n, 17)
    for row in rows:
        row["timestamp"] = parse_ts(row["timestamp"])
    return rows


def test_case_safe_time_aware_split_has_no_overlap():
    events = generated(90)
    train, test = split_case_ids(events)
    assert set(train).isdisjoint(test)
    model = train_models(events, 48)
    assert set(model["split"]["train_case_ids"]).isdisjoint(model["split"]["test_case_ids"])
    assert "unique case start" in model["split"]["method"]


def test_persisted_model_load_and_inference(tmp_path: Path):
    events = generated(100)
    trained = train_models(events, 48)
    meta = persist_models(77, trained, tmp_path)
    loaded = load_persisted_models(77, tmp_path, meta["version"])
    assert loaded["metadata"]["version"] == meta["version"]
    assert loaded["classifier"] is not None and loaded["regressor"] is not None


def test_active_snapshot_uses_only_pre_cutoff_events(tmp_path: Path):
    events = generated(120)
    timestamps = sorted(e["timestamp"] for e in events)
    cutoff = timestamps[int(0.65 * len(timestamps))]
    snapshots = active_case_snapshots(events, cutoff)
    assert snapshots
    assert all(datetime.fromisoformat(s["feature_timestamp"]) == cutoff for s in snapshots)
    trained = train_models(events, 48)
    meta = persist_models(88, trained, tmp_path)
    loaded = load_persisted_models(88, tmp_path, meta["version"])
    scored = score_active_cases(events, cutoff, loaded)
    assert scored and all(
        "breach_probability" in s and "expected_remaining_hours" in s and s["model_version"] == meta["version"]
        for s in scored
    )


def simple_sla_events():
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def e(cid, act, h, priority):
        return {
            "case_id": cid,
            "activity": act,
            "timestamp": base + timedelta(hours=h),
            "priority": priority,
            "department": "Finance",
        }

    return [
        e("1", "Request", 0, "HIGH"),
        e("1", "Finance Review", 15, "HIGH"),
        e("1", "Payment", 25, "HIGH"),
        e("2", "Request", 0, "LOW"),
        e("2", "Finance Review", 5, "LOW"),
        e("2", "Payment", 10, "LOW"),
    ]


def test_process_activity_and_segment_sla_rules():
    rules = [
        SlaRule(name="process", scope="process", threshold_hours=20),
        SlaRule(name="finance", scope="activity", activity="Finance Review", threshold_hours=12),
        SlaRule(
            name="high",
            scope="segment",
            threshold_hours=24,
            conditions=[Condition(field="priority", op="eq", value="HIGH")],
        ),
    ]
    result = evaluate_sla_rules(simple_sla_events(), rules)
    by_name = {r["name"]: r for r in result["rules"]}
    assert by_name["process"]["violation_count"] == 1
    assert by_name["finance"]["violation_count"] == 1
    assert by_name["high"]["violation_count"] == 1
    assert result["observed_duration_contribution"]

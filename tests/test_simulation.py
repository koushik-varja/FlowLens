from datetime import datetime, timedelta, timezone

import pytest

from backend.app.scenario_models import (
    ActivitySpeedup,
    AddResourceCapacity,
    AutomateEligibleCases,
    Condition,
    ParallelizeActivities,
    RemoveActivity,
    ScenarioDefinition,
)
from backend.app.simulation import build_baseline_model, simulate_counterfactual, simulate_resource_queue


def ev(cid, activity, hour, *, priority="LOW", value=1000, resource="R1"):
    return {
        "case_id": cid,
        "activity": activity,
        "timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=hour),
        "priority": priority,
        "value": value,
        "resource": resource,
        "department": "Finance" if "Finance" in activity else "Ops",
        "cost": 1.0,
    }


def dense_events():
    rows = []
    for i in range(24):
        start = i * 0.05
        priority = "LOW" if i % 2 == 0 else "HIGH"
        value = 1000 if priority == "LOW" else 50000
        rows += [
            ev(str(i), "Request", start, priority=priority, value=value),
            ev(str(i), "Approval", start + 1, priority=priority, value=value),
            ev(str(i), "Finance Review", start + 5, priority=priority, value=value, resource="F1"),
            ev(str(i), "Compliance", start + 7, priority=priority, value=value),
            ev(str(i), "Payment", start + 9, priority=priority, value=value),
        ]
    return rows


def test_noop_paired_run_is_exact_zero():
    result = simulate_counterfactual(dense_events(), ScenarioDefinition(name="noop", actions=[], runs=40, seed=11))
    assert result["common_random_numbers"] is True
    assert result["baseline_immutable"] is True
    assert result["no_op_exact"] is True
    assert result["simulated_impact"]["median_cycle_reduction_pct"] == 0
    assert result["simulated_impact"]["sla_compliance_delta_pp"] == 0
    assert result["simulated_impact"]["p95_cycle_delta_hours"] == 0
    assert result["uncertainty"]["median_cycle_delta_hours"]["median"] == 0


def test_remove_activity_changes_proposed_only():
    events = dense_events()
    original = build_baseline_model(events)
    baseline_durations = [sum(t.delays) for t in original.trajectories]
    result = simulate_counterfactual(
        events, ScenarioDefinition(actions=[RemoveActivity(activity="Finance Review")], runs=30, seed=2)
    )
    after = build_baseline_model(events)
    assert baseline_durations == [sum(t.delays) for t in after.trajectories]
    assert any("removed:Finance Review" in x["applied"] for x in result["paired_run_evidence"])
    assert result["proposed"]["median_cycle_hours"] < result["baseline"]["median_cycle_hours"]


def test_scenario_does_not_mutate_baseline_between_runs():
    events = dense_events()
    first = simulate_counterfactual(
        events,
        ScenarioDefinition(
            actions=[ActivitySpeedup(activity="Finance Review", reduction_fraction=0.5)], runs=25, seed=4
        ),
    )
    noop = simulate_counterfactual(events, ScenarioDefinition(actions=[], runs=25, seed=4))
    assert noop["no_op_exact"]
    assert first["baseline"]["median_cycle_hours"] == noop["baseline"]["median_cycle_hours"]


def test_speedup_reduces_selected_activity_delay():
    result = simulate_counterfactual(
        dense_events(),
        ScenarioDefinition(
            actions=[ActivitySpeedup(activity="Finance Review", reduction_fraction=0.5)], runs=30, seed=3
        ),
    )
    assert result["proposed"]["median_cycle_hours"] < result["baseline"]["median_cycle_hours"]


def test_selective_automation_changes_only_eligible_cases():
    result = simulate_counterfactual(
        dense_events(),
        ScenarioDefinition(
            actions=[
                AutomateEligibleCases(
                    activity="Finance Review",
                    conditions=[Condition(field="priority", op="eq", value="LOW")],
                    reduction_fraction=0.5,
                )
            ],
            runs=20,
            seed=5,
        ),
    )
    evidence = result["paired_run_evidence"]
    low_changed = [e for e in evidence if e["delta_hours"] < 0 and "automation:Finance Review" in e["applied"]]
    high_unchanged = [e for e in evidence if e["delta_hours"] == 0 and "automation:Finance Review" not in e["applied"]]
    assert low_changed and high_unchanged


def test_resource_capacity_uses_queue_mechanics():
    arrivals = [0, 0.1, 0.2, 0.3, 0.4, 0.5]
    services = [2, 2, 2, 2, 2, 2]
    one = simulate_resource_queue(arrivals, services, 1)
    two = simulate_resource_queue(arrivals, services, 2)
    assert two["average_queue_delay_hours"] < one["average_queue_delay_hours"]
    assert two["utilization"] != one["utilization"]
    result = simulate_counterfactual(
        dense_events(),
        ScenarioDefinition(
            actions=[AddResourceCapacity(activity="Finance Review", additional_capacity=1, service_fraction=0.8)],
            runs=20,
            seed=3,
        ),
    )
    diag = result["resource_diagnostics"][0]
    assert diag["proposed_capacity"] == diag["baseline_capacity"] + 1
    assert diag["proposed"]["average_queue_delay_hours"] <= diag["baseline"]["average_queue_delay_hours"]


def test_parallelization_uses_max_not_sum():
    events = []
    for i in range(20):
        s = i * 10
        events += [
            ev(str(i), "Start", s),
            ev(str(i), "Finance", s + 4),
            ev(str(i), "Compliance", s + 10),
            ev(str(i), "End", s + 11),
        ]
    result = simulate_counterfactual(
        events,
        ScenarioDefinition(
            actions=[ParallelizeActivities(first_activity="Finance", second_activity="Compliance")], runs=20, seed=8
        ),
    )
    # Sequential segment = 4+6=10; parallel segment = max(4,6)=6, so cycle falls from 11 to 7.
    assert result["baseline"]["median_cycle_hours"] == pytest.approx(11)
    assert result["proposed"]["median_cycle_hours"] == pytest.approx(7)


def test_deterministic_reproducibility():
    scenario = ScenarioDefinition(
        actions=[ActivitySpeedup(activity="Finance Review", reduction_fraction=0.2)], runs=25, seed=19
    )
    assert simulate_counterfactual(dense_events(), scenario) == simulate_counterfactual(dense_events(), scenario)


def test_fidelity_report_present_and_reasonable():
    result = simulate_counterfactual(dense_events(), ScenarioDefinition(actions=[], runs=80, seed=1))
    fidelity = result["baseline_fidelity"]
    assert fidelity["status"] in {"HIGH", "MEDIUM", "LOW"}
    assert "p95" in fidelity["observed"] and "p95" in fidelity["simulated_baseline"]


def test_fixed_horizon_throughput_is_invariant_to_analysis_cohort_size():
    events = []
    # 500 historical arrivals spread across a fixed source window so the arrival-rate estimate is stable.
    for i in range(500):
        start = i * 1.5
        events += [
            ev(str(i), "Request", start),
            ev(str(i), "Approval", start + 2),
            ev(str(i), "Finance Review", start + 8, resource="F1"),
            ev(str(i), "Payment", start + 12),
        ]
    values = []
    for cohort_size in (50, 100, 200, 400):
        result = simulate_counterfactual(
            events,
            ScenarioDefinition(
                name=f"cohort-{cohort_size}",
                actions=[ActivitySpeedup(activity="Finance Review", reduction_fraction=0.25)],
                runs=20,
                seed=123,
                cohort_size=cohort_size,
            ),
        )
        values.append(result["baseline"]["simulated_throughput_cases_per_30d"])
        assert result["throughput_methodology"]["independent_of_analysis_cohort_size"] is True
        assert result["throughput_methodology"]["simulation_horizon_hours"] == 720.0
    # Same arrival model + seed means the absolute throughput estimate is identical here. More generally,
    # it must never scale with the number of bootstrap trajectories used for cycle-time uncertainty.
    assert max(values) - min(values) <= max(values) * 0.02
    assert values[-1] < values[0] * 1.2


def test_parallelization_rejects_unobserved_dependency():
    with pytest.raises(ValueError, match="observed adjacent activities"):
        simulate_counterfactual(
            dense_events(),
            ScenarioDefinition(
                actions=[ParallelizeActivities(first_activity="Request", second_activity="Compliance")],
                runs=20,
                seed=7,
            ),
        )

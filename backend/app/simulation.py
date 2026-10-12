from __future__ import annotations

import copy
import heapq
import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

import numpy as np

from .scenario_models import (
    ActivitySpeedup,
    AddResourceCapacity,
    AutomateEligibleCases,
    ChangePriorityRouting,
    ChangeSLA,
    Condition,
    ParallelizeActivities,
    RemoveActivity,
    RouteCases,
    ScenarioDefinition,
)


@dataclass(frozen=True)
class CaseTrajectory:
    case_id: str
    start_hour: float
    activities: tuple[str, ...]
    delays: tuple[float, ...]
    attrs: dict[str, Any]
    cost: float


@dataclass(frozen=True)
class BaselineProcessModel:
    trajectories: tuple[CaseTrajectory, ...]
    activity_capacities: dict[str, int]
    observed_span_hours: float
    case_arrival_rate_per_hour: float
    arrival_observation_span_hours: float


def _percentile(values: list[float], q: float) -> float:
    return float(np.percentile(values, q)) if values else 0.0


def _coerce_number(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def matches_conditions(attrs: dict[str, Any], conditions: list[Condition]) -> bool:
    for condition in conditions:
        current = attrs.get(condition.field)
        expected = condition.value
        if condition.op in {"lt", "lte", "gt", "gte"}:
            left, right = _coerce_number(current), _coerce_number(expected)
            if left is None or right is None:
                return False
            ok = {
                "lt": left < right,
                "lte": left <= right,
                "gt": left > right,
                "gte": left >= right,
            }[condition.op]
        elif condition.op == "in":
            values = expected if isinstance(expected, list) else [expected]
            ok = str(current).lower() in {str(v).lower() for v in values}
        elif condition.op == "neq":
            ok = str(current).lower() != str(expected).lower()
        else:
            ok = str(current).lower() == str(expected).lower()
        if not ok:
            return False
    return True


def build_baseline_model(events: list[dict]) -> BaselineProcessModel:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        grouped[event["case_id"]].append(event)
    for evs in grouped.values():
        evs.sort(key=lambda x: x["timestamp"])
    if not grouped:
        raise ValueError("Simulation requires at least one case")
    global_start = min(evs[0]["timestamp"] for evs in grouped.values())
    global_end = max(evs[-1]["timestamp"] for evs in grouped.values())
    resources: dict[str, set[str]] = defaultdict(set)
    trajectories: list[CaseTrajectory] = []
    for cid, evs in sorted(grouped.items()):
        activities = tuple(e["activity"] for e in evs)
        delays = [0.0]
        for prev, curr in zip(evs, evs[1:]):
            delays.append(max(0.0, (curr["timestamp"] - prev["timestamp"]).total_seconds() / 3600))
        for event in evs:
            if event.get("resource"):
                resources[event["activity"]].add(str(event["resource"]))
        attrs = {k: evs[0].get(k) for k in ("priority", "value", "customer_type", "region", "department", "channel")}
        attrs["case_id"] = cid
        trajectories.append(
            CaseTrajectory(
                case_id=cid,
                start_hour=(evs[0]["timestamp"] - global_start).total_seconds() / 3600,
                activities=activities,
                delays=tuple(delays),
                attrs=attrs,
                cost=sum(float(e.get("cost") or 0) for e in evs),
            )
        )
    capacities = {activity: max(1, len(ids)) for activity, ids in resources.items()}
    observed_span = max(1.0, (global_end - global_start).total_seconds() / 3600)
    start_hours = sorted(t.start_hour for t in trajectories)
    arrival_span = max(0.0, start_hours[-1] - start_hours[0]) if len(start_hours) > 1 else 0.0
    if len(start_hours) > 1 and arrival_span > 0:
        arrival_rate = (len(start_hours) - 1) / arrival_span
    else:
        arrival_rate = len(start_hours) / observed_span
    return BaselineProcessModel(
        trajectories=tuple(trajectories),
        activity_capacities=capacities,
        observed_span_hours=observed_span,
        case_arrival_rate_per_hour=max(arrival_rate, 1e-9),
        arrival_observation_span_hours=arrival_span if arrival_span > 0 else observed_span,
    )


def validate_scenario_against_model(model: BaselineProcessModel, scenario: ScenarioDefinition) -> None:
    activities = {activity for t in model.trajectories for activity in t.activities}
    for action in scenario.actions:
        activity = getattr(action, "activity", None)
        if activity is not None and activity not in activities:
            raise ValueError(f"Unknown activity in scenario: {activity}")
        if isinstance(action, ParallelizeActivities):
            if action.first_activity not in activities or action.second_activity not in activities:
                raise ValueError("Parallelization activities must exist in the loaded process")
            adjacent = any(
                any(
                    a == action.first_activity and b == action.second_activity
                    for a, b in zip(t.activities, t.activities[1:])
                )
                for t in model.trajectories
            )
            if not adjacent:
                raise ValueError(
                    f"Parallelization is only supported for observed adjacent activities; "
                    f"{action.first_activity} -> {action.second_activity} was not observed"
                )
        elif isinstance(action, RouteCases):
            if action.from_activity not in activities or action.to_activity not in activities:
                raise ValueError("Conditional routing currently supports only existing observed activities")
            if action.from_activity == action.to_activity:
                raise ValueError("Routing source and destination activities must differ")


def _trajectory_duration(t: CaseTrajectory) -> float:
    return sum(t.delays)


def _infer_route_effect(activities: list[str], action: RouteCases, attrs: dict[str, Any]) -> list[str]:
    if not matches_conditions(attrs, action.conditions):
        return activities
    result = list(activities)
    try:
        idx = result.index(action.from_activity)
    except ValueError:
        return result
    if idx + 1 < len(result):
        result[idx + 1] = action.to_activity
    return result


def _apply_non_resource_actions(
    t: CaseTrajectory, scenario: ScenarioDefinition
) -> tuple[list[str], list[float], dict[str, Any]]:
    activities = list(t.activities)
    delays = list(t.delays)
    attrs = copy.deepcopy(t.attrs)
    applied: list[str] = []

    for action in scenario.actions:
        if isinstance(action, RemoveActivity):
            kept_a, kept_d = [], []
            for activity, delay in zip(activities, delays):
                if activity == action.activity:
                    applied.append(f"removed:{activity}")
                    continue
                kept_a.append(activity)
                kept_d.append(delay)
            activities, delays = kept_a, kept_d
        elif isinstance(action, ActivitySpeedup):
            for i, activity in enumerate(activities):
                if activity == action.activity and i > 0:
                    delays[i] *= 1 - action.reduction_fraction
                    applied.append(f"speedup:{activity}")
        elif isinstance(action, AutomateEligibleCases):
            if matches_conditions(attrs, action.conditions):
                for i, activity in enumerate(activities):
                    if activity == action.activity and i > 0:
                        delays[i] *= 1 - action.reduction_fraction
                        applied.append(f"automation:{activity}")
        elif isinstance(action, ChangePriorityRouting):
            if str(attrs.get("priority") or "").lower() == action.priority.lower():
                for i, activity in enumerate(activities):
                    if activity == action.activity and i > 0:
                        delays[i] *= 1 - action.reduction_fraction
                        applied.append(f"priority-routing:{activity}")
        elif isinstance(action, RouteCases):
            activities = _infer_route_effect(activities, action, attrs)
        elif isinstance(action, ParallelizeActivities):
            # Only adjacent activities can be safely parallelized in the compact sequence model.
            i = 0
            while i < len(activities) - 1:
                if activities[i] == action.first_activity and activities[i + 1] == action.second_activity:
                    # delays[i] is inbound to first; delays[i+1] is inbound to second. From the prior event,
                    # sequential elapsed is their sum; parallel elapsed is the max.
                    if i > 0:
                        first, second = delays[i], delays[i + 1]
                        delays[i] = max(first, second)
                        delays[i + 1] = 0.0
                        applied.append(f"parallel:{action.first_activity}|{action.second_activity}")
                    i += 2
                else:
                    i += 1
    return activities, delays, {"applied": applied, "attrs": attrs}


def simulate_resource_queue(arrivals: list[float], service_times: list[float], capacity: int) -> dict[str, Any]:
    if capacity < 1:
        raise ValueError("capacity must be at least 1")
    if len(arrivals) != len(service_times):
        raise ValueError("arrivals and service_times must have equal length")
    if not arrivals:
        return {
            "average_queue_delay_hours": 0.0,
            "p95_queue_delay_hours": 0.0,
            "utilization": 0.0,
            "makespan_hours": 0.0,
        }
    servers = [0.0 for _ in range(capacity)]
    heapq.heapify(servers)
    waits = []
    busy = 0.0
    last_completion = 0.0
    first_arrival = min(arrivals)
    for arrival, service in sorted(zip(arrivals, service_times), key=lambda x: x[0]):
        available = heapq.heappop(servers)
        start = max(arrival, available)
        wait = start - arrival
        completion = start + max(0.0, service)
        heapq.heappush(servers, completion)
        waits.append(wait)
        busy += max(0.0, service)
        last_completion = max(last_completion, completion)
    horizon = max(last_completion - first_arrival, 1e-9)
    return {
        "average_queue_delay_hours": round(statistics.fmean(waits), 6),
        "p95_queue_delay_hours": round(_percentile(waits, 95), 6),
        "utilization": round(min(1.0, busy / (capacity * horizon)), 6),
        "makespan_hours": round(horizon, 6),
    }


def _resource_effect(model: BaselineProcessModel, action: AddResourceCapacity) -> dict[str, Any]:
    arrivals: list[float] = []
    services: list[float] = []
    for t in model.trajectories:
        elapsed = t.start_hour
        for activity, delay in zip(t.activities, t.delays):
            if activity == action.activity:
                arrivals.append(elapsed)
                services.append(max(0.001, delay * action.service_fraction))
            elapsed += delay
    baseline_capacity = model.activity_capacities.get(action.activity, 1)
    proposed_capacity = baseline_capacity + action.additional_capacity
    baseline = simulate_resource_queue(arrivals, services, baseline_capacity)
    proposed = simulate_resource_queue(arrivals, services, proposed_capacity)
    reduction = max(0.0, baseline["average_queue_delay_hours"] - proposed["average_queue_delay_hours"])
    return {
        "activity": action.activity,
        "baseline_capacity": baseline_capacity,
        "proposed_capacity": proposed_capacity,
        "baseline": baseline,
        "proposed": proposed,
        "modeled_queue_delay_reduction_hours": round(reduction, 6),
        "assumption": f"service time proxy = {action.service_fraction:.0%} of observed inbound inter-event delay because lifecycle start/complete data is unavailable",
    }


def _metrics(durations: list[float], costs: list[float], sla_hours: float) -> dict[str, Any]:
    return {
        "mean_cycle_hours": round(statistics.fmean(durations), 4),
        "median_cycle_hours": round(statistics.median(durations), 4),
        "p90_cycle_hours": round(_percentile(durations, 90), 4),
        "p95_cycle_hours": round(_percentile(durations, 95), 4),
        "sla_compliance": round(sum(x <= sla_hours for x in durations) / max(1, len(durations)), 6),
        "estimated_process_cost": round(statistics.fmean(costs), 4) if costs else 0.0,
    }


def _scenario_duration(
    trajectory: CaseTrajectory,
    scenario: ScenarioDefinition,
    resource_reduction: dict[str, float],
) -> float:
    activities, delays, _ = _apply_non_resource_actions(trajectory, scenario)
    for index, activity in enumerate(activities):
        if index > 0 and activity in resource_reduction:
            delays[index] = max(0.0, delays[index] - resource_reduction[activity])
    return sum(delays)


def _throughput_warmup_hours(model: BaselineProcessModel) -> float:
    durations = [_trajectory_duration(t) for t in model.trajectories]
    # A pre-horizon warm-up allows cases already in flight at time zero to complete inside the
    # measurement window, reducing the finite-window boundary bias. Keep it bounded for laptops.
    return min(720.0, max(24.0, _percentile(durations, 95)))


def simulate_fixed_horizon_throughput(
    model: BaselineProcessModel,
    scenario: ScenarioDefinition,
    resource_reduction: dict[str, float],
    run_seed: int,
    horizon_hours: float = 720.0,
) -> dict[str, float]:
    """Estimate 30-day completion volume from a fixed arrival process, independent of cohort_size.

    Historical case-start timestamps calibrate a Poisson arrival rate. Each paired run generates one
    arrival stream and one bootstrap trajectory template per arrival, then applies the scenario only to
    the proposed branch. The Monte Carlo analysis cohort is intentionally not used here.
    """
    if horizon_hours <= 0:
        raise ValueError("horizon_hours must be positive")
    rng = np.random.default_rng(run_seed)
    warmup = _throughput_warmup_hours(model)
    simulated_window = horizon_hours + warmup
    expected_arrivals = model.case_arrival_rate_per_hour * simulated_window
    arrival_count = int(rng.poisson(expected_arrivals))
    if arrival_count == 0:
        return {"baseline": 0.0, "proposed": 0.0, "arrivals": 0.0, "warmup_hours": warmup}
    arrivals = rng.uniform(-warmup, horizon_hours, size=arrival_count)
    trajectory_indices = rng.integers(0, len(model.trajectories), size=arrival_count)
    baseline_completed = 0
    proposed_completed = 0
    for arrival, index in zip(arrivals, trajectory_indices):
        trajectory = model.trajectories[int(index)]
        baseline_completion = float(arrival) + _trajectory_duration(trajectory)
        proposed_completion = float(arrival) + _scenario_duration(trajectory, scenario, resource_reduction)
        if 0.0 <= baseline_completion <= horizon_hours:
            baseline_completed += 1
        if 0.0 <= proposed_completion <= horizon_hours:
            proposed_completed += 1
    scale = 720.0 / horizon_hours
    return {
        "baseline": baseline_completed * scale,
        "proposed": proposed_completed * scale,
        "arrivals": arrival_count * scale,
        "warmup_hours": warmup,
    }


def _fidelity_status(errors: list[float]) -> str:
    worst = max(errors or [0.0])
    if worst <= 0.10:
        return "HIGH"
    if worst <= 0.25:
        return "MEDIUM"
    return "LOW"


def baseline_fidelity(
    model: BaselineProcessModel,
    simulated_durations: list[float],
    sla_hours: float,
    simulated_paths: list[tuple[str, ...]] | None = None,
    simulated_delays: list[float] | None = None,
) -> dict[str, Any]:
    observed = [_trajectory_duration(t) for t in model.trajectories]

    def m(vals: list[float]) -> dict[str, float]:
        return {
            "mean": statistics.fmean(vals),
            "median": statistics.median(vals),
            "p90": _percentile(vals, 90),
            "p95": _percentile(vals, 95),
            "sla": sum(x <= sla_hours for x in vals) / max(1, len(vals)),
        }

    o, s = m(observed), m(simulated_durations)
    keys = ["mean", "median", "p90", "p95"]
    errors = [abs(s[k] - o[k]) / max(abs(o[k]), 1e-9) for k in keys]
    errors.append(abs(s["sla"] - o["sla"]))
    status = _fidelity_status(errors)
    observed_variants = Counter(t.activities for t in model.trajectories)
    sampled_variants = Counter(simulated_paths or [])
    observed_total = max(1, sum(observed_variants.values()))
    sampled_total = max(1, sum(sampled_variants.values()))
    observed_delays = [d for t in model.trajectories for d in t.delays[1:]]
    sampled_delay_values = simulated_delays or []
    return {
        "status": status,
        "observed": {k: round(v, 4) for k, v in o.items()},
        "simulated_baseline": {k: round(v, 4) for k, v in s.items()},
        "relative_error": {k: round(abs(s[k] - o[k]) / max(abs(o[k]), 1e-9), 4) for k in keys},
        "sla_absolute_error": round(abs(s["sla"] - o["sla"]), 4),
        "variant_mix": {
            "observed_top": [
                {"path": list(path), "share": round(count / observed_total, 4)}
                for path, count in observed_variants.most_common(5)
            ],
            "simulated_top": [
                {"path": list(path), "share": round(count / sampled_total, 4)}
                for path, count in sampled_variants.most_common(5)
            ],
        },
        "transition_delay_distribution": {
            "observed_median": round(statistics.median(observed_delays), 4) if observed_delays else 0.0,
            "observed_p95": round(_percentile(observed_delays, 95), 4),
            "simulated_median": round(statistics.median(sampled_delay_values), 4) if sampled_delay_values else 0.0,
            "simulated_p95": round(_percentile(sampled_delay_values, 95), 4) if sampled_delay_values else 0.0,
        },
        "warning": "Scenario outputs should be treated as exploratory because the simulator does not closely reproduce observed baseline behavior."
        if status == "LOW"
        else None,
    }


def simulate_counterfactual(events: list[dict], scenario: ScenarioDefinition) -> dict[str, Any]:
    model = build_baseline_model(events)
    validate_scenario_against_model(model, scenario)
    # Immutable baseline model: scenario is only applied to copied trajectory arrays.
    n = len(model.trajectories)
    cohort_size = min(n, scenario.cohort_size or min(200, n))
    rng = np.random.default_rng(scenario.seed)
    resource_actions = [a for a in scenario.actions if isinstance(a, AddResourceCapacity)]
    resource_diagnostics = [_resource_effect(model, action) for action in resource_actions]
    resource_reduction = {x["activity"]: x["modeled_queue_delay_reduction_hours"] for x in resource_diagnostics}

    run_rows = []
    baseline_pool: list[float] = []
    proposed_pool: list[float] = []
    cost_pool: list[float] = []
    sampled_paths: list[tuple[str, ...]] = []
    sampled_delays: list[float] = []
    first_run_case_pairs: list[dict[str, Any]] = []
    application_counts: Counter[str] = Counter()
    sampled_case_count = 0
    effective_sla = next((a.hours for a in scenario.actions if isinstance(a, ChangeSLA)), scenario.sla_hours)

    for run in range(scenario.runs):
        indices = rng.integers(0, n, size=cohort_size).tolist()
        base_d, prop_d, starts, costs = [], [], [], []
        for idx in indices:
            t = model.trajectories[idx]
            sampled_paths.append(t.activities)
            sampled_delays.extend(t.delays[1:])
            baseline_duration = _trajectory_duration(t)
            activities, delays, trace = _apply_non_resource_actions(t, scenario)
            sampled_case_count += 1
            application_counts.update(trace["applied"])
            for i, activity in enumerate(activities):
                if i > 0 and activity in resource_reduction:
                    delays[i] = max(0.0, delays[i] - resource_reduction[activity])
            proposed_duration = sum(delays)
            base_d.append(baseline_duration)
            prop_d.append(proposed_duration)
            starts.append(t.start_hour)
            costs.append(t.cost)
            if run == 0 and len(first_run_case_pairs) < 25:
                first_run_case_pairs.append(
                    {
                        "case_id": t.case_id,
                        "baseline_path": list(t.activities),
                        "proposed_path": activities,
                        "case_attributes": {
                            "priority": t.attrs.get("priority"),
                            "value": t.attrs.get("value"),
                            "customer_type": t.attrs.get("customer_type"),
                            "region": t.attrs.get("region"),
                        },
                        "baseline_hours": round(baseline_duration, 6),
                        "proposed_hours": round(proposed_duration, 6),
                        "delta_hours": round(proposed_duration - baseline_duration, 6),
                        "applied": trace["applied"],
                    }
                )
        b = _metrics(base_d, costs, effective_sla)
        p = _metrics(prop_d, costs, effective_sla)
        throughput = simulate_fixed_horizon_throughput(
            model, scenario, resource_reduction, run_seed=scenario.seed + 1_000_003 * run + 97
        )
        baseline_pool.extend(base_d)
        proposed_pool.extend(prop_d)
        cost_pool.extend(costs)
        run_rows.append(
            {
                "run": run,
                "baseline_median": b["median_cycle_hours"],
                "proposed_median": p["median_cycle_hours"],
                "baseline_throughput": throughput["baseline"],
                "proposed_throughput": throughput["proposed"],
                "cycle_delta_hours": p["median_cycle_hours"] - b["median_cycle_hours"],
                "cycle_reduction_pct": 100
                * (b["median_cycle_hours"] - p["median_cycle_hours"])
                / max(b["median_cycle_hours"], 1e-9),
                "sla_delta_pp": 100 * (p["sla_compliance"] - b["sla_compliance"]),
                "throughput_delta": throughput["proposed"] - throughput["baseline"],
            }
        )

    # Aggregate paired samples across all runs. Baseline and proposed contain the same sampled cases in the same order.
    baseline = _metrics(baseline_pool, cost_pool, effective_sla)
    proposed = _metrics(proposed_pool, cost_pool, effective_sla)
    baseline["simulated_throughput_cases_per_30d"] = round(
        statistics.median([r["baseline_throughput"] for r in run_rows]), 4
    )
    proposed["simulated_throughput_cases_per_30d"] = round(
        statistics.median([r["proposed_throughput"] for r in run_rows]), 4
    )
    if resource_diagnostics:
        baseline["modeled_queue_delay_hours"] = round(
            statistics.fmean([d["baseline"]["average_queue_delay_hours"] for d in resource_diagnostics]), 4
        )
        proposed["modeled_queue_delay_hours"] = round(
            statistics.fmean([d["proposed"]["average_queue_delay_hours"] for d in resource_diagnostics]), 4
        )
        baseline["resource_utilization"] = round(
            statistics.fmean([d["baseline"]["utilization"] for d in resource_diagnostics]), 4
        )
        proposed["resource_utilization"] = round(
            statistics.fmean([d["proposed"]["utilization"] for d in resource_diagnostics]), 4
        )
    reductions = [r["cycle_reduction_pct"] for r in run_rows]
    sla_deltas = [r["sla_delta_pp"] for r in run_rows]
    median_delta_hours = [r["cycle_delta_hours"] for r in run_rows]
    uncertainty = {
        "cycle_time_reduction_pct": {
            "median": round(statistics.median(reductions), 4),
            "p10": round(_percentile(reductions, 10), 4),
            "p90": round(_percentile(reductions, 90), 4),
        },
        "median_cycle_delta_hours": {
            "median": round(statistics.median(median_delta_hours), 6),
            "p10": round(_percentile(median_delta_hours, 10), 6),
            "p90": round(_percentile(median_delta_hours, 90), 6),
        },
        "sla_compliance_delta_pp": {
            "median": round(statistics.median(sla_deltas), 4),
            "p10": round(_percentile(sla_deltas, 10), 4),
            "p90": round(_percentile(sla_deltas, 90), 4),
        },
    }
    fidelity = baseline_fidelity(model, baseline_pool, effective_sla, sampled_paths, sampled_delays)
    no_op = not scenario.actions
    return {
        "scenario": scenario.model_dump(mode="json"),
        "baseline": baseline,
        "proposed": proposed,
        "simulated_impact": {
            "median_cycle_reduction_pct": uncertainty["cycle_time_reduction_pct"]["median"],
            "p95_cycle_delta_hours": round(proposed["p95_cycle_hours"] - baseline["p95_cycle_hours"], 6),
            "sla_compliance_delta_pp": uncertainty["sla_compliance_delta_pp"]["median"],
            "throughput_delta_cases_per_30d": round(statistics.median([r["throughput_delta"] for r in run_rows]), 4),
        },
        "uncertainty": uncertainty,
        "baseline_fidelity": fidelity,
        "resource_diagnostics": resource_diagnostics,
        "throughput_methodology": {
            "metric": "SIMULATED 30-day completion volume under calibrated historical arrivals",
            "arrival_model": "Poisson arrivals calibrated from historical case-start timestamps",
            "historical_arrival_rate_cases_per_hour": round(model.case_arrival_rate_per_hour, 8),
            "historical_arrival_rate_cases_per_30d": round(model.case_arrival_rate_per_hour * 720.0, 4),
            "arrival_observation_span_hours": round(model.arrival_observation_span_hours, 4),
            "simulation_horizon_hours": 720.0,
            "warmup_hours": round(_throughput_warmup_hours(model), 4),
            "paired_baseline_proposed_arrivals": True,
            "independent_of_analysis_cohort_size": True,
        },
        "paired_run_evidence": first_run_case_pairs,
        "application_rates": {
            key: round(value / max(1, sampled_case_count), 6) for key, value in application_counts.items()
        },
        "common_random_numbers": True,
        "baseline_immutable": True,
        "no_op_exact": no_op and all(abs(a - b) <= 1e-12 for a, b in zip(baseline_pool, proposed_pool)),
        "terminology": {
            "observed": "metrics calculated directly from event logs",
            "simulated": "counterfactual scenario outputs from paired trajectory-bootstrap runs",
            "estimated": "financial/business value from explicit user assumptions",
            "simulated_completion_volume": "completed cases inside a fixed 30-day horizon under calibrated historical arrivals; not maximum system capacity",
        },
        "disclaimer": "SIMULATED IMPACT: paired empirical counterfactual estimates are exploratory, not guaranteed future results.",
    }

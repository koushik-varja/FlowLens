from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

REQUIRED = {"case_id", "activity", "timestamp"}
OPTIONAL = {
    "resource",
    "department",
    "cost",
    "status",
    "channel",
    "customer_type",
    "priority",
    "region",
    "value",
    "lifecycle",
}
SAFE_EXTS = {".csv", ".json"}
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", "10485760"))


class ValidationError(ValueError):
    pass


def parse_ts(v: str) -> datetime:
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except Exception as e:
        raise ValidationError(f"Invalid timestamp: {v}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def sanitize_filename(name: str) -> str:
    base = Path(name).name
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    if not cleaned or cleaned.startswith("."):
        cleaned = "upload" + Path(base).suffix.lower()
    return cleaned[:128]


def load_event_bytes(data: bytes, filename: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValidationError("Upload exceeds size limit")
    ext = Path(filename).suffix.lower()
    if ext not in SAFE_EXTS:
        raise ValidationError("Only CSV and JSON are supported")
    text = data.decode("utf-8-sig", errors="strict")
    rows: Any
    if ext == ".csv":
        rows = list(csv.DictReader(io.StringIO(text)))
    else:
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"Malformed JSON: {exc.msg}") from exc
        rows = obj if isinstance(obj, list) else obj.get("events") if isinstance(obj, dict) else None
        if not isinstance(rows, list):
            raise ValidationError("JSON must be a list or contain an events list")
    if not rows:
        raise ValidationError("No events found")
    missing = REQUIRED - set(rows[0])
    if missing:
        raise ValidationError(f"Missing required columns: {', '.join(sorted(missing))}")
    report: dict[str, Any] = {
        "rows": len(rows),
        "missing_case_id": 0,
        "missing_activity": 0,
        "invalid_timestamps": 0,
        "duplicates": 0,
        "chronology_issues": 0,
        "impossible_records": 0,
    }
    normalized: list[dict[str, Any]] = []
    seen = set()
    for i, r in enumerate(rows):
        cid = str(r.get("case_id") or "").strip()
        act = str(r.get("activity") or "").strip()
        rawts = str(r.get("timestamp") or "").strip()
        if not cid:
            report["missing_case_id"] += 1
            continue
        if not act:
            report["missing_activity"] += 1
            continue
        try:
            ts = parse_ts(rawts)
        except ValidationError:
            report["invalid_timestamps"] += 1
            continue
        key = (cid, act, ts.isoformat(), str(r.get("resource") or ""))
        if key in seen:
            report["duplicates"] += 1
            continue
        seen.add(key)
        cost = None
        if r.get("cost") not in (None, ""):
            try:
                cost = float(r["cost"])
            except Exception:
                report["impossible_records"] += 1
            if cost is not None and (not math.isfinite(cost) or cost < 0):
                report["impossible_records"] += 1
                cost = None
        nr = {k: (None if r.get(k) in (None, "") else r.get(k)) for k in OPTIONAL}
        nr.update({"case_id": cid, "activity": act, "timestamp": ts, "cost": cost, "row_index": i})
        normalized.append(nr)
    by: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in normalized:
        by[e["case_id"]].append(e)
    for evs in by.values():
        original: list[datetime] = [e["timestamp"] for e in evs]
        if original != sorted(original):
            report["chronology_issues"] += 1
        evs.sort(key=lambda e: (e["timestamp"], e["row_index"]))
    events = [e for cid in sorted(by) for e in by[cid]]
    report["valid_rows"] = len(events)
    report["quality_score"] = round(
        max(
            0,
            1
            - sum(
                report[k]
                for k in [
                    "missing_case_id",
                    "missing_activity",
                    "invalid_timestamps",
                    "duplicates",
                    "chronology_issues",
                    "impossible_records",
                ]
            )
            / max(1, len(rows)),
        ),
        4,
    )
    return events, report


def percentile(vals: list[float], p: float) -> float | None:
    return round(float(np.percentile(vals, p)), 4) if vals else None


def group_cases(events: list[dict]) -> dict[str, list[dict]]:
    by = defaultdict(list)
    for e in events:
        by[e["case_id"]].append(e)
    out = {}
    for cid, v in by.items():
        v.sort(key=lambda e: e["timestamp"])
        lifecycle_values = {str(e.get("lifecycle") or "").lower() for e in v}
        if lifecycle_values & {"start", "complete", "completed", "end"}:
            completed = [
                e
                for e in v
                if str(e.get("lifecycle") or "").lower() in {"complete", "completed", "end"} or not e.get("lifecycle")
            ]
            out[cid] = completed if completed else v
        else:
            out[cid] = v
    return out


def case_duration_hours(evs: list[dict]) -> float:
    return max(0.0, (evs[-1]["timestamp"] - evs[0]["timestamp"]).total_seconds() / 3600) if len(evs) > 1 else 0.0


def discover(events: list[dict]) -> dict[str, Any]:
    cases = group_cases(events)
    activities: Counter[str] = Counter()
    edges: defaultdict[tuple[str, str], dict[str, Any]] = defaultdict(lambda: {"times": [], "cases": set()})
    starts: Counter[str] = Counter()
    ends: Counter[str] = Counter()
    activity_cases: defaultdict[str, set[str]] = defaultdict(set)
    resources: defaultdict[str, set[str]] = defaultdict(set)
    for cid, evs in cases.items():
        acts = [e["activity"] for e in evs]
        activities.update(acts)
        starts[acts[0]] += 1
        ends[acts[-1]] += 1
        for e in evs:
            activity_cases[e["activity"]].add(cid)
            if e.get("resource"):
                resources[e["activity"]].add(str(e["resource"]))
        for a, b in zip(evs, evs[1:]):
            row = edges[(a["activity"], b["activity"])]
            row["times"].append(max(0, (b["timestamp"] - a["timestamp"]).total_seconds() / 3600))
            row["cases"].add(cid)
    edge_rows = []
    total_cases = max(1, len(cases))
    for (source, target), d in edges.items():
        vals = d["times"]
        edge_rows.append(
            {
                "source": source,
                "target": target,
                "frequency": len(vals),
                "case_percentage": round(100 * len(d["cases"]) / total_cases, 2),
                "avg_inter_event_delay_hours": round(statistics.fmean(vals), 4),
                "median_inter_event_delay_hours": round(statistics.median(vals), 4),
                "p95_inter_event_delay_hours": percentile(vals, 95) if len(vals) >= 5 else None,
            }
        )
    edge_rows.sort(key=lambda x: (-x["frequency"], x["source"], x["target"]))
    return {
        "activities": [
            {
                "activity": k,
                "frequency": v,
                "case_percentage": round(100 * len(activity_cases[k]) / total_cases, 2),
                "resource_count": len(resources[k]),
            }
            for k, v in activities.most_common()
        ],
        "edges": edge_rows,
        "start_activities": dict(starts),
        "end_activities": dict(ends),
        "case_count": len(cases),
        "event_count": len(events),
        "terminology_note": "With completion-only timestamps, edge delay is observed inter-event delay; it is not labeled pure waiting or processing time.",
    }


def variants(events: list[dict], sla_hours: float = 48) -> list[dict]:
    cases = group_cases(events)
    bucket = defaultdict(list)
    for cid, evs in cases.items():
        bucket[tuple(e["activity"] for e in evs)].append((cid, evs))
    total = len(cases)
    out = []
    for path, items in bucket.items():
        ds = [case_duration_hours(e) for _, e in items]
        costs = [sum(float(x.get("cost") or 0) for x in e) for _, e in items]
        out.append(
            {
                "path": list(path),
                "case_count": len(items),
                "percentage": round(100 * len(items) / max(1, total), 2),
                "avg_duration_hours": round(statistics.fmean(ds), 3),
                "median_duration_hours": round(statistics.median(ds), 3),
                "sla_breach_rate": round(sum(d > sla_hours for d in ds) / len(ds), 4),
                "avg_cost": round(statistics.fmean(costs), 2) if any(costs) else None,
            }
        )
    return sorted(out, key=lambda x: (-x["case_count"], x["path"]))


def rework(events: list[dict]) -> dict[str, Any]:
    cases = group_cases(events)
    affected = 0
    repeats: Counter[str] = Counter()
    add_hours = []
    add_cost = []
    for evs in cases.values():
        c = Counter(e["activity"] for e in evs)
        reps = {a: n - 1 for a, n in c.items() if n > 1}
        if reps:
            affected += 1
            repeats.update(reps)
            # conservative observed overhead: time spanning repeated occurrence intervals
            for a in reps:
                idx = [i for i, e in enumerate(evs) if e["activity"] == a]
                add_hours.append((evs[idx[-1]]["timestamp"] - evs[idx[0]]["timestamp"]).total_seconds() / 3600)
                add_cost.append(sum(float(e.get("cost") or 0) for e in evs[idx[0] + 1 : idx[-1] + 1]))
    return {
        "rework_rate": round(affected / max(1, len(cases)), 4),
        "cases_affected": affected,
        "repeated_activities": dict(repeats.most_common()),
        "observed_repeat_span_hours": round(sum(add_hours), 3),
        "observed_repeat_path_cost": round(sum(add_cost), 2),
        "terminology_note": "Repeat span is elapsed time between repeated occurrences; it is not claimed as labor overhead. Rework labor savings require an explicit effort/cost assumption.",
    }


def sla_analysis(events: list[dict], process_hours: float = 48, high_priority_hours: float = 24) -> dict[str, Any]:
    cases = group_cases(events)
    rows = []
    for cid, evs in cases.items():
        d = case_duration_hours(evs)
        pr = str(evs[0].get("priority") or "").lower()
        limit = high_priority_hours if pr == "high" else process_hours
        rows.append(
            {
                "case_id": cid,
                "duration_hours": round(d, 3),
                "limit_hours": limit,
                "violated": d > limit,
                "severity_hours": round(max(0, d - limit), 3),
            }
        )
    violations = [r for r in rows if r["violated"]]
    return {
        "compliance_rate": round(1 - len(violations) / max(1, len(rows)), 4),
        "violation_count": len(violations),
        "cases": rows,
    }


def bottlenecks(events: list[dict]) -> list[dict]:
    cases = group_cases(events)
    total_cycle = sum(case_duration_hours(e) for e in cases.values())
    has_lifecycle = any(
        str(e.get("lifecycle") or "").lower() in {"start", "complete", "completed", "end"} for e in events
    )
    waits = defaultdict(list)
    processing = defaultdict(list)
    case_seen = defaultdict(set)
    if has_lifecycle:
        raw = defaultdict(list)
        for e in events:
            raw[e["case_id"]].append(e)
        for cid, evs in raw.items():
            evs.sort(key=lambda e: e["timestamp"])
            pending = defaultdict(list)
            previous_complete = None
            for e in evs:
                lc = str(e.get("lifecycle") or "").lower()
                activity = e["activity"]
                if lc == "start":
                    pending[activity].append(e["timestamp"])
                    if previous_complete is not None:
                        waits[activity].append(max(0, (e["timestamp"] - previous_complete).total_seconds() / 3600))
                    case_seen[activity].add(cid)
                elif lc in {"complete", "completed", "end"}:
                    if pending[activity]:
                        started = pending[activity].pop(0)
                        processing[activity].append(max(0, (e["timestamp"] - started).total_seconds() / 3600))
                    previous_complete = e["timestamp"]
                    case_seen[activity].add(cid)
    else:
        for cid, evs in cases.items():
            for a, b in zip(evs, evs[1:]):
                h = max(0, (b["timestamp"] - a["timestamp"]).total_seconds() / 3600)
                waits[b["activity"]].append(h)
                case_seen[b["activity"]].add(cid)
    out = []
    for activity in sorted(set(waits) | set(processing)):
        delay_vals = waits.get(activity, [])
        proc_vals = processing.get(activity, [])
        evidence_vals = delay_vals or proc_vals
        if not evidence_vals:
            continue
        affected = len(case_seen[activity])
        contrib = sum(delay_vals) + sum(proc_vals)
        contrib /= max(total_cycle, 1e-9)
        score = (
            (statistics.median(evidence_vals) if evidence_vals else 0) * math.log1p(affected) * (1 + min(contrib, 1))
        )
        row = {
            "activity": activity,
            "cases_affected": affected,
            "percentage_cases": round(100 * affected / max(1, len(cases)), 2),
            "contribution_to_total_cycle": round(contrib, 4),
            "downstream_impact": round(statistics.fmean(evidence_vals) * affected, 3),
            "score": round(score, 3),
            "bottleneck_flag": score > 0,
        }
        if has_lifecycle:
            row.update(
                {
                    "timing_basis": "lifecycle start/complete",
                    "median_wait_hours": round(statistics.median(delay_vals), 3) if delay_vals else None,
                    "p95_wait_hours": percentile(delay_vals, 95),
                    "median_processing_hours": round(statistics.median(proc_vals), 3) if proc_vals else None,
                    "p95_processing_hours": percentile(proc_vals, 95),
                    "evidence": f"{affected} cases; lifecycle-derived queue wait and processing duration are reported separately.",
                    "terminology_note": "Waiting is previous completion to activity start; processing is activity start to completion.",
                }
            )
        else:
            row.update(
                {
                    "timing_basis": "completion-only",
                    "median_inter_event_delay_hours": round(statistics.median(delay_vals), 3),
                    "p95_inter_event_delay_hours": percentile(delay_vals, 95),
                    "evidence": f"{affected} cases; median inbound inter-event delay {statistics.median(delay_vals):.2f}h; observed elapsed-time share {100 * contrib:.1f}%",
                    "terminology_note": "Completion-only events support observed inter-event delay, not pure queue waiting or processing time.",
                }
            )
        out.append(row)
    return sorted(out, key=lambda x: -x["score"])


def conformance(events: list[dict], expected: list[str], max_loops: int = 1) -> dict[str, Any]:
    cases = group_cases(events)
    exp_pos = {a: i for i, a in enumerate(expected)}
    rows = []
    for cid, evs in cases.items():
        path = [e["activity"] for e in evs]
        seen = set(path)
        skipped = [a for a in expected if a not in seen]
        unexpected = [a for a in path if a not in exp_pos]
        known = [exp_pos[a] for a in path if a in exp_pos]
        wrong = any(b < a for a, b in zip(known, known[1:]))
        excessive = [a for a, n in Counter(path).items() if n > max_loops]
        rows.append(
            {
                "case_id": cid,
                "skipped": skipped,
                "unexpected": sorted(set(unexpected)),
                "wrong_ordering": wrong,
                "excessive_loops": excessive,
                "conformant": not (skipped or unexpected or wrong or excessive),
            }
        )
    return {
        "reference": expected,
        "compliance_rate": round(sum(bool(r["conformant"]) for r in rows) / max(1, len(rows)), 4),
        "cases": rows,
        "terminology_note": "Transparent sequence comparison; not a formal token-replay conformance guarantee.",
    }


# ML, simulation and business-value implementations live in focused modules; these wrappers preserve the original public imports.
from .ml import train_models as train_models, predict_snapshot as predict_snapshot  # noqa: E402
from .scenario_models import (  # noqa: E402
    ActivitySpeedup,
    AddResourceCapacity,
    AutomateEligibleCases,
    Condition,
    RemoveActivity,
    ScenarioDefinition,
    TransformationAction,
)
from .simulation import simulate_counterfactual  # noqa: E402
from .impact import BusinessAssumptions, calculate_business_impact  # noqa: E402


@dataclass
class Scenario:
    """Backward-compatible scenario adapter for the original compact API."""

    activity_speedups: dict[str, float]
    removed_activities: set[str]
    resource_multipliers: dict[str, float]
    automate_low_priority: bool = False


def simulate(
    events: list[dict], scenario: Scenario, sla_hours: float = 48, runs: int = 300, seed: int = 42
) -> dict[str, Any]:
    actions: list[TransformationAction] = []
    for activity, reduction in scenario.activity_speedups.items():
        if reduction > 0:
            actions.append(ActivitySpeedup(activity=activity, reduction_fraction=min(float(reduction), 0.95)))
    for activity in scenario.removed_activities:
        actions.append(RemoveActivity(activity=activity))
    for activity, multiplier in scenario.resource_multipliers.items():
        # Legacy multipliers are converted to additional integer capacity; no direct duration division remains.
        if multiplier > 1:
            actions.append(
                AddResourceCapacity(activity=activity, additional_capacity=max(1, int(round(multiplier - 1))))
            )
    if scenario.automate_low_priority:
        actions.append(
            AutomateEligibleCases(
                activity="Finance Review",
                conditions=[Condition(field="priority", op="eq", value="low")],
                reduction_fraction=0.65,
            )
        )
    result = simulate_counterfactual(
        events, ScenarioDefinition(name="Legacy scenario", actions=actions, runs=runs, sla_hours=sla_hours, seed=seed)
    )
    result["estimated_scenario_impact"] = result["simulated_impact"]
    return result


def recommendations(
    events: list[dict],
    assumptions: BusinessAssumptions | None = None,
    cycle_weight: float = 1.0,
    sla_weight: float = 0.5,
    business_weight: float = 0.0,
) -> list[dict]:
    bots = bottlenecks(events)
    if not bots:
        return []
    top = bots[0]
    activity = top["activity"]
    candidates = [
        (
            "Reduce observed delay",
            "MEDIUM",
            ScenarioDefinition(
                name=f"Speed up {activity}",
                actions=[ActivitySpeedup(activity=activity, reduction_fraction=0.25)],
                runs=60,
                seed=42,
            ),
        ),
        (
            "Increase resource capacity",
            "MEDIUM",
            ScenarioDefinition(
                name=f"Add capacity to {activity}",
                actions=[AddResourceCapacity(activity=activity, additional_capacity=1)],
                runs=60,
                seed=42,
            ),
        ),
        (
            "Automate eligible low-value cases",
            "HIGH",
            ScenarioDefinition(
                name=f"Automate low-value {activity}",
                actions=[
                    AutomateEligibleCases(
                        activity=activity,
                        conditions=[Condition(field="value", op="lt", value=10000)],
                        reduction_fraction=0.7,
                        processing_effort_saved_minutes=8,
                    )
                ],
                runs=60,
                seed=42,
            ),
        ),
    ]
    out = []
    for label, effort, scenario in candidates:
        sim = simulate_counterfactual(events, scenario)
        fidelity = sim["baseline_fidelity"]
        impact = sim["simulated_impact"]
        estimate = calculate_business_impact(sim, assumptions) if assumptions is not None else None
        business_value = float(estimate["estimated_monthly_value"]) if estimate else 0.0
        score = (
            cycle_weight * float(impact["median_cycle_reduction_pct"])
            + sla_weight * float(impact["sla_compliance_delta_pp"])
            + business_weight * business_value
        )
        out.append(
            {
                "recommendation": label,
                "activity": activity,
                "why_this": {
                    "cases_affected_pct": top["percentage_cases"],
                    "median_inter_event_delay_hours": top.get(
                        "median_inter_event_delay_hours", top.get("median_wait_hours", 0)
                    ),
                    "elapsed_time_contribution": top["contribution_to_total_cycle"],
                },
                "simulated": {
                    "median_cycle_reduction_pct": impact["median_cycle_reduction_pct"],
                    "sla_compliance_delta_pp": impact["sla_compliance_delta_pp"],
                    "uncertainty": sim["uncertainty"],
                    "fidelity_status": fidelity["status"],
                },
                "implementation_effort": effort,
                "estimated_business_effect": estimate,
                "rank_score": round(score, 4),
                "warning": fidelity["warning"],
            }
        )
    return sorted(out, key=lambda x: -x["rank_score"])


def business_impact(
    sim: dict, cases_per_month: int, labor_cost_per_hour: float, sla_breach_cost: float
) -> dict[str, Any]:
    assumptions = BusinessAssumptions(
        cases_per_month=cases_per_month,
        labor_cost_per_hour=labor_cost_per_hour,
        sla_breach_cost=sla_breach_cost,
        value_of_faster_completion_per_hour=0,
        illustrative=False,
    )
    return calculate_business_impact(sim, assumptions)

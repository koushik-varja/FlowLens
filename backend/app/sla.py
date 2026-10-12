from __future__ import annotations

from collections import defaultdict
from typing import Any, Literal
from pydantic import BaseModel, Field

from .scenario_models import Condition


class SlaRule(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scope: Literal["process", "activity", "segment"]
    threshold_hours: float = Field(gt=0)
    activity: str | None = None
    conditions: list[Condition] = Field(default_factory=list)
    severity: Literal["low", "medium", "high", "critical"] = "medium"


def _matches(attrs: dict[str, Any], conditions: list[Condition]) -> bool:
    from .simulation import matches_conditions

    return matches_conditions(attrs, conditions)


def _hours(a, b) -> float:
    return max(0.0, (b["timestamp"] - a["timestamp"]).total_seconds() / 3600)


def evaluate_sla_rules(events: list[dict], rules: list[SlaRule]) -> dict[str, Any]:
    by: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        by[event["case_id"]].append(event)
    for evs in by.values():
        evs.sort(key=lambda x: x["timestamp"])

    results = []
    total_violations = 0
    contribution: defaultdict[str, float] = defaultdict(float)
    for rule in rules:
        assessed = []
        for cid, evs in by.items():
            attrs = dict(evs[0])
            attrs.update(evs[-1])
            if rule.scope == "segment" and not _matches(attrs, rule.conditions):
                continue
            if rule.scope in {"process", "segment"}:
                value = _hours(evs[0], evs[-1]) if len(evs) > 1 else 0.0
                contributions = []
                for prev, curr in zip(evs, evs[1:]):
                    contributions.append((curr["activity"], _hours(prev, curr)))
            else:
                if not rule.activity:
                    continue
                pairs = [(prev, curr) for prev, curr in zip(evs, evs[1:]) if curr["activity"] == rule.activity]
                if not pairs:
                    continue
                # Completion-only logs support inbound inter-event delay, not pure processing time.
                value = max((_hours(prev, curr) for prev, curr in pairs), default=0.0)
                contributions = [(rule.activity, value)]
            violated = value > rule.threshold_hours
            severity_hours = max(0.0, value - rule.threshold_hours)
            if violated:
                total_violations += 1
                for activity, hours in contributions:
                    contribution[activity] += hours
            assessed.append(
                {
                    "case_id": cid,
                    "observed_hours": round(value, 4),
                    "threshold_hours": rule.threshold_hours,
                    "violated": violated,
                    "severity_hours": round(severity_hours, 4),
                }
            )
        violations = [x for x in assessed if x["violated"]]
        results.append(
            {
                "name": rule.name,
                "scope": rule.scope,
                "activity": rule.activity,
                "severity": rule.severity,
                "assessed_cases": len(assessed),
                "violation_count": len(violations),
                "compliance_rate": round(1 - len(violations) / max(1, len(assessed)), 4),
                "cases": assessed,
            }
        )

    total_contrib = sum(contribution.values())
    contribution_rows = [
        {
            "activity": activity,
            "observed_elapsed_hours_in_breached_cases": round(hours, 4),
            "share": round(hours / total_contrib, 4) if total_contrib else 0.0,
        }
        for activity, hours in sorted(contribution.items(), key=lambda item: (-item[1], item[0]))
    ]
    return {
        "rules": results,
        "total_violations": total_violations,
        "observed_duration_contribution": contribution_rows,
        "terminology_note": "Activity SLA uses observed inbound inter-event delay when lifecycle start/complete timestamps are unavailable; this is not causal attribution or pure processing/waiting time.",
    }

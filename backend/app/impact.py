from __future__ import annotations

from typing import Any
from pydantic import BaseModel, Field


class BusinessAssumptions(BaseModel):
    cases_per_month: int = Field(default=1000, gt=0, le=10_000_000)
    labor_cost_per_hour: float = Field(default=30.0, ge=0)
    processing_effort_by_activity_minutes: dict[str, float] = Field(default_factory=dict)
    sla_breach_cost: float = Field(default=0.0, ge=0)
    rework_cost: float = Field(default=0.0, ge=0)
    automation_cost_monthly: float = Field(default=0.0, ge=0)
    implementation_cost_monthly: float = Field(default=0.0, ge=0)
    value_of_faster_completion_per_hour: float = Field(default=0.0, ge=0)
    illustrative: bool = True


def calculate_business_impact(simulation: dict[str, Any], assumptions: BusinessAssumptions) -> dict[str, Any]:
    baseline = simulation["baseline"]
    proposed = simulation["proposed"]
    cycle_hours_saved = max(0.0, baseline["mean_cycle_hours"] - proposed["mean_cycle_hours"])
    time_to_completion_value = (
        cycle_hours_saved * assumptions.cases_per_month * assumptions.value_of_faster_completion_per_hour
    )

    # Labor effort savings are only created by explicit automation effort assumptions in scenario actions.
    labor_savings = 0.0
    application_rates = simulation.get("application_rates", {})
    for action in simulation.get("scenario", {}).get("actions", []):
        if action.get("type") == "automate_eligible_cases":
            activity = str(action.get("activity") or "")
            explicit_saved = action.get("processing_effort_saved_minutes")
            saved_minutes = (
                float(explicit_saved)
                if explicit_saved is not None
                else float(assumptions.processing_effort_by_activity_minutes.get(activity, 0.0))
            )
            rate = float(application_rates.get(f"automation:{activity}", 0.0))
            labor_savings += (
                (saved_minutes / 60.0) * assumptions.cases_per_month * rate * assumptions.labor_cost_per_hour
            )

    sla_improvement = max(0.0, proposed["sla_compliance"] - baseline["sla_compliance"])
    sla_cost_avoidance = sla_improvement * assumptions.cases_per_month * assumptions.sla_breach_cost

    # Rework impact is zero unless the simulator explicitly reports rework reduction.
    rework_rate_delta = max(0.0, float(simulation.get("simulated_impact", {}).get("rework_rate_reduction", 0.0)))
    rework_savings = rework_rate_delta * assumptions.cases_per_month * assumptions.rework_cost

    recurring_costs = assumptions.automation_cost_monthly + assumptions.implementation_cost_monthly
    gross = time_to_completion_value + labor_savings + sla_cost_avoidance + rework_savings
    net = gross - recurring_costs
    return {
        "estimated_monthly_value": round(net, 2),
        "categories": {
            "time_to_completion_value": round(time_to_completion_value, 2),
            "labor_effort_savings": round(labor_savings, 2),
            "sla_cost_avoidance": round(sla_cost_avoidance, 2),
            "rework_savings": round(rework_savings, 2),
            "recurring_costs": round(recurring_costs, 2),
        },
        "lead_time_hours_saved_per_case": round(cycle_hours_saved, 4),
        "labor_savings_requires_effort_assumption": True,
        "assumptions": assumptions.model_dump(),
        "assumption_label": "ILLUSTRATIVE SAMPLE VALUES" if assumptions.illustrative else "USER-CONFIGURED VALUES",
        "formulas": {
            "time_to_completion": "lead-time hours saved × cases/month × explicit value_of_faster_completion_per_hour",
            "labor": "explicit processing-effort minutes saved by automation × cases/month × labor cost/hour",
            "sla": "SLA compliance improvement × cases/month × supplied breach cost",
            "rework": "modeled rework-rate reduction × cases/month × supplied rework cost",
        },
        "disclaimer": "ESTIMATED business value from explicit assumptions; elapsed cycle time is not treated as labor time.",
    }

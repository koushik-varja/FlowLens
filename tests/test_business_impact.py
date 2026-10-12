from backend.app.impact import BusinessAssumptions, calculate_business_impact


def sim(actions=None, mean_base=10, mean_prop=8, sla_base=0.8, sla_prop=0.9):
    return {
        "baseline": {"mean_cycle_hours": mean_base, "sla_compliance": sla_base},
        "proposed": {"mean_cycle_hours": mean_prop, "sla_compliance": sla_prop},
        "scenario": {"actions": actions or []},
        "simulated_impact": {},
        "application_rates": {"automation:Finance Review": 1.0},
    }


def test_cycle_time_not_equated_to_labor_savings():
    result = calculate_business_impact(
        sim(), BusinessAssumptions(cases_per_month=100, labor_cost_per_hour=50, illustrative=False)
    )
    assert result["categories"]["labor_effort_savings"] == 0
    assert result["categories"]["time_to_completion_value"] == 0


def test_labor_savings_require_explicit_effort_assumption():
    actions = [{"type": "automate_eligible_cases", "activity": "Finance Review", "processing_effort_saved_minutes": 12}]
    result = calculate_business_impact(
        sim(actions, mean_base=10, mean_prop=10, sla_base=0.8, sla_prop=0.8),
        BusinessAssumptions(cases_per_month=100, labor_cost_per_hour=60, illustrative=False),
    )
    assert result["categories"]["labor_effort_savings"] == 1200


def test_sla_cost_formula():
    result = calculate_business_impact(
        sim(mean_base=10, mean_prop=10),
        BusinessAssumptions(cases_per_month=100, sla_breach_cost=50, illustrative=False),
    )
    assert result["categories"]["sla_cost_avoidance"] == 500


def test_noop_business_value_zero():
    result = calculate_business_impact(
        sim(mean_base=10, mean_prop=10, sla_base=0.8, sla_prop=0.8),
        BusinessAssumptions(cases_per_month=100, labor_cost_per_hour=100, sla_breach_cost=500, illustrative=False),
    )
    assert result["estimated_monthly_value"] == 0

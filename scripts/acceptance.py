from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.app.core import load_event_bytes
from backend.app.impact import BusinessAssumptions, calculate_business_impact
from backend.app.ml import load_persisted_models, persist_models, score_active_cases, train_models
from backend.app.scenario_models import (
    ActivitySpeedup,
    AutomateEligibleCases,
    Condition,
    ParallelizeActivities,
    RemoveActivity,
    ScenarioDefinition,
)
from backend.app.simulation import simulate_counterfactual, simulate_resource_queue
from backend.app.sla import SlaRule, evaluate_sla_rules

p = Path("data/sample/synthetic_procurement.csv")
events, _ = load_event_bytes(p.read_bytes(), p.name)
res = {}
noop = simulate_counterfactual(events, ScenarioDefinition(name="NOOP", actions=[], runs=60, seed=42))
noimpact = calculate_business_impact(
    noop, BusinessAssumptions(cases_per_month=1000, labor_cost_per_hour=50, sla_breach_cost=100, illustrative=False)
)
res["A_noop"] = {
    "passed": noop["no_op_exact"]
    and noop["simulated_impact"]["median_cycle_reduction_pct"] == 0
    and noop["simulated_impact"]["sla_compliance_delta_pp"] == 0
    and noop["simulated_impact"]["p95_cycle_delta_hours"] == 0
    and noimpact["estimated_monthly_value"] == 0,
    "median_cycle_delta_hours": noop["uncertainty"]["median_cycle_delta_hours"]["median"],
    "sla_delta_pp": noop["simulated_impact"]["sla_compliance_delta_pp"],
    "p95_delta_hours": noop["simulated_impact"]["p95_cycle_delta_hours"],
    "business_value": noimpact["estimated_monthly_value"],
}
remove = simulate_counterfactual(
    events, ScenarioDefinition(name="remove", actions=[RemoveActivity(activity="Finance Review")], runs=40, seed=42)
)
res["B_remove_activity"] = {
    "passed": remove["baseline_immutable"]
    and remove["proposed"]["median_cycle_hours"] < remove["baseline"]["median_cycle_hours"],
    "baseline_median": remove["baseline"]["median_cycle_hours"],
    "proposed_median": remove["proposed"]["median_cycle_hours"],
}
auto = simulate_counterfactual(
    events,
    ScenarioDefinition(
        name="selective",
        actions=[
            AutomateEligibleCases(
                activity="Finance Review",
                conditions=[Condition(field="priority", op="eq", value="low")],
                reduction_fraction=0.5,
            )
        ],
        runs=40,
        seed=42,
    ),
)
applied = [x for x in auto["paired_run_evidence"] if "automation:Finance Review" in x["applied"]]
unchanged = [x for x in auto["paired_run_evidence"] if not x["applied"]]
res["C_selective_automation"] = {
    "passed": bool(applied and unchanged),
    "eligible_examples_changed": len(applied),
    "noneligible_examples_unchanged": len(unchanged),
}
q1 = simulate_resource_queue([0, 0.1, 0.2, 0.3, 0.4, 0.5], [2, 2, 2, 2, 2, 2], 1)
q2 = simulate_resource_queue([0, 0.1, 0.2, 0.3, 0.4, 0.5], [2, 2, 2, 2, 2, 2], 2)
res["D_resource_capacity"] = {
    "passed": q2["average_queue_delay_hours"] < q1["average_queue_delay_hours"]
    and q2["utilization"] != q1["utilization"],
    "capacity1": q1,
    "capacity2": q2,
}
base = datetime(2026, 1, 1, tzinfo=timezone.utc)
pe = []
for i in range(30):
    s = i * 10
    for a, h in [("Start", s), ("Finance", s + 4), ("Compliance", s + 10), ("End", s + 11)]:
        pe.append(
            {
                "case_id": str(i),
                "activity": a,
                "timestamp": base + timedelta(hours=h),
                "priority": "normal",
                "resource": "R1",
                "cost": 1,
            }
        )
par = simulate_counterfactual(
    pe,
    ScenarioDefinition(
        name="parallel",
        actions=[ParallelizeActivities(first_activity="Finance", second_activity="Compliance")],
        runs=30,
        seed=3,
    ),
)
res["E_parallelization"] = {
    "passed": abs(par["baseline"]["median_cycle_hours"] - 11) < 1e-9
    and abs(par["proposed"]["median_cycle_hours"] - 7) < 1e-9,
    "baseline_median": par["baseline"]["median_cycle_hours"],
    "proposed_median": par["proposed"]["median_cycle_hours"],
}
res["F_baseline_fidelity"] = {
    "passed": noop["baseline_fidelity"]["status"] in {"HIGH", "MEDIUM", "LOW"},
    **noop["baseline_fidelity"],
}
trained = train_models(events, 48)
overlap = set(trained["split"]["train_case_ids"]) & set(trained["split"]["test_case_ids"])
res["G_ml_leakage"] = {
    "passed": not overlap,
    "overlap_count": len(overlap),
    "train_cases": trained["split"]["train_cases"],
    "test_cases": trained["split"]["test_cases"],
    "metrics": trained["metrics"],
    "remaining_metrics": trained["remaining_metrics"],
}
with TemporaryDirectory() as td:
    meta = persist_models(101, trained, Path(td))
    persisted = load_persisted_models(101, Path(td), meta["version"])
    ts = sorted(e["timestamp"] for e in events)
    cutoff = ts[int(0.7 * (len(ts) - 1))]
    scored = score_active_cases(events, cutoff, persisted)
    res["H_active_case"] = {
        "passed": bool(scored)
        and all(
            "breach_probability" in x and "expected_remaining_hours" in x and x["model_version"] == meta["version"]
            for x in scored
        ),
        "cutoff": cutoff.isoformat(),
        "active_cases": len(scored),
        "model_version": meta["version"],
    }
sla = evaluate_sla_rules(
    events, [SlaRule(name="Finance Review < 12h", scope="activity", activity="Finance Review", threshold_hours=12)]
)
res["I_activity_sla"] = {
    "passed": sla["rules"][0]["assessed_cases"] > 0,
    "assessed_cases": sla["rules"][0]["assessed_cases"],
    "violations": sla["rules"][0]["violation_count"],
}
lead_only = {
    "baseline": {"mean_cycle_hours": 10, "sla_compliance": 0.8},
    "proposed": {"mean_cycle_hours": 8, "sla_compliance": 0.8},
    "scenario": {"actions": []},
    "simulated_impact": {},
}
bi = calculate_business_impact(
    lead_only, BusinessAssumptions(cases_per_month=100, labor_cost_per_hour=100, illustrative=False)
)
res["J_business_value"] = {
    "passed": bi["categories"]["labor_effort_savings"] == 0,
    "lead_time_saved": bi["lead_time_hours_saved_per_case"],
    "labor_savings": bi["categories"]["labor_effort_savings"],
}
os.environ["DATABASE_URL"] = "sqlite:///./acceptance_api.db"
os.environ.pop("ADMIN_API_KEY", None)
from fastapi.testclient import TestClient  # noqa: E402
from backend.app.main import app  # noqa: E402

client = TestClient(app)
raw = b"case_id,activity,timestamp\n1,A,2026-01-01T00:00:00Z\n1,B,2026-01-01T01:00:00Z\n"
r = client.post("/datasets", files={"file": ("x.csv", raw, "text/csv")})
did = r.json()["id"]
status = client.delete(f"/datasets/{did}").status_code
res["K_admin_security"] = {"passed": status == 503, "status_without_admin_key": status}
throughputs = []
for cohort in (50, 100, 200, 400):
    throughput_run = simulate_counterfactual(
        events,
        ScenarioDefinition(
            name=f"throughput-{cohort}",
            actions=[ActivitySpeedup(activity="Finance Review", reduction_fraction=0.2)],
            runs=20,
            seed=77,
            cohort_size=cohort,
        ),
    )
    throughputs.append(float(throughput_run["baseline"]["simulated_throughput_cases_per_30d"]))
spread = (max(throughputs) - min(throughputs)) / max(max(throughputs), 1e-9)
res["L_throughput_invariance"] = {
    "passed": spread <= 0.05 and throughputs[-1] < throughputs[0] * 1.2,
    "cohort_sizes": [50, 100, 200, 400],
    "baseline_throughput_cases_per_30d": throughputs,
    "relative_spread": spread,
    "methodology": throughput_run["throughput_methodology"],
}
Path("acceptance_api.db").unlink(missing_ok=True)
res["summary"] = {"passed": all(v.get("passed", False) for k, v in res.items() if k != "summary"), "executed": len(res)}
Path("benchmarks/results/acceptance.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
print(json.dumps(res, indent=2))

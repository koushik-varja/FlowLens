from pathlib import Path
from tempfile import TemporaryDirectory
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.app.core import bottlenecks, discover, load_event_bytes, variants
from backend.app.impact import BusinessAssumptions, calculate_business_impact
from backend.app.ml import load_persisted_models, persist_models, score_active_cases, train_models
from backend.app.scenario_models import ActivitySpeedup, ScenarioDefinition
from backend.app.simulation import simulate_counterfactual

path = Path("data/sample/synthetic_procurement.csv")
events, quality = load_event_bytes(path.read_bytes(), path.name)
assert quality["valid_rows"] > 0 and discover(events)["case_count"] == 500 and variants(events) and bottlenecks(events)
noop = simulate_counterfactual(events, ScenarioDefinition(name="No-op acceptance", actions=[], runs=40, seed=42))
assert (
    noop["no_op_exact"]
    and noop["simulated_impact"]["median_cycle_reduction_pct"] == 0
    and noop["simulated_impact"]["sla_compliance_delta_pp"] == 0
)
scenario = simulate_counterfactual(
    events,
    ScenarioDefinition(
        name="Finance speedup",
        actions=[ActivitySpeedup(activity="Finance Review", reduction_fraction=0.25)],
        runs=40,
        seed=42,
    ),
)
assert (
    scenario["baseline_immutable"]
    and scenario["common_random_numbers"]
    and scenario["baseline_fidelity"]["status"] in {"HIGH", "MEDIUM", "LOW"}
)
impact = calculate_business_impact(
    noop, BusinessAssumptions(cases_per_month=1000, labor_cost_per_hour=30, illustrative=False)
)
assert impact["estimated_monthly_value"] == 0
trained = train_models(events, 48)
assert set(trained["split"]["train_case_ids"]).isdisjoint(trained["split"]["test_case_ids"])
with TemporaryDirectory() as td:
    from pathlib import Path as P

    meta = persist_models(999, trained, P(td))
    loaded = load_persisted_models(999, P(td), meta["version"])
    times = sorted(e["timestamp"] for e in events)
    cutoff = times[int(0.7 * (len(times) - 1))]
    active = score_active_cases(events, cutoff, loaded)
    assert active and all(x["model_version"] == meta["version"] for x in active)
print(
    "FlowLens smoke workflow passed:",
    len(events),
    "events; no-op exact; paired scenario; case-safe persisted ML; active-case scoring",
)

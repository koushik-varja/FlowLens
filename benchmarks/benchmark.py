from __future__ import annotations

import csv
import io
import json
import os
import platform
import statistics
import sys
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import backend.app.core as core
from backend.app.core import bottlenecks, discover, load_event_bytes, variants
from backend.app.ml import predict_snapshot, train_models
from backend.app.scenario_models import ActivitySpeedup, ScenarioDefinition
from backend.app.simulation import simulate_counterfactual
from backend.app.sla import SlaRule, evaluate_sla_rules
from data.generator.generate import generate


def machine_ram_mb():
    try:
        return round(os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / 1024 / 1024)
    except Exception:
        return None


def serialize(rows):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode()


def timed(fn):
    start = time.perf_counter()
    result = fn()
    return result, time.perf_counter() - start


def bench(cases: int, simulation_runs: int):
    generated = generate(cases, 42)
    raw = serialize(generated)
    core.MAX_UPLOAD_BYTES = max(core.MAX_UPLOAD_BYTES, len(raw) + 1)
    tracemalloc.start()
    rows, import_s = timed(lambda: load_event_bytes(raw, "bench.csv")[0])
    graph, graph_s = timed(lambda: discover(rows))
    _, variants_s = timed(lambda: variants(rows))
    _, bottleneck_s = timed(lambda: bottlenecks(rows))
    sla_rules = [
        SlaRule(name="process", scope="process", threshold_hours=48),
        SlaRule(name="finance", scope="activity", activity="Finance Review", threshold_hours=12),
    ]
    _, sla_s = timed(lambda: evaluate_sla_rules(rows, sla_rules))
    scenario = ScenarioDefinition(
        name="benchmark",
        actions=[ActivitySpeedup(activity="Finance Review", reduction_fraction=0.2)],
        runs=simulation_runs,
        seed=42,
    )
    sim, simulation_s = timed(lambda: simulate_counterfactual(rows, scenario))
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return (
        {
            "cases": cases,
            "events": len(rows),
            "activities": len(graph["activities"]),
            "import_seconds": round(import_s, 6),
            "graph_seconds": round(graph_s, 6),
            "variants_seconds": round(variants_s, 6),
            "bottlenecks_seconds": round(bottleneck_s, 6),
            "sla_seconds": round(sla_s, 6),
            "simulation_runs": simulation_runs,
            "paired_monte_carlo_seconds": round(simulation_s, 6),
            "baseline_fidelity_status": sim["baseline_fidelity"]["status"],
            "baseline_throughput_cases_per_30d": sim["baseline"]["simulated_throughput_cases_per_30d"],
            "proposed_throughput_cases_per_30d": sim["proposed"]["simulated_throughput_cases_per_30d"],
            "throughput_methodology": sim["throughput_methodology"],
            "peak_python_memory_mb": round(peak / 1024 / 1024, 3),
        },
        raw,
        rows,
        sim,
    )


def percentile(values, p):
    values = sorted(values)
    idx = int((p / 100) * (len(values) - 1))
    return values[idx]


small, raw, small_rows, fidelity_sim = bench(1500, 60)
large, _, _, _ = bench(15000, 30)

# Absolute-throughput invariance: analysis cohort size must not determine fixed-horizon completions.
throughput_invariance_values = []
for cohort_size in (50, 100, 200, 400):
    scenario = ScenarioDefinition(
        name=f"throughput-invariance-{cohort_size}",
        actions=[ActivitySpeedup(activity="Finance Review", reduction_fraction=0.2)],
        runs=20,
        seed=77,
        cohort_size=cohort_size,
    )
    sim = simulate_counterfactual(small_rows, scenario)
    throughput_invariance_values.append(sim["baseline"]["simulated_throughput_cases_per_30d"])
throughput_invariance = {
    "cohort_sizes": [50, 100, 200, 400],
    "baseline_throughput_cases_per_30d": throughput_invariance_values,
    "relative_spread": round(
        (max(throughput_invariance_values) - min(throughput_invariance_values))
        / max(max(throughput_invariance_values), 1e-9),
        6,
    ),
    "passes_non_scaling_check": max(throughput_invariance_values) <= min(throughput_invariance_values) * 1.05
    if min(throughput_invariance_values) > 0
    else max(throughput_invariance_values) == 0,
    "methodology": sim["throughput_methodology"],
}

# Measured ML inference latency on the ~10k-event dataset.
trained, train_seconds = timed(lambda: train_models(small_rows, 48))
snapshot = {
    "elapsed_hours": 8,
    "current_activity": "Finance Review",
    "prior_count": 3,
    "rework_count": 0,
    "priority": "normal",
    "department": "Finance",
}
inference = []
for _ in range(100):
    start = time.perf_counter()
    predict_snapshot(trained, snapshot)
    inference.append((time.perf_counter() - start) * 1000)
ml = {
    "training_seconds": round(train_seconds, 6),
    "inference_requests": len(inference),
    "inference_p50_ms": round(statistics.median(inference), 4),
    "inference_p95_ms": round(percentile(inference, 95), 4),
    "classification_metrics": trained["metrics"],
    "remaining_time_metrics": trained["remaining_metrics"],
}

api = {}
try:
    os.environ["DATABASE_URL"] = "sqlite:///./benchmark_api.db"
    from fastapi.testclient import TestClient
    from backend.app.main import app

    client = TestClient(app)
    response = client.post("/datasets", files={"file": ("bench.csv", raw, "text/csv")})
    response.raise_for_status()
    dataset_id = response.json()["id"]
    graph_latencies = []
    for _ in range(25):
        start = time.perf_counter()
        response = client.get(f"/processes/{dataset_id}/graph")
        response.raise_for_status()
        graph_latencies.append((time.perf_counter() - start) * 1000)
    api = {
        "requests": len(graph_latencies),
        "graph_api_p50_ms": round(statistics.median(graph_latencies), 3),
        "graph_api_p95_ms": round(percentile(graph_latencies, 95), 3),
    }
except Exception as error:
    api = {"error": f"{type(error).__name__}: {error}"}
finally:
    Path("benchmark_api.db").unlink(missing_ok=True)

result = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "environment": {
        "os": platform.platform(),
        "cpu": platform.processor() or "not reported",
        "ram_mb": machine_ram_mb(),
        "python": platform.python_version(),
    },
    "results": [small, large],
    "ml": ml,
    "api_latency": api,
    "baseline_fidelity": fidelity_sim["baseline_fidelity"],
    "throughput_invariance": throughput_invariance,
}
Path("benchmarks/results").mkdir(parents=True, exist_ok=True)
Path("benchmarks/results/local.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
Path("benchmarks/results/fidelity.json").write_text(
    json.dumps(fidelity_sim["baseline_fidelity"], indent=2), encoding="utf-8"
)
print(json.dumps(result, indent=2))

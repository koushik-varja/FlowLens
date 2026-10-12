# Verification report — FlowLens final v3 freeze patch

This report contains only checks actually executed in the final patch environment. Unavailable checks are explicitly marked **NOT EXECUTED**.

## Backend and acceptance verification

- `pytest -q`: **44 passed, 0 failed**.
- `python scripts/acceptance.py`: **12/12 acceptance groups A–L passed**.
- `python -m compileall -q backend data scripts benchmarks alembic tests`: executed successfully in the final audit.

Key acceptance results:

- No-op median cycle delta: **0.0 h**.
- No-op p95 cycle delta: **0.0 h**.
- No-op SLA delta: **0.0 percentage points**.
- No-op estimated business value: **0.0**.
- Remove-activity baseline/proposed median: **41.6501 h / 29.738 h**.
- Selective automation: **10 eligible examples changed**, **15 non-eligible examples unchanged**.
- Resource queue average delay: **4.75 h → 1.8 h** when capacity increases 1 → 2.
- Parallelization median: **11.0 h → 7.0 h**.
- ML train/test case overlap: **0**.
- Activity SLA: **244 violations across 500 assessed cases**.
- Lead-time-only scenario labor savings: **0.0**.
- Admin endpoint without `ADMIN_API_KEY`: **HTTP 503**.
- Completion-volume invariance test, cohort sizes **50 / 100 / 200 / 400**: baseline SIMULATED 30-day completion volume **184.5 / 184.5 / 184.5 / 184.5 cases**, relative spread **0.0%**.

Raw acceptance output is saved at `benchmarks/results/acceptance.json`.

## SIMULATED 30-day completion-volume methodology

The previous metric counted completions from the analysis bootstrap cohort itself, so the reported absolute completion count scaled almost linearly with `cohort_size`.

The patched method is independent of that analysis cohort:

1. estimate case arrival rate from historical case-start timestamps;
2. simulate Poisson arrivals over a fixed **720-hour / 30-day** observation horizon;
3. include a bounded p95-cycle warm-up so in-flight cases can complete inside the measurement window;
4. bootstrap empirical historical trajectory templates for those arrivals;
5. run baseline and proposed branches with the **same arrivals and trajectory draws**;
6. count cases completing inside the fixed horizon.

`cohort_size` now controls cycle-time/SLA Monte Carlo sampling only. It does not determine the arrivals used for the SIMULATED 30-day completion volume. This metric is **under calibrated historical arrivals** and is not a maximum system-capacity estimate.

## Real benchmark snapshot

`python benchmarks/benchmark.py` executed successfully and regenerated `benchmarks/results/local.json` and `benchmarks/results/fidelity.json`.

Environment: Linux 6.18.44 x86_64, Python 3.13.5, RAM reported 5948 MB.

| Metric | 10,431 events | 103,853 events |
|---|---:|---:|
| Import | 0.400293 s | 4.057596 s |
| Process graph | 0.090875 s | 1.085993 s |
| Variants | 0.024838 s | 0.364795 s |
| Bottlenecks | 0.108241 s | 1.329839 s |
| SLA rules | 0.094322 s | 1.127224 s |
| Paired Monte Carlo | 1.688371 s / 60 runs | 7.142452 s / 30 runs |
| Baseline SIMULATED 30-day completion volume | 542.0 | 5394.5 |
| Proposed SIMULATED 30-day completion volume | 543.0 | 5398.0 |
| Peak Python-tracked memory | 19.814 MB | 196.185 MB |

Completion-volume calibration in the ~10k benchmark:

- historical arrival rate: **541.2321 cases/30d**;
- fixed simulation horizon: **720 h**;
- warm-up: **99.794 h**;
- cohort-size invariance benchmark (50/100/200/400): **548.5 / 548.5 / 548.5 / 548.5 cases/30d**, relative spread **0.0%**.

FastAPI graph latency across 25 requests: p50 **44.64 ms**, p95 **47.258 ms**.

ML benchmark on ~10k events:

- Training: **2.287143 s**.
- Inference p50/p95 across 100 requests: **11.8197 / 13.6946 ms**.
- Precision **0.8182**, recall **0.8257**, F1 **0.8219**.
- ROC-AUC **0.9425**, PR-AUC **0.9198**.
- Remaining-time MAE **7.03 h**, median AE **4.278 h**, RMSE **11.808 h**.

Baseline fidelity remained **HIGH**. Observed/simulated median: **41.0743 / 40.8019 h**; p95: **99.794 / 98.7557 h**; SLA absolute error: **0.0052**.

## Frontend verification

- TypeScript/TSX syntax transpilation using the globally installed TypeScript compiler: **12 source/test files checked, 0 syntax errors**.
- Transformation Lab source now exposes speedup, removal, resource capacity, selective automation, parallelization, structured routing, priority routing acceleration and scenario SLA override.
- Business Impact source exposes cases/month, labor rate, activity processing effort, SLA-breach cost, rework cost, automation cost and implementation cost and labels them **ILLUSTRATIVE USER INPUTS**.
- Frontend regression tests were added for SCC cycle layout and normal DAG layout, stale Active Case Risk data, dedicated bottleneck highlighting, safe structured scenario conditions, and scenario comparison rendering.
- Because React/Vitest/jsdom packages are not installed locally and registry access is unavailable, the Vitest suite itself is **NOT EXECUTED**. Actual source-level runtime checks were still executed for SCC layout, ActiveRisk stale-state guard, bottleneck hot-node rendering, Scenario Builder structured condition creation and Scenario Comparison wording.

### NOT EXECUTED — frontend package installation/build

- `npm ci`: **EXECUTED, FAILED before dependency installation** because npm requires an existing `package-lock.json`. A direct registry probe (`npm view react@19.1.1`) failed with `EAI_AGAIN`, so a legitimate lockfile could not be generated.
- `npm run lint`: **NOT EXECUTED — frontend dependencies are unavailable locally**.
- `npm test`: **NOT EXECUTED — frontend dependencies are unavailable locally**.
- `npm run build`: **NOT EXECUTED — frontend dependencies are unavailable locally**.
- `package-lock.json`: **NOT GENERATED**. Registry resolution is unavailable (`EAI_AGAIN`); a package-lock generation attempt could not complete, and no fake lockfile was created.

All direct frontend dependency versions in `frontend/package.json` remain exact pins; there are no `latest` ranges.

## Python dependency reproducibility

- `requirements.txt` remains exact-version pinned and was aligned to the actually verified Pydantic runtime version (`2.13.5`).
- `requirements.lock.txt` records the exact installed runtime dependency graph used by the executed backend verification.
- `psycopg`, Ruff and mypy were not installed in this container; their exact repository pins are retained and explicitly marked in the lock file instead of pretending their transitive graphs were resolved.
- `uv pip compile --offline` was attempted but could not resolve uncached packages because registry access is unavailable.

## Docker

- **Docker runtime verification: NOT EXECUTED — Docker CLI/runtime is not installed in this environment.**
- Docker configuration is retained; no Docker-runtime pass is claimed.

## Final freeze-patch checks

- `risk_category` was removed from backend/frontend structured condition fields because baseline case attributes do not supply it. Supported condition fields are `priority`, `value`, `customer_type`, `region`, `department`, and `channel`.
- Process-map layout now uses strongly connected components plus the condensation DAG, preventing cyclic/rework graphs from accumulating unbounded horizontal levels.
- Page navigation clears generic page data immediately and rejects stale async responses; Active Case Risk renders results only when `Array.isArray(data.cases)`.
- Process-map bottleneck highlights use dedicated state loaded with the graph rather than generic current-page data.
- Compose requires `POSTGRES_PASSWORD` from `.env` and constructs `DATABASE_URL` from the same variable; no default database password is committed.
- Frontend UI wording uses **SIMULATED 30-day completion volume — under calibrated historical arrivals** rather than implying maximum throughput/capacity.

## Remaining limitations

- Sequence conformance is heuristic/transparent, not Petri-net token replay.
- Conditional routing is limited to structured predicates and existing observed activities; it is not a general BPMN routing engine.
- Resource service time remains a documented proxy when lifecycle start/complete timestamps are unavailable.
- Parallelization is supported only for observed adjacent activities; domain independence is still a user assumption.
- SIMULATED 30-day completion volume is a calibrated fixed-horizon estimate under historical arrivals, not maximum or guaranteed capacity.
- Frontend production build remains unverified solely because package-registry access is unavailable in this execution environment.

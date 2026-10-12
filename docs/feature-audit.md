# Surgical upgrade audit

| Feature | Existing implementation | Correct? | Weakness found | Upgrade action |
|---|---|---:|---|---|
| CSV/JSON import | Working parser/validation | Mostly | package-root test import issue | Preserved; root test execution fixed |
| Process graph | Direct-follow analytics | Yes | UI rendered JSON; timing name too strong | Preserved algorithm; added case %, resource metadata, strict inter-event terminology and SVG UI |
| Variants | Exact paths | Yes | table-only UI | Preserved; added visual path cards |
| Rework | repeated activities | Mostly | repeat span could be confused with labor overhead | Preserved; terminology tightened |
| Bottlenecks | prevalence + delay score | Mostly | completion delay called wait | Preserved scoring; lifecycle-aware wait/processing or completion-only inter-event delay |
| SLA | process/high-priority | Partial | no activity/segment rule model | Added typed process/activity/segment rules and contribution report |
| Conformance | heuristic sequence comparison | Yes within scope | no frontend | Preserved; added UI configuration |
| Simulation pairing | independent RNG streams | **No** | no-op could show false effect | Replaced with common-random-number paired cohort runs |
| Baseline isolation | removal applied before both branches | **No** | baseline mutated | Immutable baseline + proposed-only transformations |
| Automation | boolean Finance speedup | **No** | not case-conditional | Structured safe predicates on case attributes |
| Correlation/tails | independently sampled activity delays | Weak | destroyed case-level correlation | Complete historical trajectory bootstrap |
| Resource capacity | delay division | **No** | not a queue model | finite-server queue mechanics + utilization/queue diagnostics |
| 30-day completion volume | sampled-cohort completions | **No** | absolute count scaled with `cohort_size` | fixed 720h arrival-calibrated completion simulation with paired arrivals; cohort-size invariance tested; UI explicitly avoids maximum-capacity terminology |
| Parallelization | absent | **No** | planned capability missing | adjacent-independent activity action using max rather than sum |
| Scenario model | loose dictionaries | Weak | invalid scenarios accepted late | discriminated typed Pydantic actions |
| Uncertainty | one result | Weak | no P10/P90 | paired-run P10/median/P90 |
| Baseline fidelity | absent | **No** | no calibration gate | observed vs simulated cycle/SLA/variant/delay report + HIGH/MEDIUM/LOW |
| Business impact | cycle hours × labor rate | **No** | conceptually wrong | lead time, labor effort, SLA, rework and costs separated |
| ML split | prefix-row split | **No** | same case could cross train/test | case IDs split first, time-aware |
| Model persistence | retrain per prediction | **No** | slow and unversioned | persisted classifier/regressor/schema/metrics/version |
| Active-case risk | manual snapshot input | Partial | no true active workflow | cutoff-based active-case extraction + persisted inference API/UI |
| Admin security | known development default key | **No** | known default secret | unset key disables destructive endpoint |
| Frontend dependencies | exact direct pins, no lock | Partial | registry unavailable in patch environment | exact pins preserved; lock/build still explicitly unverified rather than fabricated |

| Condition fields | structured predicates | Mostly | `risk_category` had no baseline attribute backing | removed `risk_category`; retained priority/value/customer_type/region/department/channel |

# Design decisions

## Direct event analytics
**Context:** FlowLens must be explainable in an interview. **Options:** delegate discovery to a process-mining library or implement direct sequence analytics. **Decision:** retain direct grouping, direct-follow, variant, rework, SLA and heuristic conformance algorithms. **Reason:** transparency and small dependency surface. **Tradeoff:** conformance is not formal Petri-net token replay.

## Paired empirical counterfactuals
**Context:** Independent baseline/proposed random draws can report an effect for a no-op scenario. **Options:** independent Monte Carlo, analytical scaling, or common-random-number paired runs. **Decision:** one sampled cohort per run is reused for baseline and proposed. **Reason:** removes sampling noise from intervention deltas and makes no-op exactly zero. **Tradeoff:** uncertainty reflects empirical bootstrap variability rather than a fully specified generative stochastic process.

## Immutable baseline process model
**Context:** Earlier removed-step logic could mutate baseline behavior. **Decision:** create an immutable `BaselineProcessModel`; scenario actions transform copied activity/delay arrays only. **Reason:** scenario isolation. **Tradeoff:** additional transformation code rather than in-place convenience.

## Preserve correlations with complete-trajectory bootstrap
**Context:** Independently sampling each activity delay destroys slow-case correlation and tails. **Decision:** bootstrap complete historical case trajectories, then apply scenario transforms. **Reason:** preserves observed variants, within-case correlation and heavy tails with minimal complexity. **Tradeoff:** novel unseen paths are not generated automatically.

## Resource capacity as queue mechanics
**Context:** Dividing delay by a “resource multiplier” is not capacity simulation. **Decision:** use finite-server queue scheduling to estimate capacity effects. **Reason:** added reviewers change queue delay through contention rather than arbitrary scaling. **Tradeoff:** when lifecycle timestamps are absent, service time must be an explicit proxy and is labeled as such.

## Strict event-time terminology
**Context:** Completion-to-completion delay is not necessarily waiting time. **Decision:** completion-only logs use “observed inter-event delay.” When lifecycle start/complete exists, queue wait and processing duration are derived separately. **Tradeoff:** fewer strong-sounding labels, more defensible semantics.

## Case-safe time-aware ML split
**Context:** Multiple prefixes per case can leak into both train and test when splitting rows. **Decision:** order unique cases by start time, split case IDs 80/20, then generate prefixes within each partition. **Reason:** no case overlap and better deployment realism. **Tradeoff:** fewer independent test cases than random row splitting.

## Internal-only model persistence
**Context:** Retraining on every prediction is inefficient, while loading arbitrary user-uploaded pickle/joblib files is unsafe. **Decision:** version and persist only models created by FlowLens under its own model directory. **Reason:** repeatable inference without an unsafe model-upload surface. **Tradeoff:** this is local filesystem persistence rather than a full registry service.

## Business value separation
**Context:** Lead-time reduction is not labor effort reduction. **Decision:** separate time-to-completion value, explicit automation effort savings, SLA cost avoidance, rework savings and implementation/automation costs. **Reason:** avoid fabricated savings. **Tradeoff:** some estimates remain zero until the user supplies assumptions.

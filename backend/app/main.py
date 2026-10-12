from __future__ import annotations

import json
import os
import time
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from fastapi import Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .core import (
    ValidationError,
    bottlenecks,
    conformance,
    discover,
    load_event_bytes,
    recommendations,
    rework,
    sanitize_filename,
    sla_analysis,
    variants,
)
from .db import Dataset, SessionLocal, init_db
from .impact import BusinessAssumptions, calculate_business_impact
from .ml import active_case_snapshots, load_persisted_models, persist_models, score_active_cases, train_models
from .scenario_models import ScenarioDefinition
from .simulation import simulate_counterfactual
from .sla import SlaRule, evaluate_sla_rules

app = FastAPI(title="FlowLens API", version="2.0.0")
origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "X-Admin-Key"],
)
init_db()
_upload_hits: dict[str, deque[float]] = defaultdict(deque)
_model_cache: dict[int, dict[str, Any]] = {}


def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@app.middleware("http")
async def secure_headers(request: Request, call_next):
    start = time.perf_counter()
    if request.method == "POST" and request.url.path == "/datasets":
        now = time.monotonic()
        ip = request.client.host if request.client else "unknown"
        queue = _upload_hits[ip]
        while queue and now - queue[0] > 60:
            queue.popleft()
        if len(queue) >= 20:
            return JSONResponse(
                status_code=429, content={"error": "rate_limited", "detail": "Upload limit exceeded; retry later."}
            )
        queue.append(now)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Process-Time-ms"] = f"{(time.perf_counter() - start) * 1000:.2f}"
    return response


@app.exception_handler(ValidationError)
async def bad_input(_: Request, error: ValidationError):
    return JSONResponse(status_code=422, content={"error": "validation_error", "detail": str(error)})


def get_ds(dataset_id: int, session: Session) -> Dataset:
    dataset = session.get(Dataset, dataset_id)
    if not dataset:
        raise HTTPException(404, detail="Dataset not found")
    return dataset


def get_model(dataset_id: int) -> dict[str, Any]:
    if dataset_id not in _model_cache:
        try:
            _model_cache[dataset_id] = load_persisted_models(dataset_id)
        except ValidationError as error:
            raise HTTPException(409, detail=str(error)) from error
    return _model_cache[dataset_id]


@app.get("/health")
def health():
    return {"status": "ok", "admin_endpoints_enabled": bool(os.getenv("ADMIN_API_KEY"))}


@app.get("/datasets")
def datasets(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), session: Session = Depends(db)):
    query = session.query(Dataset).order_by(Dataset.id.desc())
    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return {
        "items": [{"id": d.id, "name": d.name, "created_at": d.created_at} for d in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@app.post("/datasets", status_code=201)
async def upload(file: UploadFile = File(...), session: Session = Depends(db)):
    name = sanitize_filename(file.filename or "upload")
    ext = Path(name).suffix.lower()
    mime = (file.content_type or "").lower()
    allowed = {
        ".csv": {"text/csv", "application/csv", "text/plain", "application/octet-stream"},
        ".json": {"application/json", "text/json", "text/plain", "application/octet-stream"},
    }
    if ext not in allowed or mime not in allowed[ext]:
        raise HTTPException(415, detail="File MIME type does not match supported CSV/JSON upload types")
    raw = await file.read(int(os.getenv("MAX_UPLOAD_BYTES", "10485760")) + 1)
    events, quality = load_event_bytes(raw, name)
    serialized = []
    for event in events:
        row = dict(event)
        row["timestamp"] = row["timestamp"].isoformat()
        serialized.append(row)
    dataset = Dataset(name=name, events_json=json.dumps(serialized), quality_json=json.dumps(quality))
    session.add(dataset)
    session.commit()
    session.refresh(dataset)
    return {"id": dataset.id, "name": dataset.name, "quality": quality}


@app.delete("/datasets/{dataset_id}", status_code=204)
def delete_dataset(dataset_id: int, x_admin_key: str | None = Header(None), session: Session = Depends(db)):
    required = os.getenv("ADMIN_API_KEY")
    if not required:
        raise HTTPException(503, detail="Administrative endpoints are disabled because ADMIN_API_KEY is not configured")
    if x_admin_key != required:
        raise HTTPException(401, detail="Admin key required")
    dataset = get_ds(dataset_id, session)
    session.delete(dataset)
    session.commit()
    _model_cache.pop(dataset_id, None)


@app.get("/processes/{dataset_id}/graph")
def graph(dataset_id: int, session: Session = Depends(db)):
    return discover(get_ds(dataset_id, session).events())


@app.get("/processes/{dataset_id}/variants")
def get_variants(dataset_id: int, sla_hours: float = Query(48, gt=0), session: Session = Depends(db)):
    return variants(get_ds(dataset_id, session).events(), sla_hours)


@app.get("/processes/{dataset_id}/bottlenecks")
def get_bottlenecks(dataset_id: int, session: Session = Depends(db)):
    return bottlenecks(get_ds(dataset_id, session).events())


@app.get("/processes/{dataset_id}/rework")
def get_rework(dataset_id: int, session: Session = Depends(db)):
    return rework(get_ds(dataset_id, session).events())


@app.get("/processes/{dataset_id}/sla")
def get_sla(
    dataset_id: int,
    process_hours: float = Query(48, gt=0),
    high_priority_hours: float = Query(24, gt=0),
    session: Session = Depends(db),
):
    return sla_analysis(get_ds(dataset_id, session).events(), process_hours, high_priority_hours)


class SlaRulesIn(BaseModel):
    rules: list[SlaRule] = Field(min_length=1, max_length=50)


@app.post("/processes/{dataset_id}/sla/rules")
def configured_sla(dataset_id: int, body: SlaRulesIn, session: Session = Depends(db)):
    return evaluate_sla_rules(get_ds(dataset_id, session).events(), body.rules)


@app.get("/processes/{dataset_id}/quality")
def quality(dataset_id: int, session: Session = Depends(db)):
    return get_ds(dataset_id, session).quality()


@app.get("/processes/{dataset_id}/overview")
def overview(dataset_id: int, sla_hours: float = Query(48, gt=0), session: Session = Depends(db)):
    events = get_ds(dataset_id, session).events()
    graph_data = discover(events)
    vars_data = variants(events, sla_hours)
    bottle = bottlenecks(events)
    rw = rework(events)
    sla = sla_analysis(events, sla_hours)
    durations = []
    grouped: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        grouped[event["case_id"]].append(event)
    for evs in grouped.values():
        evs.sort(key=lambda x: x["timestamp"])
        durations.append(
            max(0.0, (evs[-1]["timestamp"] - evs[0]["timestamp"]).total_seconds() / 3600) if len(evs) > 1 else 0.0
        )
    return {
        "case_count": graph_data["case_count"],
        "event_count": graph_data["event_count"],
        "activity_count": len(graph_data["activities"]),
        "variant_count": len(vars_data),
        "median_cycle_hours": round(float(np.median(durations)), 3) if durations else 0,
        "p95_cycle_hours": round(float(np.percentile(durations, 95)), 3) if durations else 0,
        "sla_compliance": sla["compliance_rate"],
        "rework_rate": rw["rework_rate"],
        "top_bottleneck": bottle[0] if bottle else None,
    }


class Reference(BaseModel):
    expected: list[str] = Field(min_length=2)
    max_loops: int = Field(1, ge=1, le=20)


@app.post("/processes/{dataset_id}/conformance")
def conf(dataset_id: int, body: Reference, session: Session = Depends(db)):
    return conformance(get_ds(dataset_id, session).events(), body.expected, body.max_loops)


@app.post("/processes/{dataset_id}/simulation")
def simulation(dataset_id: int, body: ScenarioDefinition, session: Session = Depends(db)):
    try:
        return simulate_counterfactual(get_ds(dataset_id, session).events(), body)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


class CompareIn(BaseModel):
    scenarios: list[ScenarioDefinition] = Field(min_length=1, max_length=6)


@app.post("/processes/{dataset_id}/simulation/compare")
def compare_scenarios(dataset_id: int, body: CompareIn, session: Session = Depends(db)):
    events = get_ds(dataset_id, session).events()
    try:
        results = [simulate_counterfactual(events, scenario) for scenario in body.scenarios]
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {
        "results": results,
        "comparison_basis": "Each scenario uses its own paired baseline/proposed common-random-number runs; use a shared seed for directly comparable Monte Carlo draws.",
    }


@app.get("/processes/{dataset_id}/recommendations")
def recs(dataset_id: int, session: Session = Depends(db)):
    return recommendations(get_ds(dataset_id, session).events())


class RecommendationRequest(BaseModel):
    assumptions: BusinessAssumptions | None = None
    cycle_weight: float = Field(default=1.0, ge=0, le=100)
    sla_weight: float = Field(default=0.5, ge=0, le=100)
    business_weight: float = Field(default=0.0, ge=0, le=100)


@app.post("/processes/{dataset_id}/recommendations/evaluate")
def recs_evaluated(dataset_id: int, body: RecommendationRequest, session: Session = Depends(db)):
    return recommendations(
        get_ds(dataset_id, session).events(), body.assumptions, body.cycle_weight, body.sla_weight, body.business_weight
    )


@app.post("/models/{dataset_id}/train")
def train(dataset_id: int, sla_hours: float = Query(48, gt=0), session: Session = Depends(db)):
    trained = train_models(get_ds(dataset_id, session).events(), sla_hours)
    metadata = persist_models(dataset_id, trained)
    _model_cache[dataset_id] = load_persisted_models(dataset_id, version=metadata["version"])
    return metadata


class PredictionIn(BaseModel):
    elapsed_hours: float = Field(ge=0)
    current_activity: str = Field(min_length=1, max_length=200)
    prior_count: int = Field(ge=0, le=10000)
    rework_count: int = Field(ge=0, le=10000)
    priority: str = "unknown"
    department: str = "unknown"


@app.post("/predictions/{dataset_id}")
def prediction(dataset_id: int, body: PredictionIn):
    from .ml import predict_snapshot

    persisted = get_model(dataset_id)
    result = predict_snapshot(persisted, body.model_dump())
    result["model_version"] = persisted["metadata"]["version"]
    return result


@app.get("/models/{dataset_id}/active-cases")
def active_cases(dataset_id: int, cutoff: datetime | None = Query(None), session: Session = Depends(db)):
    events = get_ds(dataset_id, session).events()
    persisted = get_model(dataset_id)
    if cutoff is None:
        timestamps = sorted(e["timestamp"] for e in events)
        cutoff = timestamps[int(0.75 * (len(timestamps) - 1))]
    rows = score_active_cases(events, cutoff, persisted)
    return {
        "cutoff": cutoff.isoformat(),
        "active_case_count": len(rows),
        "cases": rows,
        "definition": "Historical snapshot: cases started by cutoff but not completed by cutoff; features use only events at or before cutoff.",
    }


@app.get("/processes/{dataset_id}/active-snapshot")
def active_snapshot(dataset_id: int, cutoff: datetime, session: Session = Depends(db)):
    rows = active_case_snapshots(get_ds(dataset_id, session).events(), cutoff)
    return {"cutoff": cutoff.isoformat(), "cases": rows}


class ImpactIn(BaseModel):
    simulation: dict[str, Any]
    assumptions: BusinessAssumptions


@app.post("/impact")
def impact(body: ImpactIn):
    return calculate_business_impact(body.simulation, body.assumptions)

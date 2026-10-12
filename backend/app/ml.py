from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import (
    average_precision_score,
    f1_score,
    mean_absolute_error,
    median_absolute_error,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from .core import ValidationError

NUMERIC_FEATURES = ["elapsed_hours", "prior_count", "rework_count"]
CATEGORICAL_FEATURES = ["current_activity", "priority", "department"]
FEATURES = NUMERIC_FEATURES + CATEGORICAL_FEATURES
MODEL_ROOT = Path("models")


def _group(events: list[dict]) -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        by[event["case_id"]].append(event)
    for evs in by.values():
        evs.sort(key=lambda e: e["timestamp"])
    return dict(by)


def _duration(evs: list[dict]) -> float:
    return max(0.0, (evs[-1]["timestamp"] - evs[0]["timestamp"]).total_seconds() / 3600) if len(evs) > 1 else 0.0


def split_case_ids(events: list[dict], train_fraction: float = 0.8) -> tuple[list[str], list[str]]:
    cases = _group(events)
    ordered = sorted(cases, key=lambda cid: (cases[cid][0]["timestamp"], cid))
    if len(ordered) < 2:
        raise ValidationError("At least two cases are required for a train/test split")
    split = min(len(ordered) - 1, max(1, int(len(ordered) * train_fraction)))
    return ordered[:split], ordered[split:]


def prefix_rows_for_cases(events: list[dict], case_ids: set[str], sla_hours: float) -> list[dict[str, Any]]:
    cases = _group(events)
    rows: list[dict[str, Any]] = []
    for cid in sorted(case_ids):
        evs = cases.get(cid, [])
        if len(evs) < 2:
            continue
        total = _duration(evs)
        target = int(total > sla_hours)
        # Multiple prefixes remain in the same split because the split happens by case_id first.
        cuts = sorted(set([max(1, len(evs) // 3), max(1, (2 * len(evs)) // 3), len(evs) - 1]))
        for cut in cuts:
            prefix = evs[:cut]
            elapsed = (
                (prefix[-1]["timestamp"] - prefix[0]["timestamp"]).total_seconds() / 3600 if len(prefix) > 1 else 0.0
            )
            rows.append(
                {
                    "case_id": cid,
                    "case_start": evs[0]["timestamp"],
                    "feature_timestamp": prefix[-1]["timestamp"],
                    "elapsed_hours": elapsed,
                    "current_activity": prefix[-1]["activity"],
                    "prior_count": len(prefix) - 1,
                    "rework_count": sum(n - 1 for n in Counter(e["activity"] for e in prefix).values() if n > 1),
                    "priority": prefix[0].get("priority") or "unknown",
                    "department": prefix[-1].get("department") or "unknown",
                    "target": target,
                    "remaining": max(0.0, total - elapsed),
                }
            )
    return rows


def _frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{k: row[k] for k in FEATURES} for row in rows])


def train_models(events: list[dict], sla_hours: float = 48) -> dict[str, Any]:
    train_ids, test_ids = split_case_ids(events)
    train = prefix_rows_for_cases(events, set(train_ids), sla_hours)
    test = prefix_rows_for_cases(events, set(test_ids), sla_hours)
    if len(train) < 10 or len(test) < 2:
        raise ValidationError("Not enough case-prefix samples after the case-safe split")
    Xtr, Xte = _frame(train), _frame(test)
    ytr = np.array([r["target"] for r in train])
    yte = np.array([r["target"] for r in test])
    pre = ColumnTransformer(
        [
            ("n", "passthrough", NUMERIC_FEATURES),
            ("c", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
        ]
    )
    clf = Pipeline(
        [
            ("pre", pre),
            (
                "model",
                RandomForestClassifier(
                    n_estimators=120, max_depth=7, min_samples_leaf=2, random_state=42, class_weight="balanced"
                ),
            ),
        ]
    )
    clf.fit(Xtr, ytr)
    pred = clf.predict(Xte)
    if len(set(ytr)) > 1:
        prob = clf.predict_proba(Xte)[:, list(clf.named_steps["model"].classes_).index(1)]
    else:
        prob = np.repeat(float(ytr[0]), len(yte))
    classification = {
        "precision": round(precision_score(yte, pred, zero_division=0), 4),
        "recall": round(recall_score(yte, pred, zero_division=0), 4),
        "f1": round(f1_score(yte, pred, zero_division=0), 4),
        "roc_auc": round(roc_auc_score(yte, prob), 4) if len(set(yte)) > 1 else None,
        "pr_auc": round(average_precision_score(yte, prob), 4) if len(set(yte)) > 1 else None,
    }
    reg = Pipeline(
        [
            ("pre", pre),
            ("model", RandomForestRegressor(n_estimators=120, max_depth=8, random_state=42)),
        ]
    )
    reg.fit(Xtr, np.array([r["remaining"] for r in train]))
    rp = reg.predict(Xte)
    ry = np.array([r["remaining"] for r in test])
    regression = {
        "mae_hours": round(mean_absolute_error(ry, rp), 3),
        "median_absolute_error_hours": round(median_absolute_error(ry, rp), 3),
        "rmse_hours": round(float(np.sqrt(np.mean((ry - rp) ** 2))), 3),
    }
    cutoff = max(_group(events)[cid][0]["timestamp"] for cid in train_ids)
    return {
        "classifier": clf,
        "regressor": reg,
        "metrics": classification,
        "remaining_metrics": regression,
        "split": {
            "method": "time-aware 80/20 split by unique case start; prefixes generated after case assignment",
            "train_cases": len(train_ids),
            "test_cases": len(test_ids),
            "train_samples": len(train),
            "test_samples": len(test),
            "train_case_ids": train_ids,
            "test_case_ids": test_ids,
            "training_cutoff": cutoff.isoformat(),
        },
        "feature_schema": {"numeric": NUMERIC_FEATURES, "categorical": CATEGORICAL_FEATURES},
        "feature_note": "Only information available at the prefix timestamp is used; no final duration or future activity is a model feature.",
    }


def _version(dataset_id: int, trained: dict[str, Any]) -> str:
    payload = json.dumps(
        {
            "dataset_id": dataset_id,
            "cutoff": trained["split"]["training_cutoff"],
            "features": trained["feature_schema"],
        },
        sort_keys=True,
    )
    return (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + hashlib.sha256(payload.encode()).hexdigest()[:8]
    )


def persist_models(dataset_id: int, trained: dict[str, Any], root: Path = MODEL_ROOT) -> dict[str, Any]:
    version = _version(dataset_id, trained)
    target = root / f"dataset-{dataset_id}" / version
    target.mkdir(parents=True, exist_ok=True)
    joblib.dump(trained["classifier"], target / "classifier.joblib")
    joblib.dump(trained["regressor"], target / "regressor.joblib")
    metadata = {
        "dataset_id": dataset_id,
        "version": version,
        "training_timestamp": datetime.now(timezone.utc).isoformat(),
        "feature_schema": trained["feature_schema"],
        "metrics": trained["metrics"],
        "remaining_metrics": trained["remaining_metrics"],
        "split": trained["split"],
    }
    (target / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    latest = root / f"dataset-{dataset_id}" / "LATEST"
    latest.write_text(version, encoding="utf-8")
    return metadata


def load_persisted_models(dataset_id: int, root: Path = MODEL_ROOT, version: str | None = None) -> dict[str, Any]:
    base = root / f"dataset-{dataset_id}"
    if version is None:
        latest = base / "LATEST"
        if not latest.exists():
            raise ValidationError("No persisted model exists for this dataset; train a model first")
        version = latest.read_text(encoding="utf-8").strip()
    target = base / version
    # Only paths created internally by persist_models are loaded; user-supplied model files are never accepted.
    metadata_path = target / "metadata.json"
    if not metadata_path.exists():
        raise ValidationError("Persisted model metadata is missing")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    return {
        "classifier": joblib.load(target / "classifier.joblib"),
        "regressor": joblib.load(target / "regressor.joblib"),
        "metadata": metadata,
    }


def predict_snapshot(trained: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    row = {k: snapshot.get(k) for k in FEATURES}
    row["elapsed_hours"] = float(row.get("elapsed_hours") or 0)
    row["prior_count"] = int(row.get("prior_count") or 0)
    row["rework_count"] = int(row.get("rework_count") or 0)
    for key in CATEGORICAL_FEATURES:
        row[key] = str(row.get(key) or "unknown")
    frame = pd.DataFrame([row])
    clf, reg = trained["classifier"], trained["regressor"]
    probs = clf.predict_proba(frame)
    classes = list(clf.named_steps["model"].classes_)
    risk = float(probs[0][classes.index(1)]) if 1 in classes else 0.0
    remaining = max(0.0, float(reg.predict(frame)[0]))
    return {
        "breach_probability": round(risk, 4),
        "expected_remaining_hours": round(remaining, 3),
        "sla_breach_probability": round(risk, 4),
        "predicted_remaining_hours": round(remaining, 3),
        "risk_level": "HIGH" if risk >= 0.7 else "MEDIUM" if risk >= 0.35 else "LOW",
    }


def active_case_snapshots(events: list[dict], cutoff: datetime) -> list[dict[str, Any]]:
    cases = _group(events)
    rows = []
    for cid, evs in cases.items():
        if not (evs[0]["timestamp"] <= cutoff < evs[-1]["timestamp"]):
            continue
        known = [e for e in evs if e["timestamp"] <= cutoff]
        if not known:
            continue
        elapsed = max(0.0, (cutoff - known[0]["timestamp"]).total_seconds() / 3600)
        rows.append(
            {
                "case_id": cid,
                "current_activity": known[-1]["activity"],
                "elapsed_hours": round(elapsed, 4),
                "activities_completed": len(known),
                "prior_count": max(0, len(known) - 1),
                "rework_count": sum(n - 1 for n in Counter(e["activity"] for e in known).values() if n > 1),
                "priority": known[0].get("priority") or "unknown",
                "department": known[-1].get("department") or "unknown",
                "feature_timestamp": cutoff.isoformat(),
                "known_event_count": len(known),
            }
        )
    return rows


def score_active_cases(events: list[dict], cutoff: datetime, persisted: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = persisted["metadata"]
    results = []
    for snapshot in active_case_snapshots(events, cutoff):
        prediction = predict_snapshot(persisted, snapshot)
        completion = cutoff.timestamp() + prediction["expected_remaining_hours"] * 3600
        row = dict(snapshot)
        row.update(prediction)
        row["predicted_completion_time"] = datetime.fromtimestamp(completion, tz=timezone.utc).isoformat()
        row["model_version"] = metadata["version"]
        results.append(row)
    return sorted(results, key=lambda x: -x["breach_probability"])

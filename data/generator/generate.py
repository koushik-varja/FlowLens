from __future__ import annotations
import argparse
import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path


def generate(n: int, seed: int = 42):
    r = random.Random(seed)
    rows = []
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for i in range(n):
        cid = f"SYN-{i + 1:06d}"
        t = base + timedelta(minutes=r.randint(0, 120000))
        p_priority = r.random()
        priority = "high" if p_priority < 0.16 else "low" if p_priority < 0.52 else "normal"
        path = ["Request", "Manager Approval"]
        if r.random() < 0.11:
            path += ["Rejection", "Rework", "Manager Approval"]
        path += ["Finance Review"]
        if r.random() < 0.17:
            path += ["Rework", "Finance Review"]
        path += ["Purchase Order", "Invoice"]
        if r.random() < 0.12:
            path += ["Invoice Correction", "Invoice"]
        path += ["Payment"]
        congestion = r.uniform(1.4, 2.8) if r.random() < 0.22 else 1.0
        for j, a in enumerate(path):
            baseh = {
                "Request": 0,
                "Manager Approval": r.uniform(1, 14),
                "Rejection": r.uniform(0.2, 2),
                "Rework": r.uniform(2, 12),
                "Finance Review": r.uniform(3, 18),
                "Purchase Order": r.uniform(1, 8),
                "Invoice": r.uniform(2, 10),
                "Invoice Correction": r.uniform(1, 6),
                "Payment": r.uniform(2, 12),
            }[a]
            if j:
                t += timedelta(hours=baseh * congestion * (0.7 if priority == "high" else 1))
            dept = {
                "Request": "Operations",
                "Manager Approval": "Management",
                "Rejection": "Management",
                "Rework": "Operations",
                "Finance Review": "Finance",
                "Purchase Order": "Procurement",
                "Invoice": "Finance",
                "Invoice Correction": "Finance",
                "Payment": "Treasury",
            }[a]
            rows.append(
                {
                    "case_id": cid,
                    "activity": a,
                    "timestamp": t.isoformat(),
                    "resource": f"{dept[:3].upper()}-{r.randint(1, 6)}",
                    "department": dept,
                    "cost": round(r.uniform(4, 20), 2),
                    "status": "complete",
                    "channel": r.choice(["portal", "email", "api"]),
                    "customer_type": r.choice(["internal", "vendor"]),
                    "priority": priority,
                    "region": r.choice(["South", "West", "North"]),
                    "value": round(r.uniform(500, 50000), 2),
                }
            )
    return rows


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--cases", type=int, default=500)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--output", default="data/sample/synthetic_procurement.csv")
    a = p.parse_args()
    rows = generate(a.cases, a.seed)
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} synthetic events from {a.cases} cases to {out}")


if __name__ == "__main__":
    main()

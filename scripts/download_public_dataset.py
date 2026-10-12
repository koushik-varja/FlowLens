"""Download a public CSV/JSON event log without redistributing it in this repository.
Usage: python scripts/download_public_dataset.py URL --output data/public/events.csv
The user is responsible for checking the dataset's license/terms before downloading.
"""

from __future__ import annotations
import argparse
import urllib.parse
import urllib.request
from pathlib import Path
from backend.app.core import load_event_bytes


def main():
    p = argparse.ArgumentParser()
    p.add_argument("url")
    p.add_argument("--output", required=True)
    p.add_argument("--max-bytes", type=int, default=10_000_000)
    a = p.parse_args()
    u = urllib.parse.urlparse(a.url)
    if u.scheme != "https":
        raise SystemExit("Only HTTPS URLs are accepted")
    out = Path(a.output)
    if out.suffix.lower() not in {".csv", ".json"}:
        raise SystemExit("Output must end in .csv or .json")
    req = urllib.request.Request(a.url, headers={"User-Agent": "FlowLens/1.0 public-dataset-importer"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read(a.max_bytes + 1)
    if len(data) > a.max_bytes:
        raise SystemExit("Download exceeds configured limit")
    _, q = load_event_bytes(data, out.name)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    print(f"Downloaded and validated {q['valid_rows']} events to {out}. Verify source license/attribution separately.")


if __name__ == "__main__":
    main()

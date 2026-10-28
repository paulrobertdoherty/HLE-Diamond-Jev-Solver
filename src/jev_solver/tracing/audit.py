from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .store import atomic_json


def audit(run: Path, flags: Path | None = None) -> dict:
    manifest = json.loads((run / "manifest.json").read_text())
    db = sqlite3.connect(f"file:{(run / 'events.sqlite3').resolve()}?mode=ro", uri=True)
    try:
        events = [
            (kind, json.loads(data)) for kind, data in db.execute("SELECT kind,data FROM events")
        ]
        rows = [value for kind, value in events if kind == "tool"]
        exposures = json.loads(flags.read_text()) if flags else []
        if not isinstance(exposures, list) or any(
            not isinstance(x, str) or x not in manifest["declared_ids"] for x in exposures
        ):
            raise ValueError("exposure flags must be a private JSON list of declared IDs")
        prior = run / "contamination.json"
        if prior.exists():
            exposures = sorted(set(exposures) | set(json.loads(prior.read_text())["exposed_ids"]))
        result = {
            "run_hash": manifest["run_hash"],
            "attempted_calls": len(rows),
            "blocked_calls": sum(r["outcome"] == "blocked" for r in rows),
            "replayed_calls": sum(r["replayed"] for r in rows),
            "exposed_ids": sorted(set(exposures)),
            "exposed_count": len(set(exposures)),
            "rerun_count": 0,
            "rerun_policy": "Fresh run with repaired pinned filter; retain original all-item outcomes",
        }
        atomic_json(run / "contamination.json", result)
        return {k: v for k, v in result.items() if k != "exposed_ids"}
    finally:
        db.close()

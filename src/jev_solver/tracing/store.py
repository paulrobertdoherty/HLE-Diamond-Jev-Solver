"""Private SQLite events, reservations, per-item caches and durable finalization."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ..models import canonical


def private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def atomic_json(path: Path, value: Any) -> None:
    private_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(value, f, sort_keys=True, indent=2, allow_nan=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class Store:
    def __init__(self, path: Path):
        private_dir(path.parent)
        self.db = sqlite3.connect(path, isolation_level=None)
        path.chmod(0o600)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS items (id TEXT PRIMARY KEY, state TEXT, prediction TEXT);
        CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY, item TEXT, kind TEXT, data TEXT);
        CREATE TABLE IF NOT EXISTS cache (item TEXT, key TEXT, value TEXT, PRIMARY KEY(item,key));
        CREATE TABLE IF NOT EXISTS calls (
          id INTEGER PRIMARY KEY, item TEXT, kind TEXT, reserved REAL, billed REAL,
          usage TEXT, state TEXT NOT NULL);
        """)

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        else:
            self.db.execute("COMMIT")

    def meta(self, key: str, value: Any = None) -> Any:
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        if value is None:
            return json.loads(row[0]) if row else None
        if row and canonical(json.loads(row[0])) != canonical(value):
            raise ValueError(f"resume manifest differs: {key}")
        self.db.execute("INSERT OR IGNORE INTO meta VALUES (?,?)", (key, canonical(value)))
        return value

    def event(self, item: str, kind: str, value: Any) -> None:
        self.db.execute(
            "INSERT INTO events(item,kind,data) VALUES (?,?,?)", (item, kind, canonical(value))
        )

    def cached(self, item: str, key: str) -> Any:
        row = self.db.execute(
            "SELECT value FROM cache WHERE item=? AND key=?", (item, key)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def cache(self, item: str, key: str, value: Any) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO cache VALUES (?,?,?)", (item, key, canonical(value))
        )

    def checkpoint(self, item: str, state: dict) -> None:
        self.db.execute(
            "INSERT INTO items(id,state) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state",
            (item, canonical(state)),
        )

    def prediction(self, item: str) -> dict | None:
        row = self.db.execute("SELECT prediction FROM items WHERE id=?", (item,)).fetchone()
        return json.loads(row[0]) if row and row[0] else None

    def finalize(self, item: str, prediction: dict) -> None:
        with self.transaction():
            if self.prediction(item):
                return
            self.db.execute(
                "INSERT INTO items(id,prediction) VALUES (?,?) ON CONFLICT(id) DO UPDATE SET prediction=excluded.prediction",
                (item, canonical(prediction)),
            )
            self.event(item, "finalized", {"status": prediction["status"]})

    def predictions(self) -> list[dict]:
        return [
            json.loads(r[0])
            for r in self.db.execute(
                "SELECT prediction FROM items WHERE prediction IS NOT NULL ORDER BY id"
            )
        ]

    def cost(self, item: str | None = None) -> float:
        clause, args = (" WHERE item=?", (item,)) if item else ("", ())
        return self.db.execute(
            "SELECT COALESCE(SUM(COALESCE(billed,reserved)),0) FROM calls" + clause, args
        ).fetchone()[0]

    def usage_summary(self) -> dict:
        rows = self.db.execute("SELECT kind,reserved,billed,usage FROM calls").fetchall()
        counts = {}
        totals = {"input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0}
        uncertain = 0.0
        for kind, reserved, billed, raw in rows:
            counts[kind] = counts.get(kind, 0) + 1
            usage = json.loads(raw) if raw else {}
            totals["input_tokens"] += usage.get("input_tokens", 0) or 0
            totals["output_tokens"] += usage.get("output_tokens", 0) or 0
            totals["reasoning_tokens"] += (usage.get("output_tokens_details") or {}).get(
                "reasoning_tokens", 0
            ) or 0
            if billed is None:
                uncertain += reserved
        event_counts = dict(self.db.execute("SELECT kind,COUNT(*) FROM events GROUP BY kind"))
        return {
            **totals,
            "attempts_by_kind": counts,
            "uncertain_cost_upper_usd": uncertain,
            "accounted_cost_usd": self.cost(),
            "jev_outages": event_counts.get("jev_outage", 0),
            "retries_or_errors": event_counts.get("call_error", 0),
            "model_replays": event_counts.get("model_replay", 0),
            "jev_replays": event_counts.get("jev_replay", 0),
            "cost_basis": "reported usage times frozen rates; uncertain attempts retain full reservation",
        }

    def close(self) -> None:
        self.db.close()

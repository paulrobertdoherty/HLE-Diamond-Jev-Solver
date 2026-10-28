"""Preparation is the only dataset-facing operation; solving reads allowlisted views."""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
import random
import re
from collections import defaultdict
from pathlib import Path

from ..models import QuestionView, canonical, digest, record
from ..tracing.store import atomic_json, private_dir


def read_jsonl(path: Path) -> list[dict]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    private_dir(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        for row in rows:
            f.write(canonical(row) + "\n")
        f.flush()
        os.fsync(f.fileno())


def load_questions(path: Path) -> list[QuestionView]:
    questions = [QuestionView.parse(row) for row in read_jsonl(path)]
    ids = [q.id for q in questions]
    if not questions or len(set(ids)) != len(ids):
        raise ValueError("empty dataset or duplicate original identifiers")
    return questions


def image_url(image) -> str:
    if isinstance(image, str):
        if image.startswith(("data:image/", "https://")):
            return image
        raise ValueError("unexpected image path; original image bytes or URL required")
    if isinstance(image, dict):
        data = image.get("bytes")
        if not data:
            raise ValueError("image bytes missing; do not silently discard images")
        mime = mimetypes.guess_type(image.get("path", ""))[0]
        if not mime:
            mime = "image/png" if data.startswith(b"\x89PNG") else "image/jpeg"
        return f"data:{mime};base64," + base64.b64encode(data).decode()
    raise ValueError("unsupported image encoding; prepare with datasets.Image(decode=False)")


def prepare(
    output: Path,
    revision: str,
    fixture: Path | None = None,
    dev_count: int = 0,
    seed: int = 17,
    text_only: bool = False,
    development: bool = False,
) -> dict:
    if output.exists() and any(output.iterdir()):
        raise ValueError("preparation output must be new or empty")
    dataset_name = (
        ("independent/development" if development else "synthetic")
        if fixture
        else "cais/hle-diamond"
    )
    if development and fixture is None:
        raise ValueError("independent development requires a checked local task file")
    if fixture:
        rows = read_jsonl(fixture)
        schema = {k: type(v).__name__ for k, v in rows[0].items()}
        revision = source_hash(fixture)[:40] if development else "synthetic-v1"
    else:
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise ValueError("pin dataset revision to a 40-character commit")
        if not os.environ.get("HF_TOKEN"):
            raise ValueError("HF_TOKEN is required; accept the dataset conditions first")
        from datasets import Image, load_dataset

        dataset = load_dataset(
            dataset_name, revision=revision, split="test", token=os.environ["HF_TOKEN"]
        )
        if "image" in dataset.column_names and isinstance(dataset.features["image"], Image):
            dataset = dataset.cast_column("image", Image(decode=False))
        schema = dataset.features.to_dict()
        rows = list(dataset)
        if len(rows) != 1000:
            raise ValueError(
                "unexpected Diamond size; inspect schema and update adapter explicitly"
            )
    private_dir(output)
    groups = defaultdict(list)
    solver, labels = [], []
    for row in rows:
        qid = row.get("id")
        if not isinstance(qid, str):
            raise ValueError("preserve original string identifiers")
        raw_images = row.get("images") or ([row["image"]] if row.get("image") else [])
        images = [image_url(i) for i in raw_images]
        if text_only and images:
            continue
        q = QuestionView.parse({"id": qid, "question": row["question"], "images": images})
        solver.append(record(q))
        if not isinstance(row.get("answer"), str):
            raise ValueError("reference answer must be a string")
        slices = {
            k: str(row[k])
            for k in ("partition", "subject", "category", "answer_type")
            if row.get(k) is not None
        }
        slices["modality"] = "image" if images else "text"
        labels.append(
            {"id": qid, "question": q.question, "answer": row["answer"], "slices": slices}
        )
        groups[slices.get("partition", "unspecified")].append(qid)
    ids = [q["id"] for q in solver]
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("empty scope or duplicate question identifiers")
    if not 0 <= dev_count < len(ids):
        raise ValueError("dev count must leave a nonempty held-out set")
    # Largest remainder allocation keeps the preregistered split stratified.
    allocation = {k: int(dev_count * len(v) / len(ids)) for k, v in groups.items()}
    order = sorted(
        groups, key=lambda k: (-(dev_count * len(groups[k]) / len(ids) - allocation[k]), k)
    )
    for k in order[: dev_count - sum(allocation.values())]:
        allocation[k] += 1
    rng = random.Random(seed)
    dev = []
    for key in sorted(groups):
        choices = sorted(groups[key])
        rng.shuffle(choices)
        dev.extend(choices[: allocation[key]])
    membership = {"development": sorted(dev), "heldout": sorted(set(ids) - set(dev))}
    write_jsonl(output / "solver/questions.jsonl", solver)
    write_jsonl(output / "evaluator/labels.jsonl", labels)
    atomic_json(output / "solver/split.json", membership)
    manifest = {
        "dataset": dataset_name,
        "revision": revision,
        "split": "test",
        "count": len(ids),
        "scope": "text-only subset"
        if text_only
        else ("internal stratified split" if dev_count else "full declared set"),
        "schema_hash": digest(schema),
        "schema": schema,
        "solver_hash": digest(solver),
        "labels_hash": digest(labels),
        "split_hash": digest(membership),
        "seed": seed,
        "development_count": dev_count,
        "image_count": sum(bool(q["images"]) for q in solver),
    }
    atomic_json(output / "manifest.json", manifest)
    atomic_json(
        output / "solver/manifest.json",
        {k: v for k, v in manifest.items() if k not in {"labels_hash", "schema", "schema_hash"}},
    )
    return manifest


def source_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

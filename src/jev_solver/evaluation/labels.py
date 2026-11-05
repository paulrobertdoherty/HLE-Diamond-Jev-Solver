"""Private, independently labeled cases. Observations never become automatic gold labels."""

from __future__ import annotations

import json
import hashlib
import sqlite3
from pathlib import Path

from ..benchmarks.data import read_jsonl
from ..models import digest
from ..tracing.store import atomic_json, private_dir

LABEL_STATUSES = {"unresolved", "adjudicated"}


def case_record(
    identifier, component, inputs, observation, *, task_id, test_id, claims=(), passages=()
):
    return {
        "version": 1,
        "id": identifier,
        "test_id": test_id,
        "task_id": task_id,
        "component": component,
        "split": "development",
        "input": inputs,
        "input_hash": digest(inputs),
        "identities": {"claims": list(claims), "passages": list(passages)},
        "observation": observation,
        "observation_hash": digest(observation),
        "label": {"status": "unresolved", "provenance": {}, "values": {}},
    }


def validate_case(row):
    if (
        row.get("version") != 1
        or row.get("split") != "development"
        or row.get("component") not in {"audit", "J2", "J3", "search", "reference"}
        or any(not isinstance(row.get(k), str) or not row[k] for k in ("id", "test_id", "task_id"))
        or not isinstance(row.get("input"), dict)
        or row.get("input_hash") != digest(row["input"])
        or row.get("observation_hash") != digest(row.get("observation"))
    ):
        raise ValueError("invalid labeled case identity or input hash")
    identities = row.get("identities", {})
    for key in ("claims", "passages"):
        ids = identities.get(key)
        if (
            not isinstance(ids, list)
            or any(not isinstance(i, str) or not i for i in ids)
            or len(set(ids)) != len(ids)
        ):
            raise ValueError("invalid stable claim/passage IDs")
    label = row.get("label", {})
    if label.get("status") not in LABEL_STATUSES or not isinstance(label.get("values"), dict):
        raise ValueError("invalid label status")
    provenance = label.get("provenance", {})
    if label["status"] == "adjudicated" and any(
        not isinstance(provenance.get(k), str) or not provenance[k].strip()
        for k in ("reviewer", "method", "timestamp")
    ):
        raise ValueError("adjudicated labels require independent provenance")
    return row


def load_cases(path):
    rows = [validate_case(row) for row in read_jsonl(path)]
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("duplicate labeled case ID")
    return rows


def provider_input(row):
    """Only frozen input crosses a provider boundary; labels/references stay private."""
    validate_case(row)
    if row["component"] == "reference":
        raise ValueError("reference cases belong only to the isolated grader")
    return json.loads(json.dumps(row["input"]))


def component_rows(rows):
    result = []
    for row in rows:
        validate_case(row)
        if row["component"] not in {"J2", "J3"} or row["label"]["status"] != "adjudicated":
            continue
        values = row["label"]["values"]
        if "expected" not in values:
            continue
        observation = row.get("observation", {})
        observed = observation.get("judgment") or {}
        if row["component"] == "J3":
            observed = observation.get("response", {}).get("answers", {}).get("support", {})
            observed = {"value": observed.get("choice"), "confidence": observed.get("confidence")}
        result.append(
            {
                "id": row["id"],
                "stage": row["component"],
                "task_id": row["task_id"],
                "state": provider_input(row),
                "expected": values["expected"],
                "observed": observed,
                **(
                    {"passage_id": row["identities"]["passages"][0]}
                    if row["component"] == "J2" and row["identities"]["passages"]
                    else {}
                ),
                "not_run": observation.get("judgment_executed") is False,
                "round": observation.get("round"),
                **{
                    k: values[k]
                    for k in ("answer_bearing", "useful", "contradictory")
                    if k in values
                },
            }
        )
    return result


def workflow_rows(rows):
    """Convert adjudicated saved observations without exposing labels to providers."""
    from ..judgments.verification import parse_audit

    result = []
    for row in rows:
        validate_case(row)
        if (
            row["component"] not in {"audit", "reference"}
            or row["label"]["status"] != "adjudicated"
        ):
            continue
        values, observation = row["label"]["values"], row["observation"]
        if row["component"] == "audit":
            try:
                audited = parse_audit(json.loads(json.dumps(observation.get("response"))))
                dependencies = audited["dependencies"]
            except (ValueError, TypeError, KeyError):
                dependencies = []
            if "gold_dependencies" in values:
                result.append(
                    {
                        "stage": "audit",
                        "input_hash": row["input_hash"],
                        "gold_dependencies": values["gold_dependencies"],
                        "observed_dependencies": dependencies,
                    }
                )
            if "visual" in values:
                images = row["input"]["question"].get("images", [])
                indices = {
                    i
                    for dep in dependencies
                    if dep["kind"] == "visual"
                    for i in dep["image_indices"]
                }
                result.append(
                    {
                        "stage": "visual",
                        **values["visual"],
                        "original_image_hashes": [digest(i) for i in images],
                        "reviewed_image_hashes": [
                            digest(images[i]) for i in sorted(indices) if 0 <= i < len(images)
                        ],
                    }
                )
        else:
            if "correct_ids" in values:
                history = list(row["input"]["candidate_history"])
                eligible = [
                    i
                    for i in history
                    if observation.get("assessments", {}).get(i, {}).get("eligible")
                ]
                result.append(
                    {
                        "stage": "eligibility",
                        "candidate_ids": history,
                        "correct_ids": values["correct_ids"],
                        "eligible_ids": eligible,
                    }
                )
                selection = observation.get("selection") or {}
                result.append(
                    {
                        "stage": "selection",
                        "candidate_ids": history,
                        "correct_ids": values["correct_ids"],
                        "selected_id": selection.get("selected"),
                    }
                )
            if "adjudicated_correct" in values:
                result.append(
                    {
                        "stage": "reference",
                        "original_correct": observation["original_grade"]["correct"],
                        "adjudicated_correct": values["adjudicated_correct"],
                        "disagreement": values.get("disagreement", "unresolved"),
                    }
                )
    return result


def saved_passages(audit_path, backend, run, qid, research, question):
    """Reconstruct all fetched chunks, including those never sent to J2."""
    from ..retrieval.evidence import chunk_page
    from ..tools.policy import Policy

    outcome = research["outcome"]
    if not outcome["searches"]:
        return []
    if len(outcome["searches"]) != 1:
        raise ValueError("historical fetch-to-query mapping is ambiguous")
    query = outcome["searches"][0]
    policy = Policy(Path("protocol/upstream/blocklist.json"))
    manifest = run["manifest"]
    db_path = audit_path.parent / f"sol-low-evidence-v3-j23-{backend}/events.sqlite3"
    passages = []
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as db:
        for fetch in outcome["fetches"]:
            if fetch["status"] != "fetched":
                continue
            key = digest(
                {
                    "tool": "web_fetch",
                    "url": fetch["url"],
                    "filter": policy.version,
                    "parser": manifest["config"]["parser_version"],
                    "config": manifest["config_hash"],
                }
            )
            row = db.execute(
                "SELECT value FROM cache WHERE item=? AND key=?", (qid, key)
            ).fetchone()
            if row is None:
                raise ValueError("historical fetched source cache unavailable")
            page = json.loads(row[0])["page"]
            normalized = {
                **page,
                "text": page["text"][:60000],
                "source_hash": hashlib.sha256(page["text"].encode()).hexdigest(),
                "filter_version": policy.version,
            }
            passages.extend(
                chunk_page(
                    normalized,
                    query["missing_fact"],
                    question=question,
                    search_query=query["query"],
                    dependency_id=query["dependency_id"],
                )
            )
    if len(passages) != research["pre_shortlist_passage_count"]:
        raise ValueError("fetched passage reconstruction differs from the historical trace")
    return passages


def extract_cases(audit_path: Path, index_path: Path, output: Path, questions_path: Path):
    """Extract exact saved requests and whole candidate histories for independent labeling.

    The original grades live in reference cases only. Model reviews and casebook
    hypotheses remain observations, never independent labels.
    """
    audit = json.loads(audit_path.read_text())
    index = json.loads(index_path.read_text())
    questions = {q["id"]: q for q in read_jsonl(questions_path)}
    rows = []
    for case in index["cases"]:
        alias, qid = case["alias"], case["question_id"]
        for backend, run in audit["runs"].items():
            item = run["items"][qid]
            for research in item["research"]:
                round_no = research["outcome"]["round"]
                judged_ids = {j["passage"]["id"] for j in research["judged"]}
                for p in saved_passages(
                    audit_path, backend, run, qid, research, questions[qid]["question"]
                ):
                    if p.id in judged_ids:
                        continue
                    state = {
                        "question": p.question,
                        "missing_fact": p.subquestion,
                        "search_query": p.search_query,
                        "dependency_id": p.dependency_id,
                        "passage": p.text,
                        "url": p.url,
                        "title": p.title,
                    }
                    rows.append(
                        case_record(
                            f"{alias}/{backend}/J2/not-run/{round_no}/{p.id}",
                            "J2",
                            state,
                            {
                                "judgment_executed": False,
                                "exclusion": "shortlist",
                                "round": round_no,
                            },
                            task_id=digest([backend, qid, round_no, p.subquestion]),
                            test_id="T07",
                            passages=[p.id],
                        )
                    )
                for query in research["outcome"]["searches"]:
                    rows.append(
                        case_record(
                            f"{alias}/{backend}/search/{round_no}/{digest(query['query'])}",
                            "search",
                            {
                                "id": digest([qid, query["missing_fact"], query["query"]]),
                                "question": questions[qid]["question"],
                                "missing_fact": query["missing_fact"],
                                "query": query["query"],
                            },
                            {"research_outcome": research["outcome"]},
                            task_id=digest([qid, round_no, query["missing_fact"]]),
                            test_id="T09",
                        )
                    )
                for judgment in research["judged"]:
                    p = judgment["passage"]
                    task = digest([backend, qid, round_no, p["subquestion"]])
                    state = {
                        "question": p["question"],
                        "missing_fact": p["subquestion"],
                        "search_query": p["search_query"],
                        "dependency_id": p["dependency_id"],
                        "passage": p["text"],
                        "url": p["url"],
                        "title": p["title"],
                    }
                    rows.append(
                        case_record(
                            f"{alias}/{backend}/J2/{judgment['request_hash']}",
                            "J2",
                            state,
                            {
                                "judgment": judgment["judgment"],
                                "exclusion": judgment["exclusion"],
                                "round": round_no,
                            },
                            task_id=task,
                            test_id="T07",
                            passages=[p["id"]],
                        )
                    )
            # Captured requests include initial, revised, repair and reassessed drafts.
            for capture in run["replay"]["requests"]:
                if capture["item"] != qid:
                    continue
                context = capture["context"]
                if not capture["phase"].startswith("audit-"):
                    continue
                draft = context["draft"]
                rows.append(
                    case_record(
                        f"{alias}/{backend}/audit/{capture['request_hash']}",
                        "audit",
                        {"question": questions[qid], "context": context},
                        {"response": capture.get("response"), "error": capture.get("error")},
                        task_id=digest([qid, capture["request_hash"]]),
                        test_id="T06",
                        claims=list(
                            dict.fromkeys(
                                d["id"]
                                for d in draft["dependencies"]
                                + (capture.get("response") or {}).get("dependencies", [])
                            )
                        ),
                        passages=list(dict.fromkeys(p["id"] for p in context["evidence"])),
                    )
                )
            rows.append(
                case_record(
                    f"{alias}/{backend}/reference",
                    "reference",
                    {
                        "question": questions[qid],
                        "candidate_history": item["candidates"],
                        "prediction": item["prediction"],
                    },
                    {
                        "original_grade": item["grade"],
                        "assessments": item.get("final_checks", {}),
                        "selection": item.get("selection"),
                    },
                    task_id=digest(qid),
                    test_id="T10",
                )
            )
    # J3 state is recovered directly from exact Jev cache identities in the saved DBs.
    for backend, run in audit["runs"].items():
        db_path = audit_path.parent / f"sol-low-evidence-v3-j23-{backend}/events.sqlite3"
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as db:
            aliases = {case["question_id"]: case["alias"] for case in index["cases"]}
            for qid, raw in db.execute("SELECT item,data FROM events WHERE kind='jev_response'"):
                if qid not in aliases:
                    continue
                event = json.loads(raw)
                # J3 contexts are not in this event. Reconstruct the exact citation/dependency
                # request and accept it only when its full request hash matches the event.
                item = run["items"][qid]
                states = []
                for assessment in run["replay"]["assessments"]:
                    if assessment["item"] != qid:
                        continue
                    checks = assessment["checks"]
                    for capture in run["replay"]["requests"]:
                        if (
                            capture["item"] != qid
                            or capture["phase"] != f"audit-{assessment['candidate']['id']}"
                        ):
                            continue
                        sources = {p["id"]: p for p in capture["context"]["evidence"]}
                        for citation in assessment["candidate"]["citations"]:
                            if citation["passage_id"] in sources:
                                states.append(
                                    {
                                        "claim": citation["claim"],
                                        "quote": citation["quote"],
                                        "source_context": sources[citation["passage_id"]]["text"],
                                    }
                                )
                        for dep in checks["dependencies"]:
                            refs = dep["passage_ids"]
                            if (
                                dep["kind"] == "factual"
                                and refs
                                and all(i in sources for i in refs)
                            ):
                                text = "\n\n".join(sources[i]["text"] for i in refs)
                                states.append(
                                    {
                                        "question": questions[qid]["question"],
                                        "claim": dep["statement"],
                                        "quote": text,
                                        "source_context": text,
                                        "sources": [
                                            {"id": i, "url": sources[i]["url"]} for i in refs
                                        ],
                                    }
                                )
                from ..judgments.pipeline import SUPPORT

                for state in states:
                    contract = {
                        "stage": "J3",
                        "state": state,
                        "questions": {"support": SUPPORT},
                        "provider": run["manifest"]["config"]["jev"],
                        "config_hash": run["manifest"]["config_hash"],
                    }
                    if digest(contract) == event["request_hash"]:
                        rows.append(
                            case_record(
                                f"{aliases[qid]}/{backend}/J3/{event['request_hash']}",
                                "J3",
                                state,
                                {"response": event},
                                task_id=digest([qid, state["claim"]]),
                                test_id="T08",
                                claims=["claim-" + digest(state["claim"])[:16]],
                                passages=list(
                                    dict.fromkeys(
                                        [s["id"] for s in state.get("sources", [])]
                                        + [
                                            p["id"]
                                            for research in item["research"]
                                            for p in research["packet"]
                                            if p["text"] == state["source_context"]
                                        ]
                                    )
                                ),
                            )
                        )
                        break
    rows = list({row["id"]: row for row in rows}.values())
    for row in rows:
        validate_case(row)
    private_dir(output)
    path = output / "label-cases.jsonl"
    # Never overwrite manual adjudication.
    if path.exists():
        raise ValueError("label cases already exist; choose a fresh extraction directory")
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    path.chmod(0o600)
    manifest = {
        "cases": len(rows),
        "cases_hash": digest(rows),
        "audit_hash": digest(audit),
        "index_hash": digest(index),
        "source_implementation": index["implementation_hash"],
        "label_status": "unresolved",
        "paid_calls_dispatched": 0,
        "component_counts": {
            component: sum(r["component"] == component for r in rows)
            for component in ("audit", "J2", "J3", "search", "reference")
        },
    }
    atomic_json(output / "extraction.json", manifest)
    return manifest

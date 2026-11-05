"""Isolated source-snapshot execution for the exact user-preserved comparison revision."""

import asyncio
import importlib.util
import inspect
import json
import subprocess
import sys
from pathlib import Path


def snapshot_info(source, config):
    code = """import json,sys
sys.path.insert(0,sys.argv[1])
from jev_solver.config import Config
from jev_solver.controller.engine import implementation_hash
c=Config.load(sys.argv[2])
print(json.dumps({"implementation_hash":implementation_hash(),"config_hash":c.hash}))
"""
    return json.loads(
        subprocess.check_output(
            [
                sys.executable,
                "-c",
                code,
                str(Path(source).resolve() / "src"),
                str(Path(config).resolve()),
            ],
            text=True,
        )
    )


async def foreign_trial(job, job_path):
    from ..tracing.store import atomic_json

    atomic_json(job_path, job)
    bootstrap = """import importlib.util,sys
sys.path.insert(0,sys.argv[1])
spec=importlib.util.spec_from_file_location("snapshot_worker",sys.argv[2])
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.worker(sys.argv[3])
"""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        bootstrap,
        str(Path(job["source_root"]).resolve() / "src"),
        str(Path(__file__).resolve()),
        str(job_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), 60 if not job["launch"] else 3600)
        if process.returncode:
            raise RuntimeError(
                "isolated source snapshot trial failed; inspect its private artifacts"
            )
        return json.loads(stdout)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()


def worker(job_path):
    job = json.loads(Path(job_path).read_text())
    current = Path(__file__).parent.parent
    # The engine, models, provider transports and configuration come from the
    # frozen source tree. Only the experiment adapters are loaded from this tree.
    for name, path in (
        ("jev_solver.providers.context", current / "providers/context.py"),
        ("jev_solver.evaluation.offline", current / "evaluation/offline.py"),
        ("jev_solver.evaluation.replay", current / "evaluation/replay.py"),
        ("jev_solver.evaluation.orchestration", current / "evaluation/orchestration.py"),
    ):
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    from jev_solver.config import Config
    from jev_solver.controller import engine
    from jev_solver.evaluation.offline import OfflineDispatchForbidden
    from jev_solver.evaluation.orchestration import install_replay
    from jev_solver.evaluation.replay import ControlledReplay
    from jev_solver.models import digest
    from jev_solver.tracing.store import Store, atomic_json

    async def execute():
        config = Config.load(job["config"])
        manifest = job["manifest"]
        arm = next(a for a in manifest["arms"] if a["id"] == job["arm"])
        if (
            config.hash != arm["config_hash"]
            or engine.implementation_hash() != arm["implementation_hash"]
        ):
            raise ValueError("isolated source/configuration identity differs")
        output = Path(job["experiment_output"])
        response_path = output / "generated-responses.json"
        generated = json.loads(response_path.read_text()) if response_path.exists() else []
        replay = ControlledReplay(manifest, [*job["frozen"], *generated])
        ledger = Store(output / "experiment.sqlite3")
        original = engine.Solver

        def factory(c, store, run_hash):
            return install_replay(
                original(c, store, run_hash),
                replay,
                arm,
                job["launch"],
                ledger,
                digest([arm["id"], job["replicate"]]) + ":",
                manifest["spend_caps"],
                asyncio.Lock(),
                job["replicate"],
            )

        engine.Solver = factory
        status = "completed"
        try:
            kwargs = {
                "resume": job["resume"],
                "split": "development" if config.live else "full",
                "question_ids": (job["question_id"],),
            }
            if "solver_factory" in inspect.signature(engine.run).parameters:
                kwargs["solver_factory"] = factory
            await engine.run(config, Path(job["questions"]), Path(job["destination"]), **kwargs)
        except OfflineDispatchForbidden:
            status = "unavailable_snapshot"
        finally:
            engine.Solver = original
            atomic_json(response_path, [*generated, *replay.generated.values()])
            ledger.close()
        return {"status": status, "ledger": replay.ledger}

    print(json.dumps(asyncio.run(execute())))

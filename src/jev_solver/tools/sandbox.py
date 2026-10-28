"""Docker broker: no network, host mounts, credentials, root or writable root filesystem."""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path

from ..config import Config
from ..controller.budget import Budget
from ..models import digest
from ..tracing.store import Store


class Sandbox:
    def __init__(self, config: Config, store: Store, budget: Budget):
        self.config, self.store, self.budget = config, store, budget

    def command(self, name: str) -> list[str]:
        return [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--name",
            name,
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit=64",
            "--memory=512m",
            "--cpus=1",
            "--ulimit=nofile=64:64",
            "--user=65534:65534",
            "--tmpfs=/tmp:rw,noexec,nosuid,size=64m",
            "--workdir=/tmp",
            "-i",
            self.config.sandbox_image,
            "python",
            "-I",
            "-",
        ]

    async def execute(self, item: str, code: str) -> dict:
        key = digest({"code": code, "image": self.config.sandbox_image, "config": self.config.hash})
        cached = self.store.cached(item, key)
        if cached is not None:
            self.store.event(item, "code_replay", {"request_hash": key})
            return cached

        async def call():
            if not self.config.live:
                output = {
                    "stdout": "Synthetic sandbox fixture; code was not executed.",
                    "stderr": "",
                    "returncode": 0,
                    "synthetic": True,
                    "truncated": False,
                }
            else:
                output = await self._docker(code)
            return {**output, "cost_usd": self.config.code_usd, "usage": {}}

        result = await self.budget.execute(item, "code", self.config.code_usd, call)
        self.store.event(item, "code", {"request_hash": key, **result})
        self.store.cache(item, key, result)
        return result

    async def _docker(self, code: str) -> dict:
        name = "jev-" + uuid.uuid4().hex
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        process = await asyncio.create_subprocess_exec(
            *self.command(name),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        # Validate the actual runtime on every execution, not an image's self-declared labels.
        packages = {}
        for line in Path("protocol/upstream/requirements-tools.txt").read_text().splitlines():
            if "==" in line and not line.startswith("#"):
                k, v = line.split("==")
                packages[k] = v
        prefix = (
            "import sys, importlib.metadata\n"
            "assert sys.version_info[:3] == (3,11,16), 'sandbox Python mismatch'\n"
            f"assert all(importlib.metadata.version(k)==v for k,v in {packages!r}.items()), 'sandbox packages mismatch'\n"
        )
        truncated = False

        async def read(stream):
            nonlocal truncated
            result, size = [], 0
            while True:
                chunk = await stream.read(4096)
                if not chunk:
                    break
                size += len(chunk)
                if size > 65536:
                    truncated = True
                    raise ValueError("sandbox output limit")
                result.append(chunk)
            return b"".join(result).decode(errors="replace")

        async def write():
            process.stdin.write((prefix + code).encode())
            await process.stdin.drain()
            process.stdin.close()

        try:
            async with asyncio.timeout(30):
                _, stdout, stderr, rc = await asyncio.gather(
                    write(), read(process.stdout), read(process.stderr), process.wait()
                )
            return {
                "stdout": stdout,
                "stderr": stderr,
                "returncode": rc,
                "truncated": truncated,
                "synthetic": False,
            }
        finally:
            # Removing the container kills descendants even if the CLI was cancelled.
            cleanup = await asyncio.create_subprocess_exec(
                "docker",
                "rm",
                "-f",
                name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                env=env,
            )
            try:
                await asyncio.wait_for(cleanup.wait(), 10)
            except TimeoutError:
                cleanup.kill()
                await cleanup.wait()
            if process.returncode is None:
                process.kill()
                await process.wait()

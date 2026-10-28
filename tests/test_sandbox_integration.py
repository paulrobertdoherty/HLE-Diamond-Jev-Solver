"""Opt-in container integration; unit CI never needs a Docker daemon or API keys."""

import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from jev_solver.config import Config, ProviderConfig
from jev_solver.controller.budget import Budget
from jev_solver.tools.sandbox import Sandbox
from jev_solver.tracing.store import Store


@unittest.skipUnless(
    os.environ.get("JEV_SANDBOX_IMAGE"), "set JEV_SANDBOX_IMAGE to a built pinned image"
)
class SandboxIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_network_credentials_and_filesystem_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = replace(
                Config(),
                provider=ProviderConfig(kind="openai"),
                sandbox_image=os.environ["JEV_SANDBOX_IMAGE"],
            )
            store = Store(Path(tmp) / "events.sqlite3")
            try:
                broker = Sandbox(cfg, store, Budget(store, cfg))
                result = await broker._docker("""import os, pathlib, socket
assert not any(k in os.environ for k in ['OPENAI_API_KEY','TYPESAFE_API_KEY','HF_TOKEN'])
assert not pathlib.Path('/data').exists()
assert not pathlib.Path('/home/paul').exists()
try:
    socket.create_connection(('1.1.1.1', 443), timeout=1)
except OSError:
    print('isolated')
else:
    raise AssertionError('network enabled')
""")
                self.assertEqual(result["returncode"], 0, result["stderr"])
                self.assertIn("isolated", result["stdout"])
            finally:
                store.close()

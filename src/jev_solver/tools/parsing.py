"""Bounded text-only PDF extraction in a credential-free child process."""

from __future__ import annotations

import asyncio
import json
import os
import sys

from ..providers.backbone import ProviderError

PDF_SCRIPT = r"""
import io, json, logging, resource, sys
resource.setrlimit(resource.RLIMIT_AS, (512*1024*1024, 512*1024*1024))
resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
logging.disable(logging.CRITICAL)
try:
    from pypdf import PdfReader
    body = sys.stdin.buffer.read(8_000_001)
    if len(body) > 8_000_000:
        raise ValueError('source byte limit')
    reader = PdfReader(io.BytesIO(body))
    texts, size = [], 0
    for page in reader.pages:
        text = page.extract_text() or ''
        size += len(text)
        if size > 8_000_000:
            raise ValueError('extraction text limit')
        texts.append(text)
    title = str(reader.metadata.title or '') if reader.metadata else ''
    if len(title) > 60000:
        raise ValueError('metadata limit')
    print(json.dumps({'text': '\n\n'.join(texts), 'title': title}))
except Exception:
    sys.exit(1)
"""


async def extract_pdf(body: bytes) -> dict:
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-I",
        "-c",
        PDF_SCRIPT,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},
    )
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(body), 20)
        if process.returncode != 0:
            raise ProviderError("source extraction unavailable")
        return json.loads(stdout)
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()

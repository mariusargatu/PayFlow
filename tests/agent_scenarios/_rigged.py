"""Rigged world serving for the Layer 2 scenario tests (design section 9).

A scenario hands the triage agent a live PayFlow that is wrong in a known way and
checks the verdict. This module serves the SUT in process (as the validation tools
do) and, for the broken capture scenario, applies the same monkeypatch used by
tools/triage_validation.py, then restores the mutated globals so scenarios can
run in one process without leaking into each other.
"""

from __future__ import annotations

import contextlib
import socket
import threading
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


@contextlib.contextmanager
def broken_capture_patch():
    """Drop the INV-1 over capture guard in process, then restore it.

    Reuses tools/triage_validation.py's monkeypatch (schema CHECK strip + capture
    method replacement) and undoes both on exit so a later scenario sees a clean,
    correct build.
    """
    import payflow.infrastructure.db as dbmod
    from payflow.domain import service as svc

    original_schema = dbmod._SCHEMA
    original_capture = svc.PaymentService.capture
    from tools.triage_validation import _apply_monkeypatch

    _apply_monkeypatch()
    try:
        yield
    finally:
        dbmod._SCHEMA = original_schema
        svc.PaymentService.capture = original_capture


@contextlib.contextmanager
def served_sut(db_path: str, capture_fee: int):
    """Serve create_app on a free port; yield the base URL; shut it down on exit."""
    import httpx
    import uvicorn

    from payflow.api.app import create_app
    from payflow.config import Config

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    app = create_app(Config(db_path=db_path, capture_fee=capture_fee, bug=None))
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    base_url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{base_url}/openapi.json", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.05)
    try:
        yield base_url
    finally:
        server.should_exit = True
        thread.join(timeout=10)

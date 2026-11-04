"""Start the real server in a separate process, for browser and concurrency tests.

In-process TestClient calls run one at a time. Tests that need a real
browser or real parallel HTTP requests use this instead.
"""

import os
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class LiveServer:
    url: str
    db_path: str
    process: subprocess.Popen
    # One shared, thread-safe client. A bare httpx.post() builds a new client per
    # call, which measured about 0.37 s each on the development laptop and made
    # the race tests slow (DEF-001 in docs/DEFECTS.md).
    http: httpx.Client = None

    def __post_init__(self):
        limits = httpx.Limits(max_connections=200, max_keepalive_connections=200)
        self.http = httpx.Client(base_url=self.url, timeout=30, limits=limits)

    def login(self, username: str) -> dict:
        r = self.http.post("/api/login", json={"username": username, "password": "demo-pass"})
        r.raise_for_status()
        return {"Authorization": f"Bearer {r.json()['token']}"}

    def advance_clock(self, ms: int) -> None:
        self.http.post("/api/_test/clock", json={"advance_ms": ms}).raise_for_status()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start(db_path: str, faults: str = "", sale_opens_in: float | None = None, sample_sales: float = 0.0,
          extra_env: dict | None = None) -> LiveServer:
    port = free_port()
    env = {
        **os.environ,
        "TICKET_DROP_DB": db_path,
        "TICKET_DROP_TEST_HOOKS": "1",
        "TICKET_DROP_PAYMENT_TIMEOUT": "0.5",
        "TICKET_DROP_FAULTS": faults,
        **(extra_env or {}),
    }
    args = [sys.executable, "serve.py", "--port", str(port)]
    if sale_opens_in is not None:
        args += ["--sale-opens-in", str(sale_opens_in)]
    if sample_sales:
        args += ["--sample-sales", str(sample_sales)]
    process = subprocess.Popen(args, cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    url = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Server exited early: {process.stderr.read().decode(errors='replace')}")
        try:
            if httpx.get(f"{url}/api/event", timeout=1).status_code == 200:
                return LiveServer(url, db_path, process)
        except httpx.HTTPError:
            time.sleep(0.2)
    process.kill()
    raise RuntimeError("Server did not start within 30 seconds")


def stop(server: LiveServer) -> None:
    server.http.close()
    server.process.terminate()
    try:
        server.process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        server.process.kill()
        server.process.wait(timeout=10)

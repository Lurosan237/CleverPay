"""End-to-end latency benchmark of the scoring API, over real HTTP.

    python -m momofraud.serving.bench       # writes reports/latency.md and .json

Starts the API in a separate process (one uvicorn worker, demo network of 3,000 people),
then sends a realistic mix of requests at several levels of concurrency:

- 90% payments to someone the sender has paid before (usually approved, not explained),
- 8% payments to a stranger (more reviews, so more explanations),
- 2% account takeovers: a SIM swap, then the balance sent to a new account from a new
  phone (blocked and explained).

Latency is measured by the client, from sending the request to receiving the full
response, so it includes HTTP, JSON, validation, features, the model and explanations.

On Linux with 2+ cores the server and the load generator are pinned to different CPU
cores, so the client doesn't steal CPU from the server it is measuring (an earlier
unpinned run showed throughput *falling* as concurrency rose, for that reason).
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import random
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import aiohttp
import httpx
import numpy as np

from momofraud.paths import REPORTS_DIR, ROOT

CONCURRENCY = (1, 4, 16, 64)
REQUESTS_PER_LEVEL = 3000
WARMUP = 300
SEED = 11
# A longer keep-alive than uvicorn's 5 s default avoids a race where the server closes an
# idle connection just as the client reuses it (seen intermittently at 64 clients).
# uvloop and httptools come with uvicorn[standard] (uvloop is not available on Windows).
SERVER_ARGS = ["--timeout-keep-alive", "30", "--loop", "auto", "--http", "auto"]
EXTRA_SERVER_ARGS: list[str] = []


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _can_pin() -> bool:
    return sys.platform.startswith("linux") and (os.cpu_count() or 1) >= 2 and shutil.which("taskset") is not None


def start_server(port: int) -> subprocess.Popen:
    env = os.environ | {"PYTHONPATH": str(ROOT / "src")}
    pin = ["taskset", "-c", "0"] if _can_pin() else []
    proc = subprocess.Popen(
        [*pin, sys.executable, "-m", "uvicorn", "momofraud.serving.api:app", "--port", str(port),
         "--log-level", "warning", "--no-access-log", *SERVER_ARGS, *EXTRA_SERVER_ARGS],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    deadline = time.time() + 120
    while time.time() < deadline:
        try:
            if httpx.get(f"http://127.0.0.1:{port}/health", timeout=1).status_code == 200:
                return proc
        except httpx.HTTPError:
            time.sleep(0.5)
    proc.kill()
    raise RuntimeError("API did not start: " + proc.stderr.read().decode()[-2000:])


class Traffic:
    """Builds requests from what the API itself exposes about the network."""

    def __init__(self, base: str, rng: random.Random):
        self.base, self.rng = base, rng
        customers = httpx.get(f"{base}/v1/accounts", params={"limit": 200}).json()
        self.people = []
        for c in customers:
            view = httpx.get(f"{base}/v1/accounts/{c['account']}").json()
            contacts = sorted({t["receiver"] for t in view["recent"]
                               if t["sender"] == c["account"] and t["type"] == "TRANSFER"})
            if contacts and view["device"]:
                self.people.append((c["account"], view["device"], contacts))
        self.everyone = [c["account"] for c in customers]
        self.counter = 0

    async def next_request(self, session: aiohttp.ClientSession) -> tuple[str, dict]:
        """Returns (kind, body). For takeovers, the SIM swap and the mule account are set up
        first (not timed): only the theft itself is measured."""
        self.counter += 1
        sender, device, contacts = self.rng.choice(self.people)
        roll = self.rng.random()
        if roll < 0.90:
            body = {"type": "TRANSFER", "sender": sender, "receiver": self.rng.choice(contacts),
                    "amount": self.rng.choice([500, 1000, 2000, 5000]), "device": device}
            return "known recipient", body
        if roll < 0.98:
            stranger = self.rng.choice([a for a in self.everyone if a != sender])
            body = {"type": "TRANSFER", "sender": sender, "receiver": stranger, "amount": 2000, "device": device}
            return "stranger", body
        attacker = f"D-bench-{self.counter}"
        async with session.post(f"{self.base}/v1/events",
                                json={"account": sender, "event": "SIM_SWAP", "device": attacker}) as r:
            await r.read()
        async with session.post(f"{self.base}/v1/accounts", json={}) as r:
            mule = (await r.json())["account"]
        body = {"type": "TRANSFER", "sender": sender, "receiver": mule, "amount": 2000, "device": attacker}
        return "takeover", body


async def run_level(traffic: Traffic, concurrency: int, n: int) -> list[dict]:
    results: list[dict] = []
    remaining = [n]
    connector = aiohttp.TCPConnector(limit=concurrency)
    async with aiohttp.ClientSession(connector=connector, timeout=aiohttp.ClientTimeout(total=60)) as session:
        async def worker():
            while remaining[0] > 0:
                remaining[0] -= 1
                kind, body = await traffic.next_request(session)
                start = time.perf_counter()
                async with session.post(f"{traffic.base}/v1/transactions", json=body) as response:
                    data = await response.json()
                    status = response.status
                elapsed = (time.perf_counter() - start) * 1000
                results.append({"kind": kind, "ms": elapsed, "status": status,
                                "decision": data.get("decision"), "server_us": data.get("timings_us", {})})

        started = time.perf_counter()
        await asyncio.gather(*(worker() for _ in range(concurrency)))
        wall = time.perf_counter() - started
    for r in results:
        r["wall_seconds"] = wall
    return results


def percentiles(values) -> dict[str, float]:
    v = np.asarray(values)
    return {"p50": float(np.percentile(v, 50)), "p95": float(np.percentile(v, 95)),
            "p99": float(np.percentile(v, 99)), "mean": float(v.mean())}


def server_stack() -> str:
    try:
        import uvloop  # noqa: F401
        loop = "uvloop"
    except ImportError:
        loop = "asyncio"
    try:
        import httptools  # noqa: F401
        http = "httptools"
    except ImportError:
        http = "h11"
    return f"uvicorn ({loop} event loop, {http} HTTP parser), 1 worker"


def machine() -> dict:
    cpu = platform.processor() or ""
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    return {"cpu": cpu, "cores": os.cpu_count(), "python": platform.python_version(), "os": platform.platform()}


def run() -> dict:
    if _can_pin():
        os.sched_setaffinity(0, {1})  # this process (the load generator) on core 1, the server on core 0
    port = _free_port()
    server = start_server(port)
    try:
        traffic = Traffic(f"http://127.0.0.1:{port}", random.Random(SEED))
        asyncio.run(run_level(traffic, 4, WARMUP))
        levels = {}
        for c in CONCURRENCY:
            rows = asyncio.run(run_level(traffic, c, REQUESTS_PER_LEVEL))
            ok = [r for r in rows if r["status"] == 200]
            levels[c] = {
                "requests": len(rows), "errors": len(rows) - len(ok),
                "throughput_rps": len(rows) / rows[0]["wall_seconds"],
                "all": percentiles([r["ms"] for r in ok]),
                "not_explained": percentiles([r["ms"] for r in ok if "explain" not in r["server_us"]]),
                "explained": percentiles([r["ms"] for r in ok if "explain" in r["server_us"]] or [0]),
                "explained_share": float(np.mean(["explain" in r["server_us"] for r in ok])),
                "decisions": {d: sum(r["decision"] == d for r in ok) for d in ("approve", "review", "block")},
            }
            print(f"concurrency {c:>2}: p50 {levels[c]['all']['p50']:.2f} ms, p95 {levels[c]['all']['p95']:.2f} ms, "
                  f"{levels[c]['throughput_rps']:.0f} req/s")
        server_side = asyncio.run(run_level(traffic, 1, 1000))
        breakdown = {
            stage: percentiles([r["server_us"][stage] / 1000 for r in server_side if stage in r["server_us"]])
            for stage in ("features", "model", "explain", "total")
        }
    finally:
        server.terminate()
        server.wait(timeout=10)
    return {"machine": machine(), "server": server_stack(), "pinned": _can_pin(), "levels": levels,
            "server_breakdown_ms": breakdown}


def to_markdown(r: dict) -> str:
    m = r["machine"]
    lines = [
        "# API latency",
        "",
        "Generated by `python -m momofraud.serving.bench`. Demo network of 3,000 people, measured by the",
        f"client over HTTP on localhost. Server: {r['server']}. Machine: {m['cpu']}, {m['cores']} cores,",
        f"Python {m['python']}. {REQUESTS_PER_LEVEL:,} requests per level. "
        + ("Server and load generator pinned to separate CPU cores." if r["pinned"]
           else "Server and load generator share the CPU, so these numbers are conservative."),
        "",
        "Traffic mix: 90% payments to a known contact, 8% to a stranger, 2% account takeovers.",
        "Explanations (SHAP) are computed only for review and block decisions.",
        "",
        "| Concurrent clients | p50 | p95 | p99 | Throughput | Explained |",
        "|---|---|---|---|---|---|",
    ]
    for c, v in r["levels"].items():
        a = v["all"]
        lines.append(f"| {c} | {a['p50']:.2f} ms | {a['p95']:.2f} ms | {a['p99']:.2f} ms | "
                     f"{v['throughput_rps']:.0f} req/s | {v['explained_share']:.1%} |")
    one = r["levels"][list(r["levels"])[0]]
    lines += [
        "",
        "With one client, by path:",
        "",
        "| Path | p50 | p95 | p99 |",
        "|---|---|---|---|",
        f"| Approved, not explained | {one['not_explained']['p50']:.2f} ms | {one['not_explained']['p95']:.2f} ms | "
        f"{one['not_explained']['p99']:.2f} ms |",
        f"| Review or block, explained | {one['explained']['p50']:.2f} ms | {one['explained']['p95']:.2f} ms | "
        f"{one['explained']['p99']:.2f} ms |",
        "",
        "Time spent inside the server (one client):",
        "",
        "| Stage | p50 | p95 |",
        "|---|---|---|",
    ]
    for stage, v in r["server_breakdown_ms"].items():
        lines.append(f"| {stage} | {v['p50'] * 1000:.0f} µs | {v['p95'] * 1000:.0f} µs |")
    lines += [
        "",
        "Higher concurrency raises throughput only up to what one process can do: requests are",
        "handled one at a time so the network state stays consistent. Past that point, extra clients",
        "just wait in line, which is what the p95 and p99 at 64 clients show. Scaling further needs",
        "several workers sharing the state in an external store such as Redis.",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    report = run()
    REPORTS_DIR.mkdir(exist_ok=True)
    (REPORTS_DIR / "latency.json").write_text(json.dumps(report, indent=2))
    (REPORTS_DIR / "latency.md").write_text(to_markdown(report), encoding="utf-8")
    print((REPORTS_DIR / "latency.md").read_text(encoding="utf-8"))

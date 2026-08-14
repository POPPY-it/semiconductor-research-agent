"""轻量并发压测（httpx asyncio）：/api/health 与 /api/v1/sessions。

指标：总请求数、QPS、P50/P95/P99 延迟、错误数。结果存 spikes/results/loadtest_report.json
"""
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8000"
TOKEN = "dev-token-2026"
CONCURRENCY = 20
PER_WORKER = 50  # 每个 worker 轮番打 2 个端点

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "spikes" / "results" / "loadtest_report.json"


async def worker(wid: int, latencies: list[float], errors: list[str]) -> None:
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as client:
        for i in range(PER_WORKER):
            if i % 2 == 0:
                path, headers = "/api/health", {}
            else:
                path, headers = "/api/v1/sessions", {"X-API-Token": TOKEN}
            t0 = time.perf_counter()
            try:
                resp = await client.get(path, headers=headers)
                if resp.status_code != 200:
                    errors.append(f"{path} -> {resp.status_code}")
            except Exception as e:  # noqa: BLE001
                errors.append(f"{path} -> {type(e).__name__}")
            latencies.append((time.perf_counter() - t0) * 1000)


async def main() -> None:
    latencies: list[float] = []
    errors: list[str] = []
    t0 = time.perf_counter()
    await asyncio.gather(*[worker(i, latencies, errors) for i in range(CONCURRENCY)])
    total_sec = time.perf_counter() - t0

    latencies.sort()
    n = len(latencies)
    pct = lambda p: round(latencies[min(n - 1, int(n * p))], 1)
    report = {
        "endpoints": ["GET /api/health", "GET /api/v1/sessions"],
        "concurrency": CONCURRENCY,
        "requests_per_worker": PER_WORKER,
        "total_requests": n,
        "errors": len(errors),
        "duration_sec": round(total_sec, 2),
        "qps": round(n / total_sec, 1),
        "latency_ms": {
            "mean": round(statistics.mean(latencies), 1),
            "p50": pct(0.50),
            "p95": pct(0.95),
            "p99": pct(0.99),
            "max": round(latencies[-1], 1),
        },
        "error_samples": errors[:5],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

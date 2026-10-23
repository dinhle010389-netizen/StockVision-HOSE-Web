"""100-way concurrent, offline cross-checks for StockVision; never calls providers."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import json
import random
import time
import yaml

from app.normalizers import NormalizationError, normalize_symbol, normalize_tcbs_bar
from app.risk import analyze_hermitian_matrix, covariance_from_returns, RiskMatrixError
from app.main import _split_sql_statements

ROOT = Path(__file__).resolve().parents[1]
N_WORKERS = 100
checks_per_job = 0

def run_one(worker_id: int) -> dict:
    rng = random.Random(20261023 + worker_id)
    checks = 0
    # Config/security contract checks
    render = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8")); checks += 1
    service = next(s for s in render["services"] if s["name"] == "stockvision-hose")
    env = {e["key"]: e for e in service["envVars"]}
    assert env["APP_ACCESS_PASSWORD"].get("sync") is False; checks += 1
    assert env["APP_SESSION_SECRET"].get("generateValue") is True; checks += 1
    assert env["DATABASE_URL"]["fromDatabase"]["name"] == "stockvision-db"; checks += 1
    assert env["FIREANT_API_TOKEN"].get("value", "") == ""; checks += 1
    assert env["DEMO_MODE"]["value"] == "false"; checks += 1
    assert service["plan"] == "starter"; checks += 1
    assert render["databases"][0]["plan"] == "basic-256mb"; checks += 1
    assert service["autoDeployTrigger"] == "checksPass"; checks += 1

    # Symbol canonicalization and input-safety
    raw_symbol = f"fpt{worker_id:03d}"
    assert normalize_symbol(raw_symbol) == raw_symbol.upper(); checks += 1
    for bad in ("FPT/../x", "", "@FPT"):
        try:
            normalize_symbol(bad)
            raise AssertionError(f"invalid symbol accepted: {bad!r}")
        except NormalizationError:
            checks += 1

    # Valid and invalid OHLC bar contracts
    low = 10.0 + rng.random() * 5
    opn = low + rng.random() * 5
    close = low + rng.random() * 5
    high = max(opn, close, low) + 0.5 + rng.random()
    payload = {"date": "2026-10-22", "open": opn, "high": high, "low": low,
               "close": close, "volume": rng.randrange(0, 10_000_000), "is_final": True}
    bar = normalize_tcbs_bar(payload, symbol=raw_symbol, timeframe="1d")
    assert bar.symbol == raw_symbol.upper(); checks += 1
    assert bar.high_price >= max(bar.open_price, bar.low_price, bar.close_price); checks += 1
    assert bar.low_price <= min(bar.open_price, bar.high_price, bar.close_price); checks += 1
    assert bar.volume >= 0; checks += 1
    bad_payload = dict(payload, high=min(payload["open"], payload["close"]) - 1)
    try:
        normalize_tcbs_bar(bad_payload, symbol=raw_symbol, timeframe="1d")
        raise AssertionError("invalid high accepted")
    except NormalizationError:
        checks += 1
    bad_payload = dict(payload, volume=-1)
    try:
        normalize_tcbs_bar(bad_payload, symbol=raw_symbol, timeframe="1d")
        raise AssertionError("negative volume accepted")
    except NormalizationError:
        checks += 1

    # Hermitian spectrum invariants + covariance calculation
    result = analyze_hermitian_matrix([[2.0, 0.25], [0.25, 1.0]])
    assert result["is_hermitian"] and result["is_positive_semidefinite"]; checks += 1
    assert result["eigenvalues_desc"][0] >= result["eigenvalues_desc"][1] >= 0; checks += 1
    assert abs(sum(result["variance_share_desc"]) - 1.0) < 1e-8; checks += 1
    returns = [[rng.uniform(-0.05, 0.05) for _ in range(3)] for _ in range(12)]
    cov = covariance_from_returns(returns, ["FPT", "VCB", "HPG"])
    assert cov["risk_spectrum"]["is_hermitian"]; checks += 1
    assert cov["observations"] == 12; checks += 1
    try:
        analyze_hermitian_matrix([[1, 2], [0, 1]])
        raise AssertionError("non-Hermitian matrix accepted")
    except RiskMatrixError:
        checks += 1

    # SQL, OpenAPI, static assets, Git hygiene and pinned source dependency
    sql_dir = ROOT / "backend" / "sql"
    statements = _split_sql_statements((sql_dir / "001_init.sql").read_text(encoding="utf-8")); checks += 1
    assert len(statements) >= 30; checks += 1
    spec = json.loads((ROOT / "docs/openapi.json").read_text(encoding="utf-8")); checks += 1
    assert "paths" in spec and "/api/v1/health" in spec["paths"]; checks += 1
    assert (ROOT / "backend/app/static/index.html").is_file(); checks += 1
    assert (ROOT / "backend/app/static/manifest.webmanifest").is_file(); checks += 1
    assert (ROOT / ".env.example").is_file() and not (ROOT / ".env").exists(); checks += 1
    assert "vn-market-data.git@v0.3.0" in (ROOT / "requirements.txt").read_text(encoding="utf-8"); checks += 1
    assert "sync: false" in (ROOT / "render.yaml").read_text(encoding="utf-8"); checks += 1
    repo_guide = (ROOT / "docs/GIT_PRIVATE_REPO_SETUP_VI.md").read_text(encoding="utf-8")
    assert "git clone --branch main" in repo_guide; checks += 1
    return {"worker": worker_id, "assertions": checks, "status": "passed"}

def main():
    start = time.perf_counter()
    results = []
    with ThreadPoolExecutor(max_workers=N_WORKERS, thread_name_prefix="sv-crosscheck") as pool:
        futures = [pool.submit(run_one, i) for i in range(N_WORKERS)]
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda r: r["worker"])
    elapsed = time.perf_counter() - start
    report = {
        "test": "100-way parallel cross-check",
        "workers_requested": N_WORKERS,
        "workers_completed": len(results),
        "successful_jobs": sum(r["status"] == "passed" for r in results),
        "failed_jobs": sum(r["status"] != "passed" for r in results),
        "assertions_total": sum(r["assertions"] for r in results),
        "elapsed_seconds": round(elapsed, 3),
        "network_requests_made": 0,
        "postgresql_production_tested": False,
        "live_public_sync_confirmed": False,
        "result": "PASS" if len(results) == N_WORKERS else "FAIL",
        "jobs": results,
    }
    (ROOT / "docs/QA_PARALLEL_100_RUNS.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    lines = [
        "StockVision HOSE Web — Production pack parallel cross-check report",
        f"Concurrent worker jobs: {report['workers_completed']}/{N_WORKERS}",
        f"Successful jobs: {report['successful_jobs']}",
        f"Failed jobs: {report['failed_jobs']}",
        f"Assertions: {report['assertions_total']}",
        f"Elapsed seconds: {report['elapsed_seconds']}",
        "External network requests: 0 (offline test by design)",
        "Production PostgreSQL: not tested (no server credentials/network access)",
        "Live upstream synchronization: NOT CONFIRMED",
        f"Result: {report['result']}",
    ]
    (ROOT / "docs/QA_PARALLEL_100_RUNS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    if report["failed_jobs"]:
        raise SystemExit(1)

if __name__ == "__main__":
    main()

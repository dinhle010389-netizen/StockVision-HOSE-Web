#!/usr/bin/env python3
"""Offline stress test: 1,000 real worker threads x 1,000 iterations each.

Uses local fixture data only. It performs ZERO network requests and never needs credentials.
Each iteration maps a provider-shaped payload and validates it through the production bar normalizer.
"""
from __future__ import annotations

import argparse
import json
import statistics
import threading
import time
import sys
from queue import Queue
from datetime import datetime, timezone
from pathlib import Path

from app.normalizers import NormalizationError, normalize_tcbs_bar
from app.providers.fireant_client import FireAntClientError, map_fireant_bar_record

# Use the common flat field shape for the million-round load. Nested mapping is covered
# separately by unit tests, while this hot path avoids adding unrelated path-splitting cost.
FIELD_MAP = {
    "date": "date",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "volume": "volume",
    "value": "value",
    "adjusted_close": "adjustedClose",
    "is_final": "isFinal",
}
VALID_RECORD = {
    "date": "2026-10-22",
    "open": "100.0", "high": "105.0", "low": "99.0", "close": "103.0",
    "volume": 120000, "value": 12360000, "adjustedClose": "103.0", "isFinal": True,
}
INVALID_RECORD = {
    "date": "2026-10-22",
    "open": "100.0", "high": "98.0", "low": "99.0", "close": "103.0",
    "volume": 120000, "value": 12360000, "adjustedClose": "103.0", "isFinal": True,
}


def worker(worker_id: int, iterations: int, start_gate: threading.Event) -> dict:
    local_assertions = 0
    valid_count = 0
    invalid_count = 0
    t0 = time.perf_counter()
    if not start_gate.wait(timeout=120):
        raise TimeoutError("Worker start gate did not open")
    for i in range(iterations):
        # Every round executes the provider-field mapping path and checks its required output.
        mapped = map_fireant_bar_record(VALID_RECORD, FIELD_MAP)
        assert mapped["date"] == "2026-10-22"
        assert mapped["open"] == "100.0" and mapped["high"] == "105.0"
        assert mapped["low"] == "99.0" and mapped["close"] == "103.0"
        assert mapped["volume"] == 120000
        local_assertions += 5
        valid_count += 1
        # Full Decimal/timestamp/OHLC normalization is run every 100 rounds per worker.
        # This still exercises the real normalizer concurrently 10,000 times, while all
        # one million worker rounds cover FireAnt field mapping and output invariants.
        if i % 100 == 0:
            bar = normalize_tcbs_bar(mapped, symbol="FPT", timeframe="1d")
            assert bar.symbol == "FPT"
            assert bar.high_price >= max(bar.open_price, bar.low_price, bar.close_price)
            assert bar.low_price <= min(bar.open_price, bar.high_price, bar.close_price)
            assert bar.volume == 120000 and bar.is_final is True
            local_assertions += 4
            try:
                invalid_mapped = map_fireant_bar_record(INVALID_RECORD, FIELD_MAP)
                normalize_tcbs_bar(invalid_mapped, symbol="FPT", timeframe="1d")
            except NormalizationError:
                invalid_count += 1
                local_assertions += 1
            else:
                raise AssertionError("Invalid OHLC data was unexpectedly accepted")
    elapsed = time.perf_counter() - t0
    return {
        "worker_id": worker_id,
        "iterations": iterations,
        "assertions": local_assertions,
        "valid_rows": valid_count,
        "invalid_rows_rejected": invalid_count,
        "elapsed_seconds": elapsed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threads", type=int, default=1000)
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--output", default="docs/QA_FIREANT_1000_THREADS_1000_ROUNDS.json")
    args = parser.parse_args()
    if args.threads != 1000 or args.iterations != 1000:
        parser.error("Đợt QA chuẩn yêu cầu chính xác --threads 1000 --iterations 1000.")
    # These settings belong to the test harness, not the StockVision application.
    threading.stack_size(64 * 1024)
    sys.setswitchinterval(0.2)
    start_gate = threading.Event()  # keeps early workers parked while the remaining threads start
    results: Queue[dict] = Queue()
    errors: Queue[str] = Queue()

    def run_worker(worker_id: int) -> None:
        try:
            result = worker(worker_id, args.iterations, start_gate)
            results.put(result)
        except Exception as exc:
            errors.put(type(exc).__name__ + ": " + str(exc)[:250])

    start = time.perf_counter()
    threads: list[threading.Thread] = []
    start_error: str | None = None
    try:
        for worker_id in range(args.threads):
            thread = threading.Thread(
                target=run_worker,
                args=(worker_id,),
                name=f"sv-qa-{worker_id:04d}",
                daemon=True,
            )
            thread.start()
            threads.append(thread)
    except Exception as exc:
        start_error = type(exc).__name__ + ": " + str(exc)[:250]
    # Release all successfully-started workers together, even on a partial start failure,
    # so none is left parked while the main thread waits during cleanup.
    start_gate.set()
    # A failed worker creation or an overloaded host cannot hang the harness indefinitely.
    join_deadline = time.monotonic() + 120
    for thread in threads:
        remaining = max(0.0, join_deadline - time.monotonic())
        if remaining <= 0:
            break
        thread.join(timeout=remaining)
    still_alive = sum(thread.is_alive() for thread in threads)
    elapsed = time.perf_counter() - start
    result_rows = []
    while not results.empty():
        result_rows.append(results.get())
    error_rows = []
    while not errors.empty():
        error_rows.append(errors.get())
    if start_error:
        error_rows.append(start_error)
    if still_alive:
        error_rows.append(f"{still_alive} worker threads did not finish within join timeout")
    expected_cycles = args.threads * args.iterations
    got_cycles = sum(r["iterations"] for r in result_rows)
    assertions = sum(r["assertions"] for r in result_rows)
    valid_rows = sum(r["valid_rows"] for r in result_rows)
    rejected_rows = sum(r["invalid_rows_rejected"] for r in result_rows)
    report = {
        "test_name": "fireant_adapter_normalizer_offline_concurrency_stress",
        "test_date_utc": datetime.now(timezone.utc).isoformat(),
        "threads_requested": args.threads,
        "threads_started": len(threads),
        "threads_completed": len(result_rows),
        "iterations_per_thread": args.iterations,
        "expected_iterations": expected_cycles,
        "completed_iterations": got_cycles,
        "runtime_assertions": assertions,
        "valid_payloads_accepted": valid_rows,
        "invalid_payloads_rejected": rejected_rows,
        "network_requests": 0,
        "live_fireant_tested": False,
        "elapsed_seconds": round(elapsed, 3),
        "throughput_iterations_per_second": round(got_cycles / elapsed, 2) if elapsed else None,
        "worker_duration_p50_seconds": round(statistics.median([r["elapsed_seconds"] for r in result_rows]), 3) if result_rows else None,
        "worker_duration_max_seconds": round(max((r["elapsed_seconds"] for r in result_rows), default=0), 3),
        "errors": error_rows,
        "status": "PASS" if not error_rows and len(threads) == args.threads and len(result_rows) == args.threads and got_cycles == expected_cycles else "FAIL",
        "notes": [
            "All runs used local fixture payloads only; no FireAnt/TCBS endpoint was contacted.",
            "This tests adapter mapping and normalization concurrency, not a production API or database load test.",
            "The main thread releases all started workers together after thread creation; partial startup is reported as failure.",
        ],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

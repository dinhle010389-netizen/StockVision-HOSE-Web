#!/usr/bin/env python3
"""Deterministic stress/regression harness: 100 factors x 1,000 rounds.

This validates local code against synthetic inputs and offline FastAPI routes.
It does not test a live TCBS account, a real PostgreSQL server, or Docker Engine.
"""
from __future__ import annotations

import math
import os
import random
import re
import sys
import time
import logging
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Callable, Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
# Must be set before importing the application/settings singleton.
_qa_db_path = (Path(tempfile.gettempdir()) / "stockvision_qa_stress_100k.db").resolve()
# Force an offline temporary database even if the caller has production-like env vars set.
os.environ["DATABASE_URL"] = f"sqlite:///{_qa_db_path.as_posix()}"
os.environ["DEMO_MODE"] = "true"
os.environ["AUTO_CREATE_TABLES"] = "true"
os.environ["TCBS_API_TOKEN"] = ""
os.environ["ENABLE_TCBS_STREAM"] = "false"
sys.path.insert(0, str(BACKEND))

import numpy as np
from fastapi.testclient import TestClient
from app.main import app
from app.normalizers import (
    NormalizationError,
    normalize_symbol,
    normalize_tcbs_quote,
    normalize_tcbs_bar,
    _decimal,
    _int_nonnegative,
    _timestamp,
)
from app.risk import RiskMatrixError, analyze_hermitian_matrix, covariance_from_returns
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

ROUNDS = 1000
SEED = 20261023

@dataclass
class Stats:
    factor_runs: int = 0
    assertions: int = 0
    failures: int = 0
    failure_examples: list[str] | None = None

    def __post_init__(self):
        if self.failure_examples is None:
            self.failure_examples = []

S = Stats()


def expect(condition: bool, message: str) -> None:
    S.assertions += 1
    if not condition:
        raise AssertionError(message)


def expect_raises(exc_type, fn: Callable[[], Any], message: str) -> None:
    S.assertions += 1
    try:
        fn()
    except exc_type:
        return
    except Exception as exc:
        raise AssertionError(f"{message}: raised unexpected {type(exc).__name__}: {exc}") from exc
    raise AssertionError(f"{message}: did not raise {exc_type.__name__}")


@dataclass
class Factor:
    name: str
    group: str
    fn: Callable[[random.Random, int, TestClient], None]

FACTORS: list[Factor] = []

def add(name: str, group: str, fn):
    FACTORS.append(Factor(name, group, fn))

# Factors 01-10: valid symbol normalization patterns.
valid_symbols = [
    ("FPT", "FPT"), ("vcb", "VCB"), (" hpg ", "HPG"),
    ("ssi", "SSI"), ("MWG", "MWG"), ("tcb", "TCB"),
    ("VIC", "VIC"), ("vhm", "VHM"), ("ABC.X", "ABC.X"), ("ABC-1", "ABC-1"),
]
for idx, (value, target) in enumerate(valid_symbols, 1):
    def fn(rng, i, client, value=value, target=target):
        actual = normalize_symbol(value if i % 2 else f"  {value.lower()}  ")
        expect(actual == target, f"normalize_symbol({value!r}) -> {actual!r}, expected {target!r}")
    add(f"F{idx:03d} valid symbol {value!r}", "symbol", fn)

# Factors 11-18: invalid symbols must be rejected.
invalid_symbols = ["", " ", "FPT;DROP TABLE", "A B", "A/B", "A@B", "ABCDEFGHIJK", 123]
for idx, value in enumerate(invalid_symbols, 11):
    def fn(rng, i, client, value=value):
        expect_raises(NormalizationError, lambda: normalize_symbol(value), f"invalid symbol {value!r}")
    add(f"F{idx:03d} reject invalid symbol {value!r}", "symbol", fn)

# Factors 19-23: decimal parsing, optional values and locale-like grouping.
decimal_cases = [
    ("123.45", Decimal("123.45"), False),
    ("1,234.5", Decimal("1234.5"), False),
    ("1e3", Decimal("1E+3"), False),
    (None, None, True),
    ("", None, True),
]
for idx, (value, target, optional) in enumerate(decimal_cases, 19):
    def fn(rng, i, client, value=value, target=target, optional=optional):
        actual = _decimal(value, "test_decimal", optional=optional)
        expect(actual == target, f"decimal normalization mismatch for {value!r}: {actual!r}")
    add(f"F{idx:03d} decimal valid/optional {value!r}", "numeric parsing", fn)

# Factors 24-28: non-negative integer parser, valid and invalid forms.
integer_cases = [
    ("0", 0, False), ("1,000", 1000, False), (Decimal("4"), 4, False),
    ("1.5", None, True), ("-1", None, True),
]
for idx, (value, target, invalid) in enumerate(integer_cases, 24):
    def fn(rng, i, client, value=value, target=target, invalid=invalid):
        op = lambda: _int_nonnegative(value, "test_int", optional=False)
        if invalid:
            expect_raises(NormalizationError, op, f"invalid integer {value!r}")
        else:
            expect(op() == target, f"integer normalization mismatch for {value!r}")
    add(f"F{idx:03d} nonnegative integer {value!r}", "numeric parsing", fn)

# Factors 29-33: valid timestamp forms normalize to aware UTC.
valid_timestamps = [
    "2026-10-23", "2026-10-23T10:30:00Z", "2026-10-23T17:30:00+07:00",
    1792749600, datetime(2026, 10, 23, 10, 0, tzinfo=timezone.utc),
]
for idx, value in enumerate(valid_timestamps, 29):
    def fn(rng, i, client, value=value):
        out = _timestamp(value)
        expect(out is not None and out.tzinfo is not None and out.utcoffset() == timedelta(0),
               f"timestamp not normalized to UTC: {value!r} -> {out!r}")
    add(f"F{idx:03d} timestamp valid {value!r}", "timestamps", fn)

# Factors 34-38: malformed/out-of-range timestamps are controlled validation errors.
invalid_timestamps = ["not-a-date", -1, float("nan"), float("inf"), 1e100]
for idx, value in enumerate(invalid_timestamps, 34):
    def fn(rng, i, client, value=value):
        expect_raises(NormalizationError, lambda: _timestamp(value), f"invalid timestamp {value!r}")
    add(f"F{idx:03d} reject timestamp {value!r}", "timestamps", fn)

# Factors 39-48: valid quote payload aliases and normalized invariants.
quote_alias_cases = [
    ("symbol", "matchPrice"), ("ticker", "closePrice"), ("code", "lastPrice"),
    ("symbol", "last_price"), ("ticker", "price"),
    ("code", "matchPrice"), ("symbol", "closePrice"), ("ticker", "lastPrice"),
    ("code", "last_price"), ("symbol", "price"),
]
for idx, (symkey, pricekey) in enumerate(quote_alias_cases, 39):
    def fn(rng, i, client, symkey=symkey, pricekey=pricekey):
        price = Decimal(rng.randint(10, 100000))
        payload = {symkey: "fpt", pricekey: str(price), "timeSec": str(1792700000 + i),
                   "referencePrice": str(price - 1), "totalVolume": str(rng.randint(0, 1000000)),
                   "openPrice": str(price), "highPrice": str(price + 2), "lowPrice": str(price - 2)}
        q = normalize_tcbs_quote(payload)
        expect(q.symbol == "FPT" and q.last_price == price, "quote alias normalization")
        expect(q.quote_time.tzinfo is not None and q.quote_time.utcoffset() == timedelta(0), "quote UTC timestamp")
        expect(q.high_price >= q.last_price >= q.low_price > 0, "quote OHLC invariants")
        expect(q.matched_volume is not None and q.matched_volume >= 0, "quote volume invariant")
    add(f"F{idx:03d} quote valid aliases {symkey}/{pricekey}", "quote normalization", fn)

# Factors 49-58: invalid quote payloads must be rejected.
quote_bad_cases = [
    {"symbol": "FPT"},
    {"symbol": "FPT", "matchPrice": 0},
    {"symbol": "FPT", "matchPrice": -1},
    {"symbol": "FPT;DROP", "matchPrice": 100},
    {"symbol": "FPT", "matchPrice": 100, "totalVolume": -1},
    {"symbol": "FPT", "matchPrice": 100, "totalVolume": "1.5"},
    {"symbol": "FPT", "matchPrice": 100, "totalValue": -2},
    {"symbol": "FPT", "matchPrice": 100, "openPrice": 0},
    {"symbol": "FPT", "matchPrice": 100, "lowPrice": -2},
    {"symbol": "FPT", "matchPrice": 100, "reference": -10},
]
for idx, payload in enumerate(quote_bad_cases, 49):
    def fn(rng, i, client, payload=payload):
        p = dict(payload)
        if "timeSec" not in p:
            p["timeSec"] = str(1792700000 + i)
        expect_raises(NormalizationError, lambda: normalize_tcbs_quote(p), f"invalid quote payload {payload!r}")
    add(f"F{idx:03d} reject quote payload {idx-48}", "quote normalization", fn)

# Factors 59-68: valid OHLCV bars across supported timeframes/aliases.
timeframes = ["1m", "3m", "5m", "15m", "30m", "1h", "1d", "1w", "1mo", "1d"]
bar_aliases = [
    {"open": 100, "high": 105, "low": 95, "close": 102, "volume": 10},
    {"openPrice": 100, "highPrice": 105, "lowPrice": 95, "closePrice": 102, "vol": 10},
    {"open_price": 100, "high_price": 105, "low_price": 95, "close_price": 102, "tradingVolume": 10},
]
for idx, timeframe in enumerate(timeframes, 59):
    def fn(rng, i, client, timeframe=timeframe, idx=idx):
        payload = dict(bar_aliases[(idx - 59) % len(bar_aliases)])
        payload["tradingDate"] = "2026-10-23T00:00:00Z"
        payload["valueTraded"] = str(rng.randint(0, 10_000_000))
        payload["isFinal"] = [True, False, "true", "false", 1, 0][i % 6]
        bar = normalize_tcbs_bar(payload, symbol="FPT", timeframe=timeframe)
        expect(bar.symbol == "FPT" and bar.timeframe == timeframe, "bar identity/timeframe")
        expect(bar.high_price >= max(bar.open_price, bar.close_price, bar.low_price), "bar high invariant")
        expect(bar.low_price <= min(bar.open_price, bar.close_price, bar.high_price), "bar low invariant")
        expect(bar.volume == 10 and bar.bar_end > bar.bar_start, "bar volume/time window")
        expect(bar.is_final is (payload["isFinal"] in (True, "true", 1)), "bar boolean coercion")
    add(f"F{idx:03d} valid OHLCV timeframe {timeframe}", "bar normalization", fn)

# Factors 69-78: invalid bars (timestamp, timeframe, OHLCV and boolean edges).
base_bar = {"tradingDate": "2026-10-23T00:00:00Z", "open": 100, "high": 105, "low": 95, "close": 102, "volume": 10}
bar_bad_cases = [
    ({**base_bar}, {"timeframe": "2d"}),
    ({k: v for k, v in base_bar.items() if k != "tradingDate"}, {}),
    ({**base_bar, "high": 99}, {}),
    ({**base_bar, "low": 103}, {}),
    ({**base_bar, "open": 0}, {}),
    ({**base_bar, "close": -1}, {}),
    ({**base_bar, "volume": -1}, {}),
    ({**base_bar, "volume": "1.5"}, {}),
    ({**base_bar, "bar_end": "2026-10-22T00:00:00Z"}, {}),
    ({**base_bar, "isFinal": "no"}, {}),
]
for idx, (payload, kwargs) in enumerate(bar_bad_cases, 69):
    def fn(rng, i, client, payload=payload, kwargs=kwargs, idx=idx):
        p = dict(payload)
        expect_raises(NormalizationError, lambda: normalize_tcbs_bar(p, symbol="FPT", **kwargs), f"invalid bar case {idx}")
    add(f"F{idx:03d} reject OHLCV edge case {idx-68}", "bar normalization", fn)

# Factors 79-88: PSD/Hermitian matrices with predictable invariants.
for idx in range(79, 89):
    dimension = idx - 78
    def fn(rng, i, client, dimension=dimension, idx=idx):
        if idx == 88:
            mat = np.zeros((dimension, dimension), dtype=float)
        else:
            raw = np.array([[rng.gauss(0, 1) for _ in range(min(dimension, 4))] for _ in range(dimension)])
            mat = raw @ raw.T
            if idx == 87 and dimension >= 2:
                comp = np.array([[complex(rng.gauss(0, 1), rng.gauss(0, 1)) for _ in range(min(dimension, 3))] for _ in range(dimension)])
                mat = comp @ comp.conj().T
        out = analyze_hermitian_matrix(mat.tolist())
        eig = out["eigenvalues_desc"]
        expect(out["is_hermitian"] is True and out["is_positive_semidefinite"] is True, "matrix flags")
        expect(len(eig) == dimension and all(eig[k] >= eig[k+1] - 1e-8 for k in range(len(eig)-1)), "eigenvalue order")
        expect(min(eig) >= -1e-8 and math.isfinite(out["trace"]), "PSD/trace invariant")
        share_sum = sum(out["variance_share_desc"])
        expect(abs(share_sum - (0.0 if out["trace"] <= 1e-9 else 1.0)) < 1e-6, "variance shares normalization")
    add(f"F{idx:03d} Hermitian PSD spectrum dimension {dimension}", "Hermitian risk", fn)

# Factors 89-92: invalid matrices reject safely.
invalid_matrices = [
    [[1, 2]],
    [[1, 2], [0, 1]],
    [[1, 2], [2, 1]],
    [[1, float("nan")], [float("nan"), 1]],
]
for idx, matrix in enumerate(invalid_matrices, 89):
    def fn(rng, i, client, matrix=matrix, idx=idx):
        expect_raises(RiskMatrixError, lambda: analyze_hermitian_matrix(matrix), f"invalid matrix case {idx}")
    add(f"F{idx:03d} reject invalid Hermitian matrix {idx-88}", "Hermitian risk", fn)

# Factors 93-95: covariance estimation from randomized synthetic returns.
for idx, n_symbols in zip(range(93, 96), [1, 2, 5]):
    def fn(rng, i, client, n_symbols=n_symbols, idx=idx):
        n_obs = rng.randint(3, 15)
        data = [[rng.uniform(-0.08, 0.08) for _ in range(n_symbols)] for _ in range(n_obs)]
        symbols = [f"S{j:02d}" for j in range(n_symbols)]
        out = covariance_from_returns(data, symbols)
        expect(out["observations"] == n_obs and out["symbols"] == symbols, "covariance metadata")
        expect(len(out["covariance"]) == n_symbols and all(len(row) == n_symbols for row in out["covariance"]), "covariance shape")
        expect(out["risk_spectrum"]["is_hermitian"], "covariance spectrum Hermitian")
    add(f"F{idx:03d} covariance estimated for {n_symbols} symbols", "covariance", fn)

# Factors 96-100: API and assets with TestClient; each factor executes on every round.
def api_health(rng, i, client):
    r = client.get("/api/v1/health")
    expect(r.status_code == 200, "health HTTP 200")
    b = r.json()
    expect(b.get("status") == "ok" and b.get("database") == "ok" and b.get("demo_mode") is True, "health fields")
add("F096 health API status and database", "API", api_health)

def api_overview(rng, i, client):
    r = client.get("/api/v1/market/overview")
    expect(r.status_code == 200, "overview HTTP 200")
    b = r.json()
    expect(b.get("is_demo") is True and b.get("data_mode") == "demo", "demo marker explicit")
    expect("MÔ PHỎNG" in b.get("message", "") and len(b.get("indices", [])) >= 1, "demo warning and indices")
add("F097 Market Overview demo labeling and shape", "API", api_overview)

def api_instruments_validation(rng, i, client):
    r1 = client.get("/api/v1/instruments", params={"exchange": "HOSE", "limit": rng.randint(1, 200)})
    expect(r1.status_code == 200 and isinstance(r1.json(), list), "instruments valid query")
    r2 = client.get("/api/v1/instruments", params={"exchange": "NYSE"})
    expect(r2.status_code == 422, "invalid exchange rejected")
    r3 = client.get("/api/v1/instruments", params={"limit": 201})
    expect(r3.status_code == 422, "limit above max rejected")
add("F098 instruments query validation and limits", "API", api_instruments_validation)

def api_risk_validation(rng, i, client):
    data = [[rng.uniform(-0.03, 0.03), rng.uniform(-0.03, 0.03)] for _ in range(5)]
    r1 = client.post("/api/v1/risk/hermitian", json={"symbols": ["FPT", "VCB"], "returns": data})
    expect(r1.status_code == 200 and r1.json()["risk_spectrum"]["is_hermitian"] is True, "risk valid request")
    r2 = client.post("/api/v1/risk/hermitian", json={"symbols": ["FPT", "VCB"], "returns": [[0.01], [0.02], [0.03]]})
    expect(r2.status_code == 422, "risk shape mismatch rejected")
    r3 = client.post("/api/v1/risk/hermitian", json={"symbols": ["FPT", "FPT"], "returns": [[0.01, 0.02], [0.02, 0.01], [0.0, 0.01]]})
    expect(r3.status_code == 422, "duplicate symbols rejected")
add("F099 Hermitian risk API valid and invalid payloads", "API", api_risk_validation)

def api_assets_and_docs(rng, i, client):
    page = client.get("/")
    worker = client.get("/sw.js")
    manifest = client.get("/static/manifest.webmanifest")
    schema = client.get("/openapi.json")
    expect(page.status_code == worker.status_code == manifest.status_code == schema.status_code == 200, "UI/PWA/OpenAPI assets available")
    expect("Market Overview" in page.text and "DỮ LIỆU MÔ PHỎNG" in page.text, "dashboard demo warning")
    expect(worker.headers.get("Service-Worker-Allowed") == "/", "service worker root scope")
    expect("/api/v1/risk/hermitian" in schema.text, "risk endpoint documented")
add("F100 dashboard, PWA assets and OpenAPI document", "API/assets", api_assets_and_docs)

assert len(FACTORS) == 100, f"Expected 100 test factors, got {len(FACTORS)}"

def main() -> int:
    started = time.perf_counter()
    rng = random.Random(SEED)
    with TestClient(app) as client:
        for round_idx in range(ROUNDS):
            for factor in FACTORS:
                S.factor_runs += 1
                try:
                    factor.fn(rng, round_idx, client)
                except Exception as exc:
                    S.failures += 1
                    if len(S.failure_examples) < 40:
                        S.failure_examples.append(
                            f"round={round_idx+1} factor={factor.name}: {type(exc).__name__}: {exc}"
                        )
    elapsed = time.perf_counter() - started
    print("StockVision HOSE 0.1 — 100-factor x 1,000-round offline stress test")
    print(f"seed={SEED}; factors={len(FACTORS)}; rounds={ROUNDS}; factor_runs={S.factor_runs}")
    print(f"assertions={S.assertions}; failures={S.failures}; elapsed_seconds={elapsed:.2f}")
    print("factor coverage:")
    for idx, factor in enumerate(FACTORS, 1):
        print(f"{idx:03d}. {factor.name} [{factor.group}] — {ROUNDS} rounds")
    if S.failure_examples:
        print("failure examples:")
        for item in S.failure_examples:
            print(f"- {item}")
    return 0 if S.failures == 0 and S.factor_runs == len(FACTORS) * ROUNDS else 1

if __name__ == "__main__":
    raise SystemExit(main())

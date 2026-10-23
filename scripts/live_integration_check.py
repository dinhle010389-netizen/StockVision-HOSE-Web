#!/usr/bin/env python3
"""Read-only live TCBS + real PostgreSQL integration checks for StockVision.

Required environment (set on the server, never commit or paste secrets into chat):
  DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME
  TCBS_API_TOKEN=<valid TCBS OpenAPI JWT>
Optional:
  TCBS_BASE_URL=https://openapi.tcbs.com.vn
  SV_TCBS_SYMBOL=FPT
  SV_TCBS_COUNT_BACK=5

By default, this script performs read-only checks. Pass --transactional-write-probe
only against a staging/test database to test INSERT constraints through SQLAlchemy;
the probe is rolled back and is designed not to persist market or QA rows.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env", override=False)
except Exception:
    pass

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models import DataSource, Instrument, OHLCVBar
from app.normalizers import NormalizationError, normalize_tcbs_bar, normalize_symbol
from app.providers.tcbs_client import TCBSClient, TCBSClientError

REQUIRED_TABLES = {"data_source", "instrument", "ohlcv_bar", "quote_snapshot", "index_bar"}


class IntegrationFailure(RuntimeError):
    pass


def normalize_pg_url(url: str) -> str:
    value = url.strip()
    if value.startswith("postgresql://"):
        return value.replace("postgresql://", "postgresql+psycopg://", 1)
    if value.startswith("postgres://"):
        return value.replace("postgres://", "postgresql+psycopg://", 1)
    if not value.startswith("postgresql+psycopg://"):
        raise IntegrationFailure("DATABASE_URL phải trỏ tới PostgreSQL, không dùng SQLite cho live integration.")
    return value


def pg_readiness(database_url: str) -> tuple[Any, dict[str, Any]]:
    url = normalize_pg_url(database_url)
    try:
        engine = create_engine(
            url,
            pool_pre_ping=True,
            connect_args={"options": "-csearch_path=sv,public", "connect_timeout": 8},
        )
    except Exception as exc:
        raise IntegrationFailure(f"Không khởi tạo được PostgreSQL driver ({type(exc).__name__}). Cài requirements.txt trên server.") from None

    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT version(), current_setting('server_version_num')::int AS server_version_num")).mappings().one()
            version = str(row["version"])
            if "postgresql" not in version.lower():
                raise IntegrationFailure("DATABASE_URL không kết nối tới PostgreSQL.")
            schemas = inspect(conn).get_schema_names()
            if "sv" not in schemas:
                raise IntegrationFailure("Không tìm thấy schema 'sv'. Hãy áp dụng backend/sql/001_init.sql trước khi test.")
            table_names = set(inspect(conn).get_table_names(schema="sv"))
            missing = sorted(REQUIRED_TABLES - table_names)
            if missing:
                raise IntegrationFailure("Thiếu bảng trong schema sv: " + ", ".join(missing))
            row_counts = {}
            for table in sorted(REQUIRED_TABLES):
                # Table names are from the fixed allowlist above, not user input.
                row_counts[table] = int(conn.execute(text(f'SELECT count(*) FROM sv."{table}"')).scalar_one())
            info = {
                "status": "PASS",
                "server_version": version.splitlines()[0][:120],
                "server_version_num": int(row["server_version_num"]),
                "schema": "sv",
                "required_tables": sorted(REQUIRED_TABLES),
                "table_row_counts": row_counts,
            }
        return engine, info
    except IntegrationFailure:
        engine.dispose()
        raise
    except Exception as exc:
        engine.dispose()
        raise IntegrationFailure(f"PostgreSQL connection/schema check failed ({type(exc).__name__}). Kiểm tra DATABASE_URL, firewall, TLS và quyền SELECT.") from None


async def tcbs_live_read(token: str, base_url: str, symbol: str, count_back: int) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        client = TCBSClient(token=token, base_url=base_url)
        payload = await client.fetch_daily_bars(symbol, count_back=count_back)
    except TCBSClientError as exc:
        # TCBSClientError is deliberately designed to omit token/header values.
        raise IntegrationFailure(f"TCBS REST check failed: {exc}") from None
    except Exception as exc:
        raise IntegrationFailure(f"TCBS REST check failed ({type(exc).__name__}). Không ghi token vào log.") from None

    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise IntegrationFailure("TCBS payload không có cấu trúc {ticker, data[]} như tài liệu OHLCV.")
    provider_symbol = normalize_symbol(str(payload.get("ticker") or symbol))
    requested_symbol = normalize_symbol(symbol)
    if provider_symbol != requested_symbol:
        raise IntegrationFailure(f"TCBS trả ticker={provider_symbol}, khác mã yêu cầu {requested_symbol}.")
    rows = payload["data"]
    if not rows:
        raise IntegrationFailure(f"TCBS trả 0 nến cho {requested_symbol}; thử mã khác hoặc xác minh quyền/phiên.")
    normalized = []
    rejected = []
    for index, raw in enumerate(rows[:count_back]):
        try:
            normalized.append(normalize_tcbs_bar(raw, symbol=requested_symbol, timeframe="1d"))
        except NormalizationError as exc:
            rejected.append({"row_index": index, "reason": str(exc)})
    if rejected:
        raise IntegrationFailure(f"Có {len(rejected)} payload row không qua chuẩn hóa; không ghi vào DB. Chi tiết chỉ số dòng: {rejected[:5]}")
    starts = [bar.bar_start for bar in normalized]
    if len(starts) != len(set(starts)):
        raise IntegrationFailure("Payload TCBS có tradingDate trùng lặp trong mẫu trả về.")
    info = {
        "status": "PASS",
        "provider": "TCBS OpenAPI",
        "endpoint": "/nyx/v2/stock/bars-long-term",
        "symbol": requested_symbol,
        "requested_count_back": count_back,
        "received_rows": len(rows),
        "normalized_rows": len(normalized),
        "date_min_utc": min(starts).isoformat(),
        "date_max_utc": max(starts).isoformat(),
        "sample_fields": sorted(list(rows[0].keys())) if isinstance(rows[0], dict) else [],
        "secret_logged": False,
        "raw_payload_saved": False,
    }
    return payload, info


def transactional_persistence_probe(engine: Any, symbol: str, normalized_bar: Any) -> dict[str, Any]:
    """Verify actual ORM writes/constraints on PostgreSQL while rolling back all rows."""
    probe_code = "SV_QA_TXN_" + uuid.uuid4().hex[:16].upper()
    now = normalized_bar.bar_start
    # Use a separate OHLCV timestamp so the probe won't collide with an existing bar.
    unique_start = now + timedelta(seconds=(time.time_ns() % 900) + 1)
    try:
        with engine.connect() as conn:
            outer = conn.begin()
            try:
                with Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False) as db:
                    source = DataSource(
                        code=probe_code, display_name="Temporary rolled-back live integration probe",
                        source_type="derived", base_url=None, license_status="unknown",
                        notes="QA probe; transaction is always rolled back.",
                    )
                    db.add(source)
                    db.flush()
                    instrument = Instrument(
                        symbol=symbol, exchange_code="OTHER", instrument_type="equity", currency="VND",
                        price_scale=1, is_active=True, source_id=source.source_id,
                    )
                    db.add(instrument)
                    db.flush()
                    bar = OHLCVBar(
                        instrument_id=instrument.instrument_id, source_id=source.source_id,
                        timeframe="1d", bar_start=unique_start, bar_end=unique_start + timedelta(days=1),
                        open_price=normalized_bar.open_price, high_price=normalized_bar.high_price,
                        low_price=normalized_bar.low_price, close_price=normalized_bar.close_price,
                        volume=normalized_bar.volume, value_traded=normalized_bar.value_traded,
                        adjusted_close=normalized_bar.adjusted_close, is_final=normalized_bar.is_final,
                        quality_flags=list(normalized_bar.quality_flags),
                    )
                    db.add(bar)
                    db.flush()
                    if bar.instrument_id != instrument.instrument_id or bar.source_id != source.source_id:
                        raise IntegrationFailure("ORM foreign-key linkage did not preserve IDs.")
                    db.rollback()  # Rolls back the ORM savepoint.
                outer.rollback()  # Ensures all probe rows are removed.
            except Exception:
                if outer.is_active:
                    outer.rollback()
                raise
        # Confirm the unique QA source did not persist.
        with engine.connect() as check_conn:
            count = check_conn.execute(
                text("SELECT count(*) FROM sv.data_source WHERE code = :code"), {"code": probe_code}
            ).scalar_one()
        if int(count) != 0:
            raise IntegrationFailure("Rollback probe row vẫn tồn tại; yêu cầu dừng và kiểm tra DB thủ công.")
        return {"status": "PASS", "orm_insert_constraint_check": True, "rollback_confirmed": True, "persistent_probe_rows": 0}
    except IntegrationFailure:
        raise
    except Exception as exc:
        raise IntegrationFailure(f"PostgreSQL transactional ORM probe failed ({type(exc).__name__}); mọi thao tác probe được yêu cầu rollback.") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default=os.getenv("SV_TCBS_SYMBOL", "FPT"), help="Mã TCBS read-only, mặc định FPT")
    parser.add_argument("--count-back", type=int, default=int(os.getenv("SV_TCBS_COUNT_BACK", "5")), help="Số nến daily đọc thử (1–50)")
    parser.add_argument("--transactional-write-probe", action="store_true", help="Chạy INSERT ORM trong transaction rồi rollback. Chỉ dùng trên staging/test DB.")
    parser.add_argument("--report", default="reports/live_integration_report.json", help="Đường dẫn JSON report; report không ghi token hay raw payload")
    args = parser.parse_args()

    if os.getenv("SV_RUN_LIVE_INTEGRATION") != "1":
        print("BLOCKED: Set SV_RUN_LIVE_INTEGRATION=1 to explicitly permit live external requests.", file=sys.stderr)
        return 2
    if not 1 <= args.count_back <= 50:
        parser.error("--count-back phải nằm trong khoảng 1–50 cho probe vận hành.")

    token = os.getenv("TCBS_API_TOKEN", "").strip()
    base_url = os.getenv("TCBS_BASE_URL", "https://openapi.tcbs.com.vn").rstrip("/")
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not token:
        print("BLOCKED: Missing TCBS_API_TOKEN in the server environment; token is never requested in chat or printed.", file=sys.stderr)
        return 2
    if not database_url:
        print("BLOCKED: Missing DATABASE_URL for the real PostgreSQL server.", file=sys.stderr)
        return 2

    report: dict[str, Any] = {
        "project": "StockVision HOSE",
        "suite": "live_tcbs_postgresql_integration",
        "started_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "symbol": args.symbol.upper(),
        "checks": {},
        "secret_logged": False,
        "raw_payload_saved": False,
    }
    exit_code = 0
    engine = None
    try:
        engine, db_info = pg_readiness(database_url)
        report["checks"]["postgresql"] = db_info
        payload, tcbs_info = asyncio.run(tcbs_live_read(token, base_url, args.symbol, args.count_back))
        report["checks"]["tcbs_rest_payload"] = tcbs_info
        if args.transactional_write_probe:
            first = payload["data"][0]
            normalized = normalize_tcbs_bar(first, symbol=args.symbol, timeframe="1d")
            report["checks"]["postgresql_orm_write_rollback"] = transactional_persistence_probe(engine, args.symbol.upper(), normalized)
        else:
            report["checks"]["postgresql_orm_write_rollback"] = {
                "status": "NOT_RUN", "reason": "Use --transactional-write-probe on a staging/test database to exercise ORM INSERT constraints."
            }
        report["overall_status"] = "PASS" if all(v["status"] == "PASS" for v in report["checks"].values() if isinstance(v, dict) and "status" in v) else "PARTIAL"
        report["note"] = "Live TCBS read and PostgreSQL schema/read checks were executed. The report contains no credentials or raw payload."
    except IntegrationFailure as exc:
        report["overall_status"] = "FAIL"
        report["failure"] = str(exc)
        exit_code = 1
    except Exception as exc:
        report["overall_status"] = "FAIL"
        report["failure"] = f"Unexpected integration error ({type(exc).__name__}); details omitted to avoid leaking connection secrets."
        exit_code = 1
    finally:
        if engine is not None:
            engine.dispose()
        report["finished_at_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(json.dumps(report, indent=2, ensure_ascii=False))
        print(f"Report saved to: {report_path}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

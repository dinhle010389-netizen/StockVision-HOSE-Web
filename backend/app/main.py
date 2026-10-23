from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
import asyncio
import re
import hmac
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import and_, func, select, text
from sqlalchemy.orm import Session

from .config import settings
from .db import Base, engine, get_db
from .models import DataSource, Instrument, QuoteSnapshot, IndexBar, OHLCVBar
from .fireant_sync import get_sync_status, sync_fireant_daily_bars
from .public_market_data_sync import get_public_sync_status, sync_public_market_data, public_market_data_scheduler
from .providers.public_market_data_client import PublicMarketDataClient
from .risk import RiskMatrixError, covariance_from_returns
from .providers.fireant_client import FireAntClient
from .schemas import (
    CovarianceRequest,
    CovarianceResponse,
    HealthResponse,
    InstrumentSummary,
    MarketOverviewResponse,
    Breadth,
    IndexSummary,
    StockMover,
)

logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("stockvision")
STATIC_DIR = Path(__file__).resolve().parent / "static"


def _split_sql_statements(source: str) -> list[str]:
    """Split PostgreSQL scripts without breaking semicolons in quoted text/comments."""
    statements: list[str] = []
    buf: list[str] = []
    i = 0
    single = double = line_comment = False
    block_depth = 0
    dollar_tag: str | None = None
    while i < len(source):
        if dollar_tag:
            if source.startswith(dollar_tag, i):
                buf.extend(dollar_tag)
                i += len(dollar_tag)
                dollar_tag = None
                continue
            buf.append(source[i]); i += 1; continue
        if line_comment:
            ch = source[i]; buf.append(ch); i += 1
            if ch == "\n": line_comment = False
            continue
        if block_depth:
            if source.startswith("/*", i):
                buf.extend(("/", "*")); i += 2; block_depth += 1; continue
            if source.startswith("*/", i):
                buf.extend(("*", "/")); i += 2; block_depth -= 1; continue
            buf.append(source[i]); i += 1; continue
        if single:
            ch = source[i]; buf.append(ch); i += 1
            if ch == "'":
                if i < len(source) and source[i] == "'": buf.append(source[i]); i += 1
                else: single = False
            elif ch == "\\" and i < len(source):
                buf.append(source[i]); i += 1
            continue
        if double:
            ch = source[i]; buf.append(ch); i += 1
            if ch == '"':
                if i < len(source) and source[i] == '"': buf.append(source[i]); i += 1
                else: double = False
            continue
        if source.startswith("--", i):
            buf.extend(("-", "-")); i += 2; line_comment = True; continue
        if source.startswith("/*", i):
            buf.extend(("/", "*")); i += 2; block_depth = 1; continue
        if source[i] == "'": single = True; buf.append(source[i]); i += 1; continue
        if source[i] == '"': double = True; buf.append(source[i]); i += 1; continue
        if source[i] == "$":
            match = re.match(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$", source[i:])
            if match:
                dollar_tag = match.group(0); buf.extend(dollar_tag); i += len(dollar_tag); continue
        if source[i] == ";":
            statement = "".join(buf).strip()
            if statement: statements.append(statement)
            buf.clear(); i += 1; continue
        buf.append(source[i]); i += 1
    trailing = "".join(buf).strip()
    if trailing: statements.append(trailing)
    return statements


_LOGIN_ATTEMPTS: dict[str, list[float]] = {}
_LOGIN_ATTEMPTS_LOCK = threading.Lock()
_LOGIN_WINDOW_SECONDS = 15 * 60
_LOGIN_MAX_FAILURES = 10


def _check_login_rate_limit(request: Request) -> str:
    ip_key = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _LOGIN_ATTEMPTS_LOCK:
        recent = [stamp for stamp in _LOGIN_ATTEMPTS.get(ip_key, []) if now - stamp < _LOGIN_WINDOW_SECONDS]
        _LOGIN_ATTEMPTS[ip_key] = recent
        if len(recent) >= _LOGIN_MAX_FAILURES:
            raise HTTPException(status_code=429, detail="Quá nhiều lần đăng nhập thất bại; thử lại sau 15 phút.")
    return ip_key


def _record_failed_login(ip_key: str) -> None:
    now = time.monotonic()
    with _LOGIN_ATTEMPTS_LOCK:
        recent = [stamp for stamp in _LOGIN_ATTEMPTS.get(ip_key, []) if now - stamp < _LOGIN_WINDOW_SECONDS]
        recent.append(now)
        _LOGIN_ATTEMPTS[ip_key] = recent


def _clear_failed_logins(ip_key: str) -> None:
    with _LOGIN_ATTEMPTS_LOCK:
        _LOGIN_ATTEMPTS.pop(ip_key, None)


def _bootstrap_database() -> None:
    """Initialize the idempotent MVP schema at first deployment.

    For a larger production deployment, apply reviewed migrations with a dedicated
    migration role. This preview deployment uses idempotent project SQL files.
    """
    if engine.dialect.name == "postgresql":
        sql_dir = Path(__file__).resolve().parents[1] / "sql"
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE EXTENSION IF NOT EXISTS pgcrypto")
            connection.exec_driver_sql("CREATE SCHEMA IF NOT EXISTS sv")
            connection.exec_driver_sql("SET LOCAL search_path TO sv, public")
            for filename in ("001_init.sql", "002_market_index_change_migration.sql"):
                sql_file = sql_dir / filename
                if not sql_file.is_file():
                    raise RuntimeError(f"Thiếu tệp migration bắt buộc: {filename}")
                for statement in _split_sql_statements(sql_file.read_text(encoding="utf-8")):
                    connection.exec_driver_sql(statement)
    else:
        Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.app_env.lower() == "production":
        if len(settings.app_access_password) < 12:
            raise RuntimeError("APP_ACCESS_PASSWORD phải có tối thiểu 12 ký tự trên môi trường production.")
        if settings.app_session_secret == "dev-only-change-before-deploy" or len(settings.app_session_secret) < 32:
            raise RuntimeError("APP_SESSION_SECRET phải là secret riêng được tạo cho production.")
    if settings.auto_create_tables:
        _bootstrap_database()
    sync_tasks: list[asyncio.Task] = []
    if settings.market_data_provider == "public" and settings.public_data_auto_sync_on_startup and not settings.demo_mode:
        # Non-blocking startup: public-data cache/source chain warms in the background.
        sync_tasks.append(asyncio.create_task(public_market_data_scheduler()))
    elif settings.market_data_provider == "fireant" and settings.fireant_auto_sync_on_startup:
        sync_tasks.append(asyncio.create_task(sync_fireant_daily_bars()))
    try:
        yield
    finally:
        for task in sync_tasks:
            if not task.done():
                task.cancel()
        for task in sync_tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title="StockVision HOSE API",
    version="0.5.0",
    description="Read-only market overview and risk analytics. No brokerage order routing.",
    lifespan=lifespan,
)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.app_session_secret,
    session_cookie="stockvision_session",
    same_site="lax",
    https_only=settings.app_env.lower() == "production",
    max_age=14 * 24 * 60 * 60,
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class LoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


def require_app_session(request: Request) -> None:
    """Protect market and analysis APIs when a cloud access password is configured."""
    if settings.app_access_password and not request.session.get("sv_authenticated"):
        raise HTTPException(status_code=401, detail="Cần đăng nhập StockVision để truy cập dữ liệu.")


@app.get("/api/v1/session/status", tags=["system"])
def session_status(request: Request) -> dict[str, bool]:
    access_required = bool(settings.app_access_password)
    authenticated = (not access_required) or bool(request.session.get("sv_authenticated"))
    return {"access_required": access_required, "authenticated": authenticated}


@app.post("/api/v1/session/login", tags=["system"])
def session_login(payload: LoginRequest, request: Request) -> dict[str, bool]:
    if not settings.app_access_password:
        return {"access_required": False, "authenticated": True}
    ip_key = _check_login_rate_limit(request)
    if not hmac.compare_digest(payload.password, settings.app_access_password):
        _record_failed_login(ip_key)
        raise HTTPException(status_code=401, detail="Mật khẩu StockVision không đúng.")
    _clear_failed_logins(ip_key)
    request.session["sv_authenticated"] = True
    return {"access_required": True, "authenticated": True}


@app.post("/api/v1/session/logout", tags=["system"])
def session_logout(request: Request) -> dict[str, bool]:
    request.session.clear()
    return {"authenticated": False}


DEMO_ASSETS = [
    {"symbol": "FPT", "company_name": "FPT (MÔ PHỎNG)", "last_price": 132.5, "change_value": 1.7, "change_pct": 1.30, "volume": 2_150_000, "matched_value": 282_500_000_000, "change_path": [30, 26, 27, 20, 23, 17, 13, 15, 8]},
    {"symbol": "VCB", "company_name": "Vietcombank (MÔ PHỎNG)", "last_price": 61.8, "change_value": 0.5, "change_pct": 0.82, "volume": 1_350_000, "matched_value": 83_400_000_000, "change_path": [26, 28, 24, 24, 20, 21, 15, 18, 13]},
    {"symbol": "HPG", "company_name": "Hòa Phát (MÔ PHỎNG)", "last_price": 27.4, "change_value": 0.3, "change_pct": 1.11, "volume": 12_800_000, "matched_value": 350_720_000_000, "change_path": [31, 25, 27, 23, 24, 19, 17, 11, 8]},
    {"symbol": "SSI", "company_name": "SSI (MÔ PHỎNG)", "last_price": 31.2, "change_value": 0.2, "change_pct": 0.65, "volume": 6_100_000, "matched_value": 190_320_000_000, "change_path": [29, 23, 24, 25, 20, 19, 14, 15, 11]},
    {"symbol": "MWG", "company_name": "Thế Giới Di Động (MÔ PHỎNG)", "last_price": 68.1, "change_value": -0.7, "change_pct": -1.02, "volume": 2_900_000, "matched_value": 197_490_000_000, "change_path": [9, 14, 12, 18, 15, 21, 22, 25, 30]},
    {"symbol": "TCB", "company_name": "Techcombank (MÔ PHỎNG)", "last_price": 34.7, "change_value": -0.2, "change_pct": -0.57, "volume": 5_500_000, "matched_value": 190_850_000_000, "change_path": [13, 16, 14, 20, 18, 21, 25, 27, 30]},
    {"symbol": "VIC", "company_name": "Vingroup (MÔ PHỎNG)", "last_price": 45.5, "change_value": -0.6, "change_pct": -1.30, "volume": 1_700_000, "matched_value": 77_350_000_000, "change_path": [10, 12, 16, 15, 20, 18, 25, 26, 31]},
    {"symbol": "VHM", "company_name": "Vinhomes (MÔ PHỎNG)", "last_price": 41.9, "change_value": 0.0, "change_pct": 0.0, "volume": 2_200_000, "matched_value": 92_180_000_000, "change_path": [20, 22, 18, 21, 20, 24, 22, 21, 23]},
]


def _demo_overview() -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    assets = []
    for a in DEMO_ASSETS:
        assets.append(StockMover(
            symbol=a["symbol"], company_name=a["company_name"], last_price=a["last_price"],
            change_value=a["change_value"], change_pct=a["change_pct"], volume=a["volume"],
            matched_value=a["matched_value"], updated_at=now, is_demo=True,
        ))
    winners = sorted([a for a in assets if (a.change_pct or 0) > 0], key=lambda x: x.change_pct or 0, reverse=True)
    losers = sorted([a for a in assets if (a.change_pct or 0) < 0], key=lambda x: x.change_pct or 0)
    active = sorted(assets, key=lambda x: x.matched_value or 0, reverse=True)
    return MarketOverviewResponse(
        exchange="HOSE", as_of=now, data_mode="demo", is_demo=True,
        message="DỮ LIỆU MÔ PHỎNG — chưa kết nối nguồn thị trường. Không sử dụng cho quyết định giao dịch.",
        breadth_scope="market",
        tracked_value_total=sum(float(a.matched_value or 0) for a in assets),
        freshness_seconds=0,
        breadth=Breadth(advancers=218, decliners=164, unchanged=71, observed=453, advance_decline_ratio=218 / 164),
        indices=[
            IndexSummary(symbol="VNINDEX", label="VN-INDEX", last=1284.56, change=7.92, change_pct=0.62, updated_at=now, is_demo=True),
            IndexSummary(symbol="VN30", label="VN30", last=1338.42, change=5.18, change_pct=0.39, updated_at=now, is_demo=True),
            IndexSummary(symbol="HNXINDEX", label="HNX-INDEX", last=238.71, change=-0.42, change_pct=-0.18, updated_at=now, is_demo=True),
        ],
        leaders=winners[:4], laggards=losers[:4], active_stocks=active[:8],
    ).model_dump(mode="json")


def _as_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _database_overview(db: Session) -> dict[str, Any]:
    latest_quote_keys = (
        select(
            QuoteSnapshot.instrument_id.label("instrument_id"),
            QuoteSnapshot.source_id.label("source_id"),
            func.max(QuoteSnapshot.quote_time).label("latest_quote_time"),
        )
        .group_by(QuoteSnapshot.instrument_id, QuoteSnapshot.source_id)
        .subquery()
    )
    rows = db.execute(
        select(QuoteSnapshot, Instrument, DataSource)
        .join(latest_quote_keys, and_(
            QuoteSnapshot.instrument_id == latest_quote_keys.c.instrument_id,
            QuoteSnapshot.source_id == latest_quote_keys.c.source_id,
            QuoteSnapshot.quote_time == latest_quote_keys.c.latest_quote_time,
        ))
        .join(Instrument, QuoteSnapshot.instrument_id == Instrument.instrument_id)
        .join(DataSource, QuoteSnapshot.source_id == DataSource.source_id)
        .order_by(Instrument.symbol.asc(), QuoteSnapshot.quote_time.desc())
    ).all()
    newest_by_symbol: dict[str, tuple[QuoteSnapshot, Instrument, DataSource]] = {}
    for quote, instrument, source in rows:
        if instrument.symbol not in newest_by_symbol:
            newest_by_symbol[instrument.symbol] = (quote, instrument, source)

    if not newest_by_symbol:
        # Desktop FireAnt DataFeed currently syncs daily OHLCV. Display daily closes honestly
        # when real quote snapshots are absent; never label EOD bars as realtime quotes.
        bar_rows = db.execute(
            select(OHLCVBar, Instrument, DataSource)
            .join(Instrument, OHLCVBar.instrument_id == Instrument.instrument_id)
            .join(DataSource, OHLCVBar.source_id == DataSource.source_id)
            .where(OHLCVBar.timeframe == "1d")
            .order_by(Instrument.symbol.asc(), OHLCVBar.bar_start.desc())
        ).all()
        bars_by_key: dict[tuple[str, int], list[tuple[OHLCVBar, Instrument, DataSource]]] = {}
        for bar, instrument, source in bar_rows:
            key = (instrument.symbol, source.source_id)
            group = bars_by_key.setdefault(key, [])
            if len(group) < 2:
                group.append((bar, instrument, source))
        latest_by_symbol: dict[str, list[tuple[OHLCVBar, Instrument, DataSource]]] = {}
        for group in bars_by_key.values():
            if group:
                symbol = group[0][1].symbol
                current = latest_by_symbol.get(symbol)
                if current is None or group[0][0].bar_start > current[0][0].bar_start:
                    latest_by_symbol[symbol] = group
        if latest_by_symbol:
            items: list[StockMover] = []
            latest_times: list[datetime] = []
            for group in latest_by_symbol.values():
                bar, instrument, source = group[0]
                previous = group[1][0] if len(group) > 1 else None
                close = float(bar.close_price)
                change = close - float(previous.close_price) if previous and previous.close_price else None
                pct = (change / float(previous.close_price) * 100) if change is not None and previous and previous.close_price else None
                stamp = bar.bar_start
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
                latest_times.append(stamp)
                items.append(StockMover(
                    symbol=instrument.symbol,
                    company_name=instrument.company_name,
                    last_price=close,
                    change_value=change,
                    change_pct=pct,
                    volume=bar.volume,
                    matched_value=_as_float(bar.value_traded),
                    updated_at=stamp,
                    is_demo=False,
                ))
            adv = sum(1 for item in items if (item.change_pct or 0) > 0.001)
            dec = sum(1 for item in items if (item.change_pct or 0) < -0.001)
            unchanged = len(items) - adv - dec
            as_of = max(latest_times)
            now = datetime.now(timezone.utc)
            freshness = max(0.0, (now - as_of).total_seconds())
            source_names = sorted({item[2].display_name for group in latest_by_symbol.values() for item in group[:1]})
            index_rows = db.execute(
                select(IndexBar, DataSource)
                .join(DataSource, IndexBar.source_id == DataSource.source_id)
                .where(IndexBar.timeframe == "1d")
                .order_by(IndexBar.index_code.asc(), IndexBar.bar_start.desc())
            ).all()
            index_groups: dict[tuple[str, int], list[tuple[IndexBar, DataSource]]] = {}
            for idx_bar, idx_source in index_rows:
                key = (idx_bar.index_code, idx_source.source_id)
                group = index_groups.setdefault(key, [])
                if len(group) < 2:
                    group.append((idx_bar, idx_source))
            best_by_index: dict[str, list[tuple[IndexBar, DataSource]]] = {}
            for (code, _source_id), group in index_groups.items():
                if group and (code not in best_by_index or group[0][0].bar_start > best_by_index[code][0][0].bar_start):
                    best_by_index[code] = group
            label_map = {"VNINDEX": "VN-INDEX", "VN30": "VN30", "HNXINDEX": "HNX-INDEX", "UPCOMINDEX": "UPCOM"}
            index_summaries: list[IndexSummary] = []
            for code, group in best_by_index.items():
                latest_idx = group[0][0]
                previous_idx = group[1][0] if len(group) > 1 else None
                last_value = float(latest_idx.close_value)
                change_value = last_value - float(previous_idx.close_value) if previous_idx and previous_idx.close_value else None
                change_pct = change_value / float(previous_idx.close_value) * 100 if change_value is not None and previous_idx and previous_idx.close_value else None
                stamp = latest_idx.bar_start
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
                index_summaries.append(IndexSummary(
                    symbol=code, label=label_map.get(code, code), last=last_value,
                    change=change_value, change_pct=change_pct, updated_at=stamp, is_demo=False,
                ))
            return MarketOverviewResponse(
                exchange="HOSE", as_of=as_of, data_mode="database", is_demo=False,
                message=f"Dữ liệu nến ngày/EOD từ {', '.join(source_names) if source_names else 'chuỗi nguồn đã cấu hình'}. Dữ liệu có thể trễ; không mặc định realtime.",
                breadth_scope="tracked_universe", tracked_value_total=sum(float(item.matched_value or 0) for item in items) or None,
                breadth=Breadth(advancers=adv, decliners=dec, unchanged=unchanged, observed=len(items), advance_decline_ratio=adv / dec if dec else None),
                indices=sorted(index_summaries, key=lambda x: x.symbol), leaders=sorted([item for item in items if (item.change_pct or 0) >= 0], key=lambda item: item.change_pct or 0, reverse=True)[:6],
                laggards=sorted([item for item in items if (item.change_pct or 0) < 0], key=lambda item: item.change_pct or 0)[:6],
                active_stocks=sorted(items, key=lambda item: item.matched_value or 0, reverse=True), freshness_seconds=freshness,
            ).model_dump(mode="json")
        now = datetime.now(timezone.utc)
        return MarketOverviewResponse(
            exchange="HOSE", as_of=now, data_mode="empty", is_demo=False,
            message="Chưa có quote hoặc nến OHLCV thật. Hãy cấu hình nhà cung cấp, cài chuỗi nguồn công khai hoặc chạy đồng bộ dữ liệu.",
            breadth_scope="none", tracked_value_total=None,
            breadth=Breadth(), indices=[], leaders=[], laggards=[], active_stocks=[], freshness_seconds=None,
        ).model_dump(mode="json")

    items: list[StockMover] = []
    all_demo = True
    latest_times: list[datetime] = []
    for quote, instrument, source in newest_by_symbol.values():
        is_demo = source.code.upper().startswith("DEMO") or "DEMO" in (quote.quality_flags or [])
        all_demo = all_demo and is_demo
        quote_time = quote.quote_time
        latest_times.append(quote_time)
        items.append(StockMover(
            symbol=instrument.symbol,
            company_name=instrument.company_name,
            last_price=_as_float(quote.last_price),
            change_value=_as_float(quote.change_value),
            change_pct=_as_float(quote.change_pct),
            volume=quote.matched_volume,
            matched_value=_as_float(quote.matched_value),
            updated_at=quote_time,
            is_demo=is_demo,
        ))
    adv = sum(1 for x in items if (x.change_pct or 0) > 0.001)
    dec = sum(1 for x in items if (x.change_pct or 0) < -0.001)
    unchanged = len(items) - adv - dec
    ratio = adv / dec if dec else (float("inf") if adv else None)
    ratio = ratio if ratio is None or ratio != float("inf") else None
    as_of = max(latest_times)
    now = datetime.now(timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    freshness = max(0.0, (now - as_of).total_seconds())

    # Read latest two bars per index to derive change percentage; historical/daily data may be delayed.
    ranked_index_keys = (
        select(
            IndexBar.index_code.label("index_code"),
            IndexBar.source_id.label("source_id"),
            IndexBar.timeframe.label("timeframe"),
            IndexBar.bar_start.label("bar_start"),
            func.row_number().over(
                partition_by=(IndexBar.index_code, IndexBar.source_id, IndexBar.timeframe),
                order_by=IndexBar.bar_start.desc(),
            ).label("row_number"),
        )
        .where(IndexBar.timeframe.in_(["1m", "1d"]))
        .subquery()
    )
    index_rows = db.execute(
        select(IndexBar, DataSource)
        .join(ranked_index_keys, and_(
            IndexBar.index_code == ranked_index_keys.c.index_code,
            IndexBar.source_id == ranked_index_keys.c.source_id,
            IndexBar.timeframe == ranked_index_keys.c.timeframe,
            IndexBar.bar_start == ranked_index_keys.c.bar_start,
        ))
        .join(DataSource, IndexBar.source_id == DataSource.source_id)
        .where(ranked_index_keys.c.row_number <= 2)
        .order_by(IndexBar.index_code.asc(), IndexBar.bar_start.desc())
    ).all()
    grouped: dict[str, list[tuple[IndexBar, DataSource]]] = {}
    for row in index_rows:
        if len(grouped.setdefault(row[0].index_code, [])) < 2:
            grouped[row[0].index_code].append(row)
    breadth_scope = "tracked_universe"
    # If TCBS index channel 8 has full VN-INDEX breadth, prefer it over the monitored-symbol sample.
    vnindex_rows = grouped.get("VNINDEX", [])
    if vnindex_rows:
        breadth_row = vnindex_rows[0][0]
        if breadth_row.advancers is not None and breadth_row.decliners is not None and breadth_row.unchanged_count is not None:
            adv = int(breadth_row.advancers)
            dec = int(breadth_row.decliners)
            unchanged = int(breadth_row.unchanged_count)
            ratio = adv / dec if dec else None
            breadth_scope = "market"
    index_summaries: list[IndexSummary] = []
    label_map = {"VNINDEX": "VN-INDEX", "VN30": "VN30", "HNXINDEX": "HNX-INDEX", "UPCOMINDEX": "UPCOM"}
    for code, vals in grouped.items():
        latest = vals[0][0]
        previous = vals[1][0] if len(vals) > 1 else None
        change = _as_float(latest.change_value)
        pct = _as_float(latest.change_pct)
        if change is None and previous:
            change = float(latest.close_value) - float(previous.close_value)
        if pct is None and previous and previous.close_value:
            pct = (change / float(previous.close_value) * 100) if change is not None else None
        index_summaries.append(IndexSummary(
            symbol=code, label=label_map.get(code, code), last=float(latest.close_value), change=change,
            change_pct=pct, updated_at=latest.bar_start,
            is_demo=vals[0][1].code.upper().startswith("DEMO"),
        ))

    leaders = sorted([x for x in items if (x.change_pct or 0) >= 0], key=lambda x: x.change_pct or 0, reverse=True)[:6]
    laggards = sorted([x for x in items if (x.change_pct or 0) < 0], key=lambda x: x.change_pct or 0)[:6]
    active = sorted(items, key=lambda x: x.matched_value or 0, reverse=True)[:12]
    return MarketOverviewResponse(
        exchange="HOSE", as_of=as_of, data_mode="demo" if all_demo else "database", is_demo=all_demo,
        message="Dữ liệu mẫu mô phỏng." if all_demo else "Dữ liệu lấy từ kho nội bộ; hãy kiểm tra trạng thái giấy phép, độ trễ và nguồn gốc từng bản ghi.",
        breadth_scope=breadth_scope,
        tracked_value_total=sum(float(x.matched_value or 0) for x in items),
        freshness_seconds=freshness, breadth=Breadth(advancers=adv, decliners=dec, unchanged=unchanged, observed=(adv + dec + unchanged if breadth_scope == "market" else len(items)), advance_decline_ratio=adv / dec if dec else None),
        indices=index_summaries, leaders=leaders, laggards=laggards, active_stocks=active,
    ).model_dump(mode="json")


@app.get("/", include_in_schema=False)
def ui() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/sw.js", include_in_schema=False)
def service_worker() -> FileResponse:
    return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript", headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest() -> FileResponse:
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json", headers={"Cache-Control": "no-cache"})


@app.get("/apple-touch-icon.png", include_in_schema=False)
def apple_touch_icon() -> FileResponse:
    return FileResponse(STATIC_DIR / "apple-touch-icon.png", media_type="image/png")


@app.get("/icon-192.png", include_in_schema=False)
def icon_192() -> FileResponse:
    return FileResponse(STATIC_DIR / "icon-192.png", media_type="image/png")


@app.get("/icon-512.png", include_in_schema=False)
def icon_512() -> FileResponse:
    return FileResponse(STATIC_DIR / "icon-512.png", media_type="image/png")


@app.get("/icon.svg", include_in_schema=False)
def icon_svg() -> FileResponse:
    return FileResponse(STATIC_DIR / "icon.svg", media_type="image/svg+xml")


@app.get("/api/v1/health", response_model=HealthResponse, tags=["system"])
def health(db: Session = Depends(get_db)) -> HealthResponse:
    database_status = "ok"
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        logger.exception("Database health check failed")
        database_status = "unavailable"
    status = "ok" if database_status == "ok" else "degraded"
    return HealthResponse(
        status=status, database=database_status, demo_mode=settings.demo_mode,
        tcbs_stream_enabled=settings.enable_tcbs_stream, timestamp=datetime.now(timezone.utc),
    )


@app.get("/api/v1/providers/status", tags=["system"])
def providers_status(_: None = Depends(require_app_session)) -> dict[str, Any]:
    """Return provider readiness without exposing credentials or raw configuration."""
    fireant = FireAntClient.readiness()
    public_data = PublicMarketDataClient.readiness()
    # Report observed sync telemetry separately from package readiness. A successful
    # import/cache hit alone is not proof of a live upstream request.
    public_sync = get_public_sync_status()
    public_data.update({
        "last_sync_status": public_sync.get("status"),
        "last_sync_completed_at": public_sync.get("completed_at"),
        "last_sync_bars_saved": int(public_sync.get("bars_saved", 0) or 0),
        "last_sync_bars_rejected": int(public_sync.get("bars_rejected", 0) or 0),
        "last_sync_upstream_sources": list(public_sync.get("upstream_sources", [])),
        "network_tested": bool(public_sync.get("upstream_sources")) and public_sync.get("status") in {"success", "partial"},
    })
    return {
        "active_provider": settings.market_data_provider if settings.market_data_provider in {"tcbs", "fireant", "public"} else "invalid",
        "providers": {
            "public": public_data,
            "tcbs": {
                "credential_present": bool(settings.tcbs_api_token),
                "base_url_https": settings.tcbs_base_url.startswith("https://"),
                "network_tested": False,
            },
            "fireant": fireant,
        },
        "data_policy": {
            "demo_mode": settings.demo_mode,
            "public_data_is_redistributable": False,
            "note": "Quyền lưu trữ và tái phân phối dữ liệu phải theo điều khoản từng nguồn; public endpoint không đồng nghĩa quyền tái phân phối.",
        },
    }


@app.get("/api/v1/providers/fireant/sync-status", tags=["system"])
def fireant_sync_status(_: None = Depends(require_app_session)) -> dict[str, Any]:
    """Expose safe startup/manual FireAnt sync status without credentials or raw vendor payload."""
    return get_sync_status()


@app.post("/api/v1/providers/fireant/sync", tags=["system"])
async def fireant_sync_now(_: None = Depends(require_app_session)) -> dict[str, Any]:
    """Manually refresh FireAnt daily bars; disabled unless authorized endpoint is configured."""
    return await sync_fireant_daily_bars(manual=True)


@app.get("/api/v1/providers/public/sync-status", tags=["system"])
def public_sync_status(_: None = Depends(require_app_session)) -> dict[str, Any]:
    """Safe state for public multi-source ingestion; no upstream payloads are exposed."""
    return get_public_sync_status()


@app.post("/api/v1/providers/public/sync", tags=["system"])
async def public_sync_now(_: None = Depends(require_app_session)) -> dict[str, Any]:
    """Manually run a cache-first historical/EOD sync through enabled public sources."""
    if settings.market_data_provider != "public":
        raise HTTPException(status_code=409, detail="MARKET_DATA_PROVIDER chưa chọn public.")
    if settings.demo_mode:
        raise HTTPException(
            status_code=409,
            detail="Đang ở DEMO_MODE. Đặt DEMO_MODE=false trong cấu hình và khởi động lại để lấy/lưu dữ liệu công khai thật.",
        )
    return await sync_public_market_data(manual=True)


@app.get("/api/v1/market/overview", response_model=MarketOverviewResponse, tags=["market"])
def market_overview(db: Session = Depends(get_db), _: None = Depends(require_app_session)) -> dict[str, Any]:
    if settings.demo_mode:
        return _demo_overview()
    try:
        return _database_overview(db)
    except Exception:
        logger.exception("Failed to build market overview")
        raise HTTPException(status_code=503, detail="Không thể đọc dữ liệu thị trường từ kho dữ liệu.")


@app.get("/api/v1/instruments", response_model=list[InstrumentSummary], tags=["market"])
def list_instruments(
    q: str | None = Query(default=None, max_length=80),
    exchange: str = Query(default="HOSE", pattern="^(HOSE|HNX|UPCOM)$"),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: None = Depends(require_app_session),
) -> list[InstrumentSummary]:
    stmt = select(Instrument).where(Instrument.exchange_code == exchange, Instrument.is_active.is_(True))
    if q:
        stmt = stmt.where(Instrument.symbol.ilike(f"%{q.strip().upper()}%"))
    stmt = stmt.order_by(Instrument.symbol).limit(limit)
    instruments = db.scalars(stmt).all()
    if settings.demo_mode and not instruments:
        return [InstrumentSummary(symbol=a["symbol"], exchange_code="HOSE", company_name=a["company_name"], currency="VND") for a in DEMO_ASSETS if not q or q.strip().upper() in a["symbol"]][:limit]
    return [InstrumentSummary(
        symbol=i.symbol, exchange_code=i.exchange_code, company_name=i.company_name,
        sector_code=i.sector_code, currency=i.currency, is_active=i.is_active,
    ) for i in instruments]


@app.post("/api/v1/risk/hermitian", response_model=CovarianceResponse, tags=["risk"])
def hermitian_risk(request: CovarianceRequest, _: None = Depends(require_app_session)) -> CovarianceResponse:
    try:
        result = covariance_from_returns(request.returns, request.symbols)
    except RiskMatrixError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Hermitian risk analytics failed")
        raise HTTPException(status_code=422, detail="Ma trận lợi suất không hợp lệ.") from exc
    return CovarianceResponse(**result)

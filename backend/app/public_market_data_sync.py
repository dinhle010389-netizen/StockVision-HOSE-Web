"""Background/manual EOD sync using the public multi-source adapter."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal
from .models import DataSource, Instrument, OHLCVBar, IndexBar
from .normalizers import NormalizationError, normalize_symbol, normalize_tcbs_bar
from .providers.public_market_data_client import PublicMarketDataClient, PublicMarketDataError

logger = logging.getLogger("stockvision.public_data_sync")

_STATE: dict[str, Any] = {
    "status": "waiting",
    "message": "Đang chờ đồng bộ dữ liệu công khai.",
    "started_at": None,
    "completed_at": None,
    "symbols_requested": [],
    "symbols_succeeded": [],
    "bars_received": 0,
    "bars_saved": 0,
    "bars_rejected": 0,
    "indexes_saved": 0,
    "upstream_sources": [],
    "errors": [],
}
_LOCK = asyncio.Lock()


def get_public_sync_status() -> dict[str, Any]:
    return dict(_STATE, errors=list(_STATE.get("errors", [])),
                upstream_sources=list(_STATE.get("upstream_sources", [])),
                symbols_requested=list(_STATE.get("symbols_requested", [])),
                symbols_succeeded=list(_STATE.get("symbols_succeeded", [])))


def _get_or_create_source(db: Session, code: str, upstream_sources: list[str]) -> DataSource:
    allowed = {"DNSE", "VIETCAP", "VCI", "VNDIRECT", "CAFEF", "KBS", "SSI"}
    safe_code = code if code in allowed else "PUBLIC_MULTI"
    row = db.scalar(select(DataSource).where(DataSource.code == safe_code))
    display = {
        "DNSE": "DNSE public market data",
        "VIETCAP": "Vietcap public market data",
        "VCI": "VCI public market data",
        "VNDIRECT": "VNDirect public market data",
        "CAFEF": "CafeF public market data",
        "KBS": "KBS public market data",
        "SSI": "SSI market data",
        "PUBLIC_MULTI": "Public multi-source cache/chain",
    }.get(safe_code, "Public multi-source cache/chain")
    note = (
        "Nguồn được ghi nhận từ thư viện vn-market-data; cache hit hoặc fallback chain có thể không xác định được nguồn của từng nến. "
        "Quyền sử dụng/lưu trữ/tái phân phối phải tuân theo điều khoản nguồn gốc. "
        f"Nguồn gọi quan sát được trong lượt này: {', '.join(upstream_sources) if upstream_sources else 'không xác định (có thể cache hit)'} ."
    )
    if row:
        row.display_name = display
        row.source_type = "public_market_data_chain"
        row.license_status = "review_required"
        row.notes = note
        return row
    row = DataSource(
        code=safe_code,
        display_name=display,
        source_type="public_market_data_chain",
        base_url=None,
        license_status="review_required",
        notes=note,
    )
    db.add(row)
    db.flush()
    return row


def _get_or_create_instrument(db: Session, symbol: str, source_id: int) -> Instrument:
    inst = db.scalar(
        select(Instrument).where(
            Instrument.symbol == symbol,
            Instrument.exchange_code == "HOSE",
            Instrument.is_active.is_(True),
        ).order_by(Instrument.instrument_id.asc()).limit(1)
    )
    if inst:
        if inst.source_id is None:
            inst.source_id = source_id
        return inst
    inst = Instrument(
        symbol=symbol, exchange_code="HOSE", instrument_type="equity",
        company_name=symbol, currency="VND", price_scale=1, lot_size=100,
        is_active=True, source_id=source_id,
    )
    db.add(inst)
    db.flush()
    return inst


def _db_datetime(db: Session, value: datetime) -> datetime:
    """Use UTC-naive datetimes for SQLite and timezone-aware UTC for PostgreSQL.

    SQLite's DateTime storage does not preserve tzinfo. Normalizing before INSERT
    also avoids SQLAlchemy insertmanyvalues sentinel mismatches on composite keys.
    """
    bind = db.get_bind()
    if bind.dialect.name == "sqlite" and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.astimezone(timezone.utc) if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _upsert_bar(db: Session, instrument_id: int, source_id: int, normalized) -> None:
    key = {
        "instrument_id": instrument_id,
        "source_id": source_id,
        "timeframe": "1d",
        "bar_start": _db_datetime(db, normalized.bar_start),
    }
    bar = db.get(OHLCVBar, key)
    values = dict(
        bar_end=_db_datetime(db, normalized.bar_end), open_price=normalized.open_price,
        high_price=normalized.high_price, low_price=normalized.low_price,
        close_price=normalized.close_price, volume=normalized.volume,
        value_traded=normalized.value_traded, adjusted_close=normalized.adjusted_close,
        is_final=normalized.is_final, quality_flags=list(normalized.quality_flags),
    )
    if bar is None:
        db.add(OHLCVBar(**key, **values))
    else:
        for name, value in values.items():
            setattr(bar, name, value)


async def _sync_index_rows(client: PublicMarketDataClient, symbols: list[str], lookback_days: int) -> tuple[int, list[str]]:
    """Best-effort index history sync. Each index transaction is isolated."""
    saved = 0
    errors: list[str] = []
    for index_code in symbols:
        try:
            payload = await client.fetch_daily_index(index_code, lookback_days=lookback_days)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{index_code}:index_unavailable:{type(exc).__name__}")
            continue
        rows = payload.get("data", [])
        db = SessionLocal()
        try:
            source = _get_or_create_source(db, "PUBLIC_MULTI", [])
            for raw in rows:
                try:
                    norm = normalize_tcbs_bar(raw, symbol=index_code, timeframe="1d")
                except (NormalizationError, ValueError, TypeError):
                    continue
                key = {"index_code": index_code, "source_id": source.source_id,
                       "timeframe": "1d", "bar_start": _db_datetime(db, norm.bar_start)}
                bar = db.get(IndexBar, key)
                values = dict(
                    bar_end=_db_datetime(db, norm.bar_end), open_value=norm.open_price, high_value=norm.high_price,
                    low_value=norm.low_price, close_value=norm.close_price, volume=norm.volume,
                    change_value=None, change_pct=None,
                )
                if bar is None:
                    db.add(IndexBar(**key, **values))
                else:
                    for field, value in values.items():
                        setattr(bar, field, value)
                saved += 1
            db.commit()
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.exception("Public index sync failed for %s (%s)", index_code, type(exc).__name__)
            errors.append(f"{index_code}:index_store_error")
        finally:
            db.close()
    return saved, errors


async def sync_public_market_data(*, manual: bool = False) -> dict[str, Any]:
    async with _LOCK:
        readiness = PublicMarketDataClient.readiness()
        if not readiness.get("ready"):
            _STATE.update(
                status="not_installed",
                message="Chưa cài hoặc chưa nạp được vn-market-data. Không gửi request mạng; cài gói theo requirements-public-data.txt để bật nguồn đa nguồn.",
                started_at=None, completed_at=datetime.now(timezone.utc).isoformat(),
                symbols_requested=[], symbols_succeeded=[], bars_received=0, bars_saved=0,
                bars_rejected=0, indexes_saved=0, upstream_sources=[], errors=[],
            )
            return get_public_sync_status()

        symbols: list[str] = []
        for raw in settings.public_data_symbols:
            try:
                safe = normalize_symbol(raw)
            except (NormalizationError, TypeError):
                continue
            if safe not in symbols:
                symbols.append(safe)
        if not symbols:
            _STATE.update(status="error", message="PUBLIC_DATA_SYMBOLS không có mã hợp lệ.",
                          completed_at=datetime.now(timezone.utc).isoformat(), errors=["no_valid_symbols"])
            return get_public_sync_status()

        _STATE.update(
            status="running", message="Đang lấy nến ngày qua chuỗi nguồn công khai…",
            started_at=datetime.now(timezone.utc).isoformat(), completed_at=None,
            symbols_requested=symbols, symbols_succeeded=[], bars_received=0, bars_saved=0,
            bars_rejected=0, indexes_saved=0, upstream_sources=[], errors=[],
        )
        client = PublicMarketDataClient()
        succeeded: list[str] = []
        errors: list[str] = []
        upstream: list[str] = []
        received_total = saved_total = rejected_total = 0
        for symbol in symbols:
            db = SessionLocal()
            try:
                payload = await client.fetch_daily_bars(symbol, lookback_days=settings.public_data_lookback_days)
                rows = payload.get("data", [])
                received_total += len(rows)
                for name in payload.get("upstream_sources", []):
                    if name not in upstream:
                        upstream.append(name)
                symbol_saved = 0
                # Prefer a source declared on the individual row. If attribution is
                # unavailable due a cache hit/fallback, use PUBLIC_MULTI transparently.
                for raw in rows:
                    row_source = raw.get("source") if isinstance(raw, dict) else None
                    # Request-level source calls describe only network calls made
                    # during this read; cached historical rows may have come from
                    # another source. Attribute per row only when the payload does so.
                    source_code = row_source if row_source in {"DNSE", "VIETCAP", "VCI", "VNDIRECT", "CAFEF", "KBS", "SSI"} else "PUBLIC_MULTI"
                    try:
                        normalized = normalize_tcbs_bar(raw, symbol=symbol, timeframe="1d")
                    except (NormalizationError, ValueError, TypeError):
                        rejected_total += 1
                        continue
                    source = _get_or_create_source(db, source_code, payload.get("upstream_sources", []))
                    inst = _get_or_create_instrument(db, symbol, source.source_id)
                    _upsert_bar(db, inst.instrument_id, source.source_id, normalized)
                    symbol_saved += 1
                db.commit()
                if rows and symbol_saved:
                    succeeded.append(symbol)
                elif not rows:
                    errors.append(f"{symbol}:empty_response")
                else:
                    errors.append(f"{symbol}:all_bars_rejected")
                saved_total += symbol_saved
            except PublicMarketDataError as exc:
                db.rollback()
                errors.append(f"{symbol}:{str(exc)}")
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                logger.exception("Public data sync failed for %s (%s)", symbol, type(exc).__name__)
                errors.append(f"{symbol}:internal_error")
            finally:
                db.close()

        # Index candle sync is best-effort. Do not misreport index bars as equity bars.
        index_count, index_errors = await _sync_index_rows(
            client, list(settings.public_data_index_symbols), settings.public_data_lookback_days
        ) if settings.public_data_index_symbols else (0, [])
        errors.extend(index_errors)

        status = "success" if len(succeeded) == len(symbols) and not errors and rejected_total == 0 else (
            "partial" if succeeded else "error"
        )
        summary = (
            f"Đã lưu {saved_total} nến ngày cho {len(succeeded)}/{len(symbols)} mã; "
            f"{index_count} nến chỉ số. Đây là dữ liệu lịch sử/EOD; không mặc định là realtime."
        )
        _STATE.update(
            status=status, message=summary, completed_at=datetime.now(timezone.utc).isoformat(),
            symbols_succeeded=succeeded, bars_received=received_total, bars_saved=saved_total,
            bars_rejected=rejected_total, indexes_saved=index_count,
            upstream_sources=upstream, errors=errors[:30],
        )
        return get_public_sync_status()


async def public_market_data_scheduler() -> None:
    """Sync once on startup, then periodically refresh while the backend is running."""
    while True:
        try:
            await sync_public_market_data(manual=False)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # keep service alive even if a provider call fails
            logger.exception("Public data scheduler error (%s)", type(exc).__name__)
        interval = max(5, min(1440, int(settings.public_data_sync_interval_minutes)))
        await asyncio.sleep(interval * 60)

"""Startup/manual FireAnt daily-bar sync for the Windows desktop build.

Only calls the user-configured, HTTPS endpoint that FireAnt authorized. If access,
endpoint, token or the field map is missing, no network request is made.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal
from .models import DataSource, Instrument, OHLCVBar
from .normalizers import NormalizationError, normalize_tcbs_bar, normalize_symbol
from .providers.fireant_client import FireAntClient, FireAntClientError

logger = logging.getLogger("stockvision.fireant_sync")

_STATE: dict[str, Any] = {
    "status": "waiting",
    "message": "Đang chờ khởi tạo StockVision.",
    "started_at": None,
    "completed_at": None,
    "symbols_requested": [],
    "symbols_succeeded": [],
    "bars_received": 0,
    "bars_saved": 0,
    "bars_rejected": 0,
    "errors": [],
}
_LOCK = asyncio.Lock()


def get_sync_status() -> dict[str, Any]:
    """Safe UI status; never returns token, endpoint query, or raw vendor payload."""
    return dict(_STATE, errors=list(_STATE.get("errors", [])))


def fireant_is_configured() -> bool:
    return bool(FireAntClient.readiness().get("ready"))


def _get_or_create_source(db: Session) -> DataSource:
    row = db.scalar(select(DataSource).where(DataSource.code == "FIREANT"))
    if row:
        row.display_name = "FireAnt DataFeed"
        row.source_type = "market_data_api"
        row.license_status = "confirmed" if settings.fireant_license_confirmed else "pending"
        # Save only the hostname-level base; never the token or request query.
        row.base_url = settings.fireant_base_url
        return row
    row = DataSource(
        code="FIREANT",
        display_name="FireAnt DataFeed",
        source_type="market_data_api",
        base_url=settings.fireant_base_url,
        license_status="confirmed" if settings.fireant_license_confirmed else "pending",
        notes="Read-only daily OHLCV; refresh-on-startup enabled in desktop build.",
    )
    db.add(row)
    db.flush()
    return row


def _get_or_create_instrument(db: Session, symbol: str, source_id: int) -> Instrument:
    inst = db.scalar(
        select(Instrument)
        .where(
            Instrument.symbol == symbol,
            Instrument.exchange_code == "HOSE",
            Instrument.is_active.is_(True),
        )
        .order_by(Instrument.instrument_id.asc())
        .limit(1)
    )
    if inst:
        if inst.source_id is None:
            inst.source_id = source_id
        return inst
    inst = Instrument(
        symbol=symbol,
        exchange_code="HOSE",
        instrument_type="equity",
        company_name=symbol,
        currency="VND",
        price_scale=1,
        lot_size=100,
        is_active=True,
        source_id=source_id,
    )
    db.add(inst)
    db.flush()
    return inst


async def sync_fireant_daily_bars(*, manual: bool = False) -> dict[str, Any]:
    """Fetch and persist configured daily candles; safe to call at launch or manually."""
    async with _LOCK:
        readiness = FireAntClient.readiness()
        if not readiness.get("ready"):
            _STATE.update(
                status="not_configured",
                message=(
                    "Chưa gọi FireAnt vì thiếu quyền DataFeed/token/endpoint/field map. "
                    "Ứng dụng vẫn hoạt động ở chế độ demo; không có request FireAnt nào được gửi."
                ),
                started_at=None,
                completed_at=datetime.now(timezone.utc).isoformat(),
                symbols_requested=[],
                symbols_succeeded=[],
                bars_received=0,
                bars_saved=0,
                bars_rejected=0,
                errors=[],
            )
            return get_sync_status()

        symbols: list[str] = []
        for raw in settings.fireant_symbols:
            try:
                symbol = normalize_symbol(raw)
            except (NormalizationError, TypeError):
                continue
            if symbol not in symbols:
                symbols.append(symbol)
        if not symbols:
            _STATE.update(
                status="error", message="FIREANT_SYMBOLS không có mã hợp lệ.",
                completed_at=datetime.now(timezone.utc).isoformat(), errors=["no_valid_symbols"],
            )
            return get_sync_status()

        _STATE.update(
            status="running",
            message="Đang lấy nến ngày từ FireAnt DataFeed…",
            started_at=datetime.now(timezone.utc).isoformat(),
            completed_at=None,
            symbols_requested=symbols,
            symbols_succeeded=[],
            bars_received=0,
            bars_saved=0,
            bars_rejected=0,
            errors=[],
        )
        client = FireAntClient(timeout_seconds=settings.fireant_timeout_seconds)
        succeeded: list[str] = []
        errors: list[str] = []
        received_total = saved_total = rejected_total = 0

        for symbol in symbols:
            db = SessionLocal()
            try:
                source = _get_or_create_source(db)
                inst = _get_or_create_instrument(db, symbol, source.source_id)
                payload = await client.fetch_daily_bars(symbol, count_back=settings.fireant_count_back)
                rows = payload.get("data", [])
                received_total += len(rows)
                symbol_saved = 0
                for row in rows:
                    try:
                        normalized = normalize_tcbs_bar(row, symbol=symbol, timeframe="1d")
                    except (NormalizationError, ValueError, TypeError):
                        rejected_total += 1
                        continue
                    key = {
                        "instrument_id": inst.instrument_id,
                        "source_id": source.source_id,
                        "timeframe": "1d",
                        "bar_start": normalized.bar_start,
                    }
                    bar = db.get(OHLCVBar, key)
                    if bar is None:
                        bar = OHLCVBar(**key, bar_end=normalized.bar_end,
                            open_price=normalized.open_price,
                            high_price=normalized.high_price,
                            low_price=normalized.low_price,
                            close_price=normalized.close_price,
                            volume=normalized.volume,
                            value_traded=normalized.value_traded,
                            adjusted_close=normalized.adjusted_close,
                            is_final=normalized.is_final,
                            quality_flags=list(normalized.quality_flags),
                        )
                        db.add(bar)
                    else:
                        bar.bar_end = normalized.bar_end
                        bar.open_price = normalized.open_price
                        bar.high_price = normalized.high_price
                        bar.low_price = normalized.low_price
                        bar.close_price = normalized.close_price
                        bar.volume = normalized.volume
                        bar.value_traded = normalized.value_traded
                        bar.adjusted_close = normalized.adjusted_close
                        bar.is_final = normalized.is_final
                        bar.quality_flags = list(normalized.quality_flags)
                    symbol_saved += 1
                db.commit()
                if rows and symbol_saved:
                    succeeded.append(symbol)
                elif not rows:
                    errors.append(f"{symbol}:empty_response")
                elif symbol_saved == 0:
                    errors.append(f"{symbol}:all_bars_rejected")
                saved_total += symbol_saved
            except FireAntClientError as exc:
                db.rollback()
                # Client errors are intentionally sanitized; don't store raw response.
                errors.append(f"{symbol}:{str(exc)}")
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                logger.exception("FireAnt sync failed for %s (%s)", symbol, type(exc).__name__)
                errors.append(f"{symbol}:internal_error")
            finally:
                db.close()

        status = "success" if len(succeeded) == len(symbols) and not errors and rejected_total == 0 else (
            "partial" if succeeded else "error"
        )
        summary = (
            f"Đã đồng bộ {saved_total} nến ngày cho {len(succeeded)}/{len(symbols)} mã. "
            "Đây là dữ liệu OHLCV ngày; không mặc định là bảng giá realtime."
        )
        _STATE.update(
            status=status,
            message=summary,
            completed_at=datetime.now(timezone.utc).isoformat(),
            symbols_succeeded=succeeded,
            bars_received=received_total,
            bars_saved=saved_total,
            bars_rejected=rejected_total,
            errors=errors[:30],
        )
        return get_sync_status()

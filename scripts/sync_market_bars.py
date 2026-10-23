#!/usr/bin/env python3
"""Sync daily OHLCV using the selected authorized market data provider."""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.models import DataSource, Instrument, OHLCVBar
from app.normalizers import NormalizationError, normalize_symbol, normalize_tcbs_bar
from app.providers.tcbs_client import TCBSClient, TCBSClientError
from app.providers.fireant_client import FireAntClient, FireAntClientError

logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("stockvision.sync_market_bars")


def provider_setup():
    provider = settings.market_data_provider
    if provider == "tcbs":
        return TCBSClient(), "TCBS_IFLASH", "TCBS iFlash Open API", "https://developers.tcbs.com.vn/"
    if provider == "fireant":
        return FireAntClient(), "FIREANT_DATAFEED", "FireAnt DataFeed", settings.fireant_base_url
    raise RuntimeError("MARKET_DATA_PROVIDER phải là 'tcbs' hoặc 'fireant'.")


def get_source(db, *, code: str, name: str, base_url: str) -> int:
    source = db.scalar(select(DataSource).where(DataSource.code == code))
    if source is None:
        source = DataSource(
            code=code, display_name=name, source_type="market_data_api", base_url=base_url,
            license_status="approved" if (code == "FIREANT_DATAFEED" and settings.fireant_license_confirmed) else "pending",
            notes="Chỉ sử dụng trong phạm vi quyền truy cập và lưu trữ đã được nhà cung cấp cấp.",
        )
        db.add(source); db.commit(); db.refresh(source)
    return source.source_id


async def sync_symbol(client: Any, symbol: str, count_back: int, source_code: str, source_name: str, base_url: str) -> int:
    symbol = normalize_symbol(symbol)
    payload = await client.fetch_daily_bars(symbol, count_back=count_back)
    provider_symbol = normalize_symbol(str(payload.get("ticker", symbol)))
    rows = payload.get("data", [])
    if not isinstance(rows, list):
        raise RuntimeError("Provider payload: data phải là danh sách.")
    accepted = 0
    with SessionLocal() as db:
        source_id = get_source(db, code=source_code, name=source_name, base_url=base_url)
        instrument = db.scalar(select(Instrument).where(
            Instrument.symbol == provider_symbol,
            Instrument.exchange_code == "HOSE",
            Instrument.is_active.is_(True),
        ))
        if instrument is None:
            instrument = Instrument(symbol=provider_symbol, exchange_code="HOSE", currency="VND", source_id=source_id)
            db.add(instrument); db.commit(); db.refresh(instrument)
        for raw in rows:
            try:
                bar = normalize_tcbs_bar(raw, symbol=provider_symbol, timeframe="1d")
            except NormalizationError as exc:
                log.warning("Reject %s row from %s: %s", provider_symbol, source_code, exc)
                continue
            record = OHLCVBar(
                instrument_id=instrument.instrument_id, source_id=source_id, timeframe=bar.timeframe,
                bar_start=bar.bar_start, bar_end=bar.bar_end, open_price=bar.open_price,
                high_price=bar.high_price, low_price=bar.low_price, close_price=bar.close_price,
                volume=bar.volume, value_traded=bar.value_traded, adjusted_close=bar.adjusted_close,
                is_final=bar.is_final, quality_flags=list(bar.quality_flags), updated_at=datetime.now(timezone.utc),
            )
            db.merge(record)
            accepted += 1
        db.commit()
    return accepted


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("symbols", nargs="*", help="Ví dụ: FPT VCB HPG; mặc định TCBS_SYMBOLS")
    parser.add_argument("--count-back", type=int, default=250, help="Số nến ngày muốn lấy (1–5000)")
    args = parser.parse_args()
    if not 1 <= args.count_back <= 5000:
        parser.error("--count-back phải nằm trong khoảng 1–5000")
    Base.metadata.create_all(bind=engine)
    client, source_code, source_name, base_url = provider_setup()
    symbols = args.symbols or list(settings.tcbs_symbols)
    total = 0
    for value in symbols:
        try:
            count = await sync_symbol(client, value, args.count_back, source_code, source_name, base_url)
            total += count
            log.info("%s [%s]: đã upsert %d nến ngày", value.upper(), source_code, count)
        except (TCBSClientError, FireAntClientError, NormalizationError, RuntimeError) as exc:
            log.error("%s: %s", value, exc)
        finally:
            await asyncio.sleep(1.0 / settings.tcbs_rest_requests_per_second)
    log.info("Hoàn tất: %d nến được upsert từ %s", total, source_code)


if __name__ == "__main__":
    asyncio.run(main())

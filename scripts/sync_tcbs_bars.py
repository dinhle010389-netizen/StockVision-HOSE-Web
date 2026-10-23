#!/usr/bin/env python3
"""Sync long-term daily OHLCV bars for specified TCBS symbols into PostgreSQL."""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.models import DataSource, Instrument, OHLCVBar
from app.normalizers import NormalizationError, normalize_tcbs_bar
from app.providers.tcbs_client import TCBSClient, TCBSClientError

logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("stockvision.sync_bars")


def get_source(db) -> int:
    source = db.scalar(select(DataSource).where(DataSource.code == "TCBS_IFLASH"))
    if source is None:
        source = DataSource(
            code="TCBS_IFLASH", display_name="TCBS iFlash Open API", source_type="broker_api",
            base_url="https://developers.tcbs.com.vn/", license_status="pending",
            notes="Confirm access and data license before production use.",
        )
        db.add(source); db.commit(); db.refresh(source)
    return source.source_id


async def sync_symbol(client: TCBSClient, symbol: str, count_back: int) -> int:
    payload = await client.fetch_daily_bars(symbol, count_back=count_back)
    provider_symbol = str(payload.get("ticker", symbol)).upper()
    rows = payload.get("data", [])
    accepted = 0
    with SessionLocal() as db:
        source_id = get_source(db)
        instrument = db.scalar(select(Instrument).where(Instrument.symbol == provider_symbol, Instrument.exchange_code == "HOSE", Instrument.is_active.is_(True)))
        if instrument is None:
            instrument = Instrument(symbol=provider_symbol, exchange_code="HOSE", currency="VND", source_id=source_id)
            db.add(instrument); db.commit(); db.refresh(instrument)
        for raw in rows:
            try:
                bar = normalize_tcbs_bar(raw, symbol=provider_symbol, timeframe="1d")
            except NormalizationError as exc:
                log.warning("Reject %s row: %s", provider_symbol, exc)
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
    parser.add_argument("symbols", nargs="*", help="Ví dụ: FPT VCB HPG; mặc định dùng TCBS_SYMBOLS")
    parser.add_argument("--count-back", type=int, default=250, help="Số nến ngày muốn lấy (1–5000)")
    args = parser.parse_args()
    if not 1 <= args.count_back <= 5000:
        parser.error("--count-back phải từ 1 đến 5000")
    Base.metadata.create_all(bind=engine)
    client = TCBSClient()
    symbols = [s.upper() for s in args.symbols] if args.symbols else list(settings.tcbs_symbols)
    total = 0
    for symbol in symbols:
        try:
            count = await sync_symbol(client, symbol, args.count_back)
            total += count
            log.info("%s: đã upsert %d nến ngày", symbol, count)
        except (TCBSClientError, NormalizationError) as exc:
            log.error("%s: %s", symbol, exc)
        finally:
            await asyncio.sleep(1.0 / settings.tcbs_rest_requests_per_second)
    log.info("Hoàn tất: %d nến được upsert", total)


if __name__ == "__main__":
    asyncio.run(main())

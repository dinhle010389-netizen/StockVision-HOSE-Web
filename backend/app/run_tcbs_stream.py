"""Optional read-only TCBS price-board WebSocket worker.

Enable with ENABLE_TCBS_STREAM=true and a valid server-side TCBS_API_TOKEN.
This subscribes to market data only; it never submits orders.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
from datetime import datetime, timedelta, timezone

import websockets
from sqlalchemy import select

from .config import settings
from .db import Base, SessionLocal, engine
from .models import DataSource, Instrument, QuoteSnapshot, IndexBar
from .normalizers import NormalizationError, normalize_tcbs_quote

logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("stockvision.tcbs_stream")
WS_URL = "wss://openapi.tcbs.com.vn/ws/thesis/v1/stream/normal"


def _source_id(db) -> int:
    source = db.scalar(select(DataSource).where(DataSource.code == "TCBS_IFLASH"))
    if source is None:
        source = DataSource(
            code="TCBS_IFLASH", display_name="TCBS iFlash Open API", source_type="broker_api",
            base_url="https://developers.tcbs.com.vn/", license_status="pending",
            notes="Cập nhật trạng thái giấy phép/quyền sử dụng trước khi vận hành production.",
        )
        db.add(source)
        db.commit()
        db.refresh(source)
    return source.source_id


def _store_quote(payload: dict) -> None:
    normalized = normalize_tcbs_quote(payload, received_at=datetime.now(timezone.utc))
    with SessionLocal() as db:
        source_id = _source_id(db)
        instrument = db.scalar(select(Instrument).where(
            Instrument.symbol == normalized.symbol,
            Instrument.exchange_code == "HOSE",
            Instrument.is_active.is_(True),
        ))
        if instrument is None:
            instrument = Instrument(
                symbol=normalized.symbol, exchange_code="HOSE", instrument_type="equity",
                company_name=None, currency="VND", source_id=source_id,
            )
            db.add(instrument)
            db.commit()
            db.refresh(instrument)
        quote_time = normalized.quote_time
        row = QuoteSnapshot(
            instrument_id=instrument.instrument_id,
            source_id=source_id,
            quote_time=quote_time,
            last_price=normalized.last_price,
            change_value=normalized.change_value,
            change_pct=normalized.change_pct,
            reference_price=normalized.reference_price,
            open_price=normalized.open_price,
            high_price=normalized.high_price,
            low_price=normalized.low_price,
            matched_volume=normalized.matched_volume,
            matched_value=normalized.matched_value,
            quality_flags=list(normalized.quality_flags),
            received_at=datetime.now(timezone.utc),
        )
        # Composite primary key makes a duplicate quote at an identical provider timestamp idempotent.
        db.merge(row)
        db.commit()


def _store_index(payload: dict) -> None:
    try:
        index_number = int(payload.get("indexNumber"))
        index_code = {1: "VNINDEX", 2: "VN30", 3: "HNXINDEX", 5: "UPCOMINDEX"}.get(index_number, f"INDEX_{index_number}")
        close_value = float(payload["index"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("payload chỉ số TCBS thiếu indexNumber/index hợp lệ") from exc
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    with SessionLocal() as db:
        source_id = _source_id(db)
        row = IndexBar(
            index_code=index_code, source_id=source_id, timeframe="1m", bar_start=now,
            bar_end=now + timedelta(minutes=1),
            close_value=close_value,
            change_value=payload.get("change"), change_pct=payload.get("changePercent"),
            volume=int(float(payload.get("volume", 0) or 0)),
            advancers=int(payload.get("increase", 0) or 0),
            decliners=int(payload.get("decrease", 0) or 0),
            unchanged_count=int(payload.get("notChange", 0) or 0),
            received_at=datetime.now(timezone.utc),
        )
        db.merge(row)
        db.commit()


async def _heartbeat(ws) -> None:
    while True:
        await ws.send("d|p|||")  # TCBS requires TEXT heartbeat; disable RFC ping frames.
        await asyncio.sleep(2)


async def stream_once() -> None:
    if not settings.tcbs_api_token:
        raise RuntimeError("Thiếu TCBS_API_TOKEN; không thể xác thực stream.")
    if not settings.tcbs_symbols:
        raise RuntimeError("TCBS_SYMBOLS đang rỗng.")
    Base.metadata.create_all(bind=engine)
    encoded = base64.b64encode(settings.tcbs_api_token.encode("utf-8")).decode("ascii")
    async with websockets.connect(WS_URL, ping_interval=None, ping_timeout=None, close_timeout=5, max_size=2**20) as ws:
        await ws.send(f"d|a|||{encoded}")
        # Wait for explicit auth success before subscribing, as specified by TCBS.
        authenticated = False
        for _ in range(10):
            response = await asyncio.wait_for(ws.recv(), timeout=5)
            if not isinstance(response, str) or not response.startswith("d|0|"):
                continue
            try:
                body = json.loads(response.split("|", 2)[2])
            except (ValueError, IndexError):
                continue
            if body.get("success") is True:
                authenticated = True
                break
            raise RuntimeError(f"TCBS xác thực thất bại: {body.get('error')}")
        if not authenticated:
            raise RuntimeError("Không nhận được xác nhận xác thực từ TCBS trong thời hạn.")

        symbols = ",".join(settings.tcbs_symbols)
        await ws.send(f"d|s|tk|bp+bi+tm+mp+op+fe|{symbols}")
        await ws.send("d|s|si|rt|1,2")  # VN-INDEX and VN30 index stream (channel 8)
        heartbeat_task = asyncio.create_task(_heartbeat(ws))
        log.info("Đã xác thực TCBS và subscribe giá HOSE cho %d mã.", len(settings.tcbs_symbols))
        try:
            async for frame in ws:
                if not isinstance(frame, str):
                    continue
                parts = frame.split("|", 2)
                if len(parts) != 3 or parts[0] != "s":
                    continue
                channel, payload_text = parts[1], parts[2]
                # Channel 6: ticker match. Channel 8: index values and breadth.
                if channel not in {"6", "8"}:
                    continue
                try:
                    payload = json.loads(payload_text)
                    if channel == "6":
                        _store_quote(payload)
                    else:
                        _store_index(payload)
                except (ValueError, NormalizationError, TypeError) as exc:
                    log.warning("Bỏ qua bản tin không hợp lệ từ TCBS: %s", exc)
                except Exception:
                    log.exception("Lỗi lưu quote TCBS")
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass


async def main() -> None:
    if not settings.enable_tcbs_stream:
        raise SystemExit("ENABLE_TCBS_STREAM=false. Đặt true để chạy worker stream.")
    delay = 2
    while True:
        try:
            await stream_once()
            delay = 2
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("TCBS stream lỗi: %s; thử kết nối lại sau %ss", exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)


if __name__ == "__main__":
    asyncio.run(main())

"""Strict normalization for TCBS quote and OHLCV payloads.

Principles:
- Keep provider prices unchanged (TCBS examples use VND/share values like 38,600).
- Never infer a unit/scale silently; expose quality flags.
- Store timestamps as timezone-aware UTC.
- Reject impossible OHLC bars and negative quantities.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping
import math
import re


_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,9}$")
_PLAIN_NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_GROUPED_NUMBER_RE = re.compile(r"^[+-]?(?:\d{1,3}(?:,\d{3})+)(?:\.\d*)?(?:[eE][+-]?\d+)?$")


class NormalizationError(ValueError):
    """Raised when provider data cannot be normalized safely."""


@dataclass(frozen=True)
class NormalizedQuote:
    symbol: str
    quote_time: datetime
    last_price: Decimal
    change_value: Decimal | None
    change_pct: Decimal | None
    reference_price: Decimal | None
    open_price: Decimal | None
    high_price: Decimal | None
    low_price: Decimal | None
    matched_volume: int | None
    matched_value: Decimal | None
    quality_flags: tuple[str, ...]
    raw: Mapping[str, Any]


@dataclass(frozen=True)
class NormalizedBar:
    symbol: str
    timeframe: str
    bar_start: datetime
    bar_end: datetime
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: int
    value_traded: Decimal | None
    adjusted_close: Decimal | None
    is_final: bool
    quality_flags: tuple[str, ...]
    raw: Mapping[str, Any]


def normalize_symbol(value: Any) -> str:
    if not isinstance(value, str):
        raise NormalizationError("symbol phải là chuỗi")
    symbol = value.strip().upper()
    if not _SYMBOL_RE.fullmatch(symbol):
        raise NormalizationError(f"symbol không hợp lệ: {value!r}")
    return symbol


def _numeric_text(value: Any, field: str) -> str:
    """Validate numeric syntax before removing optional thousands separators.

    Commas are accepted only as correctly grouped thousands separators (e.g. 1,234.5),
    never silently turned into a different value (e.g. 12,34 -> 1234).
    """
    text = str(value).strip()
    pattern = _GROUPED_NUMBER_RE if "," in text else _PLAIN_NUMBER_RE
    if not pattern.fullmatch(text):
        raise NormalizationError(f"{field} không phải số hợp lệ")
    return text.replace(",", "")


def _decimal(value: Any, field: str, *, optional: bool = False) -> Decimal | None:
    if value is None or value == "":
        if optional:
            return None
        raise NormalizationError(f"thiếu trường bắt buộc: {field}")
    try:
        number = Decimal(_numeric_text(value, field))
    except (InvalidOperation, ValueError, AttributeError) as exc:
        raise NormalizationError(f"{field} không phải số hợp lệ") from exc
    if not number.is_finite():
        raise NormalizationError(f"{field} không hữu hạn")
    return number


def _int_nonnegative(value: Any, field: str, *, optional: bool = True) -> int | None:
    if value is None or value == "":
        if optional:
            return None
        raise NormalizationError(f"thiếu trường bắt buộc: {field}")
    try:
        number = Decimal(_numeric_text(value, field))
    except (InvalidOperation, ValueError, AttributeError) as exc:
        raise NormalizationError(f"{field} không phải số nguyên hợp lệ") from exc
    if not number.is_finite() or number < 0 or number != number.to_integral_value():
        raise NormalizationError(f"{field} phải là số nguyên không âm")
    return int(number)


def _timestamp(value: Any, *, epoch_seconds: bool = False) -> datetime | None:
    if value is None or value == "":
        return None
    if epoch_seconds or isinstance(value, (int, float, Decimal)):
        try:
            seconds = float(value)
        except (TypeError, ValueError, OverflowError) as exc:
            raise NormalizationError("timestamp epoch không hợp lệ") from exc
        if not math.isfinite(seconds) or seconds < 0:
            raise NormalizationError("timestamp epoch ngoài phạm vi")
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError) as exc:
            raise NormalizationError("timestamp epoch ngoài phạm vi hỗ trợ") from exc
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if len(text) == 10 and text[4] == "-":
            text += "T00:00:00+00:00"
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError as exc:
            raise NormalizationError(f"timestamp không phân tích được: {value!r}") from exc
    else:
        raise NormalizationError("kiểu timestamp không được hỗ trợ")
    if dt.tzinfo is None:
        # Provider timestamps that omit timezone are treated as UTC only with an explicit flag at caller.
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def normalize_tcbs_quote(payload: Mapping[str, Any], *, received_at: datetime | None = None) -> NormalizedQuote:
    if not isinstance(payload, Mapping):
        raise NormalizationError("quote payload phải là object")
    symbol = normalize_symbol(payload.get("symbol") or payload.get("ticker") or payload.get("code"))
    flags: list[str] = []

    timestamp_value = payload.get("timeSec") or payload.get("timestamp") or payload.get("quoteTime") or payload.get("tradingDate") or payload.get("time")
    if isinstance(timestamp_value, str) and re.fullmatch(r"\d{2}:\d{2}:\d{2}", timestamp_value.strip()):
        timestamp_value = None  # A clock-only trade time has no date and cannot define an absolute timestamp.
    if payload.get("timeSec") not in (None, ""):
        quote_time = _timestamp(timestamp_value, epoch_seconds=True)
    else:
        quote_time = _timestamp(timestamp_value)
    if quote_time is None:
        fallback_time = received_at or datetime.now(timezone.utc)
        if fallback_time.tzinfo is None:
            fallback_time = fallback_time.replace(tzinfo=timezone.utc)
        quote_time = fallback_time.astimezone(timezone.utc)
        flags.append("provider_timestamp_missing")

    price_raw = next((payload.get(k) for k in ("matchPrice", "closePrice", "lastPrice", "last_price", "price") if payload.get(k) not in (None, "")), None)
    last_price = _decimal(price_raw, "last_price")
    assert last_price is not None
    if last_price <= 0:
        raise NormalizationError("last_price phải lớn hơn 0")

    ref_raw = next((payload.get(k) for k in ("reference", "referencePrice", "refPrice", "reference_price") if payload.get(k) not in (None, "")), None)
    reference = _decimal(ref_raw, "reference_price", optional=True)
    if reference is not None and reference <= 0:
        raise NormalizationError("reference_price phải lớn hơn 0 khi được cung cấp")
    change_raw = next((payload.get(k) for k in ("change", "changeValue", "change_value") if payload.get(k) not in (None, "")), None)
    change = _decimal(change_raw, "change_value", optional=True)
    pct_raw = next((payload.get(k) for k in ("changePercent", "changePct", "change_pct") if payload.get(k) not in (None, "")), None)
    pct = _decimal(pct_raw, "change_pct", optional=True)

    if reference is not None and reference > 0:
        if change is None:
            change = last_price - reference
            flags.append("change_value_derived")
        if pct is None:
            pct = (last_price - reference) / reference * Decimal(100)
            flags.append("change_pct_derived")
    elif reference is None:
        flags.append("reference_price_missing")

    open_price = _decimal(payload.get("openPrice", payload.get("open_price", payload.get("open"))), "open_price", optional=True)
    high_price = _decimal(payload.get("highPrice", payload.get("high_price", payload.get("high"))), "high_price", optional=True)
    low_price = _decimal(payload.get("lowPrice", payload.get("low_price", payload.get("low"))), "low_price", optional=True)
    vol_raw = next((payload.get(k) for k in ("totalVolume", "closeVol", "matchedVolume", "volume", "matched_volume") if payload.get(k) not in (None, "")), None)
    volume = _int_nonnegative(vol_raw, "matched_volume", optional=True)
    value_raw = next((payload.get(k) for k in ("totalValue", "totalTradingValue", "tradingValue", "matchedValue", "matched_value") if payload.get(k) not in (None, "")), None)
    value = _decimal(value_raw, "matched_value", optional=True)

    if any(x is not None and x <= 0 for x in (open_price, high_price, low_price)):
        raise NormalizationError("các giá OHLC phải lớn hơn 0")
    if any(x is not None for x in (open_price, high_price, low_price)):
        known = [x for x in (open_price, high_price, low_price, last_price) if x is not None]
        if high_price is not None and high_price < max(known):
            raise NormalizationError("high_price nhỏ hơn giá mở/đóng/thấp hơn")
        if low_price is not None and low_price > min(known):
            raise NormalizationError("low_price lớn hơn giá mở/đóng/cao hơn")
    if value is not None and value < 0:
        raise NormalizationError("matched_value không được âm")

    # The current TCBS examples express prices directly as VND/share. Do not scale implicitly.
    if last_price >= Decimal("100000000"):
        flags.append("price_scale_review_recommended")

    return NormalizedQuote(
        symbol=symbol,
        quote_time=quote_time,
        last_price=last_price,
        change_value=change,
        change_pct=pct,
        reference_price=reference,
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        matched_volume=volume,
        matched_value=value,
        quality_flags=tuple(flags),
        raw=dict(payload),
    )


def normalize_tcbs_bar(payload: Mapping[str, Any], *, symbol: str | None = None, timeframe: str = "1d") -> NormalizedBar:
    if not isinstance(payload, Mapping):
        raise NormalizationError("bar payload phải là object")
    resolved_symbol = normalize_symbol(symbol or payload.get("symbol") or payload.get("ticker") or payload.get("code"))
    if timeframe not in {"1m", "3m", "5m", "15m", "30m", "1h", "1d", "1w", "1mo"}:
        raise NormalizationError(f"timeframe không được hỗ trợ: {timeframe}")
    timestamp = payload.get("tradingDate") or payload.get("time") or payload.get("timestamp") or payload.get("bar_start") or payload.get("date")
    start = _timestamp(timestamp)
    if start is None:
        raise NormalizationError("bar thiếu timestamp")
    flags: list[str] = []
    # ISO date-only bars are intentionally stored at UTC midnight, preserving the provider date.
    duration = {
        "1m": timedelta(minutes=1), "3m": timedelta(minutes=3), "5m": timedelta(minutes=5),
        "15m": timedelta(minutes=15), "30m": timedelta(minutes=30), "1h": timedelta(hours=1),
        "1d": timedelta(days=1), "1w": timedelta(days=7), "1mo": timedelta(days=30),
    }[timeframe]
    end_raw = payload.get("bar_end") or payload.get("barEnd")
    end = _timestamp(end_raw) if end_raw is not None else start + duration

    def first(*keys: str):
        for key in keys:
            if payload.get(key) not in (None, ""):
                return payload.get(key)
        return None

    open_price = _decimal(first("open", "openPrice", "open_price"), "open_price")
    high_price = _decimal(first("high", "highPrice", "high_price"), "high_price")
    low_price = _decimal(first("low", "lowPrice", "low_price"), "low_price")
    close_price = _decimal(first("close", "closePrice", "close_price"), "close_price")
    assert open_price is not None and high_price is not None and low_price is not None and close_price is not None
    if min(open_price, high_price, low_price, close_price) <= 0:
        raise NormalizationError("giá OHLC phải lớn hơn 0")
    if high_price < max(open_price, low_price, close_price):
        raise NormalizationError("high không thể thấp hơn open/low/close")
    if low_price > min(open_price, high_price, close_price):
        raise NormalizationError("low không thể cao hơn open/high/close")
    volume = _int_nonnegative(first("volume", "vol", "tradingVolume"), "volume", optional=False)
    value = _decimal(first("value", "tradingValue", "valueTraded", "value_traded"), "value_traded", optional=True)
    adjusted = _decimal(first("adjustedClose", "adjusted_close"), "adjusted_close", optional=True)
    if adjusted is not None and adjusted <= 0:
        raise NormalizationError("adjusted_close phải lớn hơn 0 khi được cung cấp")
    if end <= start:
        raise NormalizationError("bar_end phải sau bar_start")
    if value is not None and value < 0:
        raise NormalizationError("value_traded không được âm")
    if payload.get("tradingDate") and isinstance(payload.get("tradingDate"), str) and len(payload["tradingDate"]) == 10:
        flags.append("date_only_timestamp")
    raw_is_final = payload.get("is_final", payload.get("isFinal", True))
    if isinstance(raw_is_final, bool):
        is_final = raw_is_final
    elif isinstance(raw_is_final, int) and raw_is_final in (0, 1):
        is_final = bool(raw_is_final)
    elif isinstance(raw_is_final, str) and raw_is_final.strip().lower() in {"true", "false", "1", "0"}:
        is_final = raw_is_final.strip().lower() in {"true", "1"}
    else:
        raise NormalizationError("is_final phải là boolean hoặc true/false/1/0")

    return NormalizedBar(
        symbol=resolved_symbol,
        timeframe=timeframe,
        bar_start=start,
        bar_end=end,
        open_price=open_price,
        high_price=high_price,
        low_price=low_price,
        close_price=close_price,
        volume=int(volume or 0),
        value_traded=value,
        adjusted_close=adjusted,
        is_final=is_final,
        quality_flags=tuple(flags),
        raw=dict(payload),
    )

"""Adapter for the pinned vn-market-data public multi-source chain.

The upstream package exposes normalized EOD OHLCV through DNSE/Vietcap and
other public source adapters. Provider terms, rate limits and redistribution
rights remain specific to each upstream data source.
"""
from __future__ import annotations

import asyncio
import importlib
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

from ..config import settings
from ..normalizers import NormalizationError, normalize_symbol


class PublicMarketDataError(RuntimeError):
    """Safe, user-displayable public-provider error with no secrets/raw payload."""


def _ensure_provider_cache_path() -> str:
    """Place the provider cache in a writable, app-owned directory by default."""
    existing = os.getenv("VN_MARKET_DATA_DB", "").strip()
    if existing:
        return existing
    if os.name == "nt":
        root = Path(os.getenv("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "StockVisionHOSE"
    else:
        root = Path(os.getenv("SV_DATA_DIR") or os.getenv("XDG_DATA_HOME") or ".")
        if root.name in {".", ""}:
            root = Path.cwd()
        else:
            root = root / "StockVisionHOSE"
    root.mkdir(parents=True, exist_ok=True)
    value = str(root / "vn_market_data.db")
    os.environ["VN_MARKET_DATA_DB"] = value
    return value


def _safe_upstream_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    key = value.strip().lower().replace(" ", "_").replace("-", "_")
    allowed = {
        "dnse": "DNSE", "dnse_source": "DNSE",
        "vietcap": "VIETCAP", "vietcap_source": "VIETCAP",
        "vci": "VCI", "vci_source": "VCI",
        "vndirect": "VNDIRECT", "vndirect_source": "VNDIRECT",
        "cafef": "CAFEF", "cafef_source": "CAFEF",
        "kbs": "KBS", "kbs_source": "KBS",
        "ssi": "SSI", "ssi_source": "SSI",
        "public_multi": "PUBLIC_MULTI",
        "public_multi_source": "PUBLIC_MULTI",
    }
    return allowed.get(key)


def _as_iso_date(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # Keep epoch inputs numeric so the shared normalizer applies UTC epoch logic.
        return value
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


class PublicMarketDataClient:
    """Cache-first source-chain adapter. No login bypass or endpoint scraping here."""

    def __init__(self, *, cache_ttl_seconds: int | None = None):
        self.cache_ttl_seconds = int(cache_ttl_seconds or settings.public_data_cache_ttl_seconds)
        if self.cache_ttl_seconds < 0 or self.cache_ttl_seconds > 7 * 24 * 3600:
            raise PublicMarketDataError("PUBLIC_DATA_CACHE_TTL_SECONDS phải nằm trong khoảng 0–604800.")

    @staticmethod
    def _module():
        _ensure_provider_cache_path()
        try:
            return importlib.import_module("vn_market_data")
        except (ImportError, ModuleNotFoundError) as exc:
            raise PublicMarketDataError(
                "Chưa cài vn-market-data. Cài requirements-public-data.txt hoặc triển khai qua Dockerfile của bản Public Data Edition."
            ) from None

    @staticmethod
    def readiness() -> dict[str, Any]:
        try:
            module = PublicMarketDataClient._module()
            has_ohlcv = callable(getattr(module, "get_ohlcv", None))
            has_board = callable(getattr(module, "get_board", None))
            installed = True
        except PublicMarketDataError:
            has_ohlcv = has_board = installed = False
        return {
            "provider": "public_multi_source",
            "installed": installed,
            "ohlcv_available": has_ohlcv,
            "board_available": has_board,
            "ready": bool(installed and has_ohlcv),
            "network_tested": False,
            "capabilities": ["daily_ohlcv", "source_fallback", "sqlite_cache"],
            "upstream_sources": ["DNSE", "Vietcap", "VNDirect", "CafeF"],
            "license_note": "Mã thư viện MIT; quyền sử dụng/lưu trữ/tái phân phối dữ liệu phụ thuộc điều khoản từng nguồn.",
        }

    @staticmethod
    def _call_provider(symbol: str, lookback_days: int, ttl_s: int) -> dict[str, Any]:
        module = PublicMarketDataClient._module()
        fetch = getattr(module, "get_ohlcv", None)
        if not callable(fetch):
            raise PublicMarketDataError("Gói public-data hiện tại không cung cấp get_ohlcv.")
        call_recorder = getattr(module, "record_source_calls", None)
        calls: list[Any] = []
        try:
            if callable(call_recorder):
                with call_recorder() as captured:
                    rows = fetch(symbol, lookback_days=lookback_days, ttl_s=ttl_s)
                calls = list(captured or [])
            else:
                rows = fetch(symbol, lookback_days=lookback_days, ttl_s=ttl_s)
        except Exception as exc:  # provider errors may contain URLs; do not bubble them
            raise PublicMarketDataError(f"Nguồn dữ liệu công khai không trả được {symbol} ({type(exc).__name__}).") from None
        if rows is None:
            rows = []
        if not isinstance(rows, list):
            # Deliberately don't guess how to interpret a DataFrame/object.
            raise PublicMarketDataError("Dữ liệu OHLCV trả về không phải danh sách bản ghi.")
        upstream: list[str] = []
        for item in calls:
            name = _safe_upstream_name(getattr(item, "source", None))
            outcome = getattr(item, "outcome", None)
            if name and outcome == "ok" and name not in upstream:
                upstream.append(name)
        normalized_rows: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            date_value = next((row.get(k) for k in ("date", "trading_date", "timestamp", "time", "bar_start") if row.get(k) not in (None, "")), None)
            record = {
                "date": _as_iso_date(date_value),
                "open": row.get("open", row.get("open_price")),
                "high": row.get("high", row.get("high_price")),
                "low": row.get("low", row.get("low_price")),
                "close": row.get("close", row.get("close_price")),
                "volume": row.get("volume", row.get("vol", 0)),
                "value": row.get("value", row.get("value_traded", row.get("trading_value"))),
                "adjusted_close": row.get("adjusted_close", row.get("adjustedClose")),
                "is_final": row.get("is_final", row.get("isFinal", True)),
            }
            row_source = _safe_upstream_name(row.get("source"))
            if row_source:
                record["source"] = row_source
            normalized_rows.append(record)
        return {
            "ticker": symbol,
            "data": normalized_rows,
            "provider": "public_multi_source",
            "upstream_sources": upstream,
            "source_attribution": "row" if any("source" in r for r in normalized_rows) else ("request" if len(upstream) == 1 else "cache_or_chain"),
            "cache_ttl_seconds": ttl_s,
        }

    async def fetch_daily_bars(self, symbol: str, *, lookback_days: int | None = None) -> dict[str, Any]:
        try:
            safe = normalize_symbol(symbol)
        except (NormalizationError, AttributeError, TypeError):
            raise PublicMarketDataError("Mã chứng khoán không hợp lệ.") from None
        days = int(lookback_days or settings.public_data_lookback_days)
        if not 1 <= days <= 3650:
            raise PublicMarketDataError("lookback_days phải nằm trong khoảng 1–3650.")
        return await asyncio.to_thread(self._call_provider, safe, days, self.cache_ttl_seconds)

    async def fetch_daily_index(self, symbol: str, *, lookback_days: int | None = None) -> dict[str, Any]:
        safe = normalize_symbol(symbol)
        days = int(lookback_days or settings.public_data_lookback_days)
        def call() -> dict[str, Any]:
            module = self._module()
            fetch = getattr(module, "get_ohlcv", None)
            if not callable(fetch):
                raise PublicMarketDataError("Gói public-data hiện tại không cung cấp get_ohlcv.")
            try:
                rows = fetch(safe, lookback_days=days, is_index=True, ttl_s=self.cache_ttl_seconds)
            except Exception as exc:
                raise PublicMarketDataError(f"Nguồn dữ liệu công khai không trả được chỉ số {safe} ({type(exc).__name__}).") from None
            if rows is None:
                rows = []
            if not isinstance(rows, list):
                raise PublicMarketDataError("Dữ liệu chỉ số trả về không phải danh sách bản ghi.")
            normalized_rows = []
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                dt_value = next((row.get(k) for k in ("date", "trading_date", "timestamp", "time", "bar_start") if row.get(k) not in (None, "")), None)
                normalized_rows.append({
                    "date": _as_iso_date(dt_value),
                    "open": row.get("open", row.get("open_price")),
                    "high": row.get("high", row.get("high_price")),
                    "low": row.get("low", row.get("low_price")),
                    "close": row.get("close", row.get("close_price")),
                    "volume": row.get("volume", row.get("vol", 0)),
                })
            return {"ticker": safe, "data": normalized_rows, "provider": "public_multi_source"}
        return await asyncio.to_thread(call)

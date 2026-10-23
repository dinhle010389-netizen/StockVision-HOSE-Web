from __future__ import annotations

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from app.providers.public_market_data_client import PublicMarketDataClient, PublicMarketDataError


def _fake_provider(rows):
    calls = []

    @contextmanager
    def record_source_calls():
        yield calls

    def get_ohlcv(symbol, *, lookback_days=730, ttl_s=900, is_index=False):
        calls.append(SimpleNamespace(source="dnse", outcome="ok", method="get_ohlcv", symbol=symbol))
        return rows

    return SimpleNamespace(get_ohlcv=get_ohlcv, record_source_calls=record_source_calls), calls


def test_public_adapter_maps_ohlcv_rows_and_records_upstream_source(monkeypatch):
    rows = [{
        "date": "2026-10-22", "open": 100, "high": 105, "low": 99,
        "close": 104, "volume": 12345, "value": 1283880,
    }]
    fake, _ = _fake_provider(rows)
    monkeypatch.setattr(PublicMarketDataClient, "_module", staticmethod(lambda: fake))
    client = PublicMarketDataClient(cache_ttl_seconds=900)
    result = asyncio.run(client.fetch_daily_bars("fpt", lookback_days=730))
    assert result["ticker"] == "FPT"
    assert result["provider"] == "public_multi_source"
    assert result["upstream_sources"] == ["DNSE"]
    assert result["data"][0]["date"] == "2026-10-22"
    assert result["data"][0]["close"] == 104
    assert result["data"][0]["volume"] == 12345


def test_public_adapter_rejects_invalid_symbol_before_provider_call(monkeypatch):
    monkeypatch.setattr(PublicMarketDataClient, "_module", staticmethod(lambda: (_ for _ in ()).throw(AssertionError("must not load provider"))))
    with pytest.raises(PublicMarketDataError, match="Mã chứng khoán"):
        asyncio.run(PublicMarketDataClient().fetch_daily_bars("FPT/../../bad"))


def test_public_adapter_rejects_non_list_provider_payload(monkeypatch):
    fake, _ = _fake_provider([])
    fake.get_ohlcv = lambda *args, **kwargs: {"data": []}
    monkeypatch.setattr(PublicMarketDataClient, "_module", staticmethod(lambda: fake))
    with pytest.raises(PublicMarketDataError, match="không phải danh sách"):
        asyncio.run(PublicMarketDataClient().fetch_daily_bars("FPT"))


def test_public_adapter_rejects_invalid_cache_ttl():
    with pytest.raises(PublicMarketDataError):
        PublicMarketDataClient(cache_ttl_seconds=9999999)


def test_public_adapter_readiness_does_not_claim_live_tested(monkeypatch):
    fake, _ = _fake_provider([])
    monkeypatch.setattr(PublicMarketDataClient, "_module", staticmethod(lambda: fake))
    status = PublicMarketDataClient.readiness()
    assert status["ready"] is True
    assert status["network_tested"] is False
    assert status["upstream_sources"] == ["DNSE", "Vietcap", "VNDirect", "CafeF"]
    assert status["license_note"]

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import OHLCVBar, IndexBar
from app.providers.public_market_data_client import PublicMarketDataClient
from app import public_market_data_sync as sync_module


def test_public_sync_saves_daily_bars_and_index_to_sqlite(tmp_path, monkeypatch):
    db_path = tmp_path / "public-sync-test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    settings_stub = SimpleNamespace(
        public_data_symbols=("FPT",),
        public_data_index_symbols=("VNINDEX",),
        public_data_lookback_days=730,
        public_data_cache_ttl_seconds=900,
        public_data_sync_interval_minutes=60,
    )
    monkeypatch.setattr(sync_module, "settings", settings_stub)
    monkeypatch.setattr(sync_module, "SessionLocal", Session)

    def rows_for(symbol, is_index=False):
        base = 1280 if is_index else 100
        return [
            {"date": "2026-10-20", "open": base - 1, "high": base + 2, "low": base - 2, "close": base, "volume": 1000, "value": 100000},
            {"date": "2026-10-21", "open": base, "high": base + 3, "low": base - 1, "close": base + 1, "volume": 1200, "value": 120000},
        ]

    calls = []
    @contextmanager
    def record_source_calls():
        yield calls

    def get_ohlcv(symbol, *, lookback_days=730, ttl_s=900, is_index=False):
        calls.append(SimpleNamespace(source="dnse", outcome="ok", method="get_ohlcv", symbol=symbol))
        return rows_for(symbol, is_index=is_index)

    fake_provider = SimpleNamespace(get_ohlcv=get_ohlcv, record_source_calls=record_source_calls)
    monkeypatch.setattr(PublicMarketDataClient, "_module", staticmethod(lambda: fake_provider))
    monkeypatch.setattr(PublicMarketDataClient, "readiness", staticmethod(lambda: {"ready": True, "installed": True}))
    # Avoid state from any prior API test.
    sync_module._STATE.update(status="waiting", errors=[], symbols_succeeded=[], bars_saved=0, bars_received=0)
    result = asyncio.run(sync_module.sync_public_market_data())
    assert result["status"] == "success"
    assert result["bars_received"] == 2
    assert result["bars_saved"] == 2
    assert result["indexes_saved"] == 2
    # A second sync must upsert the same composite keys instead of duplicating bars.
    result_again = asyncio.run(sync_module.sync_public_market_data())
    assert result_again["status"] == "success"
    with Session() as db:
        assert len(db.scalars(select(OHLCVBar)).all()) == 2
        assert len(db.scalars(select(IndexBar)).all()) == 2
    engine.dispose()


def test_public_sync_missing_optional_adapter_is_safe(monkeypatch):
    monkeypatch.setattr(PublicMarketDataClient, "readiness", staticmethod(lambda: {"ready": False, "installed": False}))
    result = asyncio.run(sync_module.sync_public_market_data())
    assert result["status"] == "not_installed"
    assert result["bars_saved"] == 0
    assert "Không gửi request mạng" in result["message"]


def test_manual_public_sync_is_blocked_in_demo_mode(monkeypatch):
    from fastapi.testclient import TestClient
    from app.config import settings
    from app.main import app

    old_demo = settings.demo_mode
    old_provider = settings.market_data_provider
    old_password = settings.app_access_password
    object.__setattr__(settings, "demo_mode", True)
    object.__setattr__(settings, "market_data_provider", "public")
    object.__setattr__(settings, "app_access_password", "")
    try:
        with TestClient(app) as client:
            response = client.post("/api/v1/providers/public/sync")
            assert response.status_code == 409
            assert "DEMO_MODE" in response.json()["detail"]
    finally:
        object.__setattr__(settings, "demo_mode", old_demo)
        object.__setattr__(settings, "market_data_provider", old_provider)
        object.__setattr__(settings, "app_access_password", old_password)

import asyncio
from datetime import datetime, timedelta, timezone


def test_unconfigured_fireant_sync_does_not_make_network_request(monkeypatch):
    from app import fireant_sync

    monkeypatch.setattr(fireant_sync.FireAntClient, "readiness", staticmethod(lambda: {"ready": False}))
    result = asyncio.run(fireant_sync.sync_fireant_daily_bars())
    assert result["status"] == "not_configured"
    assert result["bars_saved"] == 0
    assert result["symbols_requested"] == []
    assert "test-secret-token" not in str(result)


def test_overview_uses_real_daily_bars_when_quote_snapshots_absent():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db import Base
    from app.models import DataSource, Instrument, OHLCVBar
    from app.main import _database_overview

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    d0 = datetime(2026, 10, 21, tzinfo=timezone.utc)
    d1 = d0 + timedelta(days=1)
    with Session() as db:
        source = DataSource(code="FIREANT", display_name="FireAnt DataFeed", source_type="market_data_api", license_status="confirmed")
        db.add(source); db.commit(); db.refresh(source)
        inst = Instrument(symbol="FPT", exchange_code="HOSE", company_name="FPT", source_id=source.source_id)
        db.add(inst); db.commit(); db.refresh(inst)
        db.add(OHLCVBar(instrument_id=inst.instrument_id, source_id=source.source_id, timeframe="1d", bar_start=d0, bar_end=d0+timedelta(days=1), open_price=95, high_price=101, low_price=94, close_price=100, volume=1000, value_traded=100000, is_final=True, quality_flags=[]))
        db.commit()
        db.add(OHLCVBar(instrument_id=inst.instrument_id, source_id=source.source_id, timeframe="1d", bar_start=d1, bar_end=d1+timedelta(days=1), open_price=101, high_price=112, low_price=100, close_price=110, volume=1200, value_traded=130000, is_final=True, quality_flags=[]))
        db.commit()
        result = _database_overview(db)
        assert result["data_mode"] == "database"
        assert result["is_demo"] is False
        assert "nến ngày/EOD" in result["message"]
        assert "không mặc định realtime" in result["message"]
        assert result["active_stocks"][0]["symbol"] == "FPT"
        assert result["active_stocks"][0]["last_price"] == 110
        assert result["active_stocks"][0]["change_value"] == 10
        assert result["active_stocks"][0]["change_pct"] == 10
    engine.dispose()


def test_desktop_package_has_one_click_launcher_and_config_safety():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "desktop_launcher.py").read_text(encoding="utf-8")
    start = (root / "START_STOCKVISION.bat").read_text(encoding="utf-8")
    env = (root / ".env.example").read_text(encoding="utf-8")
    assert "127.0.0.1" in launcher
    assert "FIREANT_AUTO_SYNC_ON_STARTUP" in launcher
    assert "DEMO_MODE" in launcher
    assert "py -3.11" in start
    assert "docker compose" not in start.lower()
    assert "FIREANT_API_TOKEN=" in env
    assert "FIREANT_LICENSE_CONFIRMED=false" in env
    assert "FIREANT_BARS_PATH=" in env


def test_startup_sync_persists_valid_fireant_bars_to_local_sqlite(monkeypatch):
    from types import SimpleNamespace
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.db import Base
    from app.models import DataSource, Instrument, OHLCVBar
    from app import fireant_sync

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    sample = {
        "date": "2026-10-21", "open": "100", "high": "110", "low": "99",
        "close": "108", "volume": 250000, "value": 27000000, "is_final": True,
    }

    class FakeFireAntClient:
        @staticmethod
        def readiness():
            return {"ready": True}
        def __init__(self, **kwargs):
            pass
        async def fetch_daily_bars(self, symbol, *, count_back=250):
            assert symbol == "FPT"
            assert count_back == 5
            return {"ticker": symbol, "data": [sample]}

    monkeypatch.setattr(fireant_sync, "settings", SimpleNamespace(
        fireant_symbols=("fpt",), fireant_count_back=5, fireant_timeout_seconds=3,
        fireant_base_url="https://feed.fireant.test", fireant_license_confirmed=True,
    ))
    monkeypatch.setattr(fireant_sync, "SessionLocal", Session)
    monkeypatch.setattr(fireant_sync, "FireAntClient", FakeFireAntClient)

    result = asyncio.run(fireant_sync.sync_fireant_daily_bars())
    assert result["status"] == "success"
    assert result["symbols_succeeded"] == ["FPT"]
    assert result["bars_received"] == result["bars_saved"] == 1
    with Session() as db:
        bar = db.scalar(select(OHLCVBar))
        instrument = db.scalar(select(Instrument).where(Instrument.symbol == "FPT"))
        source = db.scalar(select(DataSource).where(DataSource.code == "FIREANT"))
        assert bar is not None and float(bar.close_price) == 108.0
        assert instrument is not None and source is not None
        assert source.license_status == "confirmed"
    engine.dispose()

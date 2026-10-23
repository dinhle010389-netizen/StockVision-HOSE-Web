import os

# Ensure tests remain offline and do not depend on a PostgreSQL/TCBS account.
os.environ.setdefault("DATABASE_URL", "sqlite:///./tests/test_stockvision.db")
os.environ.setdefault("DEMO_MODE", "true")
os.environ.setdefault("AUTO_CREATE_TABLES", "true")

from fastapi.testclient import TestClient
from app.main import app


def test_health_endpoint():
    with TestClient(app) as client:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["demo_mode"] is True


def test_market_overview_is_explicitly_demo():
    with TestClient(app) as client:
        response = client.get("/api/v1/market/overview")
        assert response.status_code == 200
        body = response.json()
        assert body["is_demo"] is True
        assert body["data_mode"] == "demo"
        assert body["indices"]
        assert all(row["is_demo"] for row in body["active_stocks"])
        assert "MÔ PHỎNG" in body["message"]


def test_risk_endpoint():
    with TestClient(app) as client:
        response = client.post("/api/v1/risk/hermitian", json={
            "symbols": ["FPT", "VCB"],
            "returns": [[0.01, 0.02], [-0.01, 0.0], [0.02, 0.01], [0.0, -0.01]],
        })
        assert response.status_code == 200
        assert response.json()["risk_spectrum"]["is_hermitian"] is True


def test_risk_endpoint_rejects_invalid_matrix_shape():
    with TestClient(app) as client:
        response = client.post("/api/v1/risk/hermitian", json={
            "symbols": ["FPT", "VCB"],
            "returns": [[0.01], [0.02], [0.03]],
        })
        assert response.status_code == 422


def test_database_market_overview_prefers_index_breadth_and_sums_all_tracked_values():
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db import Base
    from app.models import DataSource, Instrument, QuoteSnapshot, IndexBar
    from app.main import _database_overview

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    with Session() as db:
        source = DataSource(code="TCBS_IFLASH", display_name="TCBS", source_type="broker_api", license_status="approved")
        db.add(source); db.commit(); db.refresh(source)
        fpt = Instrument(symbol="FPT", exchange_code="HOSE", currency="VND", source_id=source.source_id)
        vcb = Instrument(symbol="VCB", exchange_code="HOSE", currency="VND", source_id=source.source_id)
        db.add_all([fpt, vcb]); db.commit(); db.refresh(fpt); db.refresh(vcb)
        rows = [
            QuoteSnapshot(instrument_id=fpt.instrument_id, source_id=source.source_id, quote_time=now, last_price=100, change_value=2, change_pct=2, matched_volume=100, matched_value=10000, quality_flags=[]),
            QuoteSnapshot(instrument_id=vcb.instrument_id, source_id=source.source_id, quote_time=now, last_price=200, change_value=-1, change_pct=-0.5, matched_volume=200, matched_value=30000, quality_flags=[]),
            IndexBar(index_code="VNINDEX", source_id=source.source_id, timeframe="1m", bar_start=now-timedelta(minutes=1), bar_end=now, close_value=1280, change_value=1, change_pct=0.1, advancers=200, decliners=100, unchanged_count=50),
            IndexBar(index_code="VNINDEX", source_id=source.source_id, timeframe="1m", bar_start=now, bar_end=now+timedelta(minutes=1), close_value=1281, change_value=2, change_pct=0.16, advancers=210, decliners=90, unchanged_count=50),
        ]
        # Insert separately: SQLite's datetime adapter strips timezone info from the
        # composite index_bar primary key; PostgreSQL preserves timestamptz semantics.
        for row in rows:
            db.add(row)
            db.commit()
        body = _database_overview(db)
        assert body["data_mode"] == "database"
        assert body["breadth_scope"] == "market"
        assert body["breadth"]["advancers"] == 210
        assert body["breadth"]["decliners"] == 90
        assert body["breadth"]["observed"] == 350
        assert body["tracked_value_total"] == 40000.0
        assert len(body["active_stocks"]) == 2
    engine.dispose()


def test_dashboard_and_pwa_assets_are_served():
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        assert "Market Overview" in page.text
        assert "DỮ LIỆU MÔ PHỎNG" in page.text
        assert client.get("/static/manifest.webmanifest").status_code == 200
        worker = client.get("/sw.js")
        assert worker.status_code == 200
        assert worker.headers["service-worker-allowed"] == "/"

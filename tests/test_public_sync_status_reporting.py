from fastapi.testclient import TestClient

from app.main import app
from app.providers.public_market_data_client import PublicMarketDataClient


def test_provider_status_reports_actual_sync_telemetry_without_secrets(monkeypatch):
    from app import main as main_module

    monkeypatch.setattr(
        main_module,
        "get_public_sync_status",
        lambda: {
            "status": "success",
            "completed_at": "2026-10-23T09:30:00+00:00",
            "bars_saved": 27,
            "bars_rejected": 0,
            "upstream_sources": ["DNSE", "VIETCAP"],
            "errors": [],
        },
    )
    monkeypatch.setattr(
        PublicMarketDataClient,
        "readiness",
        staticmethod(lambda: {
            "provider": "public_multi_source",
            "installed": True,
            "ohlcv_available": True,
            "board_available": True,
            "ready": True,
            "network_tested": False,
            "capabilities": ["daily_ohlcv"],
            "upstream_sources": ["DNSE", "Vietcap"],
            "license_note": "test only",
        }),
    )
    with TestClient(app) as client:
        response = client.get("/api/v1/providers/status")
    assert response.status_code == 200
    public = response.json()["providers"]["public"]
    assert public["network_tested"] is True
    assert public["last_sync_status"] == "success"
    assert public["last_sync_bars_saved"] == 27
    assert public["last_sync_upstream_sources"] == ["DNSE", "VIETCAP"]
    assert "FIREANT_API_TOKEN" not in str(response.json())


def test_provider_status_never_calls_cached_success_a_live_test_without_upstream(monkeypatch):
    from app import main as main_module

    monkeypatch.setattr(
        main_module,
        "get_public_sync_status",
        lambda: {
            "status": "success",
            "completed_at": "2026-10-23T09:30:00+00:00",
            "bars_saved": 27,
            "bars_rejected": 0,
            "upstream_sources": [],
            "errors": [],
        },
    )
    monkeypatch.setattr(
        PublicMarketDataClient,
        "readiness",
        staticmethod(lambda: {
            "provider": "public_multi_source", "installed": True,
            "ohlcv_available": True, "board_available": True, "ready": True,
            "network_tested": False, "capabilities": ["daily_ohlcv"],
            "upstream_sources": ["DNSE"], "license_note": "test only",
        }),
    )
    with TestClient(app) as client:
        response = client.get("/api/v1/providers/status")
    public = response.json()["providers"]["public"]
    assert response.status_code == 200
    assert public["network_tested"] is False
    assert public["last_sync_status"] == "success"
    assert public["last_sync_upstream_sources"] == []

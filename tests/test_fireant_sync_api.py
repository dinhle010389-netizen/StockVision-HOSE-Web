from fastapi.testclient import TestClient
from app.main import app


def test_fireant_sync_status_endpoint_does_not_expose_credentials():
    with TestClient(app) as client:
        response = client.get("/api/v1/providers/fireant/sync-status")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] in {"waiting", "not_configured", "running", "success", "partial", "error"}
        text = str(body).lower()
        assert "fireant_api_token" not in text
        assert "authorization" not in text


def test_manual_fireant_sync_when_unconfigured_is_safe():
    with TestClient(app) as client:
        response = client.post("/api/v1/providers/fireant/sync")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "not_configured"
        assert body["bars_saved"] == 0

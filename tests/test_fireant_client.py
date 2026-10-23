from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app.normalizers import NormalizationError, normalize_tcbs_bar
from app.providers.fireant_client import FireAntClient, FireAntClientError, map_fireant_bar_record

FIELD_MAP = {
    "date": "trading.date",
    "open": "ohlc.o",
    "high": "ohlc.h",
    "low": "ohlc.l",
    "close": "ohlc.c",
    "volume": "vol",
    "value": "value",
    "adjusted_close": "adjustedClose",
    "is_final": "final",
}
SOURCE_RECORD = {
    "trading": {"date": "2026-10-22"},
    "ohlc": {"o": "100.0", "h": "105.0", "l": "99.0", "c": "103.0"},
    "vol": 120000,
    "value": 12360000,
    "adjustedClose": "103.0",
    "final": True,
}


def create_client(handler, **kwargs):
    return FireAntClient(
        base_url="https://api.fireant.test",
        token="test-secret-token",
        bars_path="/authorized-spec/daily-bars",
        query_template={"symbol": "{symbol}", "limit": "{count_back}"},
        data_key="result.items",
        field_map=FIELD_MAP,
        license_confirmed=True,
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


def test_fireant_client_requires_explicit_license_confirmation():
    with pytest.raises(FireAntClientError, match="chưa được xác nhận"):
        FireAntClient(base_url="https://api.fireant.test", token="x", bars_path="/bars", license_confirmed=False)


@pytest.mark.parametrize("base_url", ["http://api.fireant.test", "https://user:pass@api.fireant.test", "api.fireant.test"])
def test_fireant_requires_safe_https_base_url(base_url):
    with pytest.raises(FireAntClientError, match="HTTPS"):
        FireAntClient(base_url=base_url, token="x", bars_path="/bars", license_confirmed=True)


@pytest.mark.parametrize("path", ["", "bars", "//evil.test/bars", "/../secret", "/bars?symbol=FPT", "/bars#fragment"])
def test_fireant_rejects_unsafe_or_undocumented_path(path):
    with pytest.raises(FireAntClientError):
        FireAntClient(base_url="https://api.fireant.test", token="x", bars_path=path, license_confirmed=True)


def test_map_nested_payload_and_normalize_bar():
    mapped = map_fireant_bar_record(SOURCE_RECORD, FIELD_MAP)
    bar = normalize_tcbs_bar(mapped, symbol="fpt", timeframe="1d")
    assert bar.symbol == "FPT"
    assert float(bar.open_price) == 100.0
    assert float(bar.high_price) == 105.0
    assert float(bar.low_price) == 99.0
    assert float(bar.close_price) == 103.0
    assert bar.volume == 120000
    assert bar.is_final is True


def test_fireant_fetch_uses_configured_endpoint_and_never_logs_token():
    seen = {}
    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"result": {"items": [SOURCE_RECORD]}})
    client = create_client(handler)
    result = asyncio.run(client.fetch_daily_bars("fpt", count_back=5))
    assert result["ticker"] == "FPT"
    assert len(result["data"]) == 1
    assert result["data"][0]["date"] == "2026-10-22"
    assert "/authorized-spec/daily-bars" in seen["url"]
    assert "symbol=FPT" in seen["url"]
    assert seen["auth"] == "Bearer test-secret-token"


@pytest.mark.parametrize("symbol", ["FPT;DROP", "A B", "ABCDEFGHIJK", "", "A/B"])
def test_fireant_rejects_invalid_symbol_before_network(symbol):
    def handler(request):
        raise AssertionError("Network should not be called for invalid ticker")
    client = create_client(handler)
    with pytest.raises(FireAntClientError, match="Mã chứng khoán"):
        asyncio.run(client.fetch_daily_bars(symbol, count_back=5))


@pytest.mark.parametrize("count_back", [0, -1, 5001, True, 1.2])
def test_fireant_rejects_invalid_count_before_network(count_back):
    def handler(request):
        raise AssertionError("Network should not be called for invalid count")
    client = create_client(handler)
    with pytest.raises(FireAntClientError, match="count_back"):
        asyncio.run(client.fetch_daily_bars("FPT", count_back=count_back))


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_fireant_http_errors_are_sanitized(status):
    def handler(request):
        return httpx.Response(status, text="test-secret-token leaked-body-should-not-appear")
    client = create_client(handler)
    with pytest.raises(FireAntClientError) as exc:
        asyncio.run(client.fetch_daily_bars("FPT", count_back=5))
    assert str(status) in str(exc.value)
    assert "test-secret-token" not in str(exc.value)
    assert "leaked-body" not in str(exc.value)


@pytest.mark.parametrize("body", [[], {"result": {"items": {}}}, {"data": []}, {"result": {"items": ["bad-row"]}}])
def test_fireant_rejects_malformed_payload(body):
    def handler(request):
        return httpx.Response(200, json=body)
    client = create_client(handler)
    with pytest.raises(FireAntClientError):
        asyncio.run(client.fetch_daily_bars("FPT", count_back=5))


def test_fireant_rejects_rows_exceeding_requested_count():
    def handler(request):
        return httpx.Response(200, json={"result": {"items": [SOURCE_RECORD, SOURCE_RECORD]}})
    client = create_client(handler)
    with pytest.raises(FireAntClientError, match="nhiều nến hơn"):
        asyncio.run(client.fetch_daily_bars("FPT", count_back=1))


def test_fireant_rejects_field_map_with_missing_required_field():
    with pytest.raises(FireAntClientError, match="thiếu trường bắt buộc"):
        map_fireant_bar_record(SOURCE_RECORD, {"date": "trading.date", "open": "ohlc.o"})


def test_fireant_rejects_invalid_bar_after_mapping():
    bad = dict(SOURCE_RECORD)
    bad["ohlc"] = {"o": 100, "h": 98, "l": 99, "c": 101}
    mapped = map_fireant_bar_record(bad, FIELD_MAP)
    with pytest.raises(NormalizationError):
        normalize_tcbs_bar(mapped, symbol="FPT", timeframe="1d")


def test_fireant_rejects_unknown_query_placeholder():
    client = create_client(lambda request: httpx.Response(200, json={"result": {"items": []}}))
    client.query_template = {"symbol": "{secret}"}
    with pytest.raises(FireAntClientError, match="placeholder"):
        asyncio.run(client.fetch_daily_bars("FPT", count_back=5))


def test_provider_status_endpoint_does_not_leak_credentials():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        response = client.get("/api/v1/providers/status")
    assert response.status_code == 200
    body = response.json()
    serialized = json.dumps(body)
    assert "test-secret-token" not in serialized
    assert "api_token" not in serialized
    assert body["providers"]["fireant"]["network_tested"] is False


def test_fireant_client_expands_symbol_path_from_configured_contract():
    seen = {}
    def handler(request):
        seen["path"] = request.url.path
        return httpx.Response(200, json={"result": {"items": [SOURCE_RECORD]}})
    client = FireAntClient(
        base_url="https://api.fireant.test", token="token",
        bars_path="/authorized-spec/symbols/{symbol}/daily-bars",
        query_template={"limit": "{count_back}"}, data_key="result.items",
        field_map=FIELD_MAP, license_confirmed=True,
        transport=httpx.MockTransport(handler),
    )
    asyncio.run(client.fetch_daily_bars("fpt", count_back=1))
    assert seen["path"] == "/authorized-spec/symbols/FPT/daily-bars"


def test_fireant_client_rejects_unknown_path_placeholder():
    with pytest.raises(FireAntClientError, match="placeholder"):
        FireAntClient(
            base_url="https://api.fireant.test", token="token",
            bars_path="/authorized-spec/{unknown}/bars",
            query_template={}, data_key="data", field_map=FIELD_MAP, license_confirmed=True,
        )

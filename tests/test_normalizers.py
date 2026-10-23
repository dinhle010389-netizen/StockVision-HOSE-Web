from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.normalizers import NormalizationError, normalize_symbol, normalize_tcbs_bar, normalize_tcbs_quote


def test_normalize_tcbs_quote_converts_epoch_and_derives_change_pct():
    payload = {
        "symbol": " fpt ", "closePrice": "38600.0", "reference": "37500",
        "change": "1100", "timeSec": "1755144180", "closeVol": "1000",
        "totalTradingValue": "38600000",
    }
    q = normalize_tcbs_quote(payload)
    assert q.symbol == "FPT"
    assert q.last_price == Decimal("38600.0")
    assert q.change_pct == Decimal("1100") / Decimal("37500") * Decimal(100)
    assert q.matched_volume == 1000
    assert q.quote_time.tzinfo == timezone.utc
    assert "provider_timestamp_missing" not in q.quality_flags


def test_normalize_quote_missing_timestamp_is_flagged():
    q = normalize_tcbs_quote({"symbol": "VCB", "matchPrice": "91000", "changePercent": "0.55"}, received_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert q.quote_time == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert "provider_timestamp_missing" in q.quality_flags
    assert "reference_price_missing" in q.quality_flags


def test_quote_rejects_nonpositive_price_and_negative_volume():
    with pytest.raises(NormalizationError):
        normalize_tcbs_quote({"symbol": "FPT", "matchPrice": 0})
    with pytest.raises(NormalizationError):
        normalize_tcbs_quote({"symbol": "FPT", "matchPrice": 100, "totalVolume": -1})


def test_normalize_daily_bar():
    bar = normalize_tcbs_bar({
        "tradingDate": "2026-10-22T00:00:00.000Z",
        "open": 100, "high": 108, "low": 98, "close": 105, "volume": 1200,
    }, symbol="HPG", timeframe="1d")
    assert bar.symbol == "HPG"
    assert bar.close_price == Decimal("105")
    assert bar.volume == 1200
    assert bar.bar_end > bar.bar_start
    assert bar.is_final


def test_bar_rejects_bad_ohlc_and_volume():
    with pytest.raises(NormalizationError):
        normalize_tcbs_bar({"tradingDate": "2026-10-22", "open": 100, "high": 90, "low": 95, "close": 99, "volume": 1}, symbol="FPT")
    with pytest.raises(NormalizationError):
        normalize_tcbs_bar({"tradingDate": "2026-10-22", "open": 100, "high": 110, "low": 95, "close": 99, "volume": -1}, symbol="FPT")


def test_symbol_validation():
    assert normalize_symbol(" fpt ") == "FPT"
    with pytest.raises(NormalizationError):
        normalize_symbol("FPT;DROP TABLE")


def test_clock_only_quote_time_does_not_get_misread_as_absolute_timestamp():
    q = normalize_tcbs_quote({"symbol": "FPT", "matchPrice": "125000", "time": "14:29:30"}, received_at=datetime(2026, 10, 23, tzinfo=timezone.utc))
    assert q.quote_time == datetime(2026, 10, 23, tzinfo=timezone.utc)
    assert "provider_timestamp_missing" in q.quality_flags

@pytest.mark.parametrize("field,value", [
    ("openPrice", -1), ("openPrice", 0),
    ("highPrice", -1), ("highPrice", 0),
    ("lowPrice", -1), ("lowPrice", 0),
])
def test_quote_rejects_nonpositive_optional_ohl_prices(field, value):
    with pytest.raises(NormalizationError, match="OHLC"):
        normalize_tcbs_quote({"symbol": "FPT", "matchPrice": 100, field: value})


@pytest.mark.parametrize("value,expected", [
    (True, True), (False, False), (1, True), (0, False),
    ("true", True), ("false", False), ("1", True), ("0", False),
    (" FALSE ", False), (" TRUE ", True),
])
def test_bar_is_final_parses_string_booleans_correctly(value, expected):
    bar = normalize_tcbs_bar({
        "tradingDate": "2026-10-22", "open": 100, "high": 105,
        "low": 95, "close": 101, "volume": 1, "isFinal": value,
    }, symbol="FPT")
    assert bar.is_final is expected


def test_bar_is_final_rejects_ambiguous_string():
    with pytest.raises(NormalizationError, match="is_final"):
        normalize_tcbs_bar({
            "tradingDate": "2026-10-22", "open": 100, "high": 105,
            "low": 95, "close": 101, "volume": 1, "isFinal": "no",
        }, symbol="FPT")


@pytest.mark.parametrize("value", [float("inf"), float("nan"), 1e100])
def test_quote_rejects_out_of_range_epoch_timestamp(value):
    with pytest.raises(NormalizationError):
        normalize_tcbs_quote({"symbol": "FPT", "matchPrice": 100, "timestamp": value})

@pytest.mark.parametrize("reference", [0, -1, "-100"])
def test_quote_rejects_nonpositive_reference_price(reference):
    with pytest.raises(NormalizationError, match="reference_price"):
        normalize_tcbs_quote({"symbol": "FPT", "matchPrice": 100, "reference": reference})


@pytest.mark.parametrize("raw", ["12,34", "1,23,456", "1_000", "12,34.5"])
def test_numeric_parser_rejects_malformed_thousands_grouping(raw):
    with pytest.raises(NormalizationError):
        normalize_tcbs_quote({"symbol": "FPT", "matchPrice": raw})


def test_numeric_parser_accepts_correct_thousands_grouping():
    q = normalize_tcbs_quote({"symbol": "FPT", "matchPrice": "1,234.5"})
    assert q.last_price == Decimal("1234.5")


@pytest.mark.parametrize("adjusted", [0, -1, "-12.5"])
def test_bar_rejects_nonpositive_adjusted_close(adjusted):
    with pytest.raises(NormalizationError, match="adjusted_close"):
        normalize_tcbs_bar({
            "tradingDate": "2026-10-22", "open": 100, "high": 105,
            "low": 95, "close": 101, "volume": 1, "adjustedClose": adjusted,
        }, symbol="FPT")

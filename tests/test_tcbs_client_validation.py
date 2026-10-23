import asyncio
import pytest
from app.providers.tcbs_client import TCBSClient, TCBSClientError

@pytest.mark.parametrize("symbol", ["FPT;DROP", "A B", "ABCDEFGHIJK", "", "A/B"])
def test_tcbs_rest_client_rejects_invalid_symbol_before_network(symbol):
    client = TCBSClient(token="offline-test-token")
    with pytest.raises(TCBSClientError, match="Mã chứng khoán"):
        asyncio.run(client.fetch_daily_bars(symbol, count_back=1))

@pytest.mark.parametrize("count_back", [0, -1, 5001])
def test_tcbs_rest_client_rejects_invalid_count_back_before_network(count_back):
    client = TCBSClient(token="offline-test-token")
    with pytest.raises(TCBSClientError, match="count_back"):
        asyncio.run(client.fetch_daily_bars("FPT", count_back=count_back))

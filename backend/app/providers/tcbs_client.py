from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from ..config import settings
from ..normalizers import NormalizationError, normalize_symbol


class TCBSClientError(RuntimeError):
    pass


class TCBSClient:
    """Small REST client for TCBS iFlash Open API's long-term OHLCV endpoint.

    The token must be acquired through TCBS/TCInvest and supplied server-side via
    TCBS_API_TOKEN. Token exchange/OTP is intentionally not automated in this MVP.
    """

    def __init__(self, token: str | None = None, base_url: str | None = None):
        self.token = (token if token is not None else settings.tcbs_api_token).strip()
        self.base_url = (base_url or settings.tcbs_base_url).rstrip("/")
        if not self.token:
            raise TCBSClientError("Thiếu TCBS_API_TOKEN; hãy cấu hình trong .env phía server.")

    async def fetch_daily_bars(self, symbol: str, *, count_back: int = 250, to_epoch: int | None = None) -> dict[str, Any]:
        try:
            symbol = normalize_symbol(symbol)
        except (NormalizationError, AttributeError, TypeError) as exc:
            raise TCBSClientError("Mã chứng khoán không hợp lệ.") from exc
        if not 1 <= count_back <= 5000:
            raise TCBSClientError("count_back phải nằm trong khoảng 1–5000.")
        params = {
            "ticker": symbol,
            "type": "stock",
            "resolution": "D",
            "to": int(to_epoch or datetime.now(timezone.utc).timestamp()),
            "countBack": count_back,
        }
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
                response = await client.get(
                    f"{self.base_url}/nyx/v2/stock/bars-long-term",
                    params=params,
                    headers=headers,
                )
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise TCBSClientError(f"TCBS trả HTTP {exc.response.status_code}; kiểm tra token/quyền truy cập.") from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise TCBSClientError(f"Không lấy được OHLCV từ TCBS: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise TCBSClientError("Cấu trúc phản hồi TCBS không đúng kỳ vọng; không nhập dữ liệu.")
        return payload

"""Config-driven FireAnt DataFeed client.

No endpoint or field schema is guessed. Endpoint path, query template and field map
must be configured from a FireAnt-provided technical specification. Credentials
stay server-side. Network calls are read-only and are never performed at import time.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Mapping
from urllib.parse import quote, urlparse

import httpx

from ..config import settings
from ..normalizers import NormalizationError, normalize_symbol


class FireAntClientError(RuntimeError):
    """Safe-to-display adapter error that never includes credentials or raw bodies."""


_REQUIRED_FIELDS = {"date", "open", "high", "low", "close", "volume"}
_ALLOWED_FIELDS = _REQUIRED_FIELDS | {"value", "adjusted_close", "is_final", "bar_start", "bar_end"}
_PLACEHOLDER_RE = re.compile(r"\{(symbol|count_back|to_epoch)\}")


def _load_json_object(value: str | Mapping[str, Any], label: str) -> dict[str, Any]:
    if isinstance(value, Mapping):
        parsed = dict(value)
    else:
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError) as exc:
            raise FireAntClientError(f"{label} phải là JSON hợp lệ.") from exc
    if not isinstance(parsed, dict):
        raise FireAntClientError(f"{label} phải là JSON object.")
    return parsed


def _get_nested(record: Mapping[str, Any], path: str) -> Any:
    current: Any = record
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def map_fireant_bar_record(record: Mapping[str, Any], field_map: Mapping[str, str]) -> dict[str, Any]:
    """Map one vendor record to StockVision's canonical bar keys (pure/offline)."""
    if not isinstance(record, Mapping):
        raise FireAntClientError("Mỗi bản ghi FireAnt phải là object.")
    if not isinstance(field_map, Mapping):
        raise FireAntClientError("Bản đồ trường FireAnt không hợp lệ.")
    unknown = set(field_map) - _ALLOWED_FIELDS
    if unknown:
        raise FireAntClientError("Bản đồ trường FireAnt chứa trường đích không hỗ trợ.")
    missing = _REQUIRED_FIELDS - set(field_map)
    if missing:
        raise FireAntClientError("Bản đồ trường FireAnt thiếu trường bắt buộc.")
    output: dict[str, Any] = {}
    for target, source_path in field_map.items():
        if not isinstance(source_path, str) or not source_path.strip():
            raise FireAntClientError("Đường dẫn trường FireAnt phải là chuỗi không rỗng.")
        value = _get_nested(record, source_path.strip())
        if value is None and target in _REQUIRED_FIELDS:
            raise FireAntClientError("Payload FireAnt thiếu trường bắt buộc sau ánh xạ.")
        if value is not None:
            output[target] = value
    return output


class FireAntClient:
    """Read-only, HTTPS-only, configuration-driven FireAnt REST/DataFeed adapter.

    `base_url`, `bars_path`, `query_template`, `data_key` and `field_map` must be
    taken from the technical specification and access plan actually granted by FireAnt.
    The default endpoint path is intentionally empty to prevent undocumented calls.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        token: str | None = None,
        bars_path: str | None = None,
        query_template: str | Mapping[str, Any] | None = None,
        data_key: str | None = None,
        field_map: str | Mapping[str, Any] | None = None,
        auth_scheme: str | None = None,
        license_confirmed: bool | None = None,
        timeout_seconds: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url if base_url is not None else settings.fireant_base_url).rstrip("/")
        self.token = (token if token is not None else settings.fireant_api_token).strip()
        self.bars_path = (bars_path if bars_path is not None else settings.fireant_bars_path).strip()
        query_value = query_template if query_template is not None else settings.fireant_bars_query_json
        map_value = field_map if field_map is not None else settings.fireant_bar_field_map_json
        self.query_template = _load_json_object(query_value, "FIREANT_BARS_QUERY_JSON")
        self.field_map = _load_json_object(map_value, "FIREANT_BAR_FIELD_MAP_JSON")
        self.data_key = (data_key if data_key is not None else settings.fireant_bars_data_key).strip()
        self.auth_scheme = (auth_scheme if auth_scheme is not None else settings.fireant_auth_scheme).strip()
        self.license_confirmed = (
            license_confirmed if license_confirmed is not None else settings.fireant_license_confirmed
        )
        self.timeout_seconds = float(timeout_seconds)
        self.transport = transport

        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise FireAntClientError("FIREANT_BASE_URL phải là URL HTTPS hợp lệ, không chứa thông tin đăng nhập.")
        if not self.license_confirmed:
            raise FireAntClientError("FireAnt DataFeed chưa được xác nhận quyền truy cập/lưu trữ; client bị khóa.")
        if not self.token:
            raise FireAntClientError("Thiếu FIREANT_API_TOKEN ở phía máy chủ.")
        if not self.bars_path or not self.bars_path.startswith("/") or self.bars_path.startswith("//"):
            raise FireAntClientError("FIREANT_BARS_PATH phải là đường dẫn tương đối được FireAnt cấp, bắt đầu bằng '/'.")
        if ".." in self.bars_path.split("/") or "?" in self.bars_path or "#" in self.bars_path:
            raise FireAntClientError("FIREANT_BARS_PATH không được chứa traversal, query hoặc fragment.")
        path_placeholders = re.findall(r"\{([^{}]+)\}", self.bars_path)
        if any(name != "symbol" for name in path_placeholders):
            raise FireAntClientError("FIREANT_BARS_PATH chỉ hỗ trợ placeholder {symbol} nếu endpoint được cấp dùng mã trong path.")
        if not self.auth_scheme or any(ch.isspace() for ch in self.auth_scheme):
            raise FireAntClientError("FIREANT_AUTH_SCHEME không hợp lệ.")
        if not self.data_key or any(not part for part in self.data_key.split(".")):
            raise FireAntClientError("FIREANT_BARS_DATA_KEY không hợp lệ.")
        if not _REQUIRED_FIELDS.issubset(self.field_map):
            raise FireAntClientError("FIREANT_BAR_FIELD_MAP_JSON phải ánh xạ date/open/high/low/close/volume.")
        if set(self.field_map) - _ALLOWED_FIELDS:
            raise FireAntClientError("FIREANT_BAR_FIELD_MAP_JSON chứa trường đích không hỗ trợ.")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 120:
            raise FireAntClientError("timeout_seconds phải trong khoảng (0, 120].")

    @staticmethod
    def readiness() -> dict[str, Any]:
        """Safe status; never returns token, endpoint query or vendor payload."""
        path = settings.fireant_bars_path.strip()
        base = urlparse(settings.fireant_base_url)
        path_placeholders = re.findall(r"\{([^{}]+)\}", path)
        endpoint_configured = bool(
            path.startswith("/") and not path.startswith("//")
            and ".." not in path.split("/") and "?" not in path and "#" not in path
            and all(name == "symbol" for name in path_placeholders)
        )
        field_map_ok = False
        try:
            field_map = _load_json_object(settings.fireant_bar_field_map_json, "FIREANT_BAR_FIELD_MAP_JSON")
            field_map_ok = _REQUIRED_FIELDS.issubset(field_map) and not (set(field_map) - _ALLOWED_FIELDS)
        except FireAntClientError:
            field_map_ok = False
        query_ok = False
        try:
            _load_json_object(settings.fireant_bars_query_json, "FIREANT_BARS_QUERY_JSON")
            query_ok = True
        except FireAntClientError:
            query_ok = False
        base_ok = base.scheme == "https" and bool(base.netloc) and not base.username and not base.password
        ready = bool(
            settings.fireant_license_confirmed and settings.fireant_api_token
            and endpoint_configured and base_ok and field_map_ok and query_ok
        )
        return {
            "provider": "fireant",
            "credential_present": bool(settings.fireant_api_token),
            "license_confirmed": bool(settings.fireant_license_confirmed),
            "base_url_https": base_ok,
            "endpoint_configured": endpoint_configured,
            "field_map_configured": field_map_ok,
            "query_template_valid": query_ok,
            "ready": ready,
            "network_tested": False,
        }

    def _build_params(self, symbol: str, count_back: int, to_epoch: int | None) -> dict[str, Any]:
        replacements = {
            "symbol": symbol,
            "count_back": str(count_back),
            "to_epoch": str(to_epoch if to_epoch is not None else int(time.time())),
        }
        rendered: dict[str, Any] = {}
        for key, raw_value in self.query_template.items():
            if isinstance(raw_value, str):
                value = _PLACEHOLDER_RE.sub(lambda match: replacements[match.group(1)], raw_value)
                # Catch unrecognized format-like placeholders rather than sending them silently.
                if "{" in value or "}" in value:
                    raise FireAntClientError("Query template có placeholder không được hỗ trợ.")
                rendered[key] = value
            elif raw_value is None or isinstance(raw_value, (int, float, bool)):
                rendered[key] = raw_value
            else:
                raise FireAntClientError("Query template chỉ hỗ trợ giá trị vô hướng.")
        return rendered

    async def fetch_daily_bars(self, symbol: str, *, count_back: int = 250, to_epoch: int | None = None) -> dict[str, Any]:
        try:
            safe_symbol = normalize_symbol(symbol)
        except (NormalizationError, AttributeError, TypeError) as exc:
            raise FireAntClientError("Mã chứng khoán không hợp lệ.") from exc
        if not isinstance(count_back, int) or isinstance(count_back, bool) or not 1 <= count_back <= 5000:
            raise FireAntClientError("count_back phải nằm trong khoảng 1–5000.")
        params = self._build_params(safe_symbol, count_back, to_epoch)
        request_path = self.bars_path.replace("{symbol}", quote(safe_symbol, safe=""))
        headers = {"Authorization": f"{self.auth_scheme} {self.token}", "Accept": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(self.timeout_seconds), transport=self.transport) as client:
                response = await client.get(f"{self.base_url}{request_path}", params=params, headers=headers)
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            # Do not expose URL, body, request headers, or bearer token.
            raise FireAntClientError(f"FireAnt trả HTTP {status}; kiểm tra quyền DataFeed, token và giới hạn tần suất.") from None
        except (httpx.HTTPError, ValueError) as exc:
            # httpx exceptions may carry URLs; sanitize to class name only.
            raise FireAntClientError(f"Không lấy được dữ liệu FireAnt ({type(exc).__name__}).") from None
        if not isinstance(payload, dict):
            raise FireAntClientError("Cấu trúc phản hồi FireAnt phải là object JSON.")
        rows: Any = payload
        for segment in self.data_key.split("."):
            if not isinstance(rows, Mapping) or segment not in rows:
                raise FireAntClientError("Phản hồi FireAnt không có data key đã cấu hình.")
            rows = rows[segment]
        if not isinstance(rows, list):
            raise FireAntClientError("Trường dữ liệu FireAnt phải là danh sách.")
        if len(rows) > count_back:
            raise FireAntClientError("FireAnt trả nhiều nến hơn count_back; từ chối dữ liệu không khớp hợp đồng.")
        mapped_rows = [map_fireant_bar_record(row, self.field_map) for row in rows]
        return {"ticker": safe_symbol, "data": mapped_rows}

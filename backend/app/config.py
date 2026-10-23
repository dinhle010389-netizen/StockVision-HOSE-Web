from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_env: str = os.getenv("APP_ENV", "development")
    app_host: str = os.getenv("APP_HOST", "0.0.0.0")
    app_port: int = int(os.getenv("APP_PORT", "8000"))
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()
    app_access_password: str = os.getenv("APP_ACCESS_PASSWORD", "")
    app_session_secret: str = os.getenv("APP_SESSION_SECRET", "dev-only-change-before-deploy")
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./stockvision_local.db")
    auto_create_tables: bool = _bool("AUTO_CREATE_TABLES", True)
    demo_mode: bool = _bool("DEMO_MODE", True)
    redis_url: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    tcbs_base_url: str = os.getenv("TCBS_BASE_URL", "https://openapi.tcbs.com.vn").rstrip("/")
    tcbs_api_token: str = os.getenv("TCBS_API_TOKEN", "")
    tcbs_symbols: tuple[str, ...] = tuple(
        symbol.strip().upper()
        for symbol in os.getenv("TCBS_SYMBOLS", "FPT,VCB,HPG,SSI,MWG,TCB,VIC,VHM").split(",")
        if symbol.strip()
    )
    tcbs_rest_requests_per_second: float = max(
        0.1, float(os.getenv("TCBS_REST_REQUESTS_PER_SECOND", "5"))
    )
    enable_tcbs_stream: bool = _bool("ENABLE_TCBS_STREAM", False)
    market_data_provider: str = os.getenv("MARKET_DATA_PROVIDER", "public").strip().lower()
    public_data_auto_sync_on_startup: bool = _bool("PUBLIC_DATA_AUTO_SYNC_ON_STARTUP", True)
    public_data_sync_interval_minutes: int = int(os.getenv("PUBLIC_DATA_SYNC_INTERVAL_MINUTES", "60"))
    public_data_lookback_days: int = int(os.getenv("PUBLIC_DATA_LOOKBACK_DAYS", "730"))
    public_data_cache_ttl_seconds: int = int(os.getenv("PUBLIC_DATA_CACHE_TTL_SECONDS", "900"))
    public_data_symbols: tuple[str, ...] = tuple(
        symbol.strip().upper()
        for symbol in os.getenv("PUBLIC_DATA_SYMBOLS", "FPT,VCB,HPG,SSI,MWG,TCB,VIC,VHM").split(",")
        if symbol.strip()
    )
    public_data_index_symbols: tuple[str, ...] = tuple(
        symbol.strip().upper()
        for symbol in os.getenv("PUBLIC_DATA_INDEX_SYMBOLS", "VNINDEX,VN30").split(",")
        if symbol.strip()
    )
    fireant_base_url: str = os.getenv("FIREANT_BASE_URL", "https://api.fireant.vn").rstrip("/")
    fireant_api_token: str = os.getenv("FIREANT_API_TOKEN", "")
    fireant_license_confirmed: bool = _bool("FIREANT_LICENSE_CONFIRMED", False)
    fireant_bars_path: str = os.getenv("FIREANT_BARS_PATH", "")
    fireant_bars_query_json: str = os.getenv("FIREANT_BARS_QUERY_JSON", "{}")
    fireant_bars_data_key: str = os.getenv("FIREANT_BARS_DATA_KEY", "data")
    fireant_auth_scheme: str = os.getenv("FIREANT_AUTH_SCHEME", "Bearer")
    fireant_auto_sync_on_startup: bool = _bool("FIREANT_AUTO_SYNC_ON_STARTUP", False)
    fireant_symbols: tuple[str, ...] = tuple(
        symbol.strip().upper()
        for symbol in os.getenv("FIREANT_SYMBOLS", "FPT,VCB,HPG,SSI,MWG,TCB,VIC,VHM").split(",")
        if symbol.strip()
    )
    fireant_count_back: int = int(os.getenv("FIREANT_COUNT_BACK", "250"))
    fireant_timeout_seconds: float = float(os.getenv("FIREANT_TIMEOUT_SECONDS", "12"))
    fireant_bar_field_map_json: str = os.getenv(
        "FIREANT_BAR_FIELD_MAP_JSON",
        '{"date":"date","open":"open","high":"high","low":"low","close":"close","volume":"volume","value":"value","adjusted_close":"adjustedClose","is_final":"isFinal"}',
    )


settings = Settings()

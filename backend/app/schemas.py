from __future__ import annotations

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict


class HealthResponse(BaseModel):
    status: str
    database: str
    demo_mode: bool
    tcbs_stream_enabled: bool
    timestamp: datetime


class Breadth(BaseModel):
    advancers: int = 0
    decliners: int = 0
    unchanged: int = 0
    observed: int = 0
    advance_decline_ratio: float | None = None


class IndexSummary(BaseModel):
    symbol: str
    label: str
    last: float | None = None
    change: float | None = None
    change_pct: float | None = None
    updated_at: datetime | None = None
    is_demo: bool = False


class StockMover(BaseModel):
    symbol: str
    company_name: str | None = None
    last_price: float | None = None
    change_value: float | None = None
    change_pct: float | None = None
    volume: int | None = None
    matched_value: float | None = None
    updated_at: datetime | None = None
    is_demo: bool = False


class MarketOverviewResponse(BaseModel):
    exchange: str = "HOSE"
    as_of: datetime
    data_mode: Literal["demo", "database", "empty"]
    is_demo: bool
    message: str
    breadth_scope: Literal["market", "tracked_universe", "none"] = "none"
    tracked_value_total: float | None = None
    freshness_seconds: float | None = None
    breadth: Breadth
    indices: list[IndexSummary]
    leaders: list[StockMover]
    laggards: list[StockMover]
    active_stocks: list[StockMover] = Field(default_factory=list)


class InstrumentSummary(BaseModel):
    symbol: str
    exchange_code: str
    company_name: str | None = None
    sector_code: str | None = None
    currency: str = "VND"
    is_active: bool = True


class CovarianceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbols: list[str] = Field(min_length=1, max_length=80)
    # Rows are sessions; columns map to symbols in the same order.
    returns: list[list[float]] = Field(min_length=3, max_length=5000)


class CovarianceResponse(BaseModel):
    symbols: list[str]
    observations: int
    covariance: list[list[float]]
    risk_spectrum: dict
    interpretation: str

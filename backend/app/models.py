from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

JSON_TYPE = JSON().with_variant(JSONB, "postgresql")


class DataSource(Base):
    __tablename__ = "data_source"

    source_id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(Text, nullable=False, default="broker_api")
    base_url: Mapped[str | None] = mapped_column(Text)
    license_status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class Instrument(Base):
    __tablename__ = "instrument"
    __table_args__ = (
        UniqueConstraint("symbol", "exchange_code", "valid_from", name="uq_instrument_symbol_exchange_validfrom"),
        CheckConstraint("price_scale > 0", name="ck_instrument_price_scale_positive"),
        Index("ix_instrument_symbol", "symbol"),
        Index("ix_instrument_exchange_active", "exchange_code", "is_active"),
    )

    instrument_id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(16), nullable=False)
    exchange_code: Mapped[str] = mapped_column(String(12), nullable=False, default="HOSE")
    instrument_type: Mapped[str] = mapped_column(String(24), nullable=False, default="equity")
    company_name: Mapped[str | None] = mapped_column(Text)
    sector_code: Mapped[str | None] = mapped_column(String(40))
    industry_code: Mapped[str | None] = mapped_column(String(60))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="VND")
    price_scale: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal("1"))
    lot_size: Mapped[int | None] = mapped_column(Integer)
    listing_date: Mapped[date | None] = mapped_column(Date)
    delisting_date: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_id: Mapped[int | None] = mapped_column(ForeignKey("data_source.source_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class QuoteSnapshot(Base):
    __tablename__ = "quote_snapshot"
    __table_args__ = (
        Index("ix_quote_time", "quote_time"),
    )

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.instrument_id"), primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_source.source_id"), primary_key=True)
    quote_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    change_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    change_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    reference_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    ceiling_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    floor_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    open_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    high_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    low_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    matched_volume: Mapped[int | None] = mapped_column(BigInteger)
    matched_value: Mapped[Decimal | None] = mapped_column(Numeric(28, 4))
    quality_flags: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False, default=list)
    raw_event_id: Mapped[int | None] = mapped_column(BigInteger)


class OHLCVBar(Base):
    __tablename__ = "ohlcv_bar"
    __table_args__ = (
        CheckConstraint("bar_end > bar_start", name="ck_ohlcv_bar_end_after_start"),
        CheckConstraint("open_price > 0 AND high_price > 0 AND low_price > 0 AND close_price > 0", name="ck_ohlcv_prices_positive"),
        CheckConstraint("volume >= 0", name="ck_ohlcv_volume_nonnegative"),
        Index("ix_ohlcv_symbol_time", "instrument_id", "timeframe", "bar_start"),
    )

    instrument_id: Mapped[int] = mapped_column(ForeignKey("instrument.instrument_id"), primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_source.source_id"), primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(8), primary_key=True)
    bar_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    bar_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open_price: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    high_price: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    low_price: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    close_price: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    value_traded: Mapped[Decimal | None] = mapped_column(Numeric(28, 4))
    adjusted_close: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    corporate_action_version: Mapped[str | None] = mapped_column(Text)
    quality_flags: Mapped[list[str]] = mapped_column(JSON_TYPE, nullable=False, default=list)
    raw_event_id: Mapped[int | None] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())


class IndexBar(Base):
    __tablename__ = "index_bar"

    index_code: Mapped[str] = mapped_column(String(24), primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("data_source.source_id"), primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(8), primary_key=True)
    bar_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    bar_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    high_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    low_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    close_value: Mapped[Decimal] = mapped_column(Numeric(20, 6), nullable=False)
    change_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 6))
    change_pct: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    volume: Mapped[int | None] = mapped_column(BigInteger)
    advancers: Mapped[int | None] = mapped_column(Integer)
    decliners: Mapped[int | None] = mapped_column(Integer)
    unchanged_count: Mapped[int | None] = mapped_column(Integer)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

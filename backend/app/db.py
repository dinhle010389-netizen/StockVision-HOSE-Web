from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


def normalize_database_url(value: str) -> str:
    """Normalize managed Postgres URLs for the psycopg v3 SQLAlchemy driver."""
    value = value.strip()
    if value.startswith("postgres://"):
        return "postgresql+psycopg://" + value[len("postgres://"):]
    if value.startswith("postgresql://"):
        return "postgresql+psycopg://" + value[len("postgresql://"):]
    return value


_connect_args: dict = {}
_database_url = normalize_database_url(settings.database_url)

if _database_url.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}
elif _database_url.startswith("postgresql+"):
    # 001_init.sql creates schema sv; keep ORM lookups aligned to it.
    _connect_args = {"options": "-csearch_path=sv,public"}

engine = create_engine(
    _database_url,
    echo=False,
    pool_pre_ping=True,
    connect_args=_connect_args,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

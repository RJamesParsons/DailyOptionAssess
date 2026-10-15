"""Database tables. Only extracted fills are stored: no PDF, no name, no address, account last 4."""
from __future__ import annotations

import json
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import (Boolean, Date, DateTime, ForeignKey, Integer, String, Text, Time,
                        TypeDecorator, UniqueConstraint, create_engine)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from . import config


class Money(TypeDecorator):
    """Exact decimals stored as text so SQLite and Postgres behave identically (never floats)."""
    impl = String(40)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else format(Decimal(value), "f")

    def process_result_value(self, value, dialect):
        return None if value is None else Decimal(value)


class Base(DeclarativeBase):
    pass


class Import(Base):
    __tablename__ = "import"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    processing_date: Mapped[date] = mapped_column(Date, index=True)
    page_count: Mapped[int | None] = mapped_column(Integer)
    file_hash: Mapped[str] = mapped_column(String(64), unique=True)
    account_last4: Mapped[str | None] = mapped_column(String(4))
    fill_count: Mapped[int] = mapped_column(Integer, default=0)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    fills: Mapped[list["FillRow"]] = relationship(back_populates="import_")


class FillRow(Base):
    __tablename__ = "fill"
    __table_args__ = (UniqueConstraint("trade_date", "trade_number"),)  # broker reuses numbers across days
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    import_id: Mapped[int] = mapped_column(ForeignKey("import.id"))
    trade_date: Mapped[date] = mapped_column(Date, index=True)
    trade_number: Mapped[str] = mapped_column(String(20))
    exec_time: Mapped[time] = mapped_column(Time)
    side: Mapped[str] = mapped_column(String(6))
    open_close: Mapped[str] = mapped_column(String(5))
    is_settlement: Mapped[bool] = mapped_column(Boolean, default=False)
    underlying: Mapped[str] = mapped_column(String(10), index=True)
    expiry: Mapped[date] = mapped_column(Date)
    right: Mapped[str] = mapped_column(String(1))
    strike: Mapped[Decimal] = mapped_column(Money)
    quantity: Mapped[int] = mapped_column(Integer)
    price: Mapped[Decimal] = mapped_column(Money)
    principal: Mapped[Decimal] = mapped_column(Money)
    fees_json: Mapped[str] = mapped_column(Text)          # {"commission": "1.50", ...}
    net_amount: Mapped[Decimal] = mapped_column(Money)
    fee_source: Mapped[str] = mapped_column(String(10), default="actual")
    import_: Mapped[Import] = relationship(back_populates="fills")

    @property
    def fees(self) -> dict:
        return {k: Decimal(v) for k, v in json.loads(self.fees_json).items()}


class TradeNote(Base):
    """Keyed by the trade's first entry fill (date + trade number), which never changes."""
    __tablename__ = "trade_note"
    trade_key: Mapped[str] = mapped_column(String(40), primary_key=True)
    market_condition: Mapped[str] = mapped_column(String(40), default="")
    learnings: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(Text, default="")     # semicolon-separated
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


_engine = None
_Session = None


def init_db(url: str | None = None):
    global _engine, _Session
    url = url or config.DATABASE_URL
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {"pool_pre_ping": True}
    _engine = create_engine(url, **kwargs)
    Base.metadata.create_all(_engine)
    _Session = sessionmaker(_engine, expire_on_commit=False)
    return _engine


def session():
    if _Session is None:
        init_db()
    return _Session()

"""
db/database.py — SQLite database with SQLAlchemy ORM.
Tables: users, subscriptions, trades, signals_log, admin_actions
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey,
    Integer, String, Text, create_engine, event
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

DB_PATH = os.environ.get("DB_PATH", "whalex.db")
engine  = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
    echo=False,
)

# WAL mode for better concurrency
@event.listens_for(engine, "connect")
def set_sqlite_pragma(conn, _):
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


# ── Models ────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id               = Column(Integer, primary_key=True, index=True)
    uid              = Column(String(36), unique=True, index=True, nullable=False)   # UUID
    username         = Column(String(80), unique=True, index=True)
    email            = Column(String(120), unique=True, index=True)
    hashed_password  = Column(String(200))
    subscription_tier= Column(String(20), default="free", nullable=False)  # free | pro
    is_active        = Column(Boolean, default=True)
    is_admin         = Column(Boolean, default=False)
    created_at       = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    last_login       = Column(DateTime, nullable=True)
    wallet_address   = Column(String(120), nullable=True)
    referral_code    = Column(String(20), nullable=True)
    total_trades     = Column(Integer, default=0)
    total_volume     = Column(Float, default=0.0)

    subscription  = relationship("Subscription", back_populates="user", uselist=False)
    trades        = relationship("TradeLog", back_populates="user")
    payments      = relationship("Payment", back_populates="user")


class Subscription(Base):
    __tablename__ = "subscriptions"

    id           = Column(Integer, primary_key=True)
    user_id      = Column(Integer, ForeignKey("users.id"), unique=True)
    plan         = Column(String(20), default="free")   # free | pro | enterprise
    price_paid   = Column(Float, default=0.0)
    currency     = Column(String(10), default="USDT")
    tx_hash      = Column(String(120), nullable=True)
    started_at   = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    expires_at   = Column(DateTime, nullable=True)       # None = lifetime
    auto_renew   = Column(Boolean, default=False)
    cancelled_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="subscription")


class TradeLog(Base):
    __tablename__ = "trades"

    id         = Column(Integer, primary_key=True)
    user_id    = Column(Integer, ForeignKey("users.id"))
    symbol     = Column(String(30))
    direction  = Column(String(10))
    trade_type = Column(String(20))
    amount     = Column(Float)
    leverage   = Column(Integer, default=1)
    chain      = Column(String(20))
    dex        = Column(String(30), nullable=True)
    tx_hash    = Column(String(120), nullable=True)
    gas_fee    = Column(Float, default=0.0)
    status     = Column(String(20), default="executed")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="trades")


class Payment(Base):
    __tablename__ = "payments"

    id          = Column(Integer, primary_key=True)
    user_id     = Column(Integer, ForeignKey("users.id"))
    amount      = Column(Float)
    currency    = Column(String(10), default="USDT")
    plan        = Column(String(20))
    tx_hash     = Column(String(120), nullable=True)
    chain       = Column(String(20))
    status      = Column(String(20), default="pending")   # pending | confirmed | failed | refunded
    created_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    confirmed_at= Column(DateTime, nullable=True)

    user = relationship("User", back_populates="payments")


class SignalLog(Base):
    __tablename__ = "signals_log"

    id          = Column(Integer, primary_key=True)
    signal_id   = Column(String(36))
    symbol      = Column(String(30))
    direction   = Column(String(10))
    grade       = Column(String(5))
    confidence  = Column(Integer)
    entry       = Column(Float)
    sl          = Column(Float)
    tp1         = Column(Float)
    tp2         = Column(Float)
    tp3         = Column(Float)
    chain       = Column(String(20))
    created_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class AdminAction(Base):
    __tablename__ = "admin_actions"

    id          = Column(Integer, primary_key=True)
    admin_id    = Column(Integer, ForeignKey("users.id"))
    action      = Column(String(100))
    target_type = Column(String(30), nullable=True)   # user | subscription | signal
    target_id   = Column(String(50), nullable=True)
    detail      = Column(Text, nullable=True)
    created_at  = Column(DateTime, default=lambda: datetime.now(timezone.utc))


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    Base.metadata.create_all(bind=engine)


def seed_admin(db: Session):
    """Create default admin user if not exists."""
    import uuid, hashlib
    existing = db.query(User).filter(User.username == "admin").first()
    if existing:
        return
    admin = User(
        uid               = str(uuid.uuid4()),
        username          = "admin",
        email             = "admin@whalex.io",
        hashed_password   = hashlib.sha256(b"admin1234").hexdigest(),
        subscription_tier = "pro",
        is_active         = True,
        is_admin          = True,
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    sub = Subscription(user_id=admin.id, plan="pro", price_paid=0.0)
    db.add(sub)
    db.commit()

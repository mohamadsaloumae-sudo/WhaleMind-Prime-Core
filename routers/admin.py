"""
routers/admin.py — /api/admin/* — Admin-only endpoints.
Requires is_admin=True on the JWT; regular PRO users are rejected.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from core.auth import require_admin
from core.websocket_manager import ws_manager
from db.database import (
    AdminAction, Payment, Subscription, TradeLog, User, get_db,
)
from models.schemas import (
    AdminBanRequest, AdminSetTierRequest, AdminStatsView, AdminUserView,
    SubscriptionPlan,
)
from services import signals_service

router  = APIRouter(prefix="/api/admin", tags=["Admin"])
logger  = logging.getLogger(__name__)


def _log(db: Session, admin: User, action: str, target_type: str = "", target_id: str = "", detail: str = ""):
    db.add(AdminAction(
        admin_id=admin.id, action=action,
        target_type=target_type, target_id=target_id, detail=detail,
    ))
    db.commit()


# ── Dashboard stats ────────────────────────────────────────────────────────────

@router.get("/stats", response_model=AdminStatsView)
def admin_stats(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    total_users   = db.query(func.count(User.id)).scalar()
    pro_users     = db.query(func.count(User.id)).filter(User.subscription_tier == "pro").scalar()
    free_users    = total_users - pro_users
    total_trades  = db.query(func.count(TradeLog.id)).scalar()
    total_volume  = db.query(func.sum(TradeLog.amount)).scalar() or 0.0
    total_revenue = db.query(func.sum(Payment.amount)).filter(Payment.status == "confirmed").scalar() or 0.0
    return AdminStatsView(
        total_users    = total_users,
        pro_users      = pro_users,
        free_users     = free_users,
        total_trades   = total_trades,
        total_volume   = round(total_volume, 2),
        total_revenue  = round(total_revenue, 2),
        active_signals = len(signals_service.get_signals()),
        ws_connections = len(ws_manager._connections),
    )


# ── User management ────────────────────────────────────────────────────────────

@router.get("/users", response_model=list[AdminUserView])
def list_users(
    page:   int = Query(1, ge=1),
    limit:  int = Query(50, le=200),
    search: Optional[str] = Query(None),
    tier:   Optional[str] = Query(None),
    admin:  User    = Depends(require_admin),
    db:     Session = Depends(get_db),
):
    q = db.query(User)
    if search:
        q = q.filter(
            (User.username.ilike(f"%{search}%")) | (User.email.ilike(f"%{search}%"))
        )
    if tier:
        q = q.filter(User.subscription_tier == tier)
    users = q.order_by(desc(User.created_at)).offset((page - 1) * limit).limit(limit).all()
    return [AdminUserView(
        id=u.id, uid=u.uid, username=u.username, email=u.email,
        subscription_tier=u.subscription_tier, is_active=u.is_active,
        is_admin=u.is_admin, created_at=u.created_at,
        total_trades=u.total_trades, total_volume=u.total_volume,
    ) for u in users]


@router.post("/users/set-tier")
def set_user_tier(
    body:  AdminSetTierRequest,
    admin: User    = Depends(require_admin),
    db:    Session = Depends(get_db),
):
    user = db.query(User).filter(User.uid == body.user_uid).first()
    if not user:
        raise HTTPException(404, "User not found")
    old_tier = user.subscription_tier
    user.subscription_tier = body.tier.value

    sub = db.query(Subscription).filter(Subscription.user_id == user.id).first()
    if sub:
        sub.plan = body.tier.value
        if body.tier.value == "pro" and not sub.expires_at:
            from datetime import timedelta
            sub.expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    else:
        db.add(Subscription(user_id=user.id, plan=body.tier.value))

    db.commit()
    _log(db, admin, "set_tier", "user", body.user_uid, f"{old_tier} → {body.tier.value}")
    logger.info("Admin %s set user %s tier: %s → %s", admin.username, body.user_uid, old_tier, body.tier.value)
    return {"status": "ok", "uid": body.user_uid, "new_tier": body.tier.value}


@router.post("/users/ban")
def ban_user(
    body:  AdminBanRequest,
    admin: User    = Depends(require_admin),
    db:    Session = Depends(get_db),
):
    if body.user_uid == admin.uid:
        raise HTTPException(400, "Cannot ban yourself")
    user = db.query(User).filter(User.uid == body.user_uid).first()
    if not user:
        raise HTTPException(404, "User not found")
    user.is_active = False
    db.commit()
    _log(db, admin, "ban_user", "user", body.user_uid, body.reason)
    return {"status": "banned", "uid": body.user_uid}


@router.post("/users/unban")
def unban_user(
    body:  AdminBanRequest,
    admin: User    = Depends(require_admin),
    db:    Session = Depends(get_db),
):
    user = db.query(User).filter(User.uid == body.user_uid).first()
    if not user:
        raise HTTPException(404, "User not found")
    user.is_active = True
    db.commit()
    _log(db, admin, "unban_user", "user", body.user_uid, body.reason)
    return {"status": "unbanned", "uid": body.user_uid}


@router.delete("/users/{user_uid}")
def delete_user(
    user_uid: str,
    admin:    User    = Depends(require_admin),
    db:       Session = Depends(get_db),
):
    if user_uid == admin.uid:
        raise HTTPException(400, "Cannot delete yourself")
    user = db.query(User).filter(User.uid == user_uid).first()
    if not user:
        raise HTTPException(404, "User not found")
    db.delete(user)
    db.commit()
    _log(db, admin, "delete_user", "user", user_uid)
    return {"status": "deleted"}


# ── Trade logs ─────────────────────────────────────────────────────────────────

@router.get("/trades")
def list_trades(
    page:   int = Query(1, ge=1),
    limit:  int = Query(50, le=200),
    admin:  User    = Depends(require_admin),
    db:     Session = Depends(get_db),
):
    trades = (
        db.query(TradeLog)
        .order_by(desc(TradeLog.created_at))
        .offset((page - 1) * limit).limit(limit).all()
    )
    return [{
        "id": t.id, "user_id": t.user_id, "symbol": t.symbol,
        "direction": t.direction, "amount": t.amount, "leverage": t.leverage,
        "chain": t.chain, "dex": t.dex, "gas_fee": t.gas_fee,
        "status": t.status, "created_at": t.created_at.isoformat(),
    } for t in trades]


# ── Payments ───────────────────────────────────────────────────────────────────

@router.get("/payments")
def list_payments(
    page:  int = Query(1, ge=1),
    limit: int = Query(50, le=200),
    admin: User    = Depends(require_admin),
    db:    Session = Depends(get_db),
):
    payments = (
        db.query(Payment)
        .order_by(desc(Payment.created_at))
        .offset((page - 1) * limit).limit(limit).all()
    )
    return [{
        "id": p.id, "user_id": p.user_id, "amount": p.amount,
        "currency": p.currency, "plan": p.plan, "tx_hash": p.tx_hash,
        "chain": p.chain, "status": p.status,
        "created_at": p.created_at.isoformat(),
    } for p in payments]


# ── Signal management ──────────────────────────────────────────────────────────

@router.get("/signals")
def admin_signals(admin: User = Depends(require_admin)):
    return {"signals": signals_service.get_signals(), "count": len(signals_service.get_signals())}


@router.post("/signals/broadcast")
async def broadcast_signal(
    signal: dict,
    admin:  User = Depends(require_admin),
    db:     Session = Depends(get_db),
):
    """Manually push a signal to all connected WebSocket clients."""
    await ws_manager.broadcast("new_signal", signal)
    _log(db, admin, "broadcast_signal", "signal", signal.get("id", ""), str(signal.get("symbol")))
    return {"status": "broadcasted", "connections": len(ws_manager._connections)}


# ── Action log ─────────────────────────────────────────────────────────────────

@router.get("/audit-log")
def audit_log(
    page:  int = Query(1, ge=1),
    limit: int = Query(100, le=500),
    admin: User    = Depends(require_admin),
    db:    Session = Depends(get_db),
):
    actions = (
        db.query(AdminAction)
        .order_by(desc(AdminAction.created_at))
        .offset((page - 1) * limit).limit(limit).all()
    )
    return [{
        "id": a.id, "admin_id": a.admin_id, "action": a.action,
        "target_type": a.target_type, "target_id": a.target_id,
        "detail": a.detail, "created_at": a.created_at.isoformat(),
    } for a in actions]


# ── WebSocket broadcast ────────────────────────────────────────────────────────

@router.post("/broadcast")
async def admin_broadcast(
    payload: dict,
    admin:   User = Depends(require_admin),
):
    event = payload.get("event", "admin_message")
    data  = payload.get("data", {})
    await ws_manager.broadcast(event, data)
    return {"status": "sent", "connections": len(ws_manager._connections)}

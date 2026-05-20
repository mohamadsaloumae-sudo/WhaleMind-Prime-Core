"""
routers/subscription.py — /api/subscription/* endpoints.
Handles plan info, upgrade payment, and status check.
"""
from __future__ import annotations

import uuid
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from core.auth import get_current_user
from db.database import User, Subscription, Payment, get_db
from models.schemas import (
    PlanInfo, SubscriptionPlan, SubscriptionStatus,
    UpgradeRequest, UpgradeResponse,
)

router = APIRouter(prefix="/api/subscription", tags=["Subscription"])
logger = logging.getLogger(__name__)

PRO_PRICE_USDT  = 29.0
PRO_DURATION_DAYS = 30

PLANS: dict[str, PlanInfo] = {
    "free": PlanInfo(
        plan="free", price=0.0, currency="USDT",
        features=[
            "Access Wallet & Trading screens",
            "Futures / Spot / Swap execution",
            "Basic auto-trade (manual only)",
            "Standard gas fees apply",
        ],
    ),
    "pro": PlanInfo(
        plan="pro", price=PRO_PRICE_USDT, currency="USDT",
        features=[
            "Everything in Free",
            "Live AI Signal Feed (unlimited)",
            "WhaleX AI Assistant (24/7)",
            "Meme Coin Rug-Pull Scanner",
            "10 AI analysis strategies",
            "Trade on 6 networks",
            "Priority support",
        ],
    ),
}


@router.get("/plans", response_model=list[PlanInfo])
def get_plans():
    return list(PLANS.values())


@router.get("/status", response_model=SubscriptionStatus)
def get_status(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sub = db.query(Subscription).filter(Subscription.user_id == user.id).first()
    if not sub:
        return SubscriptionStatus(tier="free", plan="free", expires_at=None, is_active=False)
    exp = sub.expires_at.isoformat() if sub.expires_at else None
    active = True
    if sub.expires_at and sub.expires_at < datetime.now(timezone.utc):
        # Expired — downgrade
        user.subscription_tier = "free"
        sub.plan = "free"
        db.commit()
        active = False
    return SubscriptionStatus(
        tier      = user.subscription_tier,
        plan      = sub.plan,
        expires_at= exp,
        is_active = active,
    )


@router.post("/upgrade", response_model=UpgradeResponse)
async def upgrade(
    body: UpgradeRequest,
    user: User = Depends(get_current_user),
    db:   Session = Depends(get_db),
):
    """
    Upgrade a user to PRO.

    Flow:
    1. Verify the on-chain tx_hash confirms the correct USDT payment.
    2. Update subscription_tier in the DB.
    3. Return success so frontend unlocks the PRO UI.

    In production: call your chain's RPC to verify the tx_hash really sent
    PRO_PRICE_USDT to the platform wallet before upgrading.
    """
    if user.subscription_tier == "pro":
        sub = db.query(Subscription).filter(Subscription.user_id == user.id).first()
        exp_str = sub.expires_at.isoformat() if sub and sub.expires_at else None
        return UpgradeResponse(
            status="already_pro", plan="pro",
            message="Account is already PRO.", expires_at=exp_str,
        )

    # ── Payment verification stub ─────────────────────────────────────────────
    # TODO: Replace with real on-chain verification:
    # tx = await verify_tx_on_chain(body.tx_hash, body.chain, PRO_PRICE_USDT)
    # if not tx.verified: raise HTTPException(402, "Payment not confirmed")
    tx_hash = body.tx_hash or ("demo_" + uuid.uuid4().hex[:16])

    # ── Record payment ────────────────────────────────────────────────────────
    payment = Payment(
        user_id    = user.id,
        amount     = PRO_PRICE_USDT,
        currency   = "USDT",
        plan       = "pro",
        tx_hash    = tx_hash,
        chain      = body.chain.value,
        status     = "confirmed",
        confirmed_at = datetime.now(timezone.utc),
    )
    db.add(payment)

    # ── Upgrade user ──────────────────────────────────────────────────────────
    user.subscription_tier = "pro"
    expires = datetime.now(timezone.utc) + timedelta(days=PRO_DURATION_DAYS)

    sub = db.query(Subscription).filter(Subscription.user_id == user.id).first()
    if sub:
        sub.plan       = "pro"
        sub.price_paid = PRO_PRICE_USDT
        sub.currency   = "USDT"
        sub.tx_hash    = tx_hash
        sub.started_at = datetime.now(timezone.utc)
        sub.expires_at = expires
        sub.cancelled_at = None
    else:
        sub = Subscription(
            user_id    = user.id, plan="pro",
            price_paid = PRO_PRICE_USDT, currency="USDT",
            tx_hash    = tx_hash,
            expires_at = expires,
        )
        db.add(sub)

    db.commit()
    logger.info("User %s upgraded to PRO | tx: %s", user.uid, tx_hash)

    return UpgradeResponse(
        status     = "upgraded",
        plan       = "pro",
        message    = "Upgrade successful! All PRO features are now unlocked.",
        expires_at = expires.isoformat(),
    )


@router.post("/cancel")
def cancel(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sub = db.query(Subscription).filter(Subscription.user_id == user.id).first()
    if not sub or sub.plan == "free":
        raise HTTPException(400, "No active subscription to cancel")
    sub.cancelled_at = datetime.now(timezone.utc)
    sub.auto_renew   = False
    db.commit()
    return {"status": "cancelled", "message": "Auto-renewal disabled. Access until expiry."}

"""
routers/signals.py — Live signals + stats.
GET /api/signals/live  → PRO only (403 for free tier)
GET /api/trades/stats  → all tiers
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.auth import require_pro, get_current_user
from db.database import User, get_db
from models.schemas import SignalsResponse, StatsResponse, Signal
from services import signals_service

router = APIRouter(prefix="/api", tags=["Signals"])


@router.get("/signals/live", response_model=SignalsResponse)
async def live_signals(user: User = Depends(require_pro)) -> SignalsResponse:
    """PRO ONLY — free tier gets HTTP 403; signal data is never leaked."""
    sigs = signals_service.get_signals()
    return SignalsResponse(signals=[Signal(**s) for s in sigs], count=len(sigs))


@router.get("/trades/stats", response_model=StatsResponse)
async def trade_stats(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    base = signals_service.get_stats()
    base["total_trades"] = user.total_trades
    return StatsResponse(**base)

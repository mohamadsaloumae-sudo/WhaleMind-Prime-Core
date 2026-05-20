"""
routers/trade.py — /api/trade/* endpoints.
"""
from fastapi import APIRouter, HTTPException

from models.schemas import TradeRequest, TradeResponse
from services import trade_service

router = APIRouter(prefix="/api/trade", tags=["Trade"])


@router.post("/execute", response_model=TradeResponse)
async def execute(body: TradeRequest) -> TradeResponse:
    try:
        return await trade_service.execute_trade(body)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

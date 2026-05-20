"""
routers/hft.py
All HFT API endpoints required by the blueprint.
GET  /api/radar/status    - live radar state + ML features (SSE)
GET  /api/trades/active   - live positions with SL/state
POST /api/account/switch  - toggle REAL ↔ DEMO
POST /api/radar/control   - admin override: force-close / score injection
"""
from __future__ import annotations
import asyncio, json, logging, time
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from hft.engine.context import GCM, AccountMode, TradeState
from hft.registry.trade_registry import REGISTRY

log = logging.getLogger("hft.router")
router = APIRouter(prefix="/api", tags=["HFT"])

# ── Pydantic models ───────────────────────────────────────────────────────────

class SwitchRequest(BaseModel):
    mode: str   # "REAL" or "DEMO"

class ControlRequest(BaseModel):
    action:        str              # "force_close_all" | "force_close_one" | "set_score" | "suppress" | "unsuppress"
    trade_id:      Optional[str] = None
    score_override:Optional[float]= None


# ── SSE helper ────────────────────────────────────────────────────────────────

async def _sse_generator(data_fn, interval: float = 0.5):
    while GCM.running:
        try:
            payload = data_fn()
            yield f"data: {json.dumps(payload)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        await asyncio.sleep(interval)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/radar/status")
async def radar_status(stream: bool = False):
    """
    Returns live radar state.
    Add ?stream=true for Server-Sent Events feed.
    """
    if stream:
        def _data():
            r = GCM.snapshot_radar()
            return {
                "ts":              r.ts,
                "composite_score": r.composite_score,
                "vpin":            r.vpin,
                "obi":             r.obi,
                "cvd_slope":       r.cvd_slope,
                "macro_weight":    r.macro_weight,
                "regime":          r.regime.value,
                "signal":          r.signal.value,
                "suppressed":      r.suppressed,
                "suppress_reason": r.suppress_reason,
                "liq_pool_above":  r.liq_pool_above,
                "liq_pool_below":  r.liq_pool_below,
                "feature_densities":r.feature_densities,
                "macro":           GCM.macro,
                "account_mode":    GCM.current_mode.value,
            }
        return StreamingResponse(_sse_generator(_data, 0.2),
                                  media_type="text/event-stream")

    r = GCM.snapshot_radar()
    return {
        "ts":               r.ts,
        "composite_score":  r.composite_score,
        "vpin":             r.vpin,
        "obi":              r.obi,
        "cvd_slope":        r.cvd_slope,
        "macro_weight":     r.macro_weight,
        "regime":           r.regime.value,
        "signal":           r.signal.value,
        "suppressed":       r.suppressed,
        "suppress_reason":  r.suppress_reason,
        "liq_pool_above":   r.liq_pool_above,
        "liq_pool_below":   r.liq_pool_below,
        "feature_densities":r.feature_densities,
        "macro":            GCM.macro,
        "account_mode":     GCM.current_mode.value,
        "vpin_history":     list(GCM.cvd_series)[-20:],
        "radar_history_len":len(GCM.radar_history),
    }


@router.get("/trades/active")
async def active_trades(stream: bool = False):
    """
    Returns all running positions with live SL, state, PnL.
    Add ?stream=true for SSE.
    """
    if stream:
        return StreamingResponse(
            _sse_generator(REGISTRY.get_active_positions, 0.5),
            media_type="text/event-stream",
        )
    return {
        "active":       REGISTRY.get_active_positions(),
        "closed":       REGISTRY.get_closed_trades(20),
        "demo_stats":   _get_hft_stats(),
        "account_mode": GCM.current_mode.value,
        "ts":           time.time(),
    }


@router.post("/account/switch")
async def switch_account(body: SwitchRequest):
    try:
        mode = AccountMode(body.mode.upper())
    except ValueError:
        raise HTTPException(400, f"Invalid mode '{body.mode}'. Use REAL or DEMO")

    # Force-close all positions before switching
    active = GCM.snapshot_active_trades()
    for t in active:
        await GCM.close_trade(t.trade_id, TradeState.CLOSED_MANUAL)

    await GCM.switch_mode(mode)
    GCM.enqueue_tg({
        "type":    "ACCOUNT_SWITCHED",
        "mode":    mode.value,
        "message": f"Account switched to {mode.value} mode",
    })
    return {
        "status":       "switched",
        "mode":         mode.value,
        "positions_closed": len(active),
        "demo_balance": GCM.demo_account.balance,
    }


@router.post("/radar/control")
async def radar_control(body: ControlRequest):
    action = body.action.lower()

    if action == "suppress":
        GCM.radar_suppressed = True
        return {"status": "ok", "radar_suppressed": True}

    elif action == "unsuppress":
        GCM.radar_suppressed  = False
        GCM.ai_score_override = None
        return {"status": "ok", "radar_suppressed": False}

    elif action == "set_score":
        if body.score_override is None:
            raise HTTPException(422, "score_override required")
        if not 0 <= body.score_override <= 100:
            raise HTTPException(422, "score must be 0–100")
        GCM.ai_score_override = body.score_override
        return {"status": "ok", "score_override": body.score_override}

    elif action == "force_close_all":
        trades = GCM.snapshot_active_trades()
        for t in trades:
            await GCM.close_trade(t.trade_id, TradeState.CLOSED_MANUAL)
        GCM.enqueue_tg({"type": "FORCE_CLOSE_ALL", "count": len(trades)})
        return {"status": "ok", "closed": len(trades)}

    elif action == "force_close_one":
        if not body.trade_id:
            raise HTTPException(422, "trade_id required")
        t = GCM.get_trade(body.trade_id)
        if not t:
            raise HTTPException(404, f"Trade {body.trade_id} not found")
        await GCM.close_trade(body.trade_id, TradeState.CLOSED_MANUAL)
        return {"status": "ok", "closed": body.trade_id}

    else:
        raise HTTPException(400, f"Unknown action '{action}'")


@router.get("/hft/stats")
async def hft_stats():
    return _get_hft_stats()


def _get_hft_stats() -> dict:
    acct = GCM.demo_account
    active = GCM.snapshot_active_trades()
    total_upnl = sum(t.unrealized_pnl for t in active)
    return {
        "demo_balance":     round(acct.balance, 2),
        "demo_equity":      round(acct.equity, 2),
        "demo_total_pnl":   round(acct.total_pnl, 2),
        "demo_win_rate":    round(acct.win_rate, 2),
        "demo_total_trades":acct.total_trades,
        "demo_wins":        acct.wins,
        "demo_losses":      acct.losses,
        "demo_max_drawdown":round(acct.max_drawdown * 100, 2),
        "active_trades":    len(active),
        "total_unrealized": round(total_upnl, 4),
        "mode":             GCM.current_mode.value,
        "radar_score":      GCM.radar.composite_score,
        "radar_regime":     GCM.radar.regime.value,
    }

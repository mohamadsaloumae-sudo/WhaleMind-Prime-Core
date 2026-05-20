"""
hft/registry/trade_registry.py
Central thread-safe registry bridging trade states to Telegram broadcasts.
"""
from __future__ import annotations
import asyncio, logging, time
from typing import Any, Dict, List, Optional
from hft.engine.context import GCM, AccountMode, ActiveTradeState, TradeState

log = logging.getLogger("hft.registry")

class ActiveTradeRegistry:
    def __init__(self) -> None:
        self._tg_task: Optional[asyncio.Task] = None

    async def start_telegram_bridge(self, send_fn) -> None:
        self._tg_task = asyncio.create_task(self._tg_loop(send_fn))

    async def _tg_loop(self, send_fn) -> None:
        while GCM.running:
            try:
                msg = await asyncio.wait_for(GCM.tg_queue.get(), timeout=1.0)
                await send_fn(msg)
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                log.debug("TG bridge error: %s", e)

    def get_active_positions(self) -> List[Dict[str, Any]]:
        trades = GCM.snapshot_active_trades()
        out = []
        for t in trades:
            out.append({
                "trade_id":        t.trade_id,
                "symbol":          t.signal.symbol,
                "direction":       t.signal.direction.value,
                "account_mode":    t.account_mode.value,
                "state":           t.state.value,
                "entry":           t.entry_price,
                "current_price":   t.current_price,
                "dynamic_sl":      round(t.dynamic_sl, 4),
                "tp1":             t.signal.tp1,
                "tp2":             t.signal.tp2,
                "tp3":             t.signal.tp3,
                "unrealized_pnl":  round(t.unrealized_pnl, 4),
                "realized_pnl":    round(t.realized_pnl, 4),
                "tp1_hit":         t.tp1_hit,
                "tp2_hit":         t.tp2_hit,
                "breakeven_locked":t.breakeven_locked,
                "explosion_active":t.explosion_active,
                "velocity":        round(t.velocity, 4),
                "loop_iters":      t.loop_iterations,
                "opened_at":       t.opened_at,
            })
        return out

    def get_closed_trades(self, limit: int = 50) -> List[Dict[str, Any]]:
        trades = GCM.closed_trades[-limit:]
        return [{
            "trade_id":    t.trade_id,
            "symbol":      t.signal.symbol,
            "direction":   t.signal.direction.value,
            "state":       t.state.value,
            "realized_pnl":round(t.realized_pnl, 4),
            "opened_at":   t.opened_at,
            "closed_at":   t.closed_at,
        } for t in reversed(trades)]


REGISTRY = ActiveTradeRegistry()

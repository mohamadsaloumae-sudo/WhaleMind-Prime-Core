"""
hft/simulator/demo_engine.py
═══════════════════════════════════════════════════════════════════════
PAPER TRADING / DEMO ACCOUNT SIMULATOR
- Mirrors real broker logic exactly (same Position Co-Pilot)
- Tracks virtual balance, unrealized/realized PnL, win rate
- Simulates slippage and fill quality
- All data persisted in GCM.demo_account
- Switch real → demo without touching exchange APIs
═══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from hft.engine.context import (
    GCM, AccountMode, ActiveTradeState, SignalDirection,
    TradeState, ValidatedSignal,
)
from hft.position.copilot import ActiveTradeInstance

log = logging.getLogger("hft.simulator")

# Slippage model (in price units)
SLIPPAGE_BPS  = 2   # 2 basis points on entry/exit
COMMISSION_BPS= 4   # 4 bps round-trip


@dataclass
class DemoTradeRecord:
    trade_id:     str
    symbol:       str
    direction:    str
    quantity:     float
    entry_price:  float
    sl_price:     float
    tp1:          float
    tp2:          float
    tp3:          float
    opened_at:    float = field(default_factory=time.time)
    closed_at:    Optional[float] = None
    close_price:  Optional[float] = None
    realized_pnl: float = 0.0
    max_unrealized_pnl: float = 0.0
    min_unrealized_pnl: float = 0.0
    state_history: List[str] = field(default_factory=list)
    final_state:  str = "ACTIVE"
    commission:   float = 0.0


class DemoSimulator:
    """
    Full-fidelity paper trading engine.

    Every validated signal from the radar that arrives in DEMO mode
    is routed here. The same ActiveTradeInstance co-pilot runs but
    closes positions by calling DemoSimulator.record_close() instead
    of exchange APIs.

    Virtual balance tracks every fill with realistic slippage.
    """

    def __init__(self) -> None:
        self._records: Dict[str, DemoTradeRecord] = {}
        self._running = False

    # ── Risk sizing for demo ───────────────────────────────────────────────────

    def _size_position(self, signal: ValidatedSignal) -> float:
        """
        Risk 1% of demo balance per trade.
        Size = (balance × 0.01) / (entry - sl) in base units.
        """
        balance = GCM.demo_account.balance
        risk    = balance * 0.01
        sl_dist = abs(signal.entry_price - signal.sl_price)
        if sl_dist < 1e-9:
            return 0.001
        qty = risk / sl_dist
        # Cap at 10% of balance / price
        max_qty = (balance * 0.10) / max(signal.entry_price, 1.0)
        return round(min(qty, max_qty), 6)

    def _apply_slippage(self, price: float, direction: SignalDirection, entering: bool) -> float:
        """Simulate realistic slippage on fills."""
        slip_amount = price * SLIPPAGE_BPS / 10_000
        if direction == SignalDirection.LONG:
            return price + slip_amount if entering else price - slip_amount
        else:
            return price - slip_amount if entering else price + slip_amount

    # ── Open a demo position ──────────────────────────────────────────────────

    async def open_demo_trade(self, signal: ValidatedSignal) -> str:
        trade_id = "D-" + str(uuid.uuid4())[:8].upper()
        qty      = self._size_position(signal)
        fill_px  = self._apply_slippage(signal.entry_price, signal.direction, entering=True)
        commission = fill_px * qty * COMMISSION_BPS / 10_000

        # Deduct commission from balance immediately
        GCM.demo_account.balance -= commission
        GCM.demo_account.equity   = GCM.demo_account.balance

        record = DemoTradeRecord(
            trade_id    = trade_id,
            symbol      = signal.symbol,
            direction   = signal.direction.value,
            quantity    = qty,
            entry_price = fill_px,
            sl_price    = signal.sl_price,
            tp1         = signal.tp1,
            tp2         = signal.tp2,
            tp3         = signal.tp3,
            commission  = commission,
        )
        self._records[trade_id] = record

        # Patch signal for the co-pilot to use the filled price
        signal_copy = ValidatedSignal(
            signal_id    = signal.signal_id,
            symbol       = signal.symbol,
            direction    = signal.direction,
            entry_price  = fill_px,
            sl_price     = signal.sl_price,
            tp1          = signal.tp1,
            tp2          = signal.tp2,
            tp3          = signal.tp3,
            score        = signal.score,
            radar        = signal.radar,
            account_mode = AccountMode.DEMO,
        )

        # Spawn the real co-pilot (same logic as live)
        instance = ActiveTradeInstance(signal_copy, qty)
        instance.trade_id = trade_id
        asyncio.create_task(instance.run(), name=trade_id)

        log.info(
            "[DEMO %s] Opened %s %s qty=%.6f fill=%.2f comm=%.4f",
            trade_id, signal.symbol, signal.direction.value, qty, fill_px, commission,
        )
        GCM.enqueue_tg({
            "type":      "DEMO_TRADE_OPENED",
            "trade":     trade_id,
            "symbol":    signal.symbol,
            "direction": signal.direction.value,
            "qty":       qty,
            "fill":      fill_px,
        })
        return trade_id

    # ── Periodic PnL update loop ──────────────────────────────────────────────

    async def _pnl_update_loop(self) -> None:
        """Update unrealized PnL and equity every 200 ms."""
        while self._running and GCM.running:
            total_unrealized = 0.0
            for tid, rec in list(self._records.items()):
                if rec.final_state == "ACTIVE":
                    trade = GCM.get_trade(tid)
                    if trade:
                        upnl = trade.unrealized_pnl
                        rec.max_unrealized_pnl = max(rec.max_unrealized_pnl, upnl)
                        rec.min_unrealized_pnl = min(rec.min_unrealized_pnl, upnl)
                        total_unrealized += upnl

            GCM.demo_account.equity = GCM.demo_account.balance + total_unrealized
            await asyncio.sleep(0.2)

    # ── Stats snapshot ────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        acct  = GCM.demo_account
        closed = [r for r in self._records.values() if r.final_state != "ACTIVE"]
        active = [r for r in self._records.values() if r.final_state == "ACTIVE"]
        return {
            "balance":       round(acct.balance, 2),
            "equity":        round(acct.equity, 2),
            "total_pnl":     round(acct.total_pnl, 2),
            "win_rate":      round(acct.win_rate, 2),
            "total_trades":  acct.total_trades,
            "wins":          acct.wins,
            "losses":        acct.losses,
            "max_drawdown":  round(acct.max_drawdown * 100, 2),
            "active_trades": len(active),
            "closed_trades": len(closed),
        }

    def get_trade_history(self) -> list:
        return [
            {
                "trade_id":    r.trade_id,
                "symbol":      r.symbol,
                "direction":   r.direction,
                "qty":         r.quantity,
                "entry":       r.entry_price,
                "close":       r.close_price,
                "pnl":         round(r.realized_pnl, 4),
                "state":       r.final_state,
                "opened_at":   r.opened_at,
                "closed_at":   r.closed_at,
            }
            for r in sorted(self._records.values(), key=lambda x: x.opened_at, reverse=True)
        ]

    async def run(self) -> None:
        self._running = True
        log.info("Demo simulator started")
        await self._pnl_update_loop()

    def stop(self) -> None:
        self._running = False

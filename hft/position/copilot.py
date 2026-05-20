"""
hft/position/copilot.py
═══════════════════════════════════════════════════════════════════════
MODULE 2: LIVE POSITION CO-PILOT & DYNAMIC PROFIT CHASER
- Spawns independent asyncio task per trade
- State A: Breakeven lock at TP1
- State B: Explosion mode — suppress TP3, activate AI trailing
- State C: Exhaustion — 80% close
- Elastic OB-absorption trailing stop (5 ticks below/above largest wall)
- Velocity + OI-based band expansion/contraction
- Full LONG/SHORT inversion
═══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Dict, Optional

from hft.engine.context import (
    GCM, AccountMode, ActiveTradeState, OrderBookSnapshot,
    SignalDirection, TradeState, ValidatedSignal,
)

log = logging.getLogger("hft.position")

# ── Tuning constants ───────────────────────────────────────────────────────────
COPILOT_HZ           = 500       # 500 Hz sub-ms position loop
TICK_SIZE            = 0.5       # 1 tick = 0.5 USD for BTC/USDT perp
TICKS_BEHIND_WALL    = 5         # trail SL 5 ticks beyond largest OB wall
WALL_MIN_SIZE        = 30.0      # notional threshold for "real wall"
VELOCITY_EXPAND_THRESHOLD  = 150.0  # pts/s — expand band on acceleration
VELOCITY_CONTRACT_THRESHOLD = 20.0  # pts/s — contract band on slow tape
BAND_BASE            = 10 * TICK_SIZE   # base trailing band 5 USD
BAND_MAX             = 80 * TICK_SIZE   # max band 40 USD
BAND_MIN             = 3  * TICK_SIZE   # min band 1.5 USD
CVD_EXPLOSION_MIN    = 50.0   # CVD acceleration threshold for State B
OI_EXHAUST_DELTA     = -0.02  # OI dropping 2% = exhaustion signal
VPIN_EXHAUST_GATE    = 0.15   # VPIN near zero = no momentum
PARTIAL_CLOSE_RATIO  = 0.80   # close 80% on exhaustion


class ActiveTradeInstance:
    """
    Independent co-pilot for one position.
    Spawned as asyncio.create_task — fully isolated sub-ms loop.
    Reads exclusively from GCM. Writes back to GCM registry.
    """

    def __init__(self, signal: ValidatedSignal, quantity: float) -> None:
        self.trade_id = "T-" + str(uuid.uuid4())[:8].upper()
        self.signal   = signal
        self.is_long  = signal.direction == SignalDirection.LONG
        self._running = True

        # Build initial state
        self.state = ActiveTradeState(
            trade_id          = self.trade_id,
            signal            = signal,
            state             = TradeState.ACTIVE,
            account_mode      = signal.account_mode,
            entry_price       = signal.entry_price,
            current_price     = signal.entry_price,
            dynamic_sl        = signal.sl_price,
            quantity          = quantity,
            quantity_remaining= quantity,
        )

    # ── Direction-aware helpers ────────────────────────────────────────────────

    def _is_above_price(self, a: float, b: float) -> bool:
        """Returns True if 'a' is in the profit direction vs 'b'."""
        return a > b if self.is_long else a < b

    def _profit_pct(self, price: float) -> float:
        entry = self.state.entry_price
        if self.is_long:
            return (price - entry) / entry
        return (entry - price) / entry

    def _pnl(self, close_price: float, qty: float) -> float:
        entry = self.state.entry_price
        if self.is_long:
            return (close_price - entry) * qty
        return (entry - close_price) * qty

    # ── Trailing stop computation ─────────────────────────────────────────────

    def _compute_elastic_trail(
        self,
        ob: OrderBookSnapshot,
        velocity: float,
        oi_delta: float,
    ) -> float:
        """
        1. Find largest OB wall on the profit side.
        2. Place SL 5 ticks beyond it.
        3. Adjust band size based on velocity and OI.
        """
        wall: Optional[float] = None

        if self.is_long:
            bid_wall = ob.largest_bid_wall(WALL_MIN_SIZE)
            if bid_wall:
                wall = bid_wall.price - (TICKS_BEHIND_WALL * TICK_SIZE)
        else:
            ask_wall = ob.largest_ask_wall(WALL_MIN_SIZE)
            if ask_wall:
                wall = ask_wall.price + (TICKS_BEHIND_WALL * TICK_SIZE)

        # Velocity-adaptive band
        band = BAND_BASE
        if abs(velocity) > VELOCITY_EXPAND_THRESHOLD:
            # High velocity — expand band to avoid shake-out
            band = min(BAND_MAX, BAND_BASE * (1 + abs(velocity) / VELOCITY_EXPAND_THRESHOLD))
        elif abs(velocity) < VELOCITY_CONTRACT_THRESHOLD:
            # Volume fading — contract to lock profits
            band = max(BAND_MIN, BAND_BASE * 0.5)

        # OI contraction accelerates SL tightening
        if oi_delta < OI_EXHAUST_DELTA:
            band = max(BAND_MIN, band * 0.6)

        current_price = self.state.current_price
        if wall is not None:
            # Wall-anchored SL
            candidate = wall
        else:
            # No wall found — use velocity-adjusted band from current price
            candidate = (current_price - band) if self.is_long else (current_price + band)

        # SL can only move in profit direction (ratchet)
        current_sl = self.state.dynamic_sl
        if self.is_long:
            return max(current_sl, candidate)
        else:
            return min(current_sl, candidate)

    # ── State machine ─────────────────────────────────────────────────────────

    async def _check_state_a(self) -> None:
        """TP1 hit → lock SL at entry (zero risk)."""
        if self.state.tp1_hit or self.state.breakeven_locked:
            return
        price = self.state.current_price
        if self._is_above_price(price, self.signal.tp1):
            self.state.tp1_hit        = True
            self.state.dynamic_sl     = self.signal.entry_price
            self.state.breakeven_locked = True
            self.state.state          = TradeState.STATE_A_BREAKEVEN
            await GCM.update_trade(
                self.trade_id,
                tp1_hit=True,
                dynamic_sl=self.signal.entry_price,
                breakeven_locked=True,
                state=TradeState.STATE_A_BREAKEVEN,
            )
            log.info("[%s] STATE A: Breakeven locked at %.2f", self.trade_id, self.signal.entry_price)
            GCM.enqueue_tg({
                "type":   "STATE_A_BREAKEVEN",
                "trade":  self.trade_id,
                "symbol": self.signal.symbol,
                "sl":     self.signal.entry_price,
            })

    async def _check_state_b(self, ob: OrderBookSnapshot, velocity: float) -> bool:
        """TP2 hit + accelerating CVD + skyrocketing volume → explosion mode."""
        if self.state.explosion_active or not self.state.tp1_hit:
            return False
        price = self.state.current_price
        if not self._is_above_price(price, self.signal.tp2):
            return False

        self.state.tp2_hit = True
        radar  = GCM.snapshot_radar()
        cvd_ok = radar.cvd_slope > CVD_EXPLOSION_MIN if self.is_long else radar.cvd_slope < -CVD_EXPLOSION_MIN
        vol_ok = abs(velocity) > VELOCITY_EXPAND_THRESHOLD * 0.7

        if cvd_ok and vol_ok:
            self.state.explosion_active = True
            self.state.state            = TradeState.STATE_B_EXPLOSION
            await GCM.update_trade(
                self.trade_id,
                tp2_hit=True,
                explosion_active=True,
                state=TradeState.STATE_B_EXPLOSION,
            )
            log.info("[%s] STATE B: Explosion detected — AI trailing activated", self.trade_id)
            GCM.enqueue_tg({
                "type":     "STATE_B_EXPLOSION",
                "trade":    self.trade_id,
                "symbol":   self.signal.symbol,
                "cvd":      radar.cvd_slope,
                "velocity": velocity,
            })
            return True
        else:
            # TP2 hit but no explosion — check exhaustion instead
            await self._check_state_c()
        return False

    async def _check_state_c(self) -> None:
        """
        TP2 hit but buying momentum / VPIN near zero.
        Close 80% immediately, trail remaining 20%.
        """
        if self.state.exhaustion_fired or not self.state.tp2_hit:
            return
        radar = GCM.snapshot_radar()
        vpin_low  = radar.vpin < VPIN_EXHAUST_GATE
        cvd_flat  = abs(radar.cvd_slope) < 5.0
        if vpin_low or cvd_flat:
            self.state.exhaustion_fired = True
            self.state.state            = TradeState.STATE_C_EXHAUST
            close_qty = self.state.quantity_remaining * PARTIAL_CLOSE_RATIO
            close_pnl = self._pnl(self.state.current_price, close_qty)
            self.state.realized_pnl      += close_pnl
            self.state.quantity_remaining = self.state.quantity_remaining - close_qty
            await GCM.update_trade(
                self.trade_id,
                exhaustion_fired=True,
                state=TradeState.STATE_C_EXHAUST,
                realized_pnl=self.state.realized_pnl,
                quantity_remaining=self.state.quantity_remaining,
            )
            log.info("[%s] STATE C: Exhaustion — closed 80%% PnL=%.2f", self.trade_id, close_pnl)
            GCM.enqueue_tg({
                "type":      "STATE_C_EXHAUSTION",
                "trade":     self.trade_id,
                "symbol":    self.signal.symbol,
                "close_qty": close_qty,
                "pnl":       close_pnl,
            })

    async def _check_sl_hit(self) -> bool:
        """Returns True if dynamic SL was touched."""
        price = self.state.current_price
        sl    = self.state.dynamic_sl
        if self.is_long  and price <= sl:
            return True
        if not self.is_long and price >= sl:
            return True
        return False

    async def _check_tp3_hit(self) -> bool:
        """Only relevant when NOT in explosion mode."""
        if self.state.explosion_active:
            return False
        price = self.state.current_price
        return self._is_above_price(price, self.signal.tp3)

    # ── Main sub-ms loop ──────────────────────────────────────────────────────

    async def run(self) -> None:
        interval = 1.0 / COPILOT_HZ
        log.info(
            "[%s] Co-pilot started | %s %s @ %.2f | SL=%.2f TP1=%.2f TP2=%.2f TP3=%.2f",
            self.trade_id, self.signal.symbol, self.signal.direction.value,
            self.signal.entry_price, self.signal.sl_price,
            self.signal.tp1, self.signal.tp2, self.signal.tp3,
        )

        # Register in GCM
        await GCM.register_trade(self.state)

        while self._running and GCM.running:
            t0 = time.perf_counter()
            try:
                tick = GCM.get_tick(self.signal.symbol)
                ob   = GCM.get_ob(self.signal.symbol)
                if not tick or not ob:
                    await asyncio.sleep(interval)
                    continue

                price    = tick.last
                velocity = self._compute_velocity(price)
                oi_delta = self._compute_oi_delta(tick)

                # Update live state
                self.state.current_price  = price
                self.state.velocity       = velocity
                self.state.oi_delta       = oi_delta
                self.state.loop_iterations += 1
                self.state.unrealized_pnl = self._pnl(price, self.state.quantity_remaining)

                # ── State transitions ─────────────────────────────────────────
                await self._check_state_a()
                if self.state.tp1_hit:
                    explosion = await self._check_state_b(ob, velocity)
                    if not explosion:
                        await self._check_state_c()

                # ── Trailing stop update ──────────────────────────────────────
                if self.state.state in (
                    TradeState.STATE_A_BREAKEVEN,
                    TradeState.STATE_B_EXPLOSION,
                    TradeState.STATE_C_EXHAUST,
                ):
                    new_sl = self._compute_elastic_trail(ob, velocity, oi_delta)
                    self.state.dynamic_sl = new_sl

                # ── Exit conditions ───────────────────────────────────────────
                if await self._check_sl_hit():
                    await self._close(TradeState.CLOSED_LOSS if self._profit_pct(price) < 0
                                      else TradeState.CLOSED_WIN, price)
                    break

                if await self._check_tp3_hit():
                    await self._close(TradeState.CLOSED_WIN, price)
                    break

                # Push live state to GCM every 50 iterations
                if self.state.loop_iterations % 50 == 0:
                    await GCM.update_trade(
                        self.trade_id,
                        current_price  = price,
                        dynamic_sl     = self.state.dynamic_sl,
                        unrealized_pnl = self.state.unrealized_pnl,
                        velocity       = velocity,
                        oi_delta       = oi_delta,
                    )

            except Exception as exc:
                log.exception("[%s] Co-pilot error: %s", self.trade_id, exc)

            elapsed = time.perf_counter() - t0
            await asyncio.sleep(max(0.0, interval - elapsed))

    async def _close(self, final_state: TradeState, close_price: float) -> None:
        self._running = False
        close_pnl     = self._pnl(close_price, self.state.quantity_remaining)
        self.state.realized_pnl += close_pnl
        closed = await GCM.close_trade(self.trade_id, final_state)
        log.info(
            "[%s] CLOSED %s | PnL=%.4f | price=%.2f",
            self.trade_id, final_state.value,
            self.state.realized_pnl, close_price,
        )
        GCM.enqueue_tg({
            "type":       "TRADE_CLOSED",
            "trade":      self.trade_id,
            "symbol":     self.signal.symbol,
            "direction":  self.signal.direction.value,
            "pnl":        round(self.state.realized_pnl, 4),
            "state":      final_state.value,
            "close_price":close_price,
        })

    async def force_close(self) -> None:
        """Admin manual override."""
        tick = GCM.get_tick(self.signal.symbol)
        price = tick.last if tick else self.state.current_price
        await self._close(TradeState.CLOSED_MANUAL, price)

    # ── Velocity / OI helpers ──────────────────────────────────────────────────

    _prev_price: float = 0.0
    _prev_ts:    float = 0.0
    _prev_oi:    float = 0.0

    def _compute_velocity(self, price: float) -> float:
        now = time.perf_counter()
        dt  = now - self._prev_ts if self._prev_ts else 1.0
        v   = (price - self._prev_price) / dt if dt > 0 and self._prev_price else 0.0
        self._prev_price = price
        self._prev_ts    = now
        return v

    def _compute_oi_delta(self, tick) -> float:
        oi = tick.open_interest
        if not self._prev_oi:
            self._prev_oi = oi
            return 0.0
        delta = (oi - self._prev_oi) / self._prev_oi if self._prev_oi else 0.0
        self._prev_oi = oi
        return delta


# ══════════════════════════════════════════════════════════════════════════════
# POSITION MANAGER — spawns and tracks all trade instances
# ══════════════════════════════════════════════════════════════════════════════

class PositionManager:
    """
    Receives validated signals from the Radar.
    Spawns independent asyncio tasks per signal.
    Tracks active tasks for cancellation/force-close.
    """

    def __init__(self) -> None:
        self._tasks: Dict[str, asyncio.Task] = {}

    async def open_position(
        self,
        signal: ValidatedSignal,
        quantity: float = 0.001,  # BTC units — overridden by risk sizing
    ) -> str:
        instance = ActiveTradeInstance(signal, quantity)
        task     = asyncio.create_task(instance.run(), name=instance.trade_id)
        self._tasks[instance.trade_id] = task
        log.info("Position spawned: %s", instance.trade_id)
        return instance.trade_id

    async def force_close_trade(self, trade_id: str) -> bool:
        t = self._tasks.get(trade_id)
        if t and not t.done():
            # Signal the trade instance via GCM
            trade = GCM.get_trade(trade_id)
            if trade:
                await GCM.close_trade(trade_id, TradeState.CLOSED_MANUAL)
            t.cancel()
            return True
        return False

    async def force_close_all(self) -> int:
        closed = 0
        for tid in list(self._tasks.keys()):
            if await self.force_close_trade(tid):
                closed += 1
        return closed

    def active_count(self) -> int:
        return sum(1 for t in self._tasks.values() if not t.done())

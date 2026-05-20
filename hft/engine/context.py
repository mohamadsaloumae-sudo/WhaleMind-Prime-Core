"""
hft/engine/context.py
═══════════════════════════════════════════════════════════════════════
GLOBAL CONTEXT MACHINE (GCM)
Single source of truth. Every module reads/writes exclusively here.
Thread-safe via asyncio locks. Prevents isolated execution contradictions.
═══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, List, Optional


# ── Enumerations ──────────────────────────────────────────────────────────────

class MarketRegime(str, Enum):
    TRENDING_BULL   = "TRENDING_BULL"
    TRENDING_BEAR   = "TRENDING_BEAR"
    RANGE_BOUND     = "RANGE_BOUND"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LIQUIDITY_VACUUM= "LIQUIDITY_VACUUM"
    STOP_HUNT       = "STOP_HUNT"
    UNKNOWN         = "UNKNOWN"

class SignalDirection(str, Enum):
    LONG  = "LONG"
    SHORT = "SHORT"
    FLAT  = "FLAT"

class TradeState(str, Enum):
    PENDING          = "PENDING"
    ACTIVE           = "ACTIVE"
    STATE_A_BREAKEVEN= "STATE_A_BREAKEVEN"   # SL → entry; zero risk
    STATE_B_EXPLOSION= "STATE_B_EXPLOSION"   # trailing activated
    STATE_C_EXHAUST  = "STATE_C_EXHAUSTION"  # 80% close, trail rest
    CLOSED_WIN       = "CLOSED_WIN"
    CLOSED_LOSS      = "CLOSED_LOSS"
    CLOSED_MANUAL    = "CLOSED_MANUAL"

class AccountMode(str, Enum):
    REAL = "REAL"
    DEMO = "DEMO"


# ── Immutable tick snapshot ───────────────────────────────────────────────────

@dataclass
class TickSnapshot:
    ts:          float          # unix ms
    symbol:      str
    bid:         float
    ask:         float
    last:        float
    volume:      float
    open_interest: float = 0.0


# ── Order-book level ──────────────────────────────────────────────────────────

@dataclass
class OBLevel:
    price:  float
    size:   float


# ── L2 order-book snapshot ────────────────────────────────────────────────────

@dataclass
class OrderBookSnapshot:
    ts:        float
    symbol:    str
    bids:      List[OBLevel] = field(default_factory=list)   # sorted desc
    asks:      List[OBLevel] = field(default_factory=list)   # sorted asc

    @property
    def best_bid(self) -> float:
        return self.bids[0].price if self.bids else 0.0

    @property
    def best_ask(self) -> float:
        return self.asks[0].price if self.asks else 0.0

    @property
    def mid(self) -> float:
        return (self.best_bid + self.best_ask) / 2 if self.bids and self.asks else 0.0

    def largest_bid_wall(self, min_size: float = 50.0) -> Optional[OBLevel]:
        walls = [b for b in self.bids if b.size >= min_size]
        return max(walls, key=lambda x: x.size) if walls else None

    def largest_ask_wall(self, min_size: float = 50.0) -> Optional[OBLevel]:
        walls = [a for a in self.asks if a.size >= min_size]
        return max(walls, key=lambda x: x.size) if walls else None


# ── Radar output packet ───────────────────────────────────────────────────────

@dataclass
class RadarOutput:
    ts:                float = 0.0
    composite_score:   float = 0.0       # 0–100 fuzzy logic score
    vpin:              float = 0.0       # Volume-sync probability of toxicity
    obi:               float = 0.0       # order-book imbalance  -1..+1
    cvd_slope:         float = 0.0       # cumulative volume delta slope
    macro_weight:      float = 1.0       # macro multiplier 0.5–1.5
    btc_dominance:     float = 50.0
    dxy_volatility:    float = 0.0
    regime:            MarketRegime = MarketRegime.UNKNOWN
    signal:            SignalDirection = SignalDirection.FLAT
    suppressed:        bool = False      # True = whale trap detected
    suppress_reason:   str = ""
    liq_pool_above:    float = 0.0       # liquidation pool price levels
    liq_pool_below:    float = 0.0
    feature_densities: Dict[str, float] = field(default_factory=dict)


# ── Single validated signal ───────────────────────────────────────────────────

@dataclass
class ValidatedSignal:
    signal_id:   str
    symbol:      str
    direction:   SignalDirection
    entry_price: float
    sl_price:    float
    tp1:         float
    tp2:         float
    tp3:         float
    score:       float
    radar:       RadarOutput
    ts:          float = field(default_factory=time.time)
    account_mode:AccountMode = AccountMode.DEMO


# ── Active trade instance state ───────────────────────────────────────────────

@dataclass
class ActiveTradeState:
    trade_id:          str
    signal:            ValidatedSignal
    state:             TradeState = TradeState.ACTIVE
    account_mode:      AccountMode = AccountMode.DEMO

    # Prices
    current_price:     float = 0.0
    dynamic_sl:        float = 0.0
    trailing_anchor:   float = 0.0      # price of largest OB wall trailing against
    trailing_band:     float = 0.0      # dynamic expansion/contraction

    # Position sizing
    quantity:          float = 0.0
    quantity_remaining:float = 0.0
    entry_price:       float = 0.0

    # P&L
    unrealized_pnl:    float = 0.0
    realized_pnl:      float = 0.0

    # Milestone flags
    tp1_hit:           bool = False
    tp2_hit:           bool = False
    tp3_hit:           bool = False
    breakeven_locked:  bool = False
    explosion_active:  bool = False
    exhaustion_fired:  bool = False

    # Timestamps
    opened_at:         float = field(default_factory=time.time)
    closed_at:         Optional[float] = None

    # Sub-loop metrics
    loop_iterations:   int = 0
    last_ob_scan_ts:   float = 0.0
    velocity:          float = 0.0     # price velocity (pts/s)
    oi_delta:          float = 0.0     # OI change rate


# ── Demo account ledger ───────────────────────────────────────────────────────

@dataclass
class DemoAccount:
    balance:        float = 10_000.0
    equity:         float = 10_000.0
    total_trades:   int = 0
    wins:           int = 0
    losses:         int = 0
    total_pnl:      float = 0.0
    max_drawdown:   float = 0.0
    peak_equity:    float = 10_000.0

    @property
    def win_rate(self) -> float:
        return (self.wins / self.total_trades * 100) if self.total_trades else 0.0


# ══════════════════════════════════════════════════════════════════════════════
# GLOBAL CONTEXT MACHINE
# ══════════════════════════════════════════════════════════════════════════════

class GlobalContextMachine:
    """
    Single-instance registry. All modules import GCM and interact with it.
    Uses asyncio.Lock for every write to guarantee thread-safety in the
    co-operative async event loop.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

        # ── Market data ──────────────────────────────────────────────────────
        self.ticks:    Dict[str, TickSnapshot]        = {}
        self.ob:       Dict[str, OrderBookSnapshot]   = {}
        self.tick_history: Dict[str, Deque[TickSnapshot]] = {}

        # ── Radar state ──────────────────────────────────────────────────────
        self.radar:    RadarOutput = RadarOutput()
        self.radar_history: Deque[RadarOutput] = deque(maxlen=500)

        # ── Trade registry ────────────────────────────────────────────────────
        self.active_trades: Dict[str, ActiveTradeState] = {}
        self.closed_trades: List[ActiveTradeState]      = []

        # ── Accounts ──────────────────────────────────────────────────────────
        self.demo_account: DemoAccount = DemoAccount()
        self.current_mode: AccountMode = AccountMode.DEMO

        # ── System control ────────────────────────────────────────────────────
        self.running:           bool = True
        self.radar_suppressed:  bool = False   # manual admin override
        self.ai_score_override: Optional[float] = None

        # ── Macro weights (updated by MacroAdvisor) ───────────────────────────
        self.macro: Dict[str, float] = {
            "btc_dominance":  50.0,
            "dxy_volatility": 0.0,
            "gold_corr":      0.0,
            "equity_corr":    0.0,
            "fear_greed":     50.0,
        }

        # ── Telegram broadcast queue ──────────────────────────────────────────
        self.tg_queue: asyncio.Queue = asyncio.Queue(maxsize=200)

        # ── VPIN buckets ──────────────────────────────────────────────────────
        self.vpin_buckets: Deque[Dict[str, float]] = deque(maxlen=50)

        # ── CVD rolling ───────────────────────────────────────────────────────
        self.cvd_series: Deque[float] = deque(maxlen=200)

    # ── Tick writes ───────────────────────────────────────────────────────────

    async def update_tick(self, snap: TickSnapshot) -> None:
        async with self._lock:
            self.ticks[snap.symbol] = snap
            if snap.symbol not in self.tick_history:
                self.tick_history[snap.symbol] = deque(maxlen=1000)
            self.tick_history[snap.symbol].append(snap)

    async def update_ob(self, snap: OrderBookSnapshot) -> None:
        async with self._lock:
            self.ob[snap.symbol] = snap

    # ── Radar writes ──────────────────────────────────────────────────────────

    async def update_radar(self, r: RadarOutput) -> None:
        async with self._lock:
            self.radar = r
            self.radar_history.append(r)

    # ── Trade registry ────────────────────────────────────────────────────────

    async def register_trade(self, trade: ActiveTradeState) -> None:
        async with self._lock:
            self.active_trades[trade.trade_id] = trade

    async def update_trade(self, trade_id: str, **kwargs: Any) -> None:
        async with self._lock:
            t = self.active_trades.get(trade_id)
            if t:
                for k, v in kwargs.items():
                    setattr(t, k, v)

    async def close_trade(self, trade_id: str, state: TradeState) -> Optional[ActiveTradeState]:
        async with self._lock:
            t = self.active_trades.pop(trade_id, None)
            if t:
                t.state      = state
                t.closed_at  = time.time()
                self.closed_trades.append(t)
                # Update demo account
                if t.account_mode == AccountMode.DEMO:
                    self.demo_account.total_trades += 1
                    self.demo_account.total_pnl    += t.realized_pnl
                    self.demo_account.balance      += t.realized_pnl
                    self.demo_account.equity        = self.demo_account.balance
                    if t.realized_pnl > 0:
                        self.demo_account.wins += 1
                    else:
                        self.demo_account.losses += 1
                    if self.demo_account.equity > self.demo_account.peak_equity:
                        self.demo_account.peak_equity = self.demo_account.equity
                    dd = (self.demo_account.peak_equity - self.demo_account.equity) / self.demo_account.peak_equity
                    if dd > self.demo_account.max_drawdown:
                        self.demo_account.max_drawdown = dd
            return t

    # ── Account mode ──────────────────────────────────────────────────────────

    async def switch_mode(self, mode: AccountMode) -> None:
        async with self._lock:
            self.current_mode = mode

    # ── VPIN helpers ─────────────────────────────────────────────────────────

    async def push_vpin_bucket(self, bucket: Dict[str, float]) -> None:
        async with self._lock:
            self.vpin_buckets.append(bucket)

    async def push_cvd(self, cvd_value: float) -> None:
        async with self._lock:
            self.cvd_series.append(cvd_value)

    # ── Macro ─────────────────────────────────────────────────────────────────

    async def update_macro(self, data: Dict[str, float]) -> None:
        async with self._lock:
            self.macro.update(data)

    # ── Telegram queue ────────────────────────────────────────────────────────

    def enqueue_tg(self, msg: Dict[str, Any]) -> None:
        try:
            self.tg_queue.put_nowait(msg)
        except asyncio.QueueFull:
            pass   # drop oldest — non-blocking

    # ── Read helpers (no lock needed for reads in asyncio) ────────────────────

    def get_tick(self, symbol: str) -> Optional[TickSnapshot]:
        return self.ticks.get(symbol)

    def get_ob(self, symbol: str) -> Optional[OrderBookSnapshot]:
        return self.ob.get(symbol)

    def get_trade(self, trade_id: str) -> Optional[ActiveTradeState]:
        return self.active_trades.get(trade_id)

    def snapshot_active_trades(self) -> List[ActiveTradeState]:
        return list(self.active_trades.values())

    def snapshot_radar(self) -> RadarOutput:
        return self.radar


# Module-level singleton — import GCM everywhere
GCM = GlobalContextMachine()

"""
hft/engine/orchestrator.py
Connects radar validated signals → position manager → demo/real broker.
Deduplicates signals and enforces max concurrent positions.
"""
from __future__ import annotations
import asyncio, logging, time, uuid
from hft.engine.context import GCM, AccountMode, SignalDirection, ValidatedSignal
from hft.position.copilot import PositionManager
from hft.simulator.demo_engine import DemoSimulator

log = logging.getLogger("hft.orchestrator")

MAX_CONCURRENT  = 3     # max simultaneous open positions
SIGNAL_COOLDOWN = 30.0  # seconds between signals on same symbol


class SignalOrchestrator:
    def __init__(self, position_mgr: PositionManager, demo_sim: DemoSimulator) -> None:
        self.pm          = position_mgr
        self.demo        = demo_sim
        self._last_signal: dict[str, float] = {}
        self._running    = False

    def _build_signal(self, radar) -> ValidatedSignal | None:
        if radar.signal == SignalDirection.FLAT or radar.suppressed:
            return None
        tick = GCM.get_tick("BTCUSDT")
        if not tick:
            return None
        price = tick.last
        is_long = radar.signal == SignalDirection.LONG
        sl_dist = price * 0.008       # 0.8% SL
        sl    = price - sl_dist if is_long else price + sl_dist
        tp1   = price + sl_dist * 1.2 if is_long else price - sl_dist * 1.2
        tp2   = price + sl_dist * 2.5 if is_long else price - sl_dist * 2.5
        tp3   = price + sl_dist * 4.0 if is_long else price - sl_dist * 4.0
        return ValidatedSignal(
            signal_id    = str(uuid.uuid4()),
            symbol       = "BTCUSDT",
            direction    = radar.signal,
            entry_price  = price,
            sl_price     = sl,
            tp1=tp1, tp2=tp2, tp3=tp3,
            score        = radar.composite_score,
            radar        = radar,
            account_mode = GCM.current_mode,
        )

    async def run(self) -> None:
        self._running = True
        log.info("SignalOrchestrator running")
        while self._running and GCM.running:
            radar = GCM.snapshot_radar()
            if (radar.signal != SignalDirection.FLAT
                    and not radar.suppressed
                    and self.pm.active_count() < MAX_CONCURRENT):

                symbol  = "BTCUSDT"
                last_ts = self._last_signal.get(symbol, 0.0)
                if time.time() - last_ts > SIGNAL_COOLDOWN:
                    sig = self._build_signal(radar)
                    if sig:
                        self._last_signal[symbol] = time.time()
                        if GCM.current_mode == AccountMode.DEMO:
                            await self.demo.open_demo_trade(sig)
                        else:
                            await self.pm.open_position(sig)
            await asyncio.sleep(0.1)

    def stop(self) -> None:
        self._running = False

"""
hft/execution/ingestor.py
═══════════════════════════════════════════════════════════════════════
LIVE DATA INGESTOR
- Non-blocking async WebSockets for L2 order book + trade streams
- Binance Futures & generic connector interface
- Feeds GCM and AntiSpoofRadar in real-time
- Auto-reconnect with exponential back-off
═══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Callable, Optional

try:
    import websockets
    HAS_WS = True
except ImportError:
    HAS_WS = False

from hft.engine.context import (
    GCM, OBLevel, OrderBookSnapshot, TickSnapshot,
)

log = logging.getLogger("hft.ingestor")

BINANCE_WS_BASE = "wss://fstream.binance.com/stream"
RECONNECT_BASE  = 1.0   # seconds
RECONNECT_MAX   = 60.0


class BinanceFuturesIngestor:
    """
    Connects to Binance Futures combined stream:
    - <symbol>@bookTicker  → best bid/ask
    - <symbol>@depth20@100ms → L2 top-20
    - <symbol>@aggTrade    → aggregated trades (VPIN feed)
    - <symbol>@openInterest (polled separately)
    """

    def __init__(
        self,
        symbol: str,
        radar_feed_cb: Optional[Callable] = None,
    ) -> None:
        self.symbol        = symbol.lower()
        self.radar_feed_cb = radar_feed_cb
        self._running      = False
        self._reconnect_delay = RECONNECT_BASE

        # Local OB cache for incremental updates
        self._bids: dict = {}
        self._asks: dict = {}

    def _stream_url(self) -> str:
        streams = [
            f"{self.symbol}@bookTicker",
            f"{self.symbol}@depth20@100ms",
            f"{self.symbol}@aggTrade",
        ]
        return BINANCE_WS_BASE + "?streams=" + "/".join(streams)

    async def _process_message(self, raw: str) -> None:
        try:
            msg    = json.loads(raw)
            stream = msg.get("stream", "")
            data   = msg.get("data", msg)

            if "bookTicker" in stream:
                await self._handle_book_ticker(data)
            elif "depth" in stream:
                await self._handle_depth(data)
            elif "aggTrade" in stream:
                await self._handle_agg_trade(data)
        except Exception as exc:
            log.debug("Message parse error: %s", exc)

    async def _handle_book_ticker(self, d: dict) -> None:
        snap = TickSnapshot(
            ts      = time.time() * 1000,
            symbol  = self.symbol.upper(),
            bid     = float(d.get("b", 0)),
            ask     = float(d.get("a", 0)),
            last    = (float(d.get("b", 0)) + float(d.get("a", 0))) / 2,
            volume  = 0.0,
            open_interest = 0.0,
        )
        await GCM.update_tick(snap)

    async def _handle_depth(self, d: dict) -> None:
        bids = [OBLevel(price=float(p), size=float(s)) for p, s in d.get("b", [])]
        asks = [OBLevel(price=float(p), size=float(s)) for p, s in d.get("a", [])]
        # Sort: bids desc, asks asc
        bids.sort(key=lambda x: x.price, reverse=True)
        asks.sort(key=lambda x: x.price)
        snap = OrderBookSnapshot(
            ts     = time.time(),
            symbol = self.symbol.upper(),
            bids   = bids,
            asks   = asks,
        )
        await GCM.update_ob(snap)

    async def _handle_agg_trade(self, d: dict) -> None:
        price     = float(d.get("p", 0))
        size      = float(d.get("q", 0))
        is_sell   = d.get("m", False)   # maker = sell aggressor
        aggressor = "sell" if is_sell else "buy"
        # Feed into radar
        if self.radar_feed_cb:
            self.radar_feed_cb(price, size, aggressor)
        # Update CVD in GCM
        buy_vol  = size if aggressor == "buy"  else 0.0
        sell_vol = size if aggressor == "sell" else 0.0
        cvd = list(GCM.cvd_series)[-1] if GCM.cvd_series else 0.0
        await GCM.push_cvd(cvd + buy_vol - sell_vol)

    async def _connect_and_run(self) -> None:
        if not HAS_WS:
            log.warning("websockets not installed — using mock data feed")
            await self._mock_feed()
            return
        url = self._stream_url()
        log.info("Connecting to: %s", url)
        async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
            self._reconnect_delay = RECONNECT_BASE  # reset on success
            async for raw in ws:
                if not self._running:
                    break
                await self._process_message(raw)

    async def _mock_feed(self) -> None:
        """Synthetic feed for testing when websockets are unavailable."""
        import math, random
        price = 65000.0
        oi    = 50000.0
        log.info("Mock feed active for %s", self.symbol)
        while self._running and GCM.running:
            price += random.gauss(0, 15)
            oi    += random.gauss(0, 10)
            snap = TickSnapshot(
                ts=time.time() * 1000,
                symbol=self.symbol.upper(),
                bid=price - 0.5, ask=price + 0.5, last=price,
                volume=random.uniform(0.5, 5.0),
                open_interest=max(0, oi),
            )
            await GCM.update_tick(snap)

            # Build synthetic L2
            bids = [OBLevel(price=price - i * 0.5, size=random.uniform(1, 50) * math.exp(-i * 0.1))
                    for i in range(1, 21)]
            asks = [OBLevel(price=price + i * 0.5, size=random.uniform(1, 50) * math.exp(-i * 0.1))
                    for i in range(1, 21)]
            await GCM.update_ob(OrderBookSnapshot(
                ts=time.time(), symbol=self.symbol.upper(), bids=bids, asks=asks
            ))

            # Feed radar
            aggressor = "buy" if random.random() > 0.5 else "sell"
            size = random.uniform(0.01, 2.0)
            if self.radar_feed_cb:
                self.radar_feed_cb(price, size, aggressor)

            await asyncio.sleep(0.01)   # 100 Hz mock

    async def run(self) -> None:
        self._running = True
        while self._running and GCM.running:
            try:
                await self._connect_and_run()
            except Exception as exc:
                if not self._running:
                    break
                log.warning("WS disconnected: %s — retry in %.1fs", exc, self._reconnect_delay)
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, RECONNECT_MAX)

    def stop(self) -> None:
        self._running = False

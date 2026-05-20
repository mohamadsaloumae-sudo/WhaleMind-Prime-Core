"""
hft/macro/advisor.py
═══════════════════════════════════════════════════════════════════════
MACRO ECONOMIC ADVISOR
- Polls external macro sources (CoinGecko, FRED, Yahoo Finance proxies)
- Feeds BTC dominance, DXY volatility, Fear & Greed into GCM
- Tightens/relaxes radar filter weights in real-time
- Runs on a slow loop (60s) — macro doesn't change sub-second
═══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

from hft.engine.context import GCM

log = logging.getLogger("hft.macro")

MACRO_POLL_INTERVAL = 60.0   # seconds

# Endpoint templates (replace with paid feeds in production)
FEAR_GREED_URL  = "https://api.alternative.me/fng/?limit=1"
COINGECKO_GLOBAL= "https://api.coingecko.com/api/v3/global"


class MacroAdvisor:
    """
    Asynchronously polls macro data sources.
    Normalises values and writes to GCM.macro.
    The radar automatically adjusts its composite score weights.
    """

    def __init__(self) -> None:
        self._running  = False
        self._last_poll= 0.0

    async def _fetch_fear_greed(self) -> Optional[float]:
        if not HAS_HTTPX:
            return None
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(FEAR_GREED_URL)
                d = r.json()
                return float(d["data"][0]["value"])
        except Exception as exc:
            log.debug("Fear/Greed fetch failed: %s", exc)
            return None

    async def _fetch_btc_dominance(self) -> Optional[float]:
        if not HAS_HTTPX:
            return None
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(COINGECKO_GLOBAL)
                d = r.json()
                return float(d["data"]["market_cap_percentage"].get("btc", 50.0))
        except Exception as exc:
            log.debug("BTC dominance fetch failed: %s", exc)
            return None

    def _estimate_dxy_volatility(self) -> float:
        """
        DXY feed requires a paid subscription.
        Proxy: use recent BTC price velocity as anti-correlated signal.
        In production, replace with FRED API: series DTWEXBGS.
        """
        history = GCM.tick_history.get("BTCUSDT")
        if not history or len(history) < 10:
            return 0.0
        prices = [t.last for t in list(history)[-20:]]
        if len(prices) < 2:
            return 0.0
        import statistics
        returns = [(prices[i] - prices[i-1]) / prices[i-1] for i in range(1, len(prices))]
        vol = statistics.stdev(returns) if len(returns) > 1 else 0.0
        # Rough DXY proxy: inverse of BTC vol (when BTC calms, DXY often rises)
        return round(vol * 100, 4)

    async def poll(self) -> None:
        """Single macro data poll cycle."""
        updates = {}

        fg = await self._fetch_fear_greed()
        if fg is not None:
            updates["fear_greed"] = fg

        btcd = await self._fetch_btc_dominance()
        if btcd is not None:
            updates["btc_dominance"] = btcd

        updates["dxy_volatility"] = self._estimate_dxy_volatility()

        # Gold/equity correlation — placeholder (use real feed in prod)
        # Positive = risk-off, tighten crypto filter
        updates["gold_corr"]   = 0.0
        updates["equity_corr"] = 0.0

        if updates:
            await GCM.update_macro(updates)
            log.debug(
                "Macro updated | F&G=%.0f BTC_dom=%.1f%% DXY_vol=%.4f",
                updates.get("fear_greed", 0),
                updates.get("btc_dominance", 50),
                updates.get("dxy_volatility", 0),
            )

    async def run(self) -> None:
        self._running = True
        log.info("MacroAdvisor started (poll interval=%.0fs)", MACRO_POLL_INTERVAL)
        while self._running and GCM.running:
            try:
                await self.poll()
            except Exception as exc:
                log.exception("Macro poll error: %s", exc)
            await asyncio.sleep(MACRO_POLL_INTERVAL)

    def stop(self) -> None:
        self._running = False

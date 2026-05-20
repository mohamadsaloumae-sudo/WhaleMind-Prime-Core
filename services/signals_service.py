"""
services/signals_service.py — Live signal generation and broadcasting.

In production, connect this to your on-chain data provider (Birdeye, Nansen, etc.).
Currently seeded with realistic sample data so the UI renders immediately.
"""
from __future__ import annotations

import asyncio
import logging
import random
import uuid
from datetime import datetime, timezone
from typing import Any

from core.websocket_manager import ws_manager

logger = logging.getLogger(__name__)

# ── Static seed data ───────────────────────────────────────────────────────────

_SEED_SIGNALS: list[dict[str, Any]] = [
    {
        "id":         str(uuid.uuid4()),
        "symbol":     "SOL/USDT",
        "direction":  "LONG",
        "grade":      "A",
        "confidence": 82,
        "entry":      185.34,
        "sl":         182.10,
        "tp1":        188.60,
        "tp2":        191.80,
        "tp3":        196.70,
        "strategies": "Whale Accumulation\nStoch RSI Oversold\nSupport & Resistance\nBullish Divergence",
        "chain":      "sol",
        "trade_type": "futures",
        "timestamp":  datetime.now(timezone.utc).isoformat(),
    },
    {
        "id":         str(uuid.uuid4()),
        "symbol":     "ETH/USDT",
        "direction":  "SHORT",
        "grade":      "S",
        "confidence": 91,
        "entry":      3240.50,
        "sl":         3310.00,
        "tp1":        3170.00,
        "tp2":        3100.00,
        "tp3":        3010.00,
        "strategies": "RSI Overbought\nBearish MACD Cross\nBearish Divergence\nTrend Break\nResistance Rejection",
        "chain":      "eth",
        "trade_type": "futures",
        "timestamp":  datetime.now(timezone.utc).isoformat(),
    },
    {
        "id":         str(uuid.uuid4()),
        "symbol":     "BONK/SOL",
        "direction":  "LONG",
        "grade":      "B",
        "confidence": 65,
        "entry":      0.0000218,
        "sl":         0.0000201,
        "tp1":        0.0000235,
        "tp2":        0.0000255,
        "tp3":        0.0000280,
        "strategies": "Whale Wallet Activity\nBollinger Band Squeeze\nBullish Candle Pattern",
        "chain":      "sol",
        "trade_type": "meme",
        "timestamp":  datetime.now(timezone.utc).isoformat(),
    },
]

_live_signals: list[dict[str, Any]] = list(_SEED_SIGNALS)


def get_signals() -> list[dict[str, Any]]:
    return _live_signals


def get_stats() -> dict[str, Any]:
    return {
        "total_balance":   4827.93,
        "open_trades":     len(_live_signals),
        "total_signals":   len(_live_signals),
        "symbols_watched": 40,
        "roi_pct":         34.2,
        "win_rate_pct":    71.0,
        "total_trades":    127,
    }


# ── Background broadcaster ─────────────────────────────────────────────────────

async def signal_broadcaster() -> None:
    """
    Runs as a background task; occasionally emits a synthetic signal update
    and price ticks so connected clients stay live.
    Replace the random generation with real data-feed logic.
    """
    PAIRS = [
        ("BNB/USDT",  "LONG",  "B", "bsc",  600.0,  0.02),
        ("ARB/USDT",  "SHORT", "A", "arb",  1.18,   0.03),
        ("AVAX/USDT", "LONG",  "B", "avax", 38.5,   0.025),
        ("WIF/SOL",   "LONG",  "B", "sol",  2.45,   0.04),
    ]
    prices = {"SOL": 185.34, "ETH": 3240.5, "BNB": 600.0, "ARB": 1.18}

    while True:
        await asyncio.sleep(random.randint(20, 45))

        # Price tick
        for sym, price in prices.items():
            prices[sym] = round(price * (1 + random.uniform(-0.003, 0.003)), 4)
        await ws_manager.broadcast("price_update", prices)

        # Occasional new signal
        if random.random() < 0.4:
            pair    = random.choice(PAIRS)
            sym, direction, grade, chain, base, spread = pair
            entry   = round(base * (1 + random.uniform(-spread, spread)), 4)
            sl_pct  = random.uniform(0.01, 0.02)
            tp_mult = [1.015, 1.03, 1.055]
            sig     = {
                "id":         str(uuid.uuid4()),
                "symbol":     sym,
                "direction":  direction,
                "grade":      grade,
                "confidence": random.randint(60, 89),
                "entry":      entry,
                "sl":         round(entry * (1 - sl_pct if direction == "LONG" else 1 + sl_pct), 4),
                "tp1":        round(entry * (tp_mult[0] if direction == "LONG" else 2 - tp_mult[0]), 4),
                "tp2":        round(entry * (tp_mult[1] if direction == "LONG" else 2 - tp_mult[1]), 4),
                "tp3":        round(entry * (tp_mult[2] if direction == "LONG" else 2 - tp_mult[2]), 4),
                "strategies": "Trend Following\nRSI Momentum\nVolume Spike",
                "chain":      chain,
                "trade_type": "futures",
                "timestamp":  datetime.now(timezone.utc).isoformat(),
            }
            _live_signals.insert(0, sig)
            if len(_live_signals) > 20:
                _live_signals.pop()
            await ws_manager.broadcast("new_signal", sig)
            logger.info("📡 New signal broadcast: %s %s", sym, direction)

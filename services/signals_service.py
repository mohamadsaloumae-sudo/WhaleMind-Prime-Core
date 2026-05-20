from __future__ import annotations

import asyncio
import logging
import random
import uuid
from datetime import datetime, timezone
from typing import Any

from core.websocket_manager import ws_manager
from core.config import get_settings
from telegram import Bot

logger = logging.getLogger(__name__)

# ── Static seed data ───────────────────────────────────────────────────────────

_SEED_SIGNALS: list[dict[str, Any]] = [
    {"id": str(uuid.uuid4()), "symbol": "SOL/USDT", "direction": "LONG", "grade": "A", "confidence": 82, "entry": 185.34, "sl": 182.10, "tp1": 188.60, "tp2": 191.80, "tp3": 196.70, "strategies": "Whale Accumulation", "chain": "sol", "trade_type": "futures", "timestamp": datetime.now(timezone.utc).isoformat()},
    {"id": str(uuid.uuid4()), "symbol": "ETH/USDT", "direction": "SHORT", "grade": "S", "confidence": 91, "entry": 3240.50, "sl": 3310.00, "tp1": 3170.00, "tp2": 3100.00, "tp3": 3010.00, "strategies": "RSI Overbought", "chain": "eth", "trade_type": "futures", "timestamp": datetime.now(timezone.utc).isoformat()},
]

_live_signals: list[dict[str, Any]] = list(_SEED_SIGNALS)

def get_signals() -> list[dict[str, Any]]:
    return _live_signals

def get_stats() -> dict[str, Any]:
    return {"total_balance": 4827.93, "open_trades": len(_live_signals), "total_signals": len(_live_signals)}

# ── Background broadcaster ─────────────────────────────────────────────────────

async def signal_broadcaster() -> None:
    PAIRS = [
        ("BNB/USDT",  "LONG",  "B", "bsc",  600.0,  0.02),
        ("ARB/USDT",  "SHORT", "A", "arb",  1.18,   0.03),
        ("WIF/SOL",   "LONG",  "B", "sol",  2.45,   0.04),
    ]
    prices = {"SOL": 185.34, "ETH": 3240.5, "BNB": 600.0, "ARB": 1.18}
    settings = get_settings()
    bot = Bot(token=settings.telegram_bot_token)

    while True:
        await asyncio.sleep(random.randint(20, 45))

        for sym, price in prices.items():
            prices[sym] = round(price * (1 + random.uniform(-0.003, 0.003)), 4)
        await ws_manager.broadcast("price_update", prices)

        if random.random() < 0.4:
            pair = random.choice(PAIRS)
            sym, direction, grade, chain, base, spread = pair
            entry = round(base * (1 + random.uniform(-spread, spread)), 4)
            sig = {
                "id": str(uuid.uuid4()), "symbol": sym, "direction": direction, "grade": grade,
                "confidence": random.randint(60, 89), "entry": entry,
                "sl": round(entry * 0.98, 4), "tp1": round(entry * 1.02, 4),
                "tp2": round(entry * 1.04, 4), "tp3": round(entry * 1.06, 4),
                "strategies": "Trend Following", "chain": chain, "timestamp": datetime.now(timezone.utc).isoformat()
            }
            _live_signals.insert(0, sig)
            await ws_manager.broadcast("new_signal", sig)
            logger.info("📡 New signal broadcast: %s %s", sym, direction)

            # إرسال إلى تليجرام
            try:
                msg = f"🔔 *إشارة جديدة:* {sym} {direction}\n\n📊 التقييم: {grade}\n🎯 الأهداف: {sig['tp1']} / {sig['tp2']} / {sig['tp3']}\n🛑 SL: {sig['sl']}"
                await bot.send_message(chat_id=settings.telegram_channel_id, text=msg, parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Telegram Error: {e}")

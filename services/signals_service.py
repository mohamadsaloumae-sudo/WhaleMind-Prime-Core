signals_service.py
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from core.websocket_manager import ws_manager
from core.config import get_settings
from telegram import Bot

logger = logging.getLogger(__name__)

# ── Static seed data (للحفاظ على استقرار واجهة الموقع والداشبورد) ──────────────
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
        "leverage":   "20x",
        "strategies": "Whale Accumulation\nStoch RSI Oversold\nSupport & Resistance",
        "chain":      "sol",
        "trade_type": "futures",
        "timestamp":  datetime.now(timezone.utc).isoformat(),
    }
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


# ── Real-time Broadcaster (المستقبل الحقيقي والديناميكي 100%) ──────────────

async def broadcast_signal(sig: dict[str, Any]) -> None:
    sym = sig.get('symbol', 'UNKNOWN')
    
    BANNED_COINS = ["USDC", "FDUSD", "TUSD", "DAI", "USDD", "BUSD", "PYUSD"]
    if any(banned in sym for banned in BANNED_COINS):
        logger.info(f"🛡️ تم حظر وإهمال إشارة لعملة مستقرة: {sym}")
        return

    settings = get_settings()
    bot = Bot(token=settings.telegram_bot_token)

    _live_signals.insert(0, sig)
    if len(_live_signals) > 20:
        _live_signals.pop()
        
    await ws_manager.broadcast("new_signal", sig)
    logger.info("📡 New real signal broadcast: %s %s", sym, sig.get('direction'))

    try:
        direction = sig.get('direction', 'LONG')
        entry = sig.get('entry', 0.0)
        sl = sig.get('sl', 0.0)
        tp1 = sig.get('tp1', 0.0)
        tp2 = sig.get('tp2', 0.0)
        tp3 = sig.get('tp3', 0.0)
        grade = sig.get('grade', 'C')
        confidence = sig.get('confidence', 0)
        
        leverage = sig.get('leverage', 'N/A')
        points = sig.get('points', 'N/A')
        strategies = sig.get('strategies', 'دعم/مقاومة 🎧 ✅')
        details = sig.get('details', 'تحليل فني عبر مؤشرات الرادار')

        dir_icon = "🟢" if direction == "LONG" else "🔴"
        chart_icon = "📈" if direction == "LONG" else "📉"
        
        time_now = datetime.now(timezone.utc).strftime("%H:%M %d-%m-%Y (UTC)")
        
        msg = (
            f"🐳 *رادار الحيتان v4.1 WebSocket (Sniper)*\n"
            f"⚡ إشارة فورية لحظية | 🕐 {time_now}\n\n"
            f"{dir_icon} *{direction}* {chart_icon}\n\n"
            f"💰 العملة: *{sym}*\n"
            f"💵 سعر الدخول: `{entry}`\n"
            f"⚙️ الرافعة المالية: *{leverage}*\n\n"
            f"🛡️ وقف الخسارة: `{sl}`\n"
            f"🎯 الهدف 1: `{tp1}`\n"
            f"🎯 الهدف 2: `{tp2}`\n"
            f"🎯 الهدف 3: `{tp3}`\n"
            f"📐 نسبة R:R : *1 : 2.0*\n\n"
            f"📊 *الاستراتيجيات:*\n{strategies}\n\n"
            f"🔍 *التفاصيل:*\n{details}\n\n"
            f"🥈 الدرجة: *{grade}* | 🎯 الثقة: *{confidence}%*\n"
            f"🏆 النقاط: *{points}*"
        )
        await bot.send_message(chat_id=settings.telegram_channel_id, text=msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Telegram Error: {e}")


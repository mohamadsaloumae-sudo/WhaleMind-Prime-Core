"""
services/telegram_service.py
═══════════════════════════════════════════════════════════════════════
TELEGRAM BOT — FULL INTEGRATION
- إرسال رسالة ترحيب عند /start
- بث إشارات HFT للقناة بتنسيق احترافي
- إشعارات فتح/إغلاق صفقات
- تنبيهات النظام (State A/B/C)
- Webhook handler عبر FastAPI
- زر Mini App مع كل رسالة
═══════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

from core.config import get_settings

log = logging.getLogger("telegram")

TG_API = "https://api.telegram.org/bot{token}/{method}"


# ── Low-level send ─────────────────────────────────────────────────────────────

async def _call(method: str, payload: Dict[str, Any]) -> Optional[dict]:
    settings = get_settings()
    if not settings.telegram_bot_token or not HAS_HTTPX:
        return None
    url = TG_API.format(token=settings.telegram_bot_token, method=method)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, json=payload)
            return r.json()
    except Exception as e:
        log.debug("Telegram API error (%s): %s", method, e)
        return None


async def send_message(
    chat_id: str,
    text: str,
    parse_mode: str = "HTML",
    reply_markup: Optional[dict] = None,
    disable_web_page_preview: bool = True,
) -> Optional[dict]:
    payload: Dict[str, Any] = {
        "chat_id":                  chat_id,
        "text":                     text,
        "parse_mode":               parse_mode,
        "disable_web_page_preview": disable_web_page_preview,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return await _call("sendMessage", payload)


async def set_webhook(webhook_url: str) -> Optional[dict]:
    return await _call("setWebhook", {
        "url":             webhook_url,
        "allowed_updates": ["message", "callback_query"],
        "drop_pending_updates": True,
    })


async def delete_webhook() -> Optional[dict]:
    return await _call("deleteWebhook", {"drop_pending_updates": True})


async def set_bot_commands() -> Optional[dict]:
    return await _call("setMyCommands", {"commands": [
        {"command": "start",     "description": "فتح التطبيق"},
        {"command": "status",    "description": "حالة النظام"},
        {"command": "signals",   "description": "آخر الإشارات"},
        {"command": "demo",      "description": "إحصائيات الديمو"},
        {"command": "help",      "description": "المساعدة"},
    ]})


# ── Mini App button ────────────────────────────────────────────────────────────

def _mini_app_keyboard(url: str = "") -> dict:
    settings = get_settings()
    app_url = url or settings.telegram_mini_app_url or ""
    if not app_url:
        return {}
    return {
        "inline_keyboard": [[
            {"text": "🐋 فتح WhaleX", "web_app": {"url": app_url}}
        ]]
    }


def _channel_keyboard() -> dict:
    settings = get_settings()
    app_url = settings.telegram_mini_app_url or ""
    if not app_url:
        return {}
    return {
        "inline_keyboard": [[
            {"text": "⚡ تداول الآن", "web_app": {"url": app_url}},
            {"text": "📊 Dashboard",  "web_app": {"url": app_url + "hft"}},
        ]]
    }


# ── Message templates ──────────────────────────────────────────────────────────

def _welcome_msg(first_name: str = "مستخدم") -> str:
    return (
        f"👋 <b>أهلاً وسهلاً {first_name}!</b>\n\n"
        f"🐋 <b>WhaleX Prime Core</b> — نظام تداول آلي بالذكاء الاصطناعي\n\n"
        f"<b>🔥 المزايا:</b>\n"
        f"• رادار مضاد للتلاعب (Anti-Spoof Radar)\n"
        f"• إشارات Futures حية مع VPIN + CVD\n"
        f"• مدير صفقات ذكي (Co-Pilot 500Hz)\n"
        f"• حساب تجريبي كامل (Demo Mode)\n"
        f"• تحليل AI بكلود المتقدم\n\n"
        f"<b>📋 الأوامر:</b>\n"
        f"/status — حالة النظام\n"
        f"/signals — آخر الإشارات\n"
        f"/demo — إحصائيات الديمو\n\n"
        f"<i>اضغط الزر أدناه لفتح التطبيق 👇</i>"
    )


def _signal_msg(data: dict) -> str:
    sym  = data.get("symbol", "—")
    dir_ = data.get("direction", data.get("signal", "—"))
    scr  = data.get("score", data.get("composite_score", 0))
    vpin = data.get("vpin", 0)
    reg  = data.get("regime", "—")
    ts   = time.strftime("%H:%M:%S")

    emoji = "🟢 LONG  📈" if "LONG" in str(dir_) else "🔴 SHORT 📉"
    grade = "🏆 S" if scr >= 90 else "🥇 A" if scr >= 75 else "🥈 B"

    return (
        f"⚡ <b>إشارة جديدة — {sym}</b>\n"
        f"{'─'*28}\n"
        f"{emoji}\n"
        f"📊 الدرجة: <b>{scr:.1f}/100</b> {grade}\n"
        f"🎯 الاتجاه: <b>{dir_}</b>\n"
        f"🌊 VPIN: <code>{vpin:.4f}</code>\n"
        f"📡 النظام: <code>{reg}</code>\n"
        f"🕐 الوقت: <code>{ts}</code>\n"
        f"{'─'*28}\n"
        f"<i>⚠️ ليست نصيحة مالية</i>"
    )


def _trade_opened_msg(data: dict) -> str:
    tid  = data.get("trade", "—")
    sym  = data.get("symbol", "—")
    dir_ = data.get("direction", "—")
    fill = data.get("fill", data.get("entry", 0))
    qty  = data.get("qty", 0)
    mode = data.get("mode", "DEMO")
    emoji = "🟢" if dir_ == "LONG" else "🔴"
    return (
        f"{emoji} <b>صفقة مفتوحة [{mode}]</b>\n"
        f"{'─'*24}\n"
        f"📌 الزوج:  <b>{sym}</b>\n"
        f"🎯 الاتجاه: <b>{dir_}</b>\n"
        f"💰 السعر:  <code>${fill:.2f}</code>\n"
        f"📦 الكمية: <code>{qty:.6f}</code>\n"
        f"🆔 ID: <code>{tid}</code>"
    )


def _trade_closed_msg(data: dict) -> str:
    tid  = data.get("trade", "—")
    sym  = data.get("symbol", "—")
    pnl  = data.get("pnl", 0)
    st   = data.get("state", "—")
    close= data.get("close_price", 0)
    emoji = "✅ ربح" if pnl >= 0 else "❌ خسارة"
    pnl_str = f"+${pnl:.4f}" if pnl >= 0 else f"-${abs(pnl):.4f}"
    return (
        f"{emoji} <b>صفقة مغلقة</b>\n"
        f"{'─'*24}\n"
        f"📌 الزوج:  <b>{sym}</b>\n"
        f"💵 PnL:   <b>{pnl_str}</b>\n"
        f"📉 السعر:  <code>${close:.2f}</code>\n"
        f"📊 الحالة: <code>{st}</code>\n"
        f"🆔 ID: <code>{tid}</code>"
    )


def _state_change_msg(data: dict) -> str:
    t    = data.get("type", "")
    tid  = data.get("trade", "—")
    sym  = data.get("symbol", "—")
    msgs = {
        "STATE_A_BREAKEVEN": (
            "🔒 <b>State A — تم تأمين نقطة التعادل</b>\n"
            f"الزوج: <b>{sym}</b> | SL انتقل لسعر الدخول\n"
            "✅ المخاطرة = صفر الآن"
        ),
        "STATE_B_EXPLOSION": (
            "🚀 <b>State B — انفجار السعر!</b>\n"
            f"الزوج: <b>{sym}</b>\n"
            "⚡ Trailing Stop AI مفعّل — يتابع الحائط"
        ),
        "STATE_C_EXHAUSTION": (
            "⚡ <b>State C — إشارة نفاد الزخم</b>\n"
            f"الزوج: <b>{sym}</b>\n"
            "💰 تم إغلاق 80% من الصفقة فوراً"
        ),
        "FORCE_CLOSE_ALL": (
            f"🛑 <b>إغلاق إجباري لجميع الصفقات</b>\n"
            f"تم إغلاق {data.get('count', 0)} صفقة بأمر الأدمن"
        ),
        "ACCOUNT_SWITCHED": (
            f"🔄 <b>تم تبديل وضع الحساب</b>\n"
            f"الوضع الجديد: <b>{data.get('mode', '—')}</b>"
        ),
    }
    return msgs.get(t, f"ℹ️ <b>{t}</b>\nID: {tid}")


def _system_status_msg(gcm_data: dict) -> str:
    score  = gcm_data.get("radar_score", 0)
    regime = gcm_data.get("radar_regime", "—")
    trades = gcm_data.get("active_trades", 0)
    mode   = gcm_data.get("account_mode", "—")
    equity = gcm_data.get("demo_equity", 0)
    ts     = time.strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"📊 <b>حالة النظام — WhaleX</b>\n"
        f"{'─'*28}\n"
        f"🎯 درجة الرادار:  <b>{score:.1f}/100</b>\n"
        f"🌊 النظام السوقي: <code>{regime}</code>\n"
        f"📈 الصفقات النشطة: <b>{trades}</b>\n"
        f"💼 وضع الحساب:   <b>{mode}</b>\n"
        f"💰 رصيد الديمو:  <b>${equity:,.2f}</b>\n"
        f"🕐 <code>{ts}</code>"
    )


# ══════════════════════════════════════════════════════════════════════════════
# TELEGRAM BOT SERVICE — main class
# ══════════════════════════════════════════════════════════════════════════════

class TelegramBotService:
    """
    يعالج incoming updates من Telegram ويرسل broadcasts للقناة.
    يعمل بطريقتين:
    - Webhook: FastAPI يستقبل التحديثات عبر POST /telegram/webhook
    - GCM Queue: يقرأ من GCM.tg_queue ويبث للقناة
    """

    def __init__(self) -> None:
        self._running = False

    async def setup(self) -> None:
        """يُستدعى عند الـ startup — يضبط الأوامر."""
        settings = get_settings()
        if not settings.telegram_bot_token:
            log.warning("TELEGRAM_BOT_TOKEN غير موضوع في .env — البوت معطّل")
            return
        await set_bot_commands()
        log.info("✅ Telegram bot commands registered")

        # إرسال رسالة تشغيل للأدمن
        if settings.telegram_admin_chat_id:
            await send_message(
                settings.telegram_admin_chat_id,
                "🟢 <b>WhaleX Prime Core v3 شغّال</b>\n"
                "جميع الأنظمة تعمل:\n"
                "✅ HFT Radar 100Hz\n"
                "✅ Position Copilot 500Hz\n"
                "✅ Demo Simulator\n"
                "✅ Macro Advisor\n"
                "✅ Telegram Bridge",
                reply_markup=_mini_app_keyboard(),
            )

    async def handle_update(self, update: dict) -> None:
        """يعالج update واحد من Telegram webhook."""
        msg = update.get("message", {})
        if not msg:
            return

        chat_id    = str(msg.get("chat", {}).get("id", ""))
        text       = msg.get("text", "").strip()
        first_name = msg.get("from", {}).get("first_name", "مستخدم")

        if not text or not chat_id:
            return

        if text.startswith("/start"):
            await send_message(
                chat_id,
                _welcome_msg(first_name),
                reply_markup=_mini_app_keyboard(),
            )

        elif text.startswith("/status"):
            try:
                from hft.engine.context import GCM
                data = {
                    "radar_score":   GCM.radar.composite_score,
                    "radar_regime":  GCM.radar.regime.value,
                    "active_trades": len(GCM.active_trades),
                    "account_mode":  GCM.current_mode.value,
                    "demo_equity":   GCM.demo_account.equity,
                }
                await send_message(chat_id, _system_status_msg(data),
                                   reply_markup=_mini_app_keyboard())
            except Exception as e:
                await send_message(chat_id, f"❌ خطأ: {e}")

        elif text.startswith("/signals"):
            try:
                from hft.engine.context import GCM
                from services.signals_service import get_signals
                sigs = get_signals()[:3]
                if not sigs:
                    await send_message(chat_id, "📭 لا توجد إشارات نشطة حالياً")
                else:
                    for s in sigs:
                        await send_message(chat_id, _signal_msg(s),
                                           reply_markup=_channel_keyboard())
            except Exception as e:
                await send_message(chat_id, f"❌ خطأ: {e}")

        elif text.startswith("/demo"):
            try:
                from hft.engine.context import GCM
                a = GCM.demo_account
                txt = (
                    f"💼 <b>إحصائيات الديمو</b>\n"
                    f"{'─'*24}\n"
                    f"💰 الرصيد:    <b>${a.balance:,.2f}</b>\n"
                    f"📈 Equity:    <b>${a.equity:,.2f}</b>\n"
                    f"💵 PnL الكلي: <b>${a.total_pnl:,.2f}</b>\n"
                    f"🏆 نسبة الفوز: <b>{a.win_rate:.1f}%</b>\n"
                    f"📊 عدد الصفقات: <b>{a.total_trades}</b>\n"
                    f"✅ ربح: <b>{a.wins}</b> | ❌ خسارة: <b>{a.losses}</b>\n"
                    f"📉 Max DD: <b>{a.max_drawdown*100:.2f}%</b>"
                )
                await send_message(chat_id, txt, reply_markup=_mini_app_keyboard())
            except Exception as e:
                await send_message(chat_id, f"❌ خطأ: {e}")

        elif text.startswith("/help"):
            await send_message(
                chat_id,
                "📖 <b>المساعدة — WhaleX</b>\n\n"
                "/start  — رسالة الترحيب\n"
                "/status — حالة النظام والرادار\n"
                "/signals — آخر 3 إشارات\n"
                "/demo   — إحصائيات الحساب التجريبي\n\n"
                "<i>للتداول الفعلي افتح التطبيق 👇</i>",
                reply_markup=_mini_app_keyboard(),
            )

    async def broadcast_to_channel(self, event_type: str, data: dict) -> None:
        """يبث حدث معين لقناة الإشارات."""
        settings = get_settings()
        channel  = settings.telegram_channel_id
        if not channel:
            return

        # اختر القالب حسب نوع الحدث
        signal_events = {"RADAR_SIGNAL", "new_signal"}
        trade_open    = {"DEMO_TRADE_OPENED", "TRADE_OPENED"}
        trade_close   = {"TRADE_CLOSED"}
        state_events  = {
            "STATE_A_BREAKEVEN", "STATE_B_EXPLOSION",
            "STATE_C_EXHAUSTION", "FORCE_CLOSE_ALL", "ACCOUNT_SWITCHED"
        }

        text    = None
        markup  = _channel_keyboard()

        if event_type in signal_events:
            merged = {**data, "signal": data.get("signal", data.get("direction", ""))}
            text   = _signal_msg(merged)
        elif event_type in trade_open:
            text   = _trade_opened_msg(data)
        elif event_type in trade_close:
            text   = _trade_closed_msg(data)
        elif event_type in state_events:
            text   = _state_change_msg({**data, "type": event_type})
            markup = _mini_app_keyboard()
        elif event_type == "admin_message":
            lvl   = data.get("level", "info")
            ico   = {"info":"ℹ️","warning":"⚠️","critical":"🚨"}.get(lvl,"📢")
            text  = f"{ico} <b>{data.get('message','')}</b>"

        if text:
            await send_message(channel, text, reply_markup=markup)

    async def run_queue_consumer(self) -> None:
        """
        يقرأ من GCM.tg_queue ويرسل للقناة.
        يعمل كـ asyncio task بعد startup.
        """
        from hft.engine.context import GCM
        self._running = True
        log.info("Telegram queue consumer started")
        while self._running:
            try:
                msg = await asyncio.wait_for(GCM.tg_queue.get(), timeout=1.0)
                event_type = msg.pop("type", "unknown")
                await self.broadcast_to_channel(event_type, msg)
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                log.debug("TG queue error: %s", e)

    def stop(self) -> None:
        self._running = False


# Singleton
TG = TelegramBotService()

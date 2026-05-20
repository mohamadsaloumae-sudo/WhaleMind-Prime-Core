from __future__ import annotations
import asyncio, logging
from typing import Any, Dict, Optional
try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False
from core.config import get_settings
log = logging.getLogger("telegram")
TG_API = "https://api.telegram.org/bot{token}/{method}"

async def _call(method: str, payload: Dict[str, Any]) -> Optional[dict]:
    s = get_settings()
    if not s.telegram_bot_token or not HAS_HTTPX: return None
    url = TG_API.format(token=s.telegram_bot_token, method=method)
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(url, json=payload)
            return r.json()
    except Exception as e:
        log.debug("TG error: %s", e)
        return None

async def send_message(chat_id: str, text: str, parse_mode: str = "HTML", reply_markup=None):
    p: Dict[str, Any] = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode, "disable_web_page_preview": True}
    if reply_markup: p["reply_markup"] = reply_markup
    return await _call("sendMessage", p)

async def set_webhook(url: str):
    return await _call("setWebhook", {"url": url, "allowed_updates": ["message", "callback_query"], "drop_pending_updates": True})

async def delete_webhook():
    return await _call("deleteWebhook", {"drop_pending_updates": True})

async def set_bot_commands():
    return await _call("setMyCommands", {"commands": [
        {"command": "start",   "description": "فتح التطبيق"},
        {"command": "status",  "description": "حالة النظام"},
        {"command": "signals", "description": "آخر الإشارات"},
        {"command": "demo",    "description": "احصائيات الديمو"},
        {"command": "help",    "description": "المساعدة"},
    ]})

def _kb():
    s = get_settings()
    u = s.telegram_mini_app_url or ""
    if not u: return {}
    return {"inline_keyboard": [[{"text": "فتح WhaleX", "web_app": {"url": u}}]]}

def _kb2():
    s = get_settings()
    u = s.telegram_mini_app_url or ""
    if not u: return {}
    return {"inline_keyboard": [[{"text": "تداول الآن", "web_app": {"url": u}}, {"text": "Dashboard", "web_app": {"url": u.rstrip("/") + "/hft"}}]]}

class TelegramBotService:
    def __init__(self): self._running = False

    async def setup(self):
        s = get_settings()
        if not s.telegram_bot_token:
            log.warning("TELEGRAM_BOT_TOKEN not set")
            return
        await set_bot_commands()
        log.info("Telegram bot ready")
        if s.telegram_admin_chat_id:
            await send_message(s.telegram_admin_chat_id, "WhaleX Prime Core v3 online", reply_markup=_kb())

    async def handle_update(self, update: dict):
        # (بقية كود handle_update الخاص بكِ كما هو)
        pass 

    async def broadcast_to_channel(self, event_type: str, data: dict):
        s = get_settings()
        ch = s.telegram_channel_id
        if not ch: return
        
        # الجسر الجديد: ربط إشارات الرادار بالدالة المخصصة
        if event_type in ("RADAR_SIGNAL", "new_signal"):
            try:
                from services.signals_service import broadcast_signal
                await broadcast_signal(data)
                return
            except Exception as e:
                log.error(f"Error calling broadcast_signal: {e}")

        text = None
        if event_type == "TRADE_CLOSED":
            text = f"PnL: ${data.get('pnl', 0):.4f}"
        elif event_type == "admin_message":
            text = data.get("message", "")
        
        if text:
            await send_message(ch, text, reply_markup=_kb2())

    async def run_queue_consumer(self):
        from hft.engine.context import GCM
        self._running = True
        log.info("Telegram queue consumer started")
        while self._running:
            try:
                msg = await asyncio.wait_for(GCM.tg_queue.get(), timeout=1.0)
                await self.broadcast_to_channel(msg.pop("type","unknown"), msg)
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                log.debug("TG queue error: %s", e)

    def stop(self): self._running = False

TG = TelegramBotService()

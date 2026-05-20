from __future__ import annotations
import logging
from fastapi import APIRouter, Request
from core.config import get_settings

router = APIRouter(prefix="/telegram", tags=["Telegram"])
log    = logging.getLogger("routers.telegram")

@router.post("/webhook")
async def webhook(request: Request):
    try:
        from services.telegram_service import TG
        update = await request.json()
        await TG.handle_update(update)
        return {"ok": True}
    except Exception as e:
        log.exception("Webhook error: %s", e)
        return {"ok": False}

@router.post("/setup-webhook")
async def setup_webhook():
    settings = get_settings()
    if not settings.telegram_bot_token:
        return {"error": "TELEGRAM_BOT_TOKEN not set"}
    if not settings.telegram_mini_app_url:
        return {"error": "TELEGRAM_MINI_APP_URL not set"}
    from services.telegram_service import set_webhook
    base = settings.telegram_mini_app_url.rstrip("/")
    webhook_url = f"{base}/telegram/webhook"
    result = await set_webhook(webhook_url)
    return {"webhook_url": webhook_url, "result": result}

@router.post("/delete-webhook")
async def delete_webhook_ep():
    from services.telegram_service import delete_webhook
    return {"result": await delete_webhook()}

@router.get("/info")
async def bot_info():
    settings = get_settings()
    return {
        "bot_token_set":    bool(settings.telegram_bot_token),
        "channel_set":      bool(settings.telegram_channel_id),
        "admin_chat_set":   bool(settings.telegram_admin_chat_id),
        "mini_app_url_set": bool(settings.telegram_mini_app_url),
        "webhook_url":      settings.telegram_mini_app_url.rstrip("/") + "/telegram/webhook" if settings.telegram_mini_app_url else "",
    }

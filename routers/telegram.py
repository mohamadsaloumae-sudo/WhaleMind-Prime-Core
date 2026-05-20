"""
routers/telegram.py
Webhook endpoint + setup/delete helpers.
"""
from __future__ import annotations
import logging
from fastapi import APIRouter, HTTPException, Request
from core.config import get_settings
from services.telegram_service import TG, set_webhook, delete_webhook

router = APIRouter(prefix="/telegram", tags=["Telegram"])
log    = logging.getLogger("routers.telegram")


@router.post("/webhook")
async def webhook(request: Request):
    """Telegram calls this URL for every update."""
    try:
        update = await request.json()
        await TG.handle_update(update)
        return {"ok": True}
    except Exception as e:
        log.exception("Webhook error: %s", e)
        return {"ok": False}


@router.post("/setup-webhook")
async def setup_webhook_endpoint():
    """Call this once to register your webhook URL with Telegram."""
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise HTTPException(400, "TELEGRAM_BOT_TOKEN not set in .env")
    if not settings.telegram_mini_app_url:
        raise HTTPException(400, "TELEGRAM_MINI_APP_URL not set in .env (needed for webhook URL)")

    # Webhook URL = your server URL + /telegram/webhook
    base = settings.telegram_mini_app_url.rstrip("/")
    webhook_url = f"{base}/telegram/webhook"
    result = await set_webhook(webhook_url)
    return {"webhook_url": webhook_url, "result": result}


@router.post("/delete-webhook")
async def delete_webhook_endpoint():
    """Switch from webhook to polling (for testing)."""
    result = await delete_webhook()
    return {"result": result}


@router.get("/info")
async def bot_info():
    """Check bot token and channel config."""
    settings = get_settings()
    return {
        "bot_token_set":     bool(settings.telegram_bot_token),
        "channel_set":       bool(settings.telegram_channel_id),
        "admin_chat_set":    bool(settings.telegram_admin_chat_id),
        "mini_app_url_set":  bool(settings.telegram_mini_app_url),
        "webhook_url":       (settings.telegram_mini_app_url or "").rstrip("/") + "/telegram/webhook",
    }

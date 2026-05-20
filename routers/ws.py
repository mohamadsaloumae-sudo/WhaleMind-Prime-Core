"""
routers/ws.py — WebSocket /ws/live endpoint.
"""
import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.websocket_manager import ws_manager

router = APIRouter(tags=["WebSocket"])
logger = logging.getLogger(__name__)


@router.websocket("/ws/live")
async def websocket_live(ws: WebSocket) -> None:
    await ws_manager.connect(ws)
    try:
        # Send a welcome ping so the client knows it's connected
        await ws_manager.send_personal(ws, "connected", {"msg": "WhaleX Live Engine active"})
        # Keep connection alive; client messages are ignored (read-only feed)
        while True:
            try:
                await asyncio.wait_for(ws.receive_text(), timeout=30)
            except asyncio.TimeoutError:
                await ws.send_text('{"event":"ping"}')
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)
        logger.info("Client disconnected cleanly")
    except Exception as exc:
        logger.warning("WS error: %s", exc)
        ws_manager.disconnect(ws)

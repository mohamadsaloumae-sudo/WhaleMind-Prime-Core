"""
core/websocket_manager.py — manages all active WebSocket connections
and broadcasts live events to every connected client.
"""
import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)
        logger.info("WS client connected — total: %d", len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        self._connections = [c for c in self._connections if c is not ws]
        logger.info("WS client disconnected — total: %d", len(self._connections))

    async def broadcast(self, event: str, data: Any) -> None:
        """Broadcast a typed event payload to every live connection."""
        payload = json.dumps({"event": event, "data": data})
        dead: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def send_personal(self, ws: WebSocket, event: str, data: Any) -> None:
        try:
            await ws.send_text(json.dumps({"event": event, "data": data}))
        except Exception:
            self.disconnect(ws)


# Singleton — imported everywhere it's needed
ws_manager = ConnectionManager()

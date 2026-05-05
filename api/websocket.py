"""
WebSocket manager for DACRO — maintains active connections and broadcasts events.
All real-time updates (zone_update, negotiation, xai, agent_state, dispatch) flow through here.
"""

import dataclasses
import json
import logging
from typing import List

from fastapi import WebSocket

from messaging.message_types import WebSocketEvent

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Thread-safe (asyncio-safe) manager for active WebSocket connections."""

    def __init__(self) -> None:
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info("WebSocket: client connected (total=%d)", len(self.active_connections))

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info("WebSocket: client disconnected (total=%d)", len(self.active_connections))

    async def broadcast(self, message: dict) -> None:
        """Send a raw dict to all connected clients as JSON."""
        dead: List[WebSocket] = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead.append(connection)
        for ws in dead:
            self.disconnect(ws)

    async def broadcast_event(self, event: WebSocketEvent) -> None:
        """Serialise a WebSocketEvent and broadcast to all clients."""
        if dataclasses.is_dataclass(event):
            payload = dataclasses.asdict(event)
        else:
            payload = event
        await self.broadcast(payload)

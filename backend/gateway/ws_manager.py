"""Manages all active WebSocket connections, grouped by stage_id."""
from __future__ import annotations

import logging
from collections import defaultdict

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        # stage_id → set of live WebSocket connections
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)

    async def connect(self, ws: WebSocket, stage_id: int) -> None:
        await ws.accept()
        self._connections[stage_id].add(ws)
        count = len(self._connections[stage_id])
        logger.info("[stage %d] client connected  (total: %d)", stage_id, count)

    def disconnect(self, ws: WebSocket, stage_id: int) -> None:
        self._connections[stage_id].discard(ws)
        count = len(self._connections[stage_id])
        logger.info("[stage %d] client disconnected (remaining: %d)", stage_id, count)

    async def broadcast(self, stage_id: int, message: str) -> None:
        """Send message to all clients on a stage; silently removes dead connections."""
        dead: list[WebSocket] = []
        for ws in list(self._connections.get(stage_id, set())):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self._connections[stage_id].discard(ws)

        if dead:
            logger.debug("[stage %d] pruned %d dead connection(s)", stage_id, len(dead))

    def viewer_count(self, stage_id: int) -> int:
        return len(self._connections.get(stage_id, set()))

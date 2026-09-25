"""Manages all active WebSocket connections, grouped by (stage_id, lang)."""
from __future__ import annotations

import logging
from collections import defaultdict

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        # (stage_id, lang) → set of live WebSocket connections
        # lang="original" means the client wants the untranslated transcript.
        self._connections: dict[tuple[int, str], set[WebSocket]] = defaultdict(set)

    async def connect(self, ws: WebSocket, stage_id: int, lang: str = "original") -> None:
        await ws.accept()
        self._connections[(stage_id, lang)].add(ws)
        logger.info(
            "[stage %d] [%s] client connected  (total stage: %d)",
            stage_id, lang, self.viewer_count(stage_id),
        )

    def disconnect(self, ws: WebSocket, stage_id: int, lang: str = "original") -> None:
        self._connections[(stage_id, lang)].discard(ws)
        logger.info(
            "[stage %d] [%s] client disconnected (remaining stage: %d)",
            stage_id, lang, self.viewer_count(stage_id),
        )

    async def broadcast(self, stage_id: int, lang: str, message: str) -> None:
        """Send message to all clients subscribed to a specific stage+language."""
        await self._send_to_key((stage_id, lang), message)

    async def broadcast_stage(self, stage_id: int, message: str) -> None:
        """Send message to ALL clients for a stage regardless of language (e.g. status events)."""
        keys = [key for key in self._connections if key[0] == stage_id]
        for key in keys:
            await self._send_to_key(key, message)

    async def _send_to_key(self, key: tuple[int, str], message: str) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._connections.get(key, set())):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections[key].discard(ws)
        if dead:
            logger.debug("[stage %d] [%s] pruned %d dead connection(s)", key[0], key[1], len(dead))

    def viewer_count(self, stage_id: int) -> int:
        return sum(
            len(conns) for key, conns in self._connections.items() if key[0] == stage_id
        )

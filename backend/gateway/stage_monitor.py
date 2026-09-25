"""StageMonitor: tracks real-time state of every active stage for the production panel."""
from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from fastapi import WebSocket

from backend.gateway.ws_manager import ConnectionManager

logger = logging.getLogger(__name__)


@dataclass
class StageSnapshot:
    stage_id: int
    worker_status: str = "unknown"    # active | idle | reconnecting | error | unknown
    viewer_count: int = 0
    latency_ms: Optional[int] = None
    last_text: Optional[str] = None
    last_seen_ts: Optional[float] = None
    active_langs: list[str] = field(default_factory=list)
    error_count: int = 0              # incremented on each "reconnecting" transition


class StageMonitor:
    """
    Maintains a live snapshot of every stage.
    Fed by RedisSubscriber via on_transcript() / on_status().
    Broadcasts the full snapshot list to all connected monitor WebSocket clients.
    """

    def __init__(self, manager: ConnectionManager) -> None:
        self._manager = manager
        self._stages: dict[int, StageSnapshot] = {}
        self._clients: set[WebSocket] = set()
        self._ticker: Optional[asyncio.Task[None]] = None

    # ── Called by RedisSubscriber ──────────────────────────────────────────

    def on_transcript(self, stage_id: int, raw: str) -> None:
        """Parse a raw transcript JSON string and update the snapshot."""
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError:
            return
        if ev.get("event") != "transcript" or not ev.get("is_final"):
            return

        snap = self._ensure(stage_id)
        snap.latency_ms = ev.get("latency_ms")
        snap.last_text = ev.get("text")
        snap.last_seen_ts = ev.get("timestamp") or time.time()

        lang = ev.get("language", "original")
        if lang not in snap.active_langs:
            snap.active_langs.append(lang)

        asyncio.create_task(self._push(), name="monitor-push")

    def on_status(self, stage_id: int, raw: str) -> None:
        """Parse a raw status JSON string and update the snapshot."""
        try:
            ev = json.loads(raw)
        except json.JSONDecodeError:
            return
        if ev.get("event") != "stage_status":
            return

        snap = self._ensure(stage_id)
        new_status = ev.get("status", "unknown")
        if new_status == "reconnecting" and snap.worker_status != "reconnecting":
            snap.error_count += 1
        snap.worker_status = new_status

        asyncio.create_task(self._push(), name="monitor-push")

    # ── WebSocket client management ────────────────────────────────────────

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)
        # Send current snapshot immediately on connect.
        await self._send(ws, self._payload())
        logger.info("Monitor client connected (total: %d)", len(self._clients))

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)
        logger.info("Monitor client disconnected (remaining: %d)", len(self._clients))

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> None:
        self._ticker = asyncio.create_task(self._tick(), name="monitor-tick")

    async def stop(self) -> None:
        if self._ticker:
            self._ticker.cancel()
            await asyncio.gather(self._ticker, return_exceptions=True)

    # ── Internals ──────────────────────────────────────────────────────────

    def _ensure(self, stage_id: int) -> StageSnapshot:
        if stage_id not in self._stages:
            self._stages[stage_id] = StageSnapshot(stage_id=stage_id)
        return self._stages[stage_id]

    def _payload(self) -> str:
        # Refresh viewer counts from ConnectionManager before serialising.
        for snap in self._stages.values():
            snap.viewer_count = self._manager.viewer_count(snap.stage_id)
        stages = sorted(self._stages.values(), key=lambda s: s.stage_id)
        return json.dumps({
            "event": "monitor_update",
            "stages": [dataclasses.asdict(s) for s in stages],
        })

    async def _push(self) -> None:
        """Send current state to all monitor clients."""
        if not self._clients:
            return
        payload = self._payload()
        dead: list[WebSocket] = []
        for ws in list(self._clients):
            await self._send(ws, payload, dead)
        for ws in dead:
            self._clients.discard(ws)

    @staticmethod
    async def _send(ws: WebSocket, payload: str, dead: list[WebSocket] | None = None) -> None:
        try:
            await ws.send_text(payload)
        except Exception:
            if dead is not None:
                dead.append(ws)

    async def _tick(self) -> None:
        """Periodic refresh every 5 s to keep viewer counts current."""
        while True:
            await asyncio.sleep(5)
            if self._clients:
                await self._push()

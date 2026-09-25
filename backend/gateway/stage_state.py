"""
In-memory cache of current state for all stages.

Updated on every Redis Pub/Sub event; pushes JSON snapshots to connected
dashboard WebSocket clients.  A periodic ticker refreshes viewer counts
and staleness indicators even when no events are arriving.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from fastapi import WebSocket
    from backend.gateway.ws_manager import ConnectionManager

logger = logging.getLogger(__name__)

NUM_STAGES = 10
_TICKER_INTERVAL = 5.0  # seconds between periodic dashboard refreshes


@dataclass
class StageSnapshot:
    """Live state of one stage as reported to the dashboard."""

    stage_id: int
    worker_status: str = "unknown"      # idle / active / reconnecting / error / unknown
    viewer_count: int = 0
    latency_ms: Optional[int] = None    # from most recent final transcript
    last_text: Optional[str] = None     # text of most recent final transcript
    last_seen_ts: Optional[float] = None  # Unix timestamp of last event (status or final)
    muted: bool = False


class StageStateCache:
    """
    Thread-safe (single-event-loop) in-memory state store for all stages.

    Usage
    -----
    - Call `start()` after the event loop is running (inside lifespan).
    - Feed events via `await on_event(stage_id, raw_json)`.
    - Mute/unmute stages via `set_muted(stage_id, bool)`.
    - Dashboard WebSocket clients register via `connect_dashboard` / `disconnect_dashboard`.
    """

    def __init__(self, manager: "ConnectionManager") -> None:
        self._manager = manager
        self._states: dict[int, StageSnapshot] = {
            i: StageSnapshot(stage_id=i) for i in range(1, NUM_STAGES + 1)
        }
        self._dashboard_ws: set["WebSocket"] = set()
        self._ticker_task: Optional[asyncio.Task[None]] = None

    # ── Lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> None:
        self._ticker_task = asyncio.create_task(self._ticker(), name="dashboard-tick")

    async def stop(self) -> None:
        if self._ticker_task:
            self._ticker_task.cancel()
            await asyncio.gather(self._ticker_task, return_exceptions=True)

    async def _ticker(self) -> None:
        while True:
            await asyncio.sleep(_TICKER_INTERVAL)
            self._sync_viewer_counts()
            await self._broadcast()

    # ── Event ingestion ───────────────────────────────────────────────────

    def _sync_viewer_counts(self) -> None:
        for snap in self._states.values():
            snap.viewer_count = self._manager.viewer_count(snap.stage_id)

    async def on_event(self, stage_id: int, raw: str) -> None:
        """
        Called by RedisSubscriber for every incoming Pub/Sub message.
        Updates the in-memory snapshot and pushes to dashboard clients when
        there is a meaningful change.
        """
        if stage_id not in self._states:
            self._states[stage_id] = StageSnapshot(stage_id=stage_id)
        snap = self._states[stage_id]
        snap.viewer_count = self._manager.viewer_count(stage_id)

        try:
            event = json.loads(raw)
        except Exception:
            return

        event_type = event.get("event")
        should_push = False

        if event_type == "stage_status":
            new_status = event.get("status", "unknown")
            if snap.worker_status != new_status:
                should_push = True
            snap.worker_status = new_status
            snap.last_seen_ts = event.get("timestamp") or time.time()

        elif event_type == "transcript" and event.get("is_final"):
            snap.last_text = event.get("text")
            snap.last_seen_ts = event.get("timestamp") or time.time()
            snap.latency_ms = event.get("latency_ms")
            should_push = True

        if should_push:
            await self._broadcast()

    # ── Mute control ──────────────────────────────────────────────────────

    def set_muted(self, stage_id: int, muted: bool) -> None:
        if stage_id in self._states:
            self._states[stage_id].muted = muted
        else:
            self._states[stage_id] = StageSnapshot(stage_id=stage_id, muted=muted)

    def is_muted(self, stage_id: int) -> bool:
        snap = self._states.get(stage_id)
        return snap.muted if snap else False

    def load_muted_stages(self, stage_ids: set[int]) -> None:
        """Restore mute state from Redis on gateway startup."""
        for sid in stage_ids:
            self.set_muted(sid, True)

    # ── Dashboard WebSocket ───────────────────────────────────────────────

    async def connect_dashboard(self, ws: "WebSocket") -> None:
        """Accept a dashboard connection and send the full initial snapshot."""
        self._dashboard_ws.add(ws)
        await self._send_to(ws)

    def disconnect_dashboard(self, ws: "WebSocket") -> None:
        self._dashboard_ws.discard(ws)

    async def broadcast_update(self) -> None:
        """Public entry point — push the current snapshot to all dashboard clients."""
        await self._broadcast()

    # ── Internal helpers ──────────────────────────────────────────────────

    def get_snapshots(self) -> list[StageSnapshot]:
        self._sync_viewer_counts()
        return [self._states[i] for i in sorted(self._states)]

    def _build_payload(self) -> str:
        self._sync_viewer_counts()
        return json.dumps({
            "event": "dashboard_update",
            "stages": [asdict(self._states[i]) for i in sorted(self._states)],
        })

    async def _send_to(self, ws: "WebSocket") -> None:
        try:
            await ws.send_text(self._build_payload())
        except Exception:
            self._dashboard_ws.discard(ws)

    async def _broadcast(self) -> None:
        if not self._dashboard_ws:
            return
        payload = self._build_payload()
        dead: set = set()
        for ws in list(self._dashboard_ws):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        self._dashboard_ws -= dead

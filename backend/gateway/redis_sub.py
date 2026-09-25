"""Redis Pub/Sub subscriber: listens to all stage channels and fans out to WebSockets."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import redis.asyncio as aioredis

from backend.shared.config import settings
from backend.gateway.stage_state import StageStateCache
from backend.gateway.ws_manager import ConnectionManager

logger = logging.getLogger(__name__)

_PATTERNS = ("stage:*:transcript", "stage:*:status")


class RedisSubscriber:
    def __init__(self, manager: ConnectionManager, state_cache: StageStateCache) -> None:
        self._manager = manager
        self._state_cache = state_cache
        self._redis: Optional[aioredis.Redis] = None  # type: ignore[type-arg]
        self._pubsub: Optional[aioredis.client.PubSub] = None
        self._task: Optional[asyncio.Task[None]] = None

    async def start(self) -> None:
        self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        self._pubsub = self._redis.pubsub()
        await self._pubsub.psubscribe(*_PATTERNS)
        logger.info("Redis subscriber armed on patterns: %s", _PATTERNS)
        self._task = asyncio.create_task(self._listen(), name="redis-sub")

    async def _listen(self) -> None:
        try:
            async for message in self._pubsub.listen():
                if message["type"] not in ("pmessage", "message"):
                    continue

                channel: str = message.get("channel", "")
                data: str = message.get("data", "")

                # channel format: "stage:{id}:transcript" or "stage:{id}:status"
                parts = channel.split(":")
                if len(parts) < 3:
                    continue
                try:
                    stage_id = int(parts[1])
                except ValueError:
                    continue

                channel_suffix = parts[2]  # "transcript" or "status"

                # Always update the dashboard state cache.
                await self._state_cache.on_event(stage_id, data)

                # Muted stages: suppress transcript delivery to stage viewers
                # but let status events through so the worker status stays visible.
                if channel_suffix == "transcript" and self._state_cache.is_muted(stage_id):
                    continue

                await self._manager.broadcast(stage_id, data)

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Redis subscriber crashed: %s", exc)
        finally:
            await self._cleanup()

    async def _cleanup(self) -> None:
        if self._pubsub:
            try:
                await self._pubsub.punsubscribe()
                await self._pubsub.aclose()
            except Exception:
                pass
        if self._redis:
            try:
                await self._redis.aclose()
            except Exception:
                pass

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)

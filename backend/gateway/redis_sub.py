"""Redis Pub/Sub subscriber: listens to all stage channels and fans out to WebSockets."""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import redis.asyncio as aioredis

from backend.shared.config import settings
from backend.gateway.ws_manager import ConnectionManager
from backend.gateway.stage_monitor import StageMonitor

logger = logging.getLogger(__name__)

_PATTERNS = ("stage:*:transcript", "stage:*:transcript:*", "stage:*:status")


class RedisSubscriber:
    def __init__(self, manager: ConnectionManager, monitor: StageMonitor) -> None:
        self._manager = manager
        self._monitor = monitor
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

                # Parse: "stage:{id}:transcript", "stage:{id}:transcript:{lang}", "stage:{id}:status"
                parts = channel.split(":")
                if len(parts) < 3:
                    continue
                try:
                    stage_id = int(parts[1])
                except ValueError:
                    continue

                channel_type = parts[2]

                if channel_type == "status":
                    self._monitor.on_status(stage_id, data)
                    await self._manager.broadcast_stage(stage_id, data)

                elif channel_type == "transcript":
                    if len(parts) == 3:
                        lang = "original"
                    else:
                        lang = parts[3]
                    self._monitor.on_transcript(stage_id, data)
                    await self._manager.broadcast(stage_id, lang, data)

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

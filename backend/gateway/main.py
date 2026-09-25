"""FastAPI gateway: WebSocket endpoint + Redis subscriber fan-out."""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

import redis.asyncio as aioredis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from backend.shared.config import settings
from backend.gateway.redis_sub import RedisSubscriber
from backend.gateway.ws_manager import ConnectionManager

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_manager = ConnectionManager()
_subscriber = RedisSubscriber(_manager)
_redis: Optional[aioredis.Redis] = None  # type: ignore[type-arg]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _redis
    _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    await _subscriber.start()
    logger.info("Gateway up on %s:%d", settings.gateway_host, settings.gateway_port)
    yield
    await _subscriber.stop()
    if _redis:
        await _redis.aclose()
    logger.info("Gateway shut down")


app = FastAPI(title="transcribe-ia gateway", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/ws")
async def ws_endpoint(
    ws: WebSocket,
    stage: int = 1,
    lang: str = "es",
) -> None:
    await _manager.connect(ws, stage)

    # Send recent history so the client isn't staring at a blank screen
    if _redis:
        raw_history = await _redis.lrange(f"stage:{stage}:history", 0, 29)
        if raw_history:
            lines = [json.loads(h) for h in reversed(raw_history)]
            await ws.send_text(
                json.dumps({"type": "history", "stage_id": stage, "lines": lines})
            )

        # Send current stage status if available
        state = await _redis.hgetall(f"stage:{stage}:state")
        if state:
            await ws.send_text(
                json.dumps({"type": "stage_status", "stage_id": stage, **state})
            )

    try:
        while True:
            text = await ws.receive_text()
            msg = json.loads(text)
            if msg.get("type") == "ping":
                await ws.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("WebSocket error for stage %d: %s", stage, exc)
    finally:
        _manager.disconnect(ws, stage)

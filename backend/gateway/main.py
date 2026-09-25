"""FastAPI gateway: WebSocket endpoint + Redis subscriber fan-out."""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

import redis.asyncio as aioredis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from fastapi.responses import Response

from backend.shared.config import settings
from backend.shared.models import Glossary, TranscriptEvent
from backend.gateway.redis_sub import RedisSubscriber
from backend.gateway.transcript_export import build_segments, to_srt, to_vtt
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


# ── Glossary API ──────────────────────────────────────────────────────────────


def _glossary_key(stage_id: int) -> str:
    return f"stage:{stage_id}:glossary"


@app.put("/stages/{stage_id}/glossary", status_code=200)
async def put_glossary(stage_id: int, payload: Glossary) -> dict:
    """Replace the glossary for a stage. Takes effect on the worker's next reconnect."""
    if _redis is None:
        return {"error": "Redis not available"}, 503  # type: ignore[return-value]
    await _redis.set(_glossary_key(stage_id), payload.model_dump_json())
    logger.info("Glossary updated for stage %d: %d term(s)", stage_id, len(payload.terms))
    return {"stage_id": stage_id, "terms": payload.terms, "count": len(payload.terms)}


@app.get("/stages/{stage_id}/glossary")
async def get_glossary(stage_id: int) -> dict:
    """Return the current glossary for a stage."""
    if _redis is None:
        return {"stage_id": stage_id, "terms": [], "count": 0}
    raw = await _redis.get(_glossary_key(stage_id))
    if not raw:
        return {"stage_id": stage_id, "terms": [], "count": 0}
    terms: list[str] = json.loads(raw).get("terms", [])
    return {"stage_id": stage_id, "terms": terms, "count": len(terms)}


@app.delete("/stages/{stage_id}/glossary", status_code=200)
async def delete_glossary(stage_id: int) -> dict:
    """Clear the glossary for a stage."""
    if _redis is not None:
        await _redis.delete(_glossary_key(stage_id))
    logger.info("Glossary cleared for stage %d", stage_id)
    return {"stage_id": stage_id, "terms": [], "count": 0}


# ── Transcript export ─────────────────────────────────────────────────────────


async def _load_all_history(stage_id: int) -> list[TranscriptEvent]:
    """
    Fetch every final transcript event stored for a stage, oldest first.

    Redis history is written with lpush (newest at index 0), so lrange 0 -1
    returns items newest-first; reversing restores chronological order.
    Malformed JSON items are silently dropped.
    """
    if _redis is None:
        return []
    raw_items = await _redis.lrange(f"stage:{stage_id}:history", 0, -1)
    events: list[TranscriptEvent] = []
    for raw in reversed(raw_items):
        try:
            events.append(TranscriptEvent.model_validate_json(raw))
        except Exception:
            pass
    return events


@app.get("/stages/{stage_id}/transcript.vtt")
async def export_vtt(stage_id: int) -> Response:
    """Export the stage transcript as a WebVTT subtitle file."""
    events = await _load_all_history(stage_id)
    segments = build_segments(events)
    content = to_vtt(segments)
    return Response(
        content=content,
        media_type="text/vtt; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="stage{stage_id}.vtt"',
            "Cache-Control": "no-store",
        },
    )


@app.get("/stages/{stage_id}/transcript.srt")
async def export_srt(stage_id: int) -> Response:
    """Export the stage transcript as an SRT subtitle file."""
    events = await _load_all_history(stage_id)
    segments = build_segments(events)
    content = to_srt(segments)
    return Response(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="stage{stage_id}.srt"',
            "Cache-Control": "no-store",
        },
    )


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
                json.dumps({"event": "history", "stage_id": stage, "lines": lines})
            )

        # Send current stage status if available
        state = await _redis.hgetall(f"stage:{stage}:state")
        if state:
            await ws.send_text(
                json.dumps({"event": "stage_status", "stage_id": stage, **state})
            )

    try:
        while True:
            text = await ws.receive_text()
            msg = json.loads(text)
            if msg.get("type") == "ping":
                await ws.send_text(json.dumps({"event": "pong"}))
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("WebSocket error for stage %d: %s", stage, exc)
    finally:
        _manager.disconnect(ws, stage)

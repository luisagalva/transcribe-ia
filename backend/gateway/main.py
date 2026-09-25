"""FastAPI gateway: WebSocket endpoint + Redis subscriber fan-out."""
from __future__ import annotations

import dataclasses
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
from backend.gateway.stage_monitor import StageMonitor
from backend.gateway.transcript_export import build_segments, to_srt, to_vtt
from backend.gateway.ws_manager import ConnectionManager

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_manager = ConnectionManager()
_monitor = StageMonitor(_manager)
_subscriber = RedisSubscriber(_manager, _monitor)
_redis: Optional[aioredis.Redis] = None  # type: ignore[type-arg]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _redis
    _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    await _subscriber.start()
    _monitor.start()
    logger.info("Gateway up on %s:%d", settings.gateway_host, settings.gateway_port)
    yield
    await _monitor.stop()
    await _subscriber.stop()
    if _redis:
        await _redis.aclose()
    logger.info("Gateway shut down")


app = FastAPI(title="transcribe-ia gateway", version="0.3.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health ────────────────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# ── Monitor REST (snapshot for initial load / polling fallback) ───────────────


@app.get("/monitor/stages")
async def monitor_stages() -> dict:
    """Return current snapshot of all known stages."""
    stages = sorted(_monitor._stages.values(), key=lambda s: s.stage_id)
    return {"stages": [dataclasses.asdict(s) for s in stages]}


# ── Monitor WebSocket ─────────────────────────────────────────────────────────


@app.websocket("/ws/monitor")
async def ws_monitor(ws: WebSocket) -> None:
    """
    Real-time production monitor feed.
    Pushes a full StageSnapshot list on connect and on every meaningful state change.
    No authentication required (internal network tool).
    """
    await _monitor.connect(ws)
    try:
        while True:
            text = await ws.receive_text()
            if text == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("Monitor WS error: %s", exc)
    finally:
        _monitor.disconnect(ws)


# ── Glossary API ──────────────────────────────────────────────────────────────


def _glossary_key(stage_id: int) -> str:
    return f"stage:{stage_id}:glossary"


@app.put("/stages/{stage_id}/glossary", status_code=200)
async def put_glossary(stage_id: int, payload: Glossary) -> dict:
    if _redis is None:
        return {"error": "Redis not available"}, 503  # type: ignore[return-value]
    await _redis.set(_glossary_key(stage_id), payload.model_dump_json())
    logger.info("Glossary updated for stage %d: %d term(s)", stage_id, len(payload.terms))
    return {"stage_id": stage_id, "terms": payload.terms, "count": len(payload.terms)}


@app.get("/stages/{stage_id}/glossary")
async def get_glossary(stage_id: int) -> dict:
    if _redis is None:
        return {"stage_id": stage_id, "terms": [], "count": 0}
    raw = await _redis.get(_glossary_key(stage_id))
    if not raw:
        return {"stage_id": stage_id, "terms": [], "count": 0}
    terms: list[str] = json.loads(raw).get("terms", [])
    return {"stage_id": stage_id, "terms": terms, "count": len(terms)}


@app.delete("/stages/{stage_id}/glossary", status_code=200)
async def delete_glossary(stage_id: int) -> dict:
    if _redis is not None:
        await _redis.delete(_glossary_key(stage_id))
    logger.info("Glossary cleared for stage %d", stage_id)
    return {"stage_id": stage_id, "terms": [], "count": 0}


# ── Transcript export ─────────────────────────────────────────────────────────


async def _load_history(stage_id: int, lang: str = "original") -> list[TranscriptEvent]:
    if _redis is None:
        return []
    key = (
        f"stage:{stage_id}:history"
        if lang == "original"
        else f"stage:{stage_id}:history:{lang}"
    )
    raw_items = await _redis.lrange(key, 0, -1)
    events: list[TranscriptEvent] = []
    for raw in reversed(raw_items):
        try:
            events.append(TranscriptEvent.model_validate_json(raw))
        except Exception:
            pass
    return events


@app.get("/stages/{stage_id}/transcript.vtt")
async def export_vtt(stage_id: int, lang: str = "original") -> Response:
    events = await _load_history(stage_id, lang)
    segments = build_segments(events)
    content = to_vtt(segments)
    suffix = "" if lang == "original" else f".{lang}"
    return Response(
        content=content,
        media_type="text/vtt; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="stage{stage_id}{suffix}.vtt"',
            "Cache-Control": "no-store",
        },
    )


@app.get("/stages/{stage_id}/transcript.srt")
async def export_srt(stage_id: int, lang: str = "original") -> Response:
    events = await _load_history(stage_id, lang)
    segments = build_segments(events)
    content = to_srt(segments)
    suffix = "" if lang == "original" else f".{lang}"
    return Response(
        content=content,
        media_type="text/plain; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="stage{stage_id}{suffix}.srt"',
            "Cache-Control": "no-store",
        },
    )


# ── Stage WebSocket ───────────────────────────────────────────────────────────


@app.websocket("/ws")
async def ws_endpoint(
    ws: WebSocket,
    stage: int = 1,
    lang: str = "original",
) -> None:
    """
    Real-time transcript WebSocket.
    lang: "original" (untranslated) | es | en | zh | pt
    """
    await _manager.connect(ws, stage, lang)

    if _redis:
        hist_key = (
            f"stage:{stage}:history"
            if lang == "original"
            else f"stage:{stage}:history:{lang}"
        )
        raw_history = await _redis.lrange(hist_key, 0, 29)
        if raw_history:
            lines = [json.loads(h) for h in reversed(raw_history)]
            await ws.send_text(
                json.dumps({"event": "history", "stage_id": stage, "lines": lines})
            )

    try:
        while True:
            text = await ws.receive_text()
            try:
                msg = json.loads(text)
                if msg.get("type") == "ping":
                    await ws.send_text(json.dumps({"event": "pong"}))
            except (json.JSONDecodeError, AttributeError):
                pass
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("WS error stage %d lang %s: %s", stage, lang, exc)
    finally:
        _manager.disconnect(ws, stage, lang)

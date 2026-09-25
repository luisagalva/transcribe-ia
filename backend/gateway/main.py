"""FastAPI gateway: WebSocket endpoint + Redis subscriber fan-out."""
from __future__ import annotations

import dataclasses
import json
import logging
import secrets
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, field_validator

from backend.shared.config import settings
from backend.shared.models import Glossary, TranscriptEvent
from backend.gateway.redis_sub import RedisSubscriber
from backend.gateway.session_manager import SessionManager, resolve_url
from backend.gateway.stage_state import StageStateCache
from backend.gateway.transcript_export import build_segments, to_srt, to_vtt
from backend.gateway.ws_manager import ConnectionManager

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_manager = ConnectionManager()
_state_cache = StageStateCache(_manager)
_subscriber = RedisSubscriber(_manager, _state_cache)
_session_manager = SessionManager()
_redis: Optional[aioredis.Redis] = None  # type: ignore[type-arg]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _redis
    _redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    # Restore persisted mute state so it survives gateway restarts.
    muted_raw: set[str] = await _redis.smembers("dashboard:muted_stages")
    _state_cache.load_muted_stages({int(s) for s in muted_raw if s.isdigit()})

    await _subscriber.start()
    _state_cache.start()
    logger.info("Gateway up on %s:%d", settings.gateway_host, settings.gateway_port)
    yield
    await _session_manager.stop_all()
    await _state_cache.stop()
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


# ── Auth helper ───────────────────────────────────────────────────────────────


def _verify_token(token: str) -> None:
    """Raise HTTPException if the dashboard token is missing or wrong."""
    if not settings.dashboard_token:
        raise HTTPException(
            status_code=503,
            detail="Dashboard not configured — set DASHBOARD_TOKEN in .env",
        )
    if not secrets.compare_digest(
        token.encode("utf-8"), settings.dashboard_token.encode("utf-8")
    ):
        raise HTTPException(status_code=403, detail="Invalid token")


# ── Health ────────────────────────────────────────────────────────────────────


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# ── On-demand sessions ────────────────────────────────────────────────────────

_ALLOWED_LANGS = {"es", "en", "zh"}


class StartSessionPayload(BaseModel):
    url: str
    lang: str = "es"
    output_lang: Optional[str] = None

    @field_validator("lang", "output_lang", mode="before")
    @classmethod
    def _validate_lang(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        if v not in _ALLOWED_LANGS:
            raise ValueError(f"lang must be one of {sorted(_ALLOWED_LANGS)}")
        return v

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://", "rtmp://", "rtsp://")):
            raise ValueError("url must start with http://, https://, rtmp://, or rtsp://")
        return v


@app.post("/sessions", status_code=201)
async def start_session(payload: StartSessionPayload) -> dict:
    """
    Spawn a transcription worker for any video URL (YouTube, direct link, etc.).
    Returns session_id and stage_id; use stage_id to connect to /ws?stage=<id>.
    """
    session_id = str(uuid.uuid4())

    try:
        stream_url = await resolve_url(payload.url)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not resolve URL: {exc}") from exc

    stage_id = await _session_manager.start(
        session_id=session_id,
        url=stream_url,
        lang=payload.lang,
        output_lang=payload.output_lang,
    )

    return {
        "session_id": session_id,
        "stage_id": stage_id,
        "lang": payload.lang,
        "output_lang": payload.output_lang,
    }


@app.delete("/sessions/{session_id}", status_code=200)
async def stop_session(session_id: str) -> dict:
    """Stop a running session and its worker process."""
    stopped = await _session_manager.stop(session_id)
    if not stopped:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "stopped": True}


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


# ── Mute API ──────────────────────────────────────────────────────────────────


class MutePayload(BaseModel):
    muted: bool


@app.put("/stages/{stage_id}/mute")
async def set_mute(
    stage_id: int,
    payload: MutePayload,
    token: str = Query(default=""),
) -> dict:
    """Mute or unmute a stage. Muted stages keep running but transcripts are not delivered to viewers."""
    _verify_token(token)
    _state_cache.set_muted(stage_id, payload.muted)
    if _redis is not None:
        key = "dashboard:muted_stages"
        if payload.muted:
            await _redis.sadd(key, str(stage_id))
        else:
            await _redis.srem(key, str(stage_id))
    logger.info("Stage %d muted=%s", stage_id, payload.muted)
    await _state_cache.broadcast_update()
    return {"stage_id": stage_id, "muted": payload.muted}


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


# ── Dashboard API ─────────────────────────────────────────────────────────────


@app.get("/dashboard/config")
async def dashboard_config(token: str = Query(default="")) -> dict:
    """Return the configured alert thresholds for the production dashboard."""
    _verify_token(token)
    return {
        "latency_warn_ms": settings.latency_warn_ms,
        "latency_crit_ms": settings.latency_crit_ms,
        "stale_warn_sec": settings.stale_warn_sec,
        "stale_crit_sec": settings.stale_crit_sec,
    }


@app.get("/dashboard/stages")
async def dashboard_stages(token: str = Query(default="")) -> dict:
    """Return the current snapshot of all stages (REST fallback for the dashboard)."""
    _verify_token(token)
    return {"stages": [dataclasses.asdict(s) for s in _state_cache.get_snapshots()]}


# ── Dashboard WebSocket ───────────────────────────────────────────────────────


@app.websocket("/ws/dashboard")
async def ws_dashboard(ws: WebSocket, token: str = "") -> None:
    """
    Real-time dashboard feed.  Sends a full StageSnapshot list on connect and
    on every meaningful state change.  Requires token authentication.
    """
    # Validate before accepting so the browser sees the close code.
    if not settings.dashboard_token or not secrets.compare_digest(
        token.encode("utf-8"), settings.dashboard_token.encode("utf-8")
    ):
        await ws.close(code=4003)
        return

    await ws.accept()
    await _state_cache.connect_dashboard(ws)
    try:
        while True:
            # Keep alive: echo pings from client.
            text = await ws.receive_text()
            if text == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("Dashboard WS error: %s", exc)
    finally:
        _state_cache.disconnect_dashboard(ws)


# ── Stage WebSocket ───────────────────────────────────────────────────────────


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

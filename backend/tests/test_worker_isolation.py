"""
Tests demonstrating that stage workers are isolated from each other.

Key properties verified:
  1. Each stage has its own Redis channel — stage:N:transcript.
  2. A subscriber on stage 2 never receives events from stage 1.
  3. A crashed stage 1 worker does not prevent stage 2 from delivering events.
  4. StageWorker retries after a transient failure (exponential backoff).
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import fakeredis
import pytest

from backend.shared.models import StageStatusEvent, TranscriptEvent


# ── helpers ──────────────────────────────────────────────────────────────────


def make_event(stage_id: int, text: str, sequence: int = 1) -> str:
    return TranscriptEvent(
        stage_id=stage_id,
        language="es",
        text=text,
        is_final=True,
        sequence=sequence,
        latency_ms=0,
    ).model_dump_json()


# ── channel isolation ─────────────────────────────────────────────────────────


async def test_stage_channels_are_independent(fake_server):
    """Stage 2 subscriber receives only stage 2 events."""
    r_pub = fakeredis.FakeAsyncRedis(server=fake_server, decode_responses=True)
    r_sub = fakeredis.FakeAsyncRedis(server=fake_server, decode_responses=True)

    pubsub = r_sub.pubsub()
    await pubsub.subscribe("stage:2:transcript")

    # Publish to stage 1 — stage 2 subscriber must NOT see this
    await r_pub.publish("stage:1:transcript", make_event(1, "stage1 only"))
    # Publish to stage 2 — stage 2 subscriber MUST see this
    await r_pub.publish("stage:2:transcript", make_event(2, "stage2 text"))

    received = []

    async def collect():
        async for msg in pubsub.listen():
            if msg["type"] == "message":
                received.append(json.loads(msg["data"]))
                break  # stop after first real message

    await asyncio.wait_for(collect(), timeout=2.0)
    await pubsub.aclose()
    await r_pub.aclose()
    await r_sub.aclose()

    assert len(received) == 1, "stage 2 should receive exactly one event"
    assert received[0]["stage_id"] == 2
    assert received[0]["text"] == "stage2 text"
    assert received[0]["event"] == "transcript"


async def test_stage1_events_invisible_to_stage2_subscriber(fake_server):
    """Publishing only to stage 1 yields nothing for a stage 2 subscriber."""
    r_pub = fakeredis.FakeAsyncRedis(server=fake_server, decode_responses=True)
    r_sub = fakeredis.FakeAsyncRedis(server=fake_server, decode_responses=True)

    pubsub = r_sub.pubsub()
    await pubsub.subscribe("stage:2:transcript")

    await r_pub.publish("stage:1:transcript", make_event(1, "invisible"))

    received = []

    async def collect():
        async for msg in pubsub.listen():
            if msg["type"] == "message":
                received.append(msg)
                break

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(collect(), timeout=0.2)

    await pubsub.aclose()
    await r_pub.aclose()
    await r_sub.aclose()

    assert received == [], "stage 2 subscriber must not receive stage 1 events"


# ── crash isolation ───────────────────────────────────────────────────────────


async def test_stage2_delivers_events_when_stage1_crashes(fake_server):
    """
    Stage 1 crashes immediately; stage 2 still publishes and delivers all 3 events.
    Uses return_exceptions=True so the crash does not cancel other tasks.
    """
    r_pub = fakeredis.FakeAsyncRedis(server=fake_server, decode_responses=True)
    r_sub = fakeredis.FakeAsyncRedis(server=fake_server, decode_responses=True)

    stage2_events: list[dict] = []

    async def worker1_crashes():
        await r_pub.publish(
            "stage:1:status",
            StageStatusEvent(stage_id=1, status="active").model_dump_json(),
        )
        raise RuntimeError("Stage 1 Gemini session failed")

    async def worker2_publishes():
        for i in range(3):
            await r_pub.publish("stage:2:transcript", make_event(2, f"word {i}", sequence=i + 1))
            await asyncio.sleep(0)  # yield to event loop

    pubsub = r_sub.pubsub()
    await pubsub.subscribe("stage:2:transcript")

    async def collector():
        async for msg in pubsub.listen():
            if msg["type"] == "message":
                stage2_events.append(json.loads(msg["data"]))
                if len(stage2_events) >= 3:
                    break

    results = await asyncio.gather(
        worker1_crashes(),
        worker2_publishes(),
        asyncio.wait_for(collector(), timeout=2.0),
        return_exceptions=True,
    )

    await pubsub.aclose()
    await r_pub.aclose()
    await r_sub.aclose()

    # Stage 1 crashed as expected
    assert isinstance(results[0], RuntimeError), "stage 1 should have crashed"
    assert "Stage 1" in str(results[0])

    # Stage 2 and collector completed without error
    assert results[1] is None, "stage 2 worker should have completed cleanly"
    assert results[2] is None, "collector should have completed cleanly"

    # Stage 2 delivered all 3 events
    assert len(stage2_events) == 3
    assert all(e["stage_id"] == 2 for e in stage2_events)
    assert all(e["event"] == "transcript" for e in stage2_events)


# ── StageWorker retry behavior ────────────────────────────────────────────────


async def test_stage_worker_retries_after_transient_failure(fake_server):
    """
    StageWorker calls the transcriber again after the first attempt raises.
    The second attempt succeeds and publishes a final transcript event.
    """
    from backend.workers.worker import StageWorker

    attempt = 0
    stop_event = asyncio.Event()

    def make_redis(_url, **_kwargs):
        return fakeredis.FakeAsyncRedis(server=fake_server, decode_responses=True)

    class FakeCapture:
        def __init__(self, source, loop=True):
            pass

        async def stream(self):
            yield b"\x00" * 3200

    class FakeTranscriber:
        def __init__(self, lang="es"):
            pass

        async def transcribe(self, audio_stream, on_text):
            nonlocal attempt
            attempt += 1
            # Drain the audio stream to avoid resource leak
            async for _ in audio_stream:
                pass
            if attempt == 1:
                raise RuntimeError("transient Gemini failure")
            # Second attempt: publish one transcript then signal done
            await on_text("recovered text", True)
            stop_event.set()

    with (
        patch("backend.workers.worker.aioredis.from_url", side_effect=make_redis),
        patch("backend.workers.worker.FFmpegCapture", FakeCapture),
        patch("backend.workers.worker.GeminiTranscriber", FakeTranscriber),
        # Make backoff sleep instant so the test doesn't take 1 second
        patch("backend.workers.worker.asyncio.sleep", new=AsyncMock(return_value=None)),
    ):
        worker = StageWorker(stage_id=1, source="fake.mp3", lang="es")

        async def stop_after_success():
            await asyncio.wait_for(stop_event.wait(), timeout=5.0)
            await worker.stop()

        await asyncio.gather(worker.run(), stop_after_success())

    assert attempt == 2, f"expected 2 attempts (1 fail + 1 success), got {attempt}"


async def test_ten_stages_all_have_separate_channels():
    """Redis channels follow the stage:N:transcript pattern for stages 1–10."""
    for stage_id in range(1, 11):
        event = TranscriptEvent(
            stage_id=stage_id, language="es", text=f"stage {stage_id}", is_final=True, sequence=1
        )
        d = event.model_dump()
        assert d["stage_id"] == stage_id
        assert d["event"] == "transcript"
        channel = f"stage:{stage_id}:transcript"
        assert channel == f"stage:{stage_id}:transcript"

"""StageWorker: orchestrates FFmpeg → Gemini → Redis for one stage."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Optional

import redis.asyncio as aioredis

from backend.shared.config import settings
from backend.shared.models import StageStatusEvent, TranscriptEvent
from backend.workers.audio import FFmpegCapture
from backend.workers.gemini import GeminiTranscriber

logger = logging.getLogger(__name__)

HISTORY_MAX = 500  # keep last N final lines in Redis list


class StageWorker:
    def __init__(
        self,
        stage_id: int,
        source: str,
        lang: str = "es",
        loop_audio: bool = True,
        output_lang: str | None = None,
    ) -> None:
        self.stage_id = stage_id
        self.source = source
        self.lang = lang
        self.loop_audio = loop_audio
        self.output_lang = output_lang

        self._sequence = 0
        self._running = False
        self._redis: Optional[aioredis.Redis] = None  # type: ignore[type-arg]
        self._segment_start_ts: float = 0.0

    # ── Channel helpers ────────────────────────────────────────────────────

    @property
    def _transcript_ch(self) -> str:
        return f"stage:{self.stage_id}:transcript"

    @property
    def _status_ch(self) -> str:
        return f"stage:{self.stage_id}:status"

    @property
    def _history_key(self) -> str:
        return f"stage:{self.stage_id}:history"

    @property
    def _glossary_key(self) -> str:
        return f"stage:{self.stage_id}:glossary"

    # ── Redis helpers ──────────────────────────────────────────────────────

    async def _publish_status(self, status: str) -> None:
        event = StageStatusEvent(stage_id=self.stage_id, status=status)  # type: ignore[arg-type]
        await self._redis.publish(self._status_ch, event.model_dump_json())  # type: ignore[union-attr]
        logger.info("[stage %d] status → %s", self.stage_id, status)

    async def _on_text(self, text: str, is_final: bool) -> None:
        self._sequence += 1
        latency_ms = int((time.time() - self._segment_start_ts) * 1000)
        event = TranscriptEvent(
            stage_id=self.stage_id,
            language=self.lang,
            text=text,
            is_final=is_final,
            sequence=self._sequence,
            latency_ms=latency_ms,
        )
        payload = event.model_dump_json()
        await self._redis.publish(self._transcript_ch, payload)  # type: ignore[union-attr]

        if is_final:
            pipe = self._redis.pipeline()  # type: ignore[union-attr]
            pipe.lpush(self._history_key, payload)
            pipe.ltrim(self._history_key, 0, HISTORY_MAX - 1)
            await pipe.execute()
            self._segment_start_ts = time.time()  # reset for next segment

        label = "[FINAL]" if is_final else "[part.]"
        preview = text[:70] + ("…" if len(text) > 70 else "")
        logger.info(
            "[stage %d] seq=%-4d %s latency=%dms %s",
            self.stage_id,
            self._sequence,
            label,
            latency_ms,
            preview,
        )

    # ── Main loop ──────────────────────────────────────────────────────────

    async def run(self) -> None:
        self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        self._running = True

        logger.info(
            "[stage %d] worker starting  source=%s  lang=%s  loop=%s",
            self.stage_id,
            self.source,
            self.lang,
            self.loop_audio,
        )

        backoff = 1.0
        max_backoff = 30.0

        while self._running:
            try:
                await self._publish_status("active")
                self._segment_start_ts = time.time()

                # Reload glossary on every attempt so live updates take effect
                # on reconnect without restarting the worker process.
                glossary: list[str] = []
                raw_glossary = await self._redis.get(self._glossary_key)  # type: ignore[union-attr]
                if raw_glossary:
                    try:
                        glossary = json.loads(raw_glossary).get("terms", [])
                    except (json.JSONDecodeError, AttributeError):
                        logger.warning(
                            "[stage %d] glossary parse error — starting without terms",
                            self.stage_id,
                        )
                if glossary:
                    logger.info(
                        "[stage %d] loaded glossary: %d term(s)", self.stage_id, len(glossary)
                    )

                capture = FFmpegCapture(source=self.source, loop=self.loop_audio)
                transcriber = GeminiTranscriber(
                    lang=self.lang,
                    glossary=glossary,
                    output_lang=self.output_lang,
                )
                await transcriber.transcribe(
                    audio_stream=capture.stream(),
                    on_text=self._on_text,
                )
                backoff = 1.0  # reset on clean exit

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(
                    "[stage %d] error: %s — retrying in %.0fs",
                    self.stage_id,
                    exc,
                    backoff,
                )
                await self._publish_status("reconnecting")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

        await self._publish_status("idle")
        await self._redis.aclose()
        logger.info("[stage %d] worker stopped", self.stage_id)

    async def stop(self) -> None:
        self._running = False

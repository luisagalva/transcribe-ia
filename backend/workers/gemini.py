"""Gemini Live API client: streams PCM audio in, receives text transcription out."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Any

from google import genai
from google.genai import types

from backend.shared.config import settings

logger = logging.getLogger(__name__)

# Coroutine type for the on_text callback: (text, is_final) -> None
OnTextCallback = Callable[[str, bool], Coroutine[Any, Any, None]]


class GeminiTranscriber:
    """Opens a Gemini Live session and wires audio → text callbacks."""

    def __init__(self, lang: str = "es") -> None:
        self.lang = lang
        self._client = genai.Client(api_key=settings.gemini_api_key)

    def _config(self) -> types.LiveConnectConfig:
        return types.LiveConnectConfig(
            # Enable input audio transcription — returns results via
            # server_content.input_transcription (final)
            # and server_content.interim_input_transcription (partial)
            input_audio_transcription=types.AudioTranscriptionConfig(),
            # No TEXT modality needed for transcription-only mode
            response_modalities=[],
        )

    async def transcribe(
        self,
        audio_stream: AsyncIterator[bytes],
        on_text: OnTextCallback,
    ) -> None:
        """
        Consumes audio_stream and invokes on_text(text, is_final) for each
        transcription fragment. Runs until the stream ends or an exception is raised.
        """
        async with self._client.aio.live.connect(
            model=settings.gemini_model,
            config=self._config(),
        ) as session:
            logger.info(
                "Gemini Live session open (model=%s, lang=%s)",
                settings.gemini_model,
                self.lang,
            )

            send_task = asyncio.create_task(
                self._send(session, audio_stream), name="gemini-send"
            )
            recv_task = asyncio.create_task(
                self._recv(session, on_text), name="gemini-recv"
            )

            try:
                done, pending = await asyncio.wait(
                    [send_task, recv_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)

                for task in done:
                    if not task.cancelled():
                        exc = task.exception()
                        if exc is not None:
                            raise exc
            except asyncio.CancelledError:
                send_task.cancel()
                recv_task.cancel()
                await asyncio.gather(send_task, recv_task, return_exceptions=True)
                raise

        logger.info("Gemini Live session closed")

    @staticmethod
    async def _send(
        session: types.AsyncSession,
        audio_stream: AsyncIterator[bytes],
    ) -> None:
        async for chunk in audio_stream:
            await session.send_realtime_input(
                media=types.Blob(data=chunk, mime_type="audio/pcm;rate=16000")
            )

    @staticmethod
    async def _recv(
        session: types.AsyncSession,
        on_text: OnTextCallback,
    ) -> None:
        async for response in session.receive():
            sc = response.server_content
            if sc is None:
                continue

            # ── Partial transcription ─────────────────────────────────────
            if sc.interim_input_transcription and sc.interim_input_transcription.text:
                await on_text(sc.interim_input_transcription.text, False)
                logger.debug("Transcript [part.]: %s", sc.interim_input_transcription.text[:80])

            # ── Final transcription ───────────────────────────────────────
            elif sc.input_transcription and sc.input_transcription.text:
                await on_text(sc.input_transcription.text, True)
                logger.debug("Transcript [FINAL]: %s", sc.input_transcription.text[:80])

            # ── Fallback: text generation mode (for non-transcribe models) ─
            elif sc.model_turn:
                parts = [
                    p.text
                    for p in sc.model_turn.parts
                    if hasattr(p, "text") and p.text
                ]
                if parts:
                    text = "".join(parts)
                    is_final = bool(sc.turn_complete)
                    await on_text(text, is_final)
                    logger.debug(
                        "Transcript [%s] (gen): %s",
                        "FINAL" if is_final else "part.",
                        text[:80],
                    )

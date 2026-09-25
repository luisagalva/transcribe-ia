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

SYSTEM_PROMPT = """\
You are a real-time speech transcription system for live technology conferences.

Your ONLY task: transcribe the audio you hear into text.

Rules:
- Output ONLY the spoken words. No commentary, no greetings, no explanations.
- If you hear silence or noise, output nothing.
- Preserve technical terms, product names, and proper nouns accurately.
- Transcribe continuously without summarizing.
"""


class GeminiTranscriber:
    """Opens a Gemini Live session and wires audio → text callbacks."""

    def __init__(self, lang: str = "es") -> None:
        self.lang = lang
        self._client = genai.Client(api_key=settings.gemini_api_key)

    def _config(self) -> types.LiveConnectConfig:
        lang_hint = (
            f"\nThe speaker is speaking in language code '{self.lang}'."
            if self.lang != "auto"
            else ""
        )
        return types.LiveConnectConfig(
            response_modalities=["TEXT"],
            system_instruction=SYSTEM_PROMPT + lang_hint,
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
            logger.info("Gemini Live session open (model=%s, lang=%s)", settings.gemini_model, self.lang)

            send_task = asyncio.create_task(
                self._send(session, audio_stream), name="gemini-send"
            )
            recv_task = asyncio.create_task(
                self._recv(session, on_text), name="gemini-recv"
            )

            try:
                # Run until the first task finishes (send ends → stream EOF)
                done, pending = await asyncio.wait(
                    [send_task, recv_task],
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)

                # Re-raise any exception from completed tasks
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
            text: str | None = None

            # Convenience accessor available on recent SDK versions
            if hasattr(response, "text") and response.text:
                text = response.text
            elif (
                response.server_content
                and response.server_content.model_turn
            ):
                parts = []
                for part in response.server_content.model_turn.parts:
                    if hasattr(part, "text") and part.text:
                        parts.append(part.text)
                if parts:
                    text = "".join(parts)

            if text:
                is_final = bool(
                    response.server_content
                    and response.server_content.turn_complete
                )
                await on_text(text, is_final)
                logger.debug(
                    "Transcript [%s] %s",
                    "FINAL" if is_final else "part.",
                    text[:80],
                )

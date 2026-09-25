"""FFmpeg-based audio capture: reads any stream/file and yields PCM chunks."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Optional

logger = logging.getLogger(__name__)

# 100 ms of PCM at 16 kHz, 16-bit mono (16000 * 2 * 0.1)
CHUNK_BYTES = 3200


class FFmpegCapture:
    """Wraps an FFmpeg subprocess and yields raw 16-kHz mono PCM chunks."""

    def __init__(self, source: str, loop: bool = True) -> None:
        self.source = source
        self.loop = loop
        self._process: Optional[asyncio.subprocess.Process] = None

    def _build_cmd(self) -> list[str]:
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error"]
        if self.loop:
            cmd += ["-stream_loop", "-1"]
        cmd += [
            "-re",        # simulate real-time playback
            "-i", self.source,
            "-vn",        # drop video
            "-ar", "16000",
            "-ac", "1",
            "-f", "s16le",  # signed 16-bit little-endian PCM, no header
            "pipe:1",
        ]
        return cmd

    async def stream(self) -> AsyncIterator[bytes]:
        cmd = self._build_cmd()
        logger.info("FFmpeg cmd: %s", " ".join(cmd))

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        logger.info("FFmpeg PID %d started", self._process.pid)

        try:
            while True:
                chunk = await self._process.stdout.read(CHUNK_BYTES)  # type: ignore[union-attr]
                if not chunk:
                    logger.warning("FFmpeg stdout closed (stream ended)")
                    break
                yield chunk
        finally:
            await self._stop()

    async def _stop(self) -> None:
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self._process.kill()
            logger.info("FFmpeg process stopped")

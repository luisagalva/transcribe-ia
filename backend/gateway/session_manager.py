"""Manages on-demand worker subprocesses spawned via the /sessions API."""
from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

_next_stage_id = 100


async def resolve_url(url: str) -> str:
    """
    For YouTube URLs, use yt-dlp to extract the direct audio stream URL so
    FFmpeg can consume it.  Falls back to the original URL if yt-dlp is not
    installed or fails, letting FFmpeg try on its own.
    """
    if "youtube.com" not in url and "youtu.be" not in url:
        return url

    logger.info("Resolving YouTube URL via yt-dlp: %s", url[:80])
    try:
        proc = await asyncio.create_subprocess_exec(
            "yt-dlp",
            "-f", "bestaudio/best",
            "-g",
            "--no-playlist",
            url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
        if proc.returncode == 0:
            stream_url = stdout.decode().strip().split("\n")[0]
            if stream_url:
                logger.info("yt-dlp resolved stream URL (len=%d)", len(stream_url))
                return stream_url
        logger.warning("yt-dlp exited %d: %s", proc.returncode, stderr.decode()[:200])
    except FileNotFoundError:
        logger.warning("yt-dlp not found — passing URL directly to FFmpeg")
    except asyncio.TimeoutError:
        logger.warning("yt-dlp timed out — passing URL directly to FFmpeg")

    return url


@dataclass
class WorkerSession:
    session_id: str
    stage_id: int
    url: str
    lang: str
    output_lang: Optional[str]
    process: asyncio.subprocess.Process


class SessionManager:
    """Spawns and tracks StageWorker subprocesses for on-demand sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, WorkerSession] = {}
        self._lock = asyncio.Lock()

    async def start(
        self,
        session_id: str,
        url: str,
        lang: str,
        output_lang: Optional[str] = None,
    ) -> int:
        global _next_stage_id

        async with self._lock:
            stage_id = _next_stage_id
            _next_stage_id += 1

        cmd = [
            sys.executable, "-m", "backend.run_worker",
            "--stage", str(stage_id),
            "--source", url,
            "--lang", lang,
            "--no-loop",
        ]
        if output_lang:
            cmd += ["--output-lang", output_lang]

        process = await asyncio.create_subprocess_exec(*cmd)
        logger.info(
            "Started worker PID %d session=%s stage=%d lang=%s output_lang=%s",
            process.pid, session_id, stage_id, lang, output_lang,
        )

        self._sessions[session_id] = WorkerSession(
            session_id=session_id,
            stage_id=stage_id,
            url=url,
            lang=lang,
            output_lang=output_lang,
            process=process,
        )

        # Watch for natural process exit so we can clean up.
        asyncio.create_task(
            self._watch(session_id, process), name=f"watch-{session_id}"
        )
        return stage_id

    async def stop(self, session_id: str) -> bool:
        session = self._sessions.pop(session_id, None)
        if not session:
            return False
        await _terminate(session.process)
        logger.info("Stopped session %s (stage %d)", session_id, session.stage_id)
        return True

    async def stop_all(self) -> None:
        for sid in list(self._sessions):
            await self.stop(sid)

    def get_stage_id(self, session_id: str) -> Optional[int]:
        s = self._sessions.get(session_id)
        return s.stage_id if s else None

    # ── Internal ──────────────────────────────────────────────────────────

    async def _watch(self, session_id: str, process: asyncio.subprocess.Process) -> None:
        await process.wait()
        removed = self._sessions.pop(session_id, None)
        if removed:
            logger.info(
                "Worker for session %s (stage %d) exited naturally (rc=%s)",
                session_id, removed.stage_id, process.returncode,
            )


async def _terminate(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()

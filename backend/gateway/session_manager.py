"""Manages on-demand worker subprocesses spawned via the /sessions API."""
from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

_next_stage_id = 100


async def resolve_url(url: str) -> str:
    """
    For YouTube URLs, use yt-dlp to extract the direct audio stream URL.
    Falls back gracefully to the original URL if yt-dlp is unavailable or fails.
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
            stream_url = stdout.decode(errors="replace").strip().split("\n")[0]
            if stream_url:
                logger.info("yt-dlp resolved stream URL (len=%d)", len(stream_url))
                return stream_url
        logger.warning(
            "yt-dlp exited %d: %s", proc.returncode,
            stderr.decode(errors="replace")[:300],
        )
    except FileNotFoundError:
        logger.warning("yt-dlp not found — passing URL directly to FFmpeg")
    except (asyncio.TimeoutError, TimeoutError):
        logger.warning("yt-dlp timed out — passing URL directly to FFmpeg")
    except Exception as exc:
        logger.warning("yt-dlp error (%s: %s) — passing URL directly to FFmpeg", type(exc).__name__, exc)

    return url


@dataclass
class WorkerSession:
    session_id: str
    stage_id: int
    url: str
    lang: str
    target_langs: list[str] = field(default_factory=list)
    process: Optional[asyncio.subprocess.Process] = None


class SessionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, WorkerSession] = {}
        self._lock = asyncio.Lock()

    async def start(
        self,
        session_id: str,
        url: str,
        lang: str,
        target_langs: list[str] | None = None,
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
        if target_langs:
            cmd += ["--target-langs", ",".join(target_langs)]

        process = await asyncio.create_subprocess_exec(*cmd)
        logger.info(
            "Started worker PID %d session=%s stage=%d lang=%s target_langs=%s",
            process.pid, session_id, stage_id, lang, target_langs,
        )

        session = WorkerSession(
            session_id=session_id,
            stage_id=stage_id,
            url=url,
            lang=lang,
            target_langs=target_langs or [],
            process=process,
        )
        self._sessions[session_id] = session

        asyncio.create_task(
            self._watch(session_id, process), name=f"watch-{session_id}"
        )
        return stage_id

    async def stop(self, session_id: str) -> bool:
        session = self._sessions.pop(session_id, None)
        if not session:
            return False
        if session.process and session.process.returncode is None:
            session.process.terminate()
            try:
                await asyncio.wait_for(session.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                session.process.kill()
                await session.process.wait()
        logger.info("Stopped session %s (stage %d)", session_id, session.stage_id)
        return True

    async def stop_all(self) -> None:
        for sid in list(self._sessions):
            await self.stop(sid)

    async def _watch(self, session_id: str, process: asyncio.subprocess.Process) -> None:
        await process.wait()
        removed = self._sessions.pop(session_id, None)
        if removed:
            logger.info(
                "Worker for session %s (stage %d) exited naturally (rc=%s)",
                session_id, removed.stage_id, process.returncode,
            )

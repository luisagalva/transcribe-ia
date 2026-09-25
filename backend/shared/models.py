from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, Field


class TranscriptEvent(BaseModel):
    v: int = 1
    event: Literal["transcript"] = "transcript"
    stage_id: int
    language: str
    text: str
    is_final: bool
    sequence: int
    timestamp: float = Field(default_factory=time.time)
    latency_ms: int = 0


class StageStatusEvent(BaseModel):
    v: int = 1
    event: Literal["stage_status"] = "stage_status"
    stage_id: int
    status: Literal["idle", "active", "paused", "error", "reconnecting"]
    muted: bool = False
    timestamp: float = Field(default_factory=time.time)


class ErrorEvent(BaseModel):
    v: int = 1
    event: Literal["error"] = "error"
    stage_id: int
    code: str
    message: str
    timestamp: float = Field(default_factory=time.time)

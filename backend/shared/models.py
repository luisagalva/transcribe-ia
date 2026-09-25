from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, Field


class TranscriptEvent(BaseModel):
    type: Literal["transcript"] = "transcript"
    stage_id: int
    lang: str
    text: str
    is_final: bool
    sequence: int
    ts: float = Field(default_factory=time.time)


class StageStatusEvent(BaseModel):
    type: Literal["stage_status"] = "stage_status"
    stage_id: int
    status: Literal["idle", "active", "paused", "error", "reconnecting"]
    muted: bool = False
    ts: float = Field(default_factory=time.time)


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    stage_id: int
    code: str
    message: str
    ts: float = Field(default_factory=time.time)

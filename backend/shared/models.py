from __future__ import annotations

import re
import time
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# Characters permitted in a glossary term.
# Allows letters, digits, spaces, tabs and common tech punctuation.
# Deliberately excludes newlines, curly braces, backticks, quotes, semicolons,
# pipes and angle brackets so a term cannot escape its role as a list item.
_SAFE_TERM_RE = re.compile(r"^[A-Za-z0-9 \t.\-+#@:/]+$")


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


class Glossary(BaseModel):
    """Validated list of technical terms for a stage."""

    terms: list[str]

    @field_validator("terms")
    @classmethod
    def validate_terms(cls, v: list[str]) -> list[str]:
        if len(v) > 200:
            raise ValueError("glossary may contain at most 200 terms")
        cleaned: list[str] = []
        for raw in v:
            term = raw.strip()
            if not term:
                raise ValueError("term must not be blank")
            if "\n" in term or "\r" in term:
                raise ValueError(f"term must not contain newlines: {term!r}")
            if len(term) > 80:
                raise ValueError(f"term exceeds 80-character limit: {term!r}")
            if not _SAFE_TERM_RE.match(term):
                raise ValueError(
                    f"term contains invalid characters — only letters, digits, "
                    f"spaces, and . - + # @ : / are allowed: {term!r}"
                )
            cleaned.append(term)
        return cleaned

"""
Subtitle export: convert a stage's transcript history into VTT or SRT.

Timing model
------------
The first segment's timestamp becomes the session origin (t = 0).  Every other
segment's start time is `segment.timestamp - origin`.  End time is the start of
the next segment; the final segment gets a fixed `DEFAULT_LAST_DURATION` second
tail so the cue stays visible after the last word.

Segments are sorted by `sequence` before any time arithmetic is done so that
out-of-order delivery from Redis cannot produce invalid (start >= end) cues.

Time arithmetic uses integer milliseconds throughout to avoid floating-point
accumulation across long sessions.
"""
from __future__ import annotations

from dataclasses import dataclass

from backend.shared.models import TranscriptEvent

# Minimum tail duration (seconds) added to the last cue.
DEFAULT_LAST_DURATION: float = 3.0


@dataclass(frozen=True)
class TranscriptSegment:
    """One subtitle cue derived from a final TranscriptEvent."""

    stage_id: int
    language: str
    text: str
    sequence: int
    start: float  # seconds from session origin
    end: float    # seconds from session origin

    @property
    def duration(self) -> float:
        return self.end - self.start


# ── Time formatters ───────────────────────────────────────────────────────────


def _ms_to_vtt(total_ms: int) -> str:
    """Format integer milliseconds as HH:MM:SS.mmm (WebVTT)."""
    h, rem = divmod(total_ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _ms_to_srt(total_ms: int) -> str:
    """Format integer milliseconds as HH:MM:SS,mmm (SRT)."""
    h, rem = divmod(total_ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1_000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# ── Segment builder ───────────────────────────────────────────────────────────


def build_segments(events: list[TranscriptEvent]) -> list[TranscriptSegment]:
    """
    Convert a list of final TranscriptEvents into ordered, timed segments.

    Returns an empty list when `events` is empty.
    """
    if not events:
        return []

    ordered = sorted(events, key=lambda e: e.sequence)
    origin = ordered[0].timestamp  # seconds (Unix time)

    segments: list[TranscriptSegment] = []
    for i, ev in enumerate(ordered):
        start = ev.timestamp - origin
        if i + 1 < len(ordered):
            end = ordered[i + 1].timestamp - origin
        else:
            end = start + DEFAULT_LAST_DURATION
        segments.append(
            TranscriptSegment(
                stage_id=ev.stage_id,
                language=ev.language,
                text=ev.text,
                sequence=ev.sequence,
                start=start,
                end=end,
            )
        )
    return segments


# ── Formatters ────────────────────────────────────────────────────────────────


def to_vtt(segments: list[TranscriptSegment]) -> str:
    """
    Render segments as a WebVTT string.

    The VTT spec requires the file to begin with "WEBVTT".  Each cue is:

        <cue-id>
        HH:MM:SS.mmm --> HH:MM:SS.mmm
        <text>

    An empty session returns the bare header so the response is still a valid
    VTT file (useful for video players that pre-load the track).
    """
    if not segments:
        return "WEBVTT\n"

    lines: list[str] = ["WEBVTT", ""]
    for i, seg in enumerate(segments, start=1):
        start_ms = round(seg.start * 1000)
        end_ms = round(seg.end * 1000)
        lines.append(str(i))
        lines.append(f"{_ms_to_vtt(start_ms)} --> {_ms_to_vtt(end_ms)}")
        lines.append(seg.text)
        lines.append("")
    return "\n".join(lines)


def to_srt(segments: list[TranscriptSegment]) -> str:
    """
    Render segments as an SRT string.

    SRT format:

        <index>
        HH:MM:SS,mmm --> HH:MM:SS,mmm
        <text>

    Returns an empty string for an empty session (SRT has no mandatory header).
    """
    if not segments:
        return ""

    lines: list[str] = []
    for i, seg in enumerate(segments, start=1):
        start_ms = round(seg.start * 1000)
        end_ms = round(seg.end * 1000)
        lines.append(str(i))
        lines.append(f"{_ms_to_srt(start_ms)} --> {_ms_to_srt(end_ms)}")
        lines.append(seg.text)
        lines.append("")
    return "\n".join(lines)

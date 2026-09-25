"""
Tests for the transcript export feature.

Coverage:
  - build_segments: ordering, timing, edge cases
  - to_vtt / to_srt: format correctness
  - Time formatter functions: boundary values
  - API endpoints: GET /stages/{id}/transcript.vtt and .srt
  - Cases: short text, long text, multiple segments, consecutive timestamps,
           Unicode characters, empty session.
"""
from __future__ import annotations

import json
import re

import fakeredis
import pytest
from httpx import ASGITransport, AsyncClient

from backend.gateway.transcript_export import (
    DEFAULT_LAST_DURATION,
    TranscriptSegment,
    _ms_to_srt,
    _ms_to_vtt,
    build_segments,
    to_srt,
    to_vtt,
)
from backend.shared.models import TranscriptEvent


# ── Test helpers ──────────────────────────────────────────────────────────────


def make_event(
    *,
    stage_id: int = 1,
    text: str = "hello",
    sequence: int = 1,
    timestamp: float = 0.0,
    language: str = "es",
) -> TranscriptEvent:
    return TranscriptEvent(
        stage_id=stage_id,
        language=language,
        text=text,
        is_final=True,
        sequence=sequence,
        timestamp=timestamp,
        latency_ms=100,
    )


# ── Time formatter unit tests ─────────────────────────────────────────────────


def test_vtt_zero():
    assert _ms_to_vtt(0) == "00:00:00.000"


def test_srt_zero():
    assert _ms_to_srt(0) == "00:00:00,000"


def test_vtt_sub_second():
    assert _ms_to_vtt(500) == "00:00:00.500"


def test_srt_sub_second():
    assert _ms_to_srt(500) == "00:00:00,500"


def test_vtt_one_minute():
    assert _ms_to_vtt(60_000) == "00:01:00.000"


def test_srt_one_hour():
    assert _ms_to_srt(3_600_000) == "01:00:00,000"


def test_vtt_complex():
    # 1h 23m 45s 678ms
    ms = (1 * 3_600 + 23 * 60 + 45) * 1_000 + 678
    assert _ms_to_vtt(ms) == "01:23:45.678"


def test_srt_complex():
    ms = (1 * 3_600 + 23 * 60 + 45) * 1_000 + 678
    assert _ms_to_srt(ms) == "01:23:45,678"


# ── build_segments ────────────────────────────────────────────────────────────


def test_empty_session_returns_no_segments():
    assert build_segments([]) == []


def test_single_segment_starts_at_zero():
    ev = make_event(text="Solo", sequence=1, timestamp=1_000_000.0)
    segs = build_segments([ev])
    assert len(segs) == 1
    assert segs[0].start == pytest.approx(0.0)


def test_single_segment_end_is_default_duration():
    ev = make_event(sequence=1, timestamp=1_000_000.0)
    segs = build_segments([ev])
    assert segs[0].end == pytest.approx(DEFAULT_LAST_DURATION)
    assert segs[0].duration == pytest.approx(DEFAULT_LAST_DURATION)


def test_multiple_segments_consecutive_timestamps():
    events = [
        make_event(text="First",  sequence=1, timestamp=1_000.0),
        make_event(text="Second", sequence=2, timestamp=1_003.5),
        make_event(text="Third",  sequence=3, timestamp=1_007.2),
    ]
    segs = build_segments(events)

    assert segs[0].start == pytest.approx(0.0)
    assert segs[0].end   == pytest.approx(3.5)
    assert segs[1].start == pytest.approx(3.5)
    assert segs[1].end   == pytest.approx(7.2)
    assert segs[2].start == pytest.approx(7.2)
    assert segs[2].end   == pytest.approx(7.2 + DEFAULT_LAST_DURATION)


def test_segments_sorted_by_sequence_not_arrival_order():
    """Out-of-order sequences must be re-sorted before timing."""
    events = [
        make_event(text="Second", sequence=2, timestamp=1_003.0),
        make_event(text="First",  sequence=1, timestamp=1_000.0),
    ]
    segs = build_segments(events)
    assert segs[0].text == "First"
    assert segs[1].text == "Second"
    assert segs[0].start < segs[1].start


def test_start_always_less_than_end():
    events = [make_event(sequence=i, timestamp=float(i)) for i in range(1, 6)]
    segs = build_segments(events)
    for seg in segs:
        assert seg.start < seg.end, f"start >= end for segment {seg.sequence}"


def test_segment_stores_all_required_fields():
    ev = make_event(stage_id=3, text="Test", sequence=1, timestamp=500.0, language="en")
    seg = build_segments([ev])[0]
    assert seg.stage_id == 3
    assert seg.language == "en"
    assert seg.text == "Test"
    assert seg.sequence == 1
    assert seg.start == pytest.approx(0.0)
    assert seg.duration > 0


# ── Short and long text ───────────────────────────────────────────────────────


def test_short_text_preserved():
    ev = make_event(text="Hi")
    seg = build_segments([ev])[0]
    assert seg.text == "Hi"


def test_long_text_preserved():
    long_text = "Esta es una oración muy larga que contiene muchas palabras " * 10
    ev = make_event(text=long_text.strip())
    seg = build_segments([ev])[0]
    assert seg.text == long_text.strip()


# ── Unicode ───────────────────────────────────────────────────────────────────


def test_unicode_chinese_characters():
    ev = make_event(text="这是一个测试")
    segs = build_segments([ev])
    assert segs[0].text == "这是一个测试"


def test_unicode_arabic():
    ev = make_event(text="مرحبا بالعالم")
    segs = build_segments([ev])
    assert segs[0].text == "مرحبا بالعالم"


def test_unicode_accents_and_symbols():
    ev = make_event(text="Ñoño: áéíóú ü — ¿Cómo estás?")
    segs = build_segments([ev])
    assert segs[0].text == "Ñoño: áéíóú ü — ¿Cómo estás?"


def test_unicode_emoji():
    ev = make_event(text="Hello 🌎 world 🚀")
    segs = build_segments([ev])
    assert segs[0].text == "Hello 🌎 world 🚀"


# ── VTT formatter ─────────────────────────────────────────────────────────────


def test_vtt_empty_session_is_valid_vtt():
    out = to_vtt([])
    assert out.startswith("WEBVTT")


def test_vtt_starts_with_webvtt():
    segs = build_segments([make_event()])
    assert to_vtt(segs).startswith("WEBVTT")


def test_vtt_single_segment_structure():
    segs = build_segments([make_event(text="Hola mundo", sequence=1, timestamp=0.0)])
    out = to_vtt(segs)
    lines = out.split("\n")
    # WEBVTT, blank, cue-id, timing, text, blank
    assert lines[0] == "WEBVTT"
    assert lines[1] == ""
    assert lines[2] == "1"                         # cue number
    assert "-->" in lines[3]                        # timing line
    assert lines[4] == "Hola mundo"
    assert lines[5] == ""


def test_vtt_timing_format():
    segs = build_segments([make_event(timestamp=0.0)])
    out = to_vtt(segs)
    timing_line = [l for l in out.split("\n") if "-->" in l][0]
    # Both sides must match HH:MM:SS.mmm
    vtt_time = r"\d{2}:\d{2}:\d{2}\.\d{3}"
    assert re.match(rf"^{vtt_time} --> {vtt_time}$", timing_line)


def test_vtt_multiple_segments_numbered_sequentially():
    events = [make_event(sequence=i, timestamp=float(i), text=f"Line {i}") for i in range(1, 4)]
    segs = build_segments(events)
    out = to_vtt(segs)
    assert "\n1\n" in out
    assert "\n2\n" in out
    assert "\n3\n" in out


def test_vtt_consecutive_cues_do_not_overlap():
    events = [
        make_event(sequence=1, timestamp=0.0),
        make_event(sequence=2, timestamp=5.0),
    ]
    segs = build_segments(events)
    out = to_vtt(segs)
    timing_lines = [l for l in out.split("\n") if "-->" in l]
    assert len(timing_lines) == 2
    # First cue ends at 00:00:05.000, second starts at 00:00:05.000
    assert "00:00:05.000" in timing_lines[0]
    assert timing_lines[1].startswith("00:00:05.000")


def test_vtt_unicode_content():
    ev = make_event(text="Ñoño: áéíóú — ¿Cómo estás? 🚀")
    out = to_vtt(build_segments([ev]))
    assert "Ñoño: áéíóú — ¿Cómo estás? 🚀" in out


def test_vtt_long_text_is_included_verbatim():
    long_text = "palabra " * 50
    ev = make_event(text=long_text.strip())
    out = to_vtt(build_segments([ev]))
    assert long_text.strip() in out


# ── SRT formatter ─────────────────────────────────────────────────────────────


def test_srt_empty_session_returns_empty_string():
    assert to_srt([]) == ""


def test_srt_single_segment_structure():
    segs = build_segments([make_event(text="Hola", sequence=1, timestamp=0.0)])
    out = to_srt(segs)
    lines = out.split("\n")
    assert lines[0] == "1"
    assert "-->" in lines[1]
    assert "," in lines[1]   # SRT uses comma, not dot
    assert lines[2] == "Hola"
    assert lines[3] == ""


def test_srt_timing_format():
    segs = build_segments([make_event(timestamp=0.0)])
    out = to_srt(segs)
    timing_line = [l for l in out.split("\n") if "-->" in l][0]
    srt_time = r"\d{2}:\d{2}:\d{2},\d{3}"
    assert re.match(rf"^{srt_time} --> {srt_time}$", timing_line)


def test_srt_multiple_segments_numbered():
    events = [make_event(sequence=i, timestamp=float(i), text=f"Word {i}") for i in range(1, 5)]
    out = to_srt(build_segments(events))
    for n in range(1, 5):
        assert f"\n{n}\n" in out or out.startswith(str(n))


def test_srt_uses_comma_not_dot_in_timestamps():
    segs = build_segments([make_event()])
    out = to_srt(segs)
    timing_line = [l for l in out.split("\n") if "-->" in l][0]
    assert "," in timing_line
    # Must not contain a dot in the time portions
    start, end = timing_line.split(" --> ")
    assert "." not in start
    assert "." not in end


def test_srt_unicode():
    ev = make_event(text="这是一个测试 — مرحبا 🌎")
    out = to_srt(build_segments([ev]))
    assert "这是一个测试 — مرحبا 🌎" in out


# ── Gateway API endpoints ─────────────────────────────────────────────────────


async def _push_events_to_redis(
    fake_server: fakeredis.FakeServer, events: list[TranscriptEvent]
) -> None:
    """Push serialised TranscriptEvents into fake Redis history (newest first via lpush)."""
    r = fakeredis.FakeAsyncRedis(server=fake_server, decode_responses=True)
    for ev in events:
        await r.lpush(f"stage:{ev.stage_id}:history", ev.model_dump_json())
    await r.aclose()


async def test_vtt_endpoint_empty_session(gateway_with_fake_redis):
    async with AsyncClient(
        transport=ASGITransport(app=gateway_with_fake_redis), base_url="http://test"
    ) as client:
        resp = await client.get("/stages/99/transcript.vtt")
    assert resp.status_code == 200
    assert resp.text.startswith("WEBVTT")
    assert resp.headers["content-type"].startswith("text/vtt")


async def test_srt_endpoint_empty_session(gateway_with_fake_redis):
    async with AsyncClient(
        transport=ASGITransport(app=gateway_with_fake_redis), base_url="http://test"
    ) as client:
        resp = await client.get("/stages/99/transcript.srt")
    assert resp.status_code == 200
    assert resp.text == ""


async def test_vtt_endpoint_with_events(gateway_with_fake_redis, fake_server):
    events = [
        make_event(text="Bienvenidos",   sequence=1, timestamp=1_000.0),
        make_event(text="al evento",     sequence=2, timestamp=1_004.0),
        make_event(text="de tecnología", sequence=3, timestamp=1_008.5),
    ]
    await _push_events_to_redis(fake_server, events)

    async with AsyncClient(
        transport=ASGITransport(app=gateway_with_fake_redis), base_url="http://test"
    ) as client:
        resp = await client.get("/stages/1/transcript.vtt")

    assert resp.status_code == 200
    body = resp.text
    assert body.startswith("WEBVTT")
    assert "Bienvenidos" in body
    assert "al evento" in body
    assert "de tecnología" in body
    assert "00:00:00.000" in body   # first cue starts at origin


async def test_srt_endpoint_with_events(gateway_with_fake_redis, fake_server):
    events = [
        make_event(text="Hello", sequence=1, timestamp=2_000.0),
        make_event(text="World", sequence=2, timestamp=2_003.0),
    ]
    await _push_events_to_redis(fake_server, events)

    async with AsyncClient(
        transport=ASGITransport(app=gateway_with_fake_redis), base_url="http://test"
    ) as client:
        resp = await client.get("/stages/1/transcript.srt")

    assert resp.status_code == 200
    body = resp.text
    assert "Hello" in body
    assert "World" in body
    # SRT uses comma
    assert re.search(r"\d{2}:\d{2}:\d{2},\d{3}", body)


async def test_vtt_content_disposition_header(gateway_with_fake_redis):
    async with AsyncClient(
        transport=ASGITransport(app=gateway_with_fake_redis), base_url="http://test"
    ) as client:
        resp = await client.get("/stages/1/transcript.vtt")
    assert "stage1.vtt" in resp.headers.get("content-disposition", "")


async def test_srt_content_disposition_header(gateway_with_fake_redis):
    async with AsyncClient(
        transport=ASGITransport(app=gateway_with_fake_redis), base_url="http://test"
    ) as client:
        resp = await client.get("/stages/2/transcript.srt")
    assert "stage2.srt" in resp.headers.get("content-disposition", "")


async def test_stages_export_independently(gateway_with_fake_redis, fake_server):
    """Exporting stage 1 must not include stage 2 text and vice versa."""
    events_s1 = [make_event(stage_id=1, text="Stage one", sequence=1, timestamp=0.0)]
    events_s2 = [make_event(stage_id=2, text="Stage two", sequence=1, timestamp=0.0)]
    await _push_events_to_redis(fake_server, events_s1)
    await _push_events_to_redis(fake_server, events_s2)

    async with AsyncClient(
        transport=ASGITransport(app=gateway_with_fake_redis), base_url="http://test"
    ) as client:
        vtt1 = (await client.get("/stages/1/transcript.vtt")).text
        vtt2 = (await client.get("/stages/2/transcript.vtt")).text

    assert "Stage one" in vtt1
    assert "Stage two" not in vtt1
    assert "Stage two" in vtt2
    assert "Stage one" not in vtt2

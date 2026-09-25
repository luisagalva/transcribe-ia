"""Tests for the versioned event schema (backend/shared/models.py)."""
import json

from backend.shared.models import ErrorEvent, StageStatusEvent, TranscriptEvent


def test_transcript_event_versioned_fields():
    e = TranscriptEvent(
        stage_id=1, language="es", text="hola mundo", is_final=True, sequence=1, latency_ms=250
    )
    d = e.model_dump()

    assert d["event"] == "transcript"
    assert d["v"] == 1
    assert d["language"] == "es"
    assert d["latency_ms"] == 250
    assert "timestamp" in d
    assert d["timestamp"] > 0

    # Old field names must be absent
    assert "type" not in d
    assert "lang" not in d
    assert "ts" not in d


def test_stage_status_event_versioned_fields():
    e = StageStatusEvent(stage_id=2, status="active")
    d = e.model_dump()

    assert d["event"] == "stage_status"
    assert d["v"] == 1
    assert d["stage_id"] == 2
    assert "timestamp" in d
    assert "type" not in d
    assert "ts" not in d


def test_error_event_versioned_fields():
    e = ErrorEvent(stage_id=3, code="GEMINI_TIMEOUT", message="session closed")
    d = e.model_dump()

    assert d["event"] == "error"
    assert d["v"] == 1
    assert d["code"] == "GEMINI_TIMEOUT"
    assert "type" not in d
    assert "ts" not in d


def test_transcript_serializes_correctly():
    e = TranscriptEvent(
        stage_id=1, language="es", text="test", is_final=False, sequence=5, latency_ms=100
    )
    raw = e.model_dump_json()
    d = json.loads(raw)

    assert d["event"] == "transcript"
    assert d["v"] == 1
    assert d["language"] == "es"
    assert d["latency_ms"] == 100
    assert d["is_final"] is False
    assert d["sequence"] == 5


def test_transcript_defaults():
    e = TranscriptEvent(stage_id=1, language="en", text="hi", is_final=True, sequence=1)
    assert e.latency_ms == 0
    assert e.v == 1
    assert e.event == "transcript"


def test_stage_ids_are_independent():
    e1 = TranscriptEvent(stage_id=1, language="es", text="stage1", is_final=True, sequence=1)
    e2 = TranscriptEvent(stage_id=2, language="es", text="stage2", is_final=True, sequence=1)

    assert e1.stage_id == 1
    assert e2.stage_id == 2
    assert e1.text != e2.text

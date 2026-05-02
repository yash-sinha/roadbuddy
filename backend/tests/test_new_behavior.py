"""Coverage for behavior added in 2026-05-02 session:
- db.cancel_stale_active_claims
- agent._field_quality / _merge_schema (no-downgrade merge)
- agent.MAX_FOLLOWUP_RETRIES handling
- extraction.infer_urgency
- extraction._strip_fences (regex JSON-block fallback)
- main /escalation/resolve historical mode
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import tempfile
import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# db.cancel_stale_active_claims
# ---------------------------------------------------------------------------


@pytest.fixture
def temp_db(monkeypatch):
    """Spin up a temporary SQLite file for db.* and return the module."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    from backend import db as db_module
    monkeypatch.setattr(db_module, "DB_PATH", path)
    db_module.init_db()
    yield db_module
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def _insert_active(db_module, claim_id: str, age_minutes: int) -> None:
    created = (datetime.utcnow() - timedelta(minutes=age_minutes)).isoformat()
    with sqlite3.connect(db_module.DB_PATH) as conn:
        conn.execute(
            "INSERT INTO claims (id, created_at, stage, status) VALUES (?,?,?,?)",
            (claim_id, created, "intake", "active"),
        )
        conn.commit()


def _row_status(db_module, claim_id: str) -> tuple[str, str]:
    """Return (status, stage) directly from the table, bypassing list_claims filters."""
    with sqlite3.connect(db_module.DB_PATH) as conn:
        row = conn.execute(
            "SELECT status, stage FROM claims WHERE id=?", (claim_id,)
        ).fetchone()
    assert row is not None, f"row {claim_id} missing"
    return row[0], row[1]


def test_cancel_stale_active_claims_marks_old_rows_cancelled(temp_db):
    _insert_active(temp_db, "old-1", age_minutes=10)
    _insert_active(temp_db, "old-2", age_minutes=15)
    _insert_active(temp_db, "fresh-1", age_minutes=1)

    cancelled = temp_db.cancel_stale_active_claims(threshold_minutes=5)

    assert set(cancelled) == {"old-1", "old-2"}
    assert _row_status(temp_db, "old-1") == ("cancelled", "cancelled")
    assert _row_status(temp_db, "old-2") == ("cancelled", "cancelled")
    assert _row_status(temp_db, "fresh-1") == ("active", "intake")


def test_cancel_stale_active_claims_skips_in_flight_id(temp_db):
    _insert_active(temp_db, "in-flight", age_minutes=20)
    _insert_active(temp_db, "other-old", age_minutes=20)

    cancelled = temp_db.cancel_stale_active_claims(
        threshold_minutes=5,
        skip_claim_ids={"in-flight"},
    )

    assert cancelled == ["other-old"]
    assert _row_status(temp_db, "in-flight") == ("active", "intake")
    assert _row_status(temp_db, "other-old") == ("cancelled", "cancelled")


def test_cancel_stale_active_claims_returns_empty_when_no_matches(temp_db):
    _insert_active(temp_db, "fresh", age_minutes=1)
    assert temp_db.cancel_stale_active_claims(threshold_minutes=5) == []


# ---------------------------------------------------------------------------
# db.archive_claim
# ---------------------------------------------------------------------------


def test_archive_claim_marks_row_archived(temp_db):
    _insert_active(temp_db, "stuck", age_minutes=1)
    assert temp_db.archive_claim("stuck") is True
    assert _row_status(temp_db, "stuck") == ("archived", "archived")


def test_archive_claim_returns_false_for_unknown_id(temp_db):
    assert temp_db.archive_claim("nope") is False


@pytest.mark.asyncio
async def test_archive_endpoint_broadcasts(temp_db, monkeypatch):
    from backend import main as main_module
    _insert_active(temp_db, "to-archive", age_minutes=1)
    monkeypatch.setattr(main_module.db, "DB_PATH", temp_db.DB_PATH)
    sent = []

    async def fake_send(message):
        sent.append(message)

    monkeypatch.setattr(main_module, "_send_to_clients", fake_send)
    res = await main_module.archive_claim_endpoint("to-archive")
    assert res == {"status": "archived"}
    assert sent and sent[0]["claim_id"] == "to-archive"
    assert sent[0]["stage"] == "archived"
    assert sent[0]["status"] == "archived"


@pytest.mark.asyncio
async def test_archive_endpoint_404_for_unknown(temp_db, monkeypatch):
    from backend import main as main_module
    from fastapi.responses import JSONResponse
    monkeypatch.setattr(main_module.db, "DB_PATH", temp_db.DB_PATH)
    res = await main_module.archive_claim_endpoint("missing")
    assert isinstance(res, JSONResponse)
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# agent._field_quality / _merge_schema — no-downgrade behavior
# ---------------------------------------------------------------------------


def test_merge_schema_keeps_higher_quality_name():
    from backend import agent
    existing = {"name": "Adam Driver", "location": None, "vehicle": None, "issue_type": None, "urgency": None}
    extracted = {"name": "Adam", "location": None, "vehicle": None, "issue_type": None, "urgency": None}
    merged = agent._merge_schema(existing, extracted)
    assert merged["name"] == "Adam Driver"


def test_merge_schema_takes_new_value_when_existing_missing():
    from backend import agent
    existing = {"name": None, "location": None, "vehicle": None, "issue_type": None, "urgency": None}
    extracted = {"name": "Adam", "location": "M25 J4", "vehicle": "BMW", "issue_type": "accident", "urgency": "high"}
    merged = agent._merge_schema(existing, extracted)
    assert merged["name"] == "Adam"
    assert merged["location"] == "M25 J4"
    assert merged["issue_type"] == "accident"


def test_merge_schema_prefers_specific_issue_over_other():
    from backend import agent
    existing = {"name": None, "location": None, "vehicle": None, "issue_type": "other", "urgency": None}
    extracted = {"name": None, "location": None, "vehicle": None, "issue_type": "battery", "urgency": None}
    merged = agent._merge_schema(existing, extracted)
    assert merged["issue_type"] == "battery"


def test_merge_schema_does_not_downgrade_specific_to_other():
    from backend import agent
    existing = {"name": None, "location": None, "vehicle": None, "issue_type": "battery", "urgency": None}
    extracted = {"name": None, "location": None, "vehicle": None, "issue_type": "other", "urgency": None}
    merged = agent._merge_schema(existing, extracted)
    assert merged["issue_type"] == "battery"


def test_merge_schema_keeps_longer_location():
    from backend import agent
    existing = {"name": None, "location": "23 King's Cross Road, London N1C 4AB", "vehicle": None, "issue_type": None, "urgency": None}
    extracted = {"name": None, "location": "London", "vehicle": None, "issue_type": None, "urgency": None}
    merged = agent._merge_schema(existing, extracted)
    assert merged["location"] == "23 King's Cross Road, London N1C 4AB"


# ---------------------------------------------------------------------------
# extraction.infer_urgency
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("transcript,issue_type,expected", [
    ("My car is on fire and there's a fluid leak", "engine_failure", "critical"),
    ("Someone is injured in the back seat", "accident", "critical"),
    ("Plain accident report with no other signals", "accident", "high"),
    ("I have a meeting in two hours, this is urgent", "battery", "high"),
    ("Just a small flat tyre, no rush", "flat_tyre", "low"),
    ("Tomorrow whenever, no rush at all", "engine_failure", "low"),
    ("Plain battery problem", "battery", "medium"),
    ("Not sure what's wrong", None, None),
])
def test_infer_urgency(transcript, issue_type, expected):
    from backend import extraction
    schema = {"issue_type": issue_type}
    assert extraction.infer_urgency(schema, transcript) == expected


# ---------------------------------------------------------------------------
# extraction._strip_fences — fallback to regex JSON-block extraction
# ---------------------------------------------------------------------------


def test_strip_fences_handles_clean_json():
    from backend.extraction import _strip_fences
    assert _strip_fences('{"a": 1}') == '{"a": 1}'


def test_strip_fences_strips_code_fence_with_language_tag():
    from backend.extraction import _strip_fences
    text = '```json\n{"a": 1}\n```'
    assert _strip_fences(text) == '{"a": 1}'


def test_strip_fences_strips_code_fence_no_tag():
    from backend.extraction import _strip_fences
    text = '```\n{"a": 1}\n```'
    assert _strip_fences(text) == '{"a": 1}'


def test_strip_fences_extracts_json_from_chatty_response():
    from backend.extraction import _strip_fences
    text = (
        "Here is the extracted data:\n\n"
        '{"name": "Priya Shah", "issue_type": "accident"}\n\n'
        "Hope this helps!"
    )
    cleaned = _strip_fences(text)
    parsed = json.loads(cleaned)
    assert parsed["name"] == "Priya Shah"
    assert parsed["issue_type"] == "accident"


def test_strip_fences_extracts_json_from_fenced_chatty_response():
    from backend.extraction import _strip_fences
    text = (
        "Here is the extracted data:\n\n"
        "```json\n{\"name\": \"Priya\"}\n```\n"
        "Let me know if you need more."
    )
    cleaned = _strip_fences(text)
    parsed = json.loads(cleaned)
    assert parsed["name"] == "Priya"


# ---------------------------------------------------------------------------
# Phase-1 follow-up retry cap (MAX_FOLLOWUP_RETRIES)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_followup_retry_cap_advances_after_max_attempts():
    """After 3 failed attempts on the same field, intake stops looping and advances."""
    from backend import agent

    # Force extract_schema to always return a schema with missing name (1-token).
    partial_schema_json = json.dumps({
        "name": "Adam",
        "location": "23 King's Cross Road, London N1C 4AB",
        "vehicle": "2024 Ford Focus Titanium",
        "issue_type": "battery",
        "urgency": "high",
    })

    # Make _transcribe + _tts no-ops; control _call so extraction always returns the partial.
    transcribe_mock = AsyncMock(return_value="The dashboard lights flicker then nothing")
    tts_mock = AsyncMock(return_value=b"")
    extract_call_mock = AsyncMock(side_effect=[
        partial_schema_json, "What's your full name?",
        partial_schema_json, "What's your full name?",
        partial_schema_json, "What's your full name?",
        partial_schema_json, "What's your full name?",
    ])

    broadcasts = []

    async def fake_broadcast(message):
        broadcasts.append(message)

    session_state: dict = {}

    with patch.object(agent, "_transcribe", transcribe_mock), \
         patch.object(agent, "_tts", tts_mock), \
         patch("backend.extraction._call", new=extract_call_mock):

        # First three turns should ask for the name; fourth should NOT broadcast a follow-up
        # for the same field — the retry cap kicks in.
        for _ in range(3):
            await agent.run_voice_turn(b"audio", fake_broadcast, session_state)

        followup_count_first_three = sum(
            1 for m in broadcasts if m.get("follow_up") and "name" in m.get("follow_up", "").lower()
        )
        assert session_state["followup_retries"]["name"] == 3
        assert followup_count_first_three >= 1  # at least one follow-up went out

        broadcasts_before = len(broadcasts)
        # Fourth turn — should NOT emit another follow-up for "name".
        await agent.run_voice_turn(b"audio", fake_broadcast, session_state)
        new_messages = broadcasts[broadcasts_before:]
        new_followups = [m for m in new_messages if m.get("follow_up")]
        assert all("name" not in (m.get("follow_up") or "").lower() for m in new_followups)
        assert session_state["followup_retries"]["name"] == 4


# ---------------------------------------------------------------------------
# /escalation/resolve historical mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_escalation_resolve_historical_updates_db_and_broadcasts(temp_db, monkeypatch):
    """When no live future exists, POST /escalation/resolve with claim_id should
    update the DB row and broadcast a 'complete' message."""
    from backend import main as main_module

    # Seed an escalated claim directly via db.save (mimic seed_demo).
    claim_id = str(uuid.uuid4())
    temp_db.create_stub(claim_id)
    temp_db.save(claim_id, {
        "schema": {"name": "Test User", "location": "X", "vehicle": "Y", "issue_type": "accident", "urgency": "high"},
        "transcript": "transcript",
        "damage": {"type": "accident", "severity": "severe", "ambiguous": True, "reason": "test"},
        "coverage": {"covered": None, "confidence": 0.4, "reasoning": "needs review", "escalate": True},
        "stage": "escalation",
    })

    # Point main_module at the same temp DB.
    monkeypatch.setattr(main_module.db, "DB_PATH", temp_db.DB_PATH)

    # Capture broadcasts.
    sent_messages = []

    async def fake_send(message):
        sent_messages.append(message)

    monkeypatch.setattr(main_module, "_send_to_clients", fake_send)
    # Make sure no live future is set.
    monkeypatch.setattr(main_module, "_escalation_future", None)

    body = main_module.EscalationResolve(
        approved=False,
        override="not_covered",
        claim_id=claim_id,
        notes="declined per phone call with reviewer",
    )
    result = await main_module.resolve_escalation(body)

    assert result == {"status": "resolved", "mode": "historical", "covered": False}

    saved = temp_db.get_claim(claim_id)
    assert saved["covered"] == 0
    assert saved["stage"] == "complete"
    assert "declined per phone call with reviewer" in saved["reasoning"]

    assert sent_messages, "expected at least one broadcast"
    assert sent_messages[0]["claim_id"] == claim_id
    assert sent_messages[0]["stage"] == "complete"
    assert sent_messages[0]["human_resolved"] is True


@pytest.mark.asyncio
async def test_escalation_resolve_returns_409_without_claim_id_or_future(monkeypatch):
    from backend import main as main_module
    from fastapi.responses import JSONResponse

    monkeypatch.setattr(main_module, "_escalation_future", None)
    body = main_module.EscalationResolve(approved=True, override=None, claim_id=None, notes=None)
    result = await main_module.resolve_escalation(body)
    assert isinstance(result, JSONResponse)
    assert result.status_code == 409


@pytest.mark.asyncio
async def test_escalation_resolve_returns_404_for_unknown_claim(temp_db, monkeypatch):
    from backend import main as main_module
    from fastapi.responses import JSONResponse

    monkeypatch.setattr(main_module.db, "DB_PATH", temp_db.DB_PATH)
    monkeypatch.setattr(main_module, "_escalation_future", None)

    body = main_module.EscalationResolve(
        approved=True,
        override=None,
        claim_id="does-not-exist",
        notes=None,
    )
    result = await main_module.resolve_escalation(body)
    assert isinstance(result, JSONResponse)
    assert result.status_code == 404

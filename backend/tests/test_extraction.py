"""Tests for extraction.py."""
import json
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_extract_schema_complete():
    """All fields present → returns schema with no follow-up."""
    schema_json = json.dumps({
        "name": "Alice Smith",
        "location": "SW1A 1AA",
        "vehicle": "2021 Toyota Corolla",
        "issue_type": "flat_tyre",
        "urgency": "high",
    })

    with patch("backend.extraction._call", new=AsyncMock(return_value=schema_json)):
        from backend.extraction import extract_schema
        schema, follow_up = await extract_schema("I have a flat tyre at SW1A 1AA. I'm Alice Smith driving a 2021 Toyota Corolla.")

    assert schema["name"] == "Alice Smith"
    assert schema["issue_type"] == "flat_tyre"
    assert follow_up is None


@pytest.mark.asyncio
async def test_extract_schema_missing_field_generates_followup():
    """Missing field → follow-up question returned."""
    partial_schema = json.dumps({
        "name": "Bob Jones",
        "location": None,
        "vehicle": "2020 Ford Focus",
        "issue_type": "battery",
        "urgency": "medium",
    })
    followup_text = "Could you tell me where you are located?"

    mock_call = AsyncMock(
        side_effect=[
            partial_schema,
            followup_text,
        ]
    )

    with patch("backend.extraction._call", new=mock_call):
        from backend.extraction import extract_schema
        schema, follow_up = await extract_schema("My car battery died. I'm Bob Jones in a 2020 Ford Focus.")

    assert schema["name"] == "Bob Jones"
    assert schema["location"] is None
    assert follow_up == followup_text


@pytest.mark.asyncio
async def test_extract_schema_invalid_json_falls_back():
    """If Claude returns non-JSON, schema defaults to all-None."""
    mock_call = AsyncMock(
        side_effect=[
            "not json at all",
            "What is your name?",
        ]
    )

    with patch("backend.extraction._call", new=mock_call):
        from backend.extraction import extract_schema
        schema, follow_up = await extract_schema("Hello")

    assert all(v is None for v in schema.values())
    assert follow_up is not None


@pytest.mark.asyncio
async def test_extract_schema_strips_markdown_fences():
    """Claude response wrapped in ```json ... ``` is parsed correctly."""
    raw = '```json\n{"name":"Jane Doe","location":"E1 6RF","vehicle":"Tesla Model 3","issue_type":"engine_failure","urgency":"critical"}\n```'
    with patch("backend.extraction._call", new=AsyncMock(return_value=raw)):
        from backend.extraction import extract_schema
        schema, follow_up = await extract_schema("My engine seized on the A12.")

    assert schema["name"] == "Jane Doe"
    assert schema["issue_type"] == "engine_failure"
    assert follow_up is None


def test_review_intake_rejects_low_quality_fields():
    from backend.extraction import review_intake

    schema = {
        "name": "Adam",
        "location": "x 42111",
        "vehicle": "Pinto",
        "issue_type": "other",
        "urgency": "medium",
    }

    review = review_intake(
        schema,
        "Something wrong with my car. Adam. Right on the x 42111. Four Pinto.",
    )

    assert review["ready"] is False
    assert review["next_field"] == "issue_type"


@pytest.mark.asyncio
async def test_extract_schema_infers_issue_type_from_transcript():
    partial_schema = json.dumps({
        "name": "Alice Smith",
        "location": "M25 Junction 12",
        "vehicle": "2021 Toyota Corolla",
        "issue_type": "other",
        "urgency": "high",
    })

    with patch("backend.extraction._call", new=AsyncMock(return_value=partial_schema)):
        from backend.extraction import extract_schema
        schema, follow_up = await extract_schema(
            "I have a flat tyre on the M25 near Junction 12 in my 2021 Toyota Corolla."
        )

    assert schema["issue_type"] == "flat_tyre"
    assert follow_up is None

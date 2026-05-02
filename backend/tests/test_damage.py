"""Tests for damage.py."""
import json
import pytest
from unittest.mock import AsyncMock, patch


SAMPLE_SCHEMA = {
    "name": "Alice",
    "location": "SW1A 1AA",
    "vehicle": "2021 Toyota Corolla",
    "issue_type": "flat_tyre",
    "urgency": "high",
}


@pytest.mark.asyncio
async def test_assess_damage_clear_case():
    result_json = json.dumps({"type": "flat_tyre", "severity": "minor", "ambiguous": False})

    with patch("backend.damage._call", new=AsyncMock(return_value=result_json)):
        from backend.damage import assess_damage
        result = await assess_damage("I have a flat tyre", SAMPLE_SCHEMA)

    assert result["type"] == "flat_tyre"
    assert result["severity"] == "minor"
    assert result["ambiguous"] is False


@pytest.mark.asyncio
async def test_assess_damage_marks_ambiguous():
    result_json = json.dumps({"type": "accident", "severity": "severe", "ambiguous": True})

    with patch("backend.damage._call", new=AsyncMock(return_value=result_json)):
        from backend.damage import assess_damage
        result = await assess_damage("There was some kind of incident", SAMPLE_SCHEMA)

    assert result["ambiguous"] is True


@pytest.mark.asyncio
async def test_assess_damage_invalid_json_falls_back():
    with patch("backend.damage._call", new=AsyncMock(return_value="broken")):
        from backend.damage import assess_damage
        result = await assess_damage("unclear situation", SAMPLE_SCHEMA)

    # Falls back gracefully: ambiguous=True, severity from schema issue_type
    assert "type" in result
    assert "severity" in result
    assert result["ambiguous"] is True

"""Tests for the two-phase agent pipeline."""
import asyncio
import copy
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

FULL_SCHEMA = {
    "name": "Alice Smith",
    "location": "SW1A 1AA",
    "vehicle": "2021 Toyota Corolla",
    "issue_type": "flat_tyre",
    "urgency": "high",
}
DAMAGE = {"type": "flat_tyre", "severity": "minor", "ambiguous": False}
COVERAGE_HIGH_CONF = {"covered": True, "confidence": 0.92, "reasoning": "Flat tyre covered.", "escalate": False}
COVERAGE_LOW_CONF = {"covered": True, "confidence": 0.45, "reasoning": "Ambiguous claim.", "escalate": True}


def _mock_tts():
    return patch("backend.agent._tts", new=AsyncMock(return_value=b"audio"))


def _mock_transcribe(text: str):
    return patch("backend.agent._transcribe", new=AsyncMock(return_value=text))


class TestRunVoiceTurn:
    @pytest.mark.asyncio
    async def test_returns_false_when_fields_missing(self):
        """Schema incomplete → returns False and broadcasts follow-up."""
        partial = {k: None for k in FULL_SCHEMA}
        partial["name"] = "Alice"

        broadcast_calls = []
        async def broadcast(msg):
            broadcast_calls.append(msg)

        with _mock_transcribe("Hi I'm Alice"), _mock_tts():
            with patch("backend.agent.extraction.extract_schema", new=AsyncMock(
                return_value=(partial, "Could you tell me your location?")
            )):
                from backend.agent import run_voice_turn
                session = {}
                result = await run_voice_turn(b"audio", broadcast, session)

        assert result is False
        follow_up_msgs = [m for m in broadcast_calls if m.get("follow_up")]
        assert len(follow_up_msgs) == 1

    @pytest.mark.asyncio
    async def test_returns_true_when_schema_complete(self):
        """All fields present → asks one final question, then ends the call."""
        broadcast_calls = []
        async def broadcast(msg):
            broadcast_calls.append(msg)

        with _mock_transcribe("Full details here"), _mock_tts():
            with patch("backend.agent.extraction.extract_schema", new=AsyncMock(
                return_value=(FULL_SCHEMA, None)
            )):
                from backend.agent import run_voice_turn
                session = {}
                result = await run_voice_turn(b"audio", broadcast, session)

        assert result is False
        assert any(m.get("follow_up") for m in broadcast_calls)

        with _mock_transcribe("No, that's everything"), _mock_tts():
            with patch("backend.agent.extraction.extract_schema", new=AsyncMock(
                return_value=(FULL_SCHEMA, None)
            )):
                from backend.agent import run_voice_turn
                result = await run_voice_turn(b"audio", broadcast, session)

        assert result is True
        stages = [m["stage"] for m in broadcast_calls]
        assert "call_ended" in stages

    @pytest.mark.asyncio
    async def test_status_question_after_preclose_gets_short_answer_and_ends_call(self):
        """Customer asks what happens next → agent answers briefly and ends the call."""
        broadcast_calls = []
        async def broadcast(msg):
            broadcast_calls.append(msg)

        with _mock_transcribe("Full details here"), _mock_tts():
            with patch("backend.agent.extraction.extract_schema", new=AsyncMock(
                return_value=(FULL_SCHEMA, None)
            )):
                from backend.agent import run_voice_turn
                session = {}
                result = await run_voice_turn(b"audio", broadcast, session)

        assert result is False

        with _mock_transcribe("When will I get an update?"), _mock_tts():
            with patch("backend.agent.extraction.extract_schema", new=AsyncMock(
                return_value=(FULL_SCHEMA, None)
            )):
                result = await run_voice_turn(b"audio", broadcast, session)

        assert result is True
        final_message = next(m for m in reversed(broadcast_calls) if m["stage"] == "call_ended")
        assert "update you shortly" in final_message["message"]

    @pytest.mark.asyncio
    async def test_empty_transcription_returns_false(self):
        """Deepgram returns empty string → returns False, no broadcast."""
        broadcast_calls = []
        async def broadcast(msg):
            broadcast_calls.append(msg)

        with _mock_transcribe(""):
            from backend.agent import run_voice_turn
            result = await run_voice_turn(b"audio", broadcast, {})

        assert result is False
        assert len(broadcast_calls) == 0

    @pytest.mark.asyncio
    async def test_transcript_accumulated_across_turns(self):
        """Transcript from multiple turns is concatenated."""
        broadcast_calls = []
        async def broadcast(msg):
            broadcast_calls.append(msg)

        partial = {**FULL_SCHEMA, "location": None}

        with _mock_tts():
            with patch("backend.agent._transcribe", new=AsyncMock(return_value="turn one")):
                with patch("backend.agent.extraction.extract_schema", new=AsyncMock(
                    return_value=(partial, "Where are you?")
                )):
                    from backend.agent import run_voice_turn
                    session = {}
                    await run_voice_turn(b"audio", broadcast, session)

        assert session["transcript"] == "turn one"

        with _mock_tts():
            with patch("backend.agent._transcribe", new=AsyncMock(return_value="turn two")):
                with patch("backend.agent.extraction.extract_schema", new=AsyncMock(
                    return_value=(FULL_SCHEMA, None)
                )):
                    await run_voice_turn(b"audio", broadcast, session)

        assert "turn one" in session["transcript"]
        assert "turn two" in session["transcript"]

    @pytest.mark.asyncio
    async def test_callback_status_question_uses_existing_context(self):
        """Callback status question should answer from prior claim state and not restart intake."""
        broadcast_calls = []
        async def broadcast(msg):
            broadcast_calls.append(msg)

        callback_context = {
            "caller_name": "Alice",
            "vehicle": "2021 Toyota Corolla",
            "issue_type": "flat_tyre",
            "location": "SW1A 1AA",
            "stage": "coverage",
            "covered": None,
        }

        with _mock_transcribe("When will I get an update?"), _mock_tts():
            with patch("backend.agent.extraction.extract_schema", new=AsyncMock(
                return_value=({k: None for k in FULL_SCHEMA}, "Where are you now?")
            )):
                from backend.agent import run_voice_turn
                session = {"callback_context": callback_context}
                result = await run_voice_turn(b"audio", broadcast, session)

        assert result is True
        assert session["skip_phase2"] is True
        final_message = next(m for m in reversed(broadcast_calls) if m["stage"] == "callback_complete")
        assert "still being reviewed" in final_message["message"]
        assert final_message["callback_status_only"] is True

    @pytest.mark.asyncio
    async def test_status_question_with_low_quality_intake_keeps_collecting_details(self):
        """ETA question should not end intake when the captured details are still vague."""
        broadcast_calls = []
        async def broadcast(msg):
            broadcast_calls.append(msg)

        low_quality_schema = {
            "name": "Adam",
            "location": "x 42111",
            "vehicle": "Pinto",
            "issue_type": "other",
            "urgency": "medium",
        }

        with _mock_transcribe("Something wrong with my car. Adam. Right on the x 42111. Four Pinto. How long before help arrives?"), _mock_tts():
            with patch("backend.agent.extraction.extract_schema", new=AsyncMock(
                return_value=(low_quality_schema, "What exactly is wrong with the car?")
            )):
                with patch("backend.agent.extraction.review_intake", return_value={
                    "ready": False,
                    "gaps": [{"field": "issue_type", "reason": "You still do not know exactly what is wrong with the car."}],
                    "next_field": "issue_type",
                    "next_reason": "You still do not know exactly what is wrong with the car.",
                }):
                    from backend.agent import run_voice_turn
                    session = {}
                    result = await run_voice_turn(b"audio", broadcast, session)

        assert result is False
        follow_up = next(m for m in reversed(broadcast_calls) if m.get("follow_up"))
        assert follow_up["follow_up"].startswith("I'll help with that. First, what exactly is wrong")


class TestRunPostCallPipeline:
    @pytest.mark.asyncio
    async def test_happy_path_no_escalation(self):
        """High-confidence coverage → no escalation, broadcasts complete."""
        stages = []
        async def broadcast(msg):
            stages.append(msg["stage"])

        session = {"schema": FULL_SCHEMA, "transcript": "I have a flat tyre"}

        with patch("backend.agent.damage.assess_damage", new=AsyncMock(return_value=DAMAGE)):
            with patch("backend.agent.rag.query", return_value=["Flat tyre is covered."]):
                with patch("backend.agent._call", new=AsyncMock(side_effect=[
                    json.dumps(COVERAGE_HIGH_CONF),
                    "Alice reported a flat tyre and help was confirmed.",
                ])):
                    from backend.agent import run_post_call_pipeline
                    await run_post_call_pipeline(broadcast, session, lambda: None)

        assert "complete" in stages
        assert "escalation" not in stages

    @pytest.mark.asyncio
    async def test_low_confidence_triggers_escalation(self):
        """Low-confidence coverage → escalation stage broadcast, awaits future."""
        stages = []
        async def broadcast(msg):
            stages.append(msg["stage"])

        session = {"schema": FULL_SCHEMA, "transcript": "unclear incident"}

        # get_escalation_future must be sync (returns an already-resolved future)
        loop = asyncio.get_event_loop()
        resolution = MagicMock(approved=True, override="covered")
        resolved_future = loop.create_future()
        resolved_future.set_result(resolution)

        with patch("backend.agent.damage.assess_damage", new=AsyncMock(return_value=DAMAGE)):
            with patch("backend.agent.rag.query", return_value=["Policy section."]):
                with patch("backend.agent._call", new=AsyncMock(side_effect=[
                    json.dumps(COVERAGE_LOW_CONF),
                    "Alice's claim was reviewed by a human and approved.",
                ])):
                    from backend.agent import run_post_call_pipeline
                    await run_post_call_pipeline(broadcast, session, lambda: resolved_future)

        assert "escalation" in stages
        assert "complete" in stages

    @pytest.mark.asyncio
    async def test_complete_state_includes_sms_text(self):
        """Final broadcast contains sms_text field."""
        broadcasts = []
        async def broadcast(msg):
            broadcasts.append(msg)

        session = {"schema": FULL_SCHEMA, "transcript": "flat tyre on the motorway"}

        with patch("backend.agent.damage.assess_damage", new=AsyncMock(return_value=DAMAGE)):
            with patch("backend.agent.rag.query", return_value=["Flat tyre covered."]):
                with patch("backend.agent._call", new=AsyncMock(side_effect=[
                    json.dumps(COVERAGE_HIGH_CONF),
                    "Alice's assistance was confirmed and dispatched.",
                ])):
                    from backend.agent import run_post_call_pipeline
                    await run_post_call_pipeline(broadcast, session, lambda: None)

        complete = next(b for b in broadcasts if b["stage"] == "complete")
        assert "sms_text" in complete
        assert len(complete["sms_text"]) > 0

    @pytest.mark.asyncio
    async def test_denied_claim_does_not_dispatch_assistance(self):
        """Denied claims should not persist tow/repair actions or assistance language in the summary."""
        broadcasts = []

        async def broadcast(msg):
            broadcasts.append(msg)

        denied_coverage = {
            "covered": False,
            "confidence": 0.91,
            "reasoning": "Engine failure is not covered.",
            "escalate": False,
        }
        denied_schema = {
            "name": "Adam Burger",
            "location": "Exit 52 on I-5",
            "vehicle": "Ford Pinto",
            "issue_type": "engine_failure",
            "urgency": "high",
        }
        denied_damage = {"type": "engine_failure", "severity": "moderate", "ambiguous": False}
        session = {"schema": denied_schema, "transcript": "Engine failure at Exit 52 on I-5"}

        with patch("backend.agent.damage.assess_damage", new=AsyncMock(return_value=denied_damage)):
            with patch("backend.agent.rag.query", return_value=["Engine failure is excluded."]):
                with patch("backend.agent._call", new=AsyncMock(side_effect=[
                    json.dumps(denied_coverage),
                    "Adam Burger reported an engine failure in his Ford Pinto at Exit 52 on I-5. The claim is not covered and no assistance was dispatched.",
                ])):
                    from backend.agent import run_post_call_pipeline
                    await run_post_call_pipeline(broadcast, session, lambda: None)

        complete = next(b for b in broadcasts if b["stage"] == "complete")
        assert complete["coverage"]["covered"] is False
        assert complete["action"]["type"] is None
        assert complete["action"]["garage"] is None
        assert "not covered under your policy" in complete["sms_text"]
        assert "tow truck" not in complete["summary"].lower()

    @pytest.mark.asyncio
    async def test_low_quality_intake_forces_escalation(self):
        """If weak intake slips through, automatic denial should be blocked behind human review."""
        stages = []
        coverages = []

        async def broadcast(msg):
            stages.append(msg["stage"])
            if msg["stage"] in {"coverage", "escalation"}:
                coverages.append(copy.deepcopy(msg.get("coverage")))

        low_quality_schema = {
            "name": "Adam",
            "location": "x 42111",
            "vehicle": "Pinto",
            "issue_type": "other",
            "urgency": "medium",
        }
        session = {"schema": low_quality_schema, "transcript": "Something wrong with my car. Adam. Right on the x 42111. Four Pinto."}

        loop = asyncio.get_event_loop()
        resolution = MagicMock(approved=True, override="covered")
        resolved_future = loop.create_future()
        resolved_future.set_result(resolution)

        with patch("backend.agent.damage.assess_damage", new=AsyncMock(return_value=DAMAGE)):
            with patch("backend.agent.rag.query", return_value=["Policy section."]):
                with patch("backend.agent.extraction.review_intake", return_value={
                    "ready": False,
                    "gaps": [{"field": "issue_type", "reason": "You still do not know exactly what is wrong with the car."}],
                    "next_field": "issue_type",
                    "next_reason": "You still do not know exactly what is wrong with the car.",
                }):
                    with patch("backend.agent._call", new=AsyncMock(side_effect=[
                        json.dumps(COVERAGE_HIGH_CONF),
                        "Adam's claim was routed for human review before help was confirmed.",
                    ])):
                        from backend.agent import run_post_call_pipeline
                        await run_post_call_pipeline(broadcast, session, lambda: resolved_future)

        assert "escalation" in stages
        assert any(coverage and coverage["escalate"] is True for coverage in coverages)

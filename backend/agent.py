"""
Two-phase voice agent:
  Phase 1 — run_voice_turn()        : multi-turn intake until schema complete, then goodbye TTS
  Phase 2 — run_post_call_pipeline(): damage → RAG → coverage → escalation gate → decision → SMS
"""
import asyncio
import base64
import json
import os
import re
from typing import Callable, Awaitable

from . import extraction, damage, rag, decision
from .extraction import _call, _strip_fences

CARTESIA_MODEL = "sonic-2"
CARTESIA_VOICE_ID = "a0e99841-438c-4a64-b679-ae501e7d6091"  # Barbra

MAX_FOLLOWUP_RETRIES = 3

SUMMARY_PROMPT = """You write the one-paragraph claim summary that a human claims \
handler reads first when they open a claim on the dashboard. The handler needs to \
understand the situation in under five seconds.

================================================================
INPUTS
================================================================
Claim details (intake):
{schema}

Damage assessment:
{damage}

Coverage decision:
{coverage}

Action / dispatch:
{action}

================================================================
WRITING RULES
================================================================
- 2 to 3 sentences, plain English, no bullet points, no JSON.
- Sentence 1: WHO + WHAT + WHERE + WHICH VEHICLE.
    e.g. "Olivia Bennett reported a dead battery on her 2024 Ford Focus at King's Cross."
- Sentence 2: outcome and the reason for it (cite the policy section if coverage was \
  decided automatically).
    e.g. "Covered under SECTION 2.4 (Battery and Electrical Failure)."
- Sentence 3 (only if relevant): what is happening next.
    e.g. "Tow truck dispatched (ETA 12 min)." OR "Held for human review — liability unclear."

NEVER:
- Mention dispatched assistance unless `action` explicitly contains a confirmed service \
  (garage, taxi, or rental with a name).
- Speculate about coverage if the coverage decision is not in the input.
- Use call-centre register ("the customer was reaching out to inquire about…").
- Use bullet points, headers, or markdown.

Output only the paragraph — no preamble, no closing line."""

COVERAGE_PROMPT = """You are a senior motor-insurance coverage adjudicator for ClaimBuddy. \
A junior agent has captured a claim from a roadside caller. Your job is to decide whether \
the policy covers the incident, how confident you are, and articulate the reasoning a human \
reviewer can audit in seconds.

================================================================
INPUTS
================================================================
Claim details (from voice intake):
{schema}

Damage assessment (from automated classifier):
{damage}

Policy sections retrieved by RAG (these are the ONLY policy facts you may rely on):
{chunks}

================================================================
DECISION ALGORITHM — follow in order
================================================================
1. Identify the candidate covered event (Section 2.x) that best matches `damage.type` and \
   the transcript-derived issue.
2. Check every Section 3 exclusion and decide whether any applies. An exclusion that \
   plausibly applies should drag confidence down even if not certain.
3. Check Section 1 / Section 2 prerequisites (vehicle on schedule, valid plan, incident \
   reference if required, etc.).
4. Reconcile damage classifier output with transcript evidence. If they disagree, prefer \
   the transcript and lower confidence.
5. Apply the calibration scale below to set `confidence`.
6. Set `covered = true` only when at least one Section 2 clause clearly applies AND no \
   Section 3 exclusion plausibly applies AND prerequisites are met.

================================================================
CONFIDENCE CALIBRATION (must follow)
================================================================
- 0.90-1.00 — Direct policy match, all required facts present, no exclusion in sight.
- 0.70-0.89 — Clear match with one minor gap (e.g. exact mileage unstated) but no \
              competing exclusion.
- 0.40-0.69 — Mixed signals: a covered clause applies AND an exclusion plausibly applies, \
              OR a required fact is missing (no incident reference, unclear liability, \
              third-party uninsured, ambiguous damage classification).
- 0.20-0.39 — Most evidence points away from coverage but caller provided enough to make \
              the call.
- 0.00-0.19 — Insufficient information to adjudicate; request human review.

ANY of the following force confidence ≤ 0.69 (escalation territory):
- damage.ambiguous == true
- caller uncertain about their own actions (e.g. "I'm not sure if I was in the right lane")
- exclusion in Section 3 plausibly applies but cannot be confirmed
- policy sections retrieved do not actually address the described incident
- two policy clauses give conflicting verdicts and the transcript can't break the tie

DO NOT escalate or downgrade confidence merely because:
- The caller did not provide an incident reference number, police report, or other \
  administrative document. Voice intake never collects these — they are follow-up items \
  the claims handler obtains after roadside assistance is dispatched.
- The third party in an accident left the scene. Hit-and-run is a common road incident; \
  it is NOT a coverage exclusion on its own — only flag it if it materially changes the \
  Section 2.3 analysis (e.g. the caller's own liability becomes ambiguous as a result).
- The caller did not state their policy number. Identity is verified out of band.

================================================================
REASONING REQUIREMENTS
================================================================
The `reasoning` field must:
- Be 2-4 sentences (not 1).
- Cite the specific section identifier (e.g. "SECTION 2.4") for the covered clause and \
  for any exclusion considered.
- Quote or paraphrase the exact phrase from the transcript / damage assessment that drove \
  the decision.
- If confidence < 0.70, end with one sentence beginning "Escalating because…" naming the \
  specific gap that a human must resolve.

================================================================
OUTPUT SCHEMA
================================================================
Return ONLY a JSON object with these fields (no prose, no code fences):
{{
  "covered": true | false,
  "confidence": <float 0.0-1.0, calibrated per scale above>,
  "reasoning": "<2-4 sentences following the requirements above>",
  "escalate": <true if confidence < 0.7, false otherwise>
}}

================================================================
EXAMPLE — high-confidence approval
================================================================
{{
  "covered": true,
  "confidence": 0.93,
  "reasoning": "Caller's symptom 'dashboard lights flicker then nothing' is a textbook \
discharged-battery presentation, which is explicitly named in SECTION 2.4 (Battery and \
Electrical Failure Coverage). Vehicle (2024 Ford Focus Titanium) is consistent with a \
listed schedule entry, and no Section 3 exclusion is in play. Damage classifier agrees \
(type=battery, severity=moderate, ambiguous=false), so confidence sits at the top of the \
0.90+ band.",
  "escalate": false
}}

================================================================
EXAMPLE — escalation due to ambiguous liability
================================================================
{{
  "covered": false,
  "confidence": 0.42,
  "reasoning": "SECTION 2.3 (Accident Damage) covers a road traffic accident that renders \
the vehicle unsafe — the caller's 'fluid leak and detached bumper' meets that bar. \
However the third party left the scene with no plate captured and the caller said 'I'm \
not sure I was in the right lane', so liability is unclear and SECTION 2.3's incident-\
reference prerequisite cannot be satisfied. Damage classifier flagged ambiguous=true. \
Escalating because liability and the missing incident reference need human verification \
before coverage can be confirmed.",
  "escalate": true
}}
"""

BroadcastFn = Callable[[dict], Awaitable[None]]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _tts(text: str) -> bytes | None:
    api_key = os.environ.get("CARTESIA_API_KEY", "")
    if not api_key:
        print("[TTS] CARTESIA_API_KEY not set — skipping TTS")
        return None
    try:
        from cartesia import AsyncCartesia
        async with AsyncCartesia(api_key=api_key) as client:
            stream = await client.tts.bytes(
                model_id=CARTESIA_MODEL,
                transcript=text,
                voice={"mode": "id", "id": CARTESIA_VOICE_ID},
                output_format={
                    "container": "wav",
                    "encoding": "pcm_f32le",
                    "sample_rate": 44100,
                },
            )
            chunks: list[bytes] = []
            async for chunk in stream:
                chunks.append(chunk)
        return b"".join(chunks)
    except Exception as e:
        print(f"[TTS error] {e}")
        return None


async def _transcribe(audio_bytes: bytes) -> str:
    from deepgram import DeepgramClient, PrerecordedOptions
    dg = DeepgramClient(os.environ["DEEPGRAM_API_KEY"])
    options = PrerecordedOptions(model="nova-2", smart_format=True)
    response = await dg.listen.asyncrest.v("1").transcribe_file(
        {"buffer": audio_bytes, "mimetype": "audio/webm;codecs=opus"},
        options,
    )
    try:
        return response.results.channels[0].alternatives[0].transcript
    except Exception:
        return ""


def _b64(audio: bytes | None) -> str | None:
    return base64.b64encode(audio).decode() if audio else None


def _field_quality(field: str, value):
    """Higher score = better. None / empty = -1 so any captured value beats it."""
    if not value:
        return -1
    if field == "name":
        # More tokens = better (prefer "Adam Driver" over "Adam").
        return len(re.findall(r"[A-Za-z][A-Za-z'-]+", str(value)))
    if field == "issue_type":
        # Specific type beats "other".
        return 0 if value == "other" else 2
    if field == "urgency":
        return 1
    # location, vehicle: prefer longer / more specific.
    return len(str(value).strip())


def _merge_schema(existing: dict | None, extracted: dict) -> dict:
    if not existing:
        return {f: extracted.get(f) for f in extraction.SCHEMA_FIELDS}
    merged = {}
    for field in extraction.SCHEMA_FIELDS:
        ex_val = existing.get(field)
        new_val = extracted.get(field)
        if _field_quality(field, new_val) > _field_quality(field, ex_val):
            merged[field] = new_val
        else:
            merged[field] = ex_val
    return merged


def _append_conversation(session_state: dict, speaker: str, text: str) -> None:
    line = text.strip()
    if not line:
        return
    existing = session_state.get("conversation_transcript", "")
    next_line = f"{speaker}: {line}"
    session_state["conversation_transcript"] = f"{existing}\n{next_line}".strip() if existing else next_line


def _dashboard_context(session_state: dict) -> dict:
    return {
        "intake_review": session_state.get("intake_review"),
        "callback_context": session_state.get("callback_context"),
        "conversation_transcript": session_state.get("conversation_transcript", session_state.get("transcript", "")),
    }


def _lowercase_first(text: str) -> str:
    if not text:
        return text
    return text[:1].lower() + text[1:]


def _bridge_follow_up_for_customer_question(follow_up: str) -> str:
    return f"I'll help with that. First, {_lowercase_first(follow_up)}"


def _looks_like_status_question(text: str) -> bool:
    normalized = text.lower()
    keywords = (
        "when will",
        "when do i",
        "when can i",
        "when should i",
        "status",
        "result",
        "results",
        "outcome",
        "update",
        "hear back",
        "find out",
        "how long",
        "how soon",
        "what happens next",
        "next step",
        "next steps",
    )
    return any(keyword in normalized for keyword in keywords)


def _has_new_incident_details(text: str) -> bool:
    normalized = text.lower()
    return any(
        keyword in normalized
        for keyword in (
            "flat tyre",
            "flat tire",
            "accident",
            "battery",
            "engine",
            "breakdown",
            "won't start",
            "won’t start",
            "stranded",
            "tow",
            "repair",
            "another issue",
            "something else happened",
        )
    )


def _claim_stage_phrase(callback_context: dict) -> str:
    stage = callback_context.get("stage")
    if stage == "complete":
        if callback_context.get("covered"):
            return "Help was already confirmed."
        return "It currently shows as not covered."
    return "It's still being reviewed."


def _callback_status_reply(callback_context: dict) -> str:
    issue = (callback_context.get("issue_type") or "claim").replace("_", " ")
    location = callback_context.get("location")
    stage = callback_context.get("stage")
    if stage == "complete":
        if callback_context.get("covered"):
            return (
                f"I can see your {issue} claim"
                f"{f' from {location}' if location else ''} already has help confirmed. "
                "You should already see the update, but if anything still looks wrong we can have someone follow up."
            )
        return (
            f"I can see your {issue} claim"
            f"{f' from {location}' if location else ''} currently shows as not covered. "
            "If you want it reviewed again, a claims handler can follow up."
        )
    return (
        f"I can see your {issue} claim"
        f"{f' from {location}' if location else ''} is still being reviewed. "
        "We'll update you as soon as there's a decision."
    )


def _callback_status_label(callback_context: dict) -> str:
    stage = callback_context.get("stage")
    if stage == "complete":
        if callback_context.get("covered"):
            return "Help confirmed"
        return "Not covered"
    return "Still reviewing"


async def _handle_callback_turn(
    transcript_new: str,
    broadcast: BroadcastFn,
    session_state: dict,
) -> bool:
    full_transcript = session_state["transcript"]
    callback_context = session_state["callback_context"]

    if _looks_like_status_question(transcript_new) and not _has_new_incident_details(transcript_new):
        reply = _callback_status_reply(callback_context)
        _append_conversation(session_state, "Assistant", reply)
        audio = await _tts(reply)
        await broadcast(_make_state(
            "callback_complete",
            transcript=full_transcript,
            schema=session_state.get("schema"),
            coverage={
                "covered": callback_context.get("covered"),
                "confidence": callback_context.get("confidence"),
                "reasoning": callback_context.get("reasoning") or "",
                "escalate": False,
            },
            audio_b64=_b64(audio),
            message=reply,
            callback_status_only=True,
            callback_claim_id=callback_context.get("id"),
            callback_status_label=_callback_status_label(callback_context),
            **_dashboard_context(session_state),
        ))
        session_state["callback_resolved"] = True
        session_state["skip_phase2"] = True
        return True

    if not session_state.get("callback_context_acknowledged"):
        session_state["callback_context_acknowledged"] = True
        reply = (
            "I've got your earlier claim here, "
            "so just tell me what's changed or what you need help with."
        )
        _append_conversation(session_state, "Assistant", reply)
        audio = await _tts(reply)
        await broadcast(_make_state(
            "intake",
            transcript=full_transcript,
            turn_transcript=transcript_new,
            schema=session_state.get("schema"),
            audio_b64=_b64(audio),
            follow_up=reply,
            **_dashboard_context(session_state),
        ))
        return False

    return False


def _make_state(
    stage: str,
    *,
    transcript: str = "",
    schema: dict | None = None,
    damage_info: dict | None = None,
    coverage: dict | None = None,
    action: dict | None = None,
    chunks: list[str] | None = None,
    audio_b64: str | None = None,
    **extra,
) -> dict:
    state = {
        "stage": stage,
        "transcript": transcript,
        "schema": schema or {k: None for k in extraction.SCHEMA_FIELDS},
        "damage": damage_info or {"type": None, "severity": None, "ambiguous": False},
        "coverage": coverage or {"covered": None, "confidence": None, "reasoning": "", "escalate": False},
        "action": action or {"type": None, "garage": None, "eta_minutes": None, "taxi": None, "rental": None},
        "policy_chunks": chunks or [],
        "audio": audio_b64,
    }
    state.update(extra)
    return state


# ---------------------------------------------------------------------------
# Phase 1 — Voice intake (client on the line)
# ---------------------------------------------------------------------------

async def run_voice_turn(
    audio_bytes: bytes,
    broadcast: BroadcastFn,
    session_state: dict,
) -> bool:
    """
    Process one voice turn.
    Returns True when schema is complete and the goodbye TTS has been sent.
    The caller should immediately start Phase 2 when True is returned.
    """
    transcript_new = await _transcribe(audio_bytes)
    if not transcript_new.strip():
        return False

    session_state["transcript"] = (
        session_state.get("transcript", "") + " " + transcript_new
    ).strip()
    _append_conversation(session_state, "Customer", transcript_new)
    full_transcript = session_state["transcript"]

    await broadcast(_make_state(
        "intake",
        transcript=full_transcript,
        turn_transcript=transcript_new,
        schema=session_state.get("schema"),
        **_dashboard_context(session_state),
    ))

    # Pre-populate schema from callback context so agent skips known fields
    if not session_state.get("schema") and session_state.get("callback_context"):
        ctx = session_state["callback_context"]
        session_state["schema"] = {
            "name": ctx.get("caller_name"),
            "location": None,
            "vehicle": ctx.get("vehicle"),
            "issue_type": None,
            "urgency": None,
        }

    extracted_schema, follow_up = await extraction.extract_schema(full_transcript)
    schema = _merge_schema(session_state.get("schema"), extracted_schema)
    session_state["schema"] = schema
    intake_review = extraction.review_intake(schema, full_transcript)
    session_state["intake_review"] = intake_review

    if session_state.get("callback_context") and not session_state.get("phase2_started"):
        callback_done = await _handle_callback_turn(transcript_new, broadcast, session_state)
        if callback_done:
            return True
        if not _has_new_incident_details(transcript_new):
            return False

    # First turn with nothing useful captured — user probably said a greeting.
    # Ask an open question rather than jumping to field collection.
    filled = [f for f in extraction.SCHEMA_FIELDS if schema.get(f)]
    if not filled and not session_state.get("situation_asked"):
        session_state["situation_asked"] = True
        question = "Tell me what's happened and where you are."
        _append_conversation(session_state, "Assistant", question)
        audio = await _tts(question)
        await broadcast(_make_state(
            "intake",
            transcript=full_transcript,
            turn_transcript=transcript_new,
            schema=schema,
            audio_b64=_b64(audio),
            follow_up=question,
            **_dashboard_context(session_state),
        ))
        return False

    if follow_up:
        next_field = intake_review.get("next_field")
        retry_counts = session_state.setdefault("followup_retries", {})
        retry_counts[next_field] = retry_counts.get(next_field, 0) + 1
        if retry_counts[next_field] > MAX_FOLLOWUP_RETRIES:
            # Bot has asked for the same field too many times. Stop looping —
            # advance to Phase 2 and let the escalation gate handle the gap.
            print(f"[intake] giving up on field={next_field} after {retry_counts[next_field]} attempts")
        else:
            line_to_say = follow_up
            if _looks_like_status_question(transcript_new):
                line_to_say = _bridge_follow_up_for_customer_question(follow_up)
            _append_conversation(session_state, "Assistant", line_to_say)
            audio = await _tts(line_to_say)
            await broadcast(_make_state(
                "intake",
                transcript=full_transcript,
                turn_transcript=transcript_new,
                schema=schema,
                audio_b64=_b64(audio),
                follow_up=line_to_say,
                **_dashboard_context(session_state),
            ))
            return False  # More turns needed

    # Schema complete — one pre-close before ending the call
    if not session_state.get("anything_else_asked"):
        session_state["anything_else_asked"] = True
        anything_else = "Got it. Anything else I should know before I let you go?"
        _append_conversation(session_state, "Assistant", anything_else)
        audio = await _tts(anything_else)
        await broadcast(_make_state(
            "intake",
            transcript=full_transcript,
            turn_transcript=transcript_new,
            schema=schema,
            audio_b64=_b64(audio),
            follow_up=anything_else,
            **_dashboard_context(session_state),
        ))
        return False

    # Final response — answer briefly and close the call in the same turn
    name = schema.get("name") or "there"
    if _looks_like_status_question(transcript_new):
        goodbye = (
            f"Thanks, {name}. We're checking that now and we'll update you shortly. Take care."
        )
    else:
        goodbye = (
            f"Thanks, {name}. We'll take it from here and update you shortly. Take care."
        )
    _append_conversation(session_state, "Assistant", goodbye)
    audio = await _tts(goodbye)
    await broadcast(_make_state(
        "call_ended",
        transcript=full_transcript,
        schema=schema,
        audio_b64=_b64(audio),
        message=goodbye,
        **_dashboard_context(session_state),
    ))
    return True  # Phase 1 done — caller off the line, start Phase 2


# ---------------------------------------------------------------------------
# Phase 2 — Post-call pipeline (client off the line, dashboard watching)
# ---------------------------------------------------------------------------

async def run_post_call_pipeline(
    broadcast: BroadcastFn,
    session_state: dict,
    get_escalation_future: Callable[[], asyncio.Future],
) -> None:
    """
    Runs immediately after Phase 1 completes.
    Client is NOT on the line. Escalation gate holds the SMS notification, not the call.
    Human agent approves/declines via POST /escalation/resolve.
    """
    schema = session_state["schema"]
    full_transcript = session_state["transcript"]

    # Damage assessment
    await broadcast(_make_state("damage_assessment", transcript=full_transcript, schema=schema, **_dashboard_context(session_state)))
    damage_info = await damage.assess_damage(full_transcript, schema)
    await broadcast(_make_state("damage_assessment", transcript=full_transcript, schema=schema, damage_info=damage_info, **_dashboard_context(session_state)))

    # RAG retrieval
    await broadcast(_make_state("rag", transcript=full_transcript, schema=schema, damage_info=damage_info, **_dashboard_context(session_state)))
    query_str = (
        f"claim type: {schema.get('issue_type')} "
        f"severity: {damage_info.get('severity')} "
        f"vehicle: {schema.get('vehicle')} "
        f"incident: {full_transcript[:200]}"
    )
    chunks = rag.query(query_str)
    await broadcast(_make_state("rag", transcript=full_transcript, schema=schema, damage_info=damage_info, chunks=chunks, **_dashboard_context(session_state)))

    # Coverage reasoning
    await broadcast(_make_state("coverage", transcript=full_transcript, schema=schema, damage_info=damage_info, chunks=chunks, **_dashboard_context(session_state)))
    cov_text = _strip_fences(await _call(COVERAGE_PROMPT.format(
        schema=json.dumps(schema, indent=2),
        damage=json.dumps(damage_info, indent=2),
        chunks="\n\n---\n\n".join(chunks),
    )))
    try:
        coverage = json.loads(cov_text)
    except json.JSONDecodeError:
        coverage = {"covered": False, "confidence": 0.5, "reasoning": "Unable to determine coverage.", "escalate": True}

    coverage.setdefault("escalate", coverage.get("confidence", 1.0) < 0.7)
    intake_review = extraction.review_intake(schema, full_transcript)
    if not intake_review["ready"]:
        coverage = {
            "covered": False,
            "confidence": 0.0,
            "reasoning": (
                "Automatic coverage review was paused because the call did not capture enough reliable detail. "
                f"Still needed: {intake_review['next_reason'].lower()}"
            ),
            "escalate": True,
        }
    elif damage_info.get("ambiguous"):
        coverage["escalate"] = True
        coverage["confidence"] = min(coverage.get("confidence", 1.0), 0.69)
        coverage["reasoning"] = (
            f"{coverage.get('reasoning', '').strip()} Damage assessment was ambiguous, so it needs human review."
        ).strip()
    session_state["intake_review"] = intake_review
    await broadcast(_make_state("coverage", transcript=full_transcript, schema=schema, damage_info=damage_info, chunks=chunks, coverage=coverage, **_dashboard_context(session_state)))

    # Escalation gate — holds SMS notification until human resolves via POST /escalation/resolve
    if coverage.get("escalate"):
        await broadcast(_make_state(
            "escalation",
            transcript=full_transcript,
            schema=schema,
            damage_info=damage_info,
            chunks=chunks,
            coverage=coverage,
            **_dashboard_context(session_state),
        ))
        future = get_escalation_future()
        resolution = await future  # Resolved by POST /escalation/resolve

        coverage["covered"] = (
            resolution.override == "covered" if resolution.override else resolution.approved
        )
        coverage["escalate"] = False
        coverage["confidence"] = 1.0
        coverage["reasoning"] += " [Reviewed and confirmed by human agent.]"

    # Decision engine (deterministic)
    await broadcast(_make_state("decision", transcript=full_transcript, schema=schema, damage_info=damage_info, chunks=chunks, coverage=coverage, **_dashboard_context(session_state)))
    action = {
        "type": None,
        "garage": None,
        "eta_minutes": None,
        "taxi": None,
        "rental": None,
    }
    action_summary = "No assistance dispatched because the claim is not covered."

    if coverage.get("covered"):
        action_type = decision.get_action(
            schema.get("issue_type", "other"),
            transcript=full_transcript,
            damage_severity=damage_info.get("severity"),
        )
        garage = decision.get_nearest_garage(schema.get("location", ""), action_type)
        taxi = decision.get_taxi(schema.get("location", ""))
        rental = decision.get_rental(damage_info.get("severity", "minor"), schema.get("location", ""))

        action = {
            "type": action_type,
            "garage": garage,
            "eta_minutes": garage["eta_minutes"],
            "taxi": taxi,
            "rental": rental,
        }
        action_summary = f"Help confirmed: {action_type} from {garage['name']}, ETA {garage['eta_minutes']} min"

    # Build SMS text (simulated — no real SMS gateway)
    name = schema.get("name") or "Customer"
    if coverage.get("covered"):
        garage = action["garage"]
        taxi = action["taxi"]
        rental = action["rental"]
        action_type = action["type"]
        vehicle_action = "Tow truck" if action_type == "tow_truck" else "Repair truck"
        sms_text = (
            f"ClaimBuddy: Hi {name}, roadside assistance is confirmed. "
            f"{vehicle_action} from {garage['name']} — ETA {garage['eta_minutes']} min. "
            f"Taxi arranged ({taxi['name']}) — ETA {taxi['eta_minutes']} min."
        )
        if rental:
            sms_text += f" Rental car at {rental['name']}."
    else:
        sms_text = (
            f"ClaimBuddy: Hi {name}, this incident is not covered under your policy. "
            "A claims handler will contact you within 2 hours."
        )

    # Call summary for the agent dashboard
    try:
        summary = await _call(SUMMARY_PROMPT.format(
            schema=json.dumps(schema, indent=2),
            damage=json.dumps(damage_info, indent=2),
            coverage=json.dumps({k: v for k, v in coverage.items() if k != "escalate"}, indent=2),
            action=action_summary,
        ))
    except Exception:
        summary = ""

    await broadcast(_make_state(
        "complete",
        transcript=full_transcript,
        schema=schema,
        damage_info=damage_info,
        chunks=chunks,
        coverage=coverage,
        action=action,
        sms_text=sms_text,
        summary=summary,
        **_dashboard_context(session_state),
    ))

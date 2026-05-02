import json
import os
import re
from typing import Any

_client: Any | None = None

GROQ_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"


def get_client():
    global _client
    if _client is None:
        from openai import AsyncOpenAI
        _client = AsyncOpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=os.environ["GROQ_API_KEY"],
        )
    return _client


async def _call(prompt: str) -> str:
    response = await get_client().chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.6,
    )
    content = response.choices[0].message.content or ""
    # Strip Qwen3 thinking blocks regardless of /no_think
    if "</think>" in content:
        content = content.split("</think>", 1)[-1]
    return content.strip()


_JSON_OBJECT_RE = re.compile(r"\{(?:[^{}]|(?:\{[^{}]*\}))*\}", re.DOTALL)


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        # Strip the opening fence (with optional language tag) and anything after the closing fence.
        text = text.split("```", 2)[1]
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.split("```", 1)[0].strip()
    # If the model wrapped the JSON object in commentary, pull out the first {...} block.
    if not text.startswith("{"):
        match = _JSON_OBJECT_RE.search(text)
        if match:
            text = match.group(0)
    return text.strip()


SCHEMA_FIELDS = ["name", "location", "vehicle", "issue_type", "urgency"]
ISSUE_TYPES = "engine_failure, flat_tyre, accident, battery, other"
URGENCY_TYPES = "low, medium, high, critical"

EXTRACT_PROMPT = """You are the intake extractor for ClaimBuddy. Convert a free-form \
roadside-assistance call transcript into a tight, machine-readable claim schema. Be \
conservative — only extract a value when it is clearly stated or unambiguously implied. \
A null value is better than a wrong one.

================================================================
INPUT
================================================================
Transcript so far (most recent turns at the bottom):
{transcript}

================================================================
FIELDS — extract each independently
================================================================
- name: caller's full name as they said it. First-name-only is acceptable if no surname \
        was given. NEVER invent a surname.
- location: where the vehicle currently is. Prefer the most specific form the caller \
        provided: postcode > street + city > road + junction > landmark. A vague phrase \
        like "on the highway" / "near London" / "somewhere in town" is NOT specific \
        enough — return null in that case so intake can ask again.
- vehicle: year + make + model when available. "My car" / "the van" / "a sedan" alone \
        is NOT specific enough — return null. If the caller gave make + model but no \
        year, return what they said.
- issue_type: one of [{issue_types}].
        - engine_failure: drivetrain failure, seizure, overheating, stall, oil leak
        - flat_tyre: puncture, blowout, deflation
        - accident: collision, hit-and-run, run-off-road
        - battery: discharged battery, won't crank, dashboard dark
        - other: anything else, or when transcript is too vague to choose one of above
- urgency: one of [{urgency_types}].
        - critical: occupant safety risk, on a live carriageway, fluid leak, injury
        - high: vehicle blocking traffic, time-critical (e.g. caller has hard deadline)
        - medium: vehicle off the road but inconvenient
        - low: parked, no time pressure

================================================================
EXTRACTION RULES
================================================================
- Use only what is in the transcript. Do not infer demographics, vehicle history, or \
  policy details.
- If the caller corrects an earlier statement, prefer the latest version.
- Normalise minor speech artefacts (e.g. "twenty twenty-four" → "2024") but do not add \
  detail that was not said.
- For multi-word names spelled out phonetically, reconstruct the most likely spelling \
  and use that.

================================================================
OUTPUT SCHEMA
================================================================
Return ONLY a JSON object with exactly these fields. No prose before or after. No \
markdown code fences. No explanation. The first character of your response must be `{{` \
and the last character must be `}}`.
{{
  "name": <string or null>,
  "location": <string or null>,
  "vehicle": <string or null>,
  "issue_type": <one of [{issue_types}] or null>,
  "urgency": <one of [{urgency_types}] or null>
}}

================================================================
EXAMPLE — clean extraction
================================================================
Transcript:
  Customer: Hi, I'm Olivia Bennett. I'm at 23 King's Cross Road, London N1C 4AB.
  Customer: My 2024 Ford Focus Titanium will not start, dashboard lights flicker then nothing.
  Customer: I have a meeting in two hours so it's pretty urgent.

Output:
{{"name": "Olivia Bennett", "location": "23 King's Cross Road, London N1C 4AB", \
"vehicle": "2024 Ford Focus Titanium", "issue_type": "battery", "urgency": "high"}}

================================================================
EXAMPLE — partial extraction (preserve nulls)
================================================================
Transcript:
  Customer: Something happened to my car, it just stopped working. I'm somewhere on the highway.

Output:
{{"name": null, "location": null, "vehicle": null, "issue_type": "other", "urgency": "medium"}}
"""

FOLLOWUP_PROMPT = """You are speaking out loud, in real time, to a driver who has just \
called ClaimBuddy roadside assistance. Your voice is calm, brief, and human — like a \
seasoned dispatcher, not a chatbot. The driver may be stressed; do not make them work \
harder than necessary.

================================================================
INPUTS
================================================================
What is already known about the claim:
{schema}

The single missing detail you need next:
  field: {next_field}
  why it matters: {reason}

Recent transcript (most recent turns at the bottom):
{transcript}

================================================================
WHAT TO SAY
================================================================
Produce one short spoken line. The line may have at most two parts in this order:
  1. Optional micro-acknowledgement of what the caller just said (≤ 5 words). Skip it \
     entirely if there is nothing meaningful to acknowledge.
  2. One question that gets exactly the missing field above.

================================================================
HARD RULES
================================================================
- ≤ 14 words total.
- Ask exactly ONE thing.
- Plain spoken English. No call-centre register: avoid "provide", "process your claim", \
  "current status", "outcome", "kindly", "could you please".
- No empty empathy clichés ("I'm sorry to hear that", "I understand", "of course", \
  "certainly", "no worries").
- Do not address the caller by name unless they explicitly asked you to use it.
- Do not re-ask anything in the schema that already has a non-null value.
- Vary sentence openings — do not start two consecutive turns with the same word.
- If the caller asked YOU a question, briefly bridge ("I'll come to that") before \
  asking your one question.

================================================================
EXAMPLES BY FIELD
================================================================
  name        -> "What's your full name?"
  location    -> "Got it. Where are you right now?" / "Postcode or nearest junction?"
  vehicle     -> "Which car — make and model?" / "What are you driving?"
  issue_type  -> "Tell me what's wrong with the car." / "What happened?"
  urgency     -> "How urgent is this — are you safe where you are?"

================================================================
OUTPUT
================================================================
Return ONLY the spoken line. No quotation marks, no JSON, no explanation."""

UK_POSTCODE_RE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b", re.IGNORECASE)
GENERIC_ISSUE_PHRASES = (
    "something wrong with my car",
    "something wrong with the car",
    "problem with my car",
    "problem with the car",
    "issue with my car",
    "issue with the car",
    "car trouble",
    "vehicle trouble",
)
ISSUE_KEYWORDS = {
    "accident": ("accident", "crash", "collision", "hit by", "rear ended", "rear-ended"),
    "flat_tyre": ("flat tyre", "flat tire", "puncture", "punctured", "blowout", "blown tyre", "blown tire"),
    "battery": ("battery", "dead battery", "jump start", "jump-start"),
    "engine_failure": (
        "engine",
        "overheating",
        "overheat",
        "smoke",
        "stall",
        "stalled",
        "gearbox",
        "clutch",
        "alternator",
        "fuel leak",
        "oil leak",
    ),
}
LOCATION_MARKERS = (
    "road",
    "rd",
    "street",
    "st",
    "avenue",
    "ave",
    "highway",
    "hwy",
    "route",
    "interstate",
    "junction",
    "exit",
    "mile",
    "near",
    "outside",
    "by",
    "motorway",
    "freeway",
)
ROBOTIC_FOLLOWUP_PHRASES = (
    "provide",
    "details",
    "process your claim",
    "current status",
    "outcome",
)


def _clean_value(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _normalize_schema(schema: dict) -> dict:
    normalized = {}
    for field in SCHEMA_FIELDS:
        normalized[field] = _clean_value(schema.get(field))
    return normalized


def infer_issue_type(transcript: str) -> str | None:
    transcript_lc = transcript.lower()
    for issue_type, keywords in ISSUE_KEYWORDS.items():
        if any(keyword in transcript_lc for keyword in keywords):
            return issue_type
    return None


CRITICAL_URGENCY_KEYWORDS = (
    "injured", "injury", "bleeding", "hurt", "ambulance", "unconscious",
    "fluid leak", "smoke", "fire", "smell of fuel", "fuel leak", "oil leak",
    "live carriageway", "motorway", "highway", "freeway", "fast lane",
)
HIGH_URGENCY_KEYWORDS = (
    "blocking traffic", "blocking the road", "in the road", "stranded",
    "very urgent", "really urgent", "asap", "right now", "immediately",
    "meeting", "appointment", "flight", "in two hours", "within an hour",
)
LOW_URGENCY_KEYWORDS = (
    "no rush", "whenever", "tomorrow", "next week", "parked at home",
    "parked overnight", "in the driveway", "in my garage",
)


def infer_urgency(schema: dict, transcript: str) -> str | None:
    transcript_lc = transcript.lower()
    if any(kw in transcript_lc for kw in CRITICAL_URGENCY_KEYWORDS):
        return "critical"
    issue_type = schema.get("issue_type")
    if issue_type == "accident":
        return "high"
    if any(kw in transcript_lc for kw in HIGH_URGENCY_KEYWORDS):
        return "high"
    if any(kw in transcript_lc for kw in LOW_URGENCY_KEYWORDS):
        return "low"
    if issue_type in ("engine_failure", "battery", "flat_tyre"):
        return "medium"
    return None


def _looks_like_full_name(name: str | None) -> bool:
    if not name:
        return False
    tokens = re.findall(r"[A-Za-z][A-Za-z'-]+", name)
    return len(tokens) >= 2


def _looks_like_dispatchable_location(location: str | None) -> bool:
    if not location:
        return False
    location_lc = location.lower()
    if UK_POSTCODE_RE.search(location):
        return True
    if any(marker in location_lc for marker in LOCATION_MARKERS) and any(ch.isdigit() for ch in location_lc):
        return True
    tokens = [token for token in re.split(r"[^a-z0-9]+", location_lc) if token]
    substantial = [token for token in tokens if len(token) > 1]
    if len(substantial) >= 3:
        return True
    if len(substantial) >= 2 and any(ch.isdigit() for ch in location_lc):
        return True
    if len(substantial) >= 2 and any(marker in location_lc for marker in ("near", "outside", "by")):
        return True
    return False


def _looks_like_specific_vehicle(vehicle: str | None) -> bool:
    if not vehicle:
        return False
    tokens = [token for token in re.split(r"[^a-z0-9]+", vehicle.lower()) if token]
    meaningful = [token for token in tokens if token not in {"car", "vehicle", "the"}]
    return len(meaningful) >= 2


def _has_specific_issue(schema: dict, transcript: str) -> bool:
    issue_type = schema.get("issue_type")
    if issue_type and issue_type != "other":
        return True
    if infer_issue_type(transcript) is not None:
        return True
    transcript_lc = transcript.lower()
    if any(phrase in transcript_lc for phrase in GENERIC_ISSUE_PHRASES):
        return False
    return False


def review_intake(schema: dict, transcript: str) -> dict:
    gaps: list[dict[str, str]] = []

    if not _has_specific_issue(schema, transcript):
        gaps.append({
            "field": "issue_type",
            "reason": "You still do not know exactly what is wrong with the car.",
        })
    if not _looks_like_dispatchable_location(schema.get("location")):
        gaps.append({
            "field": "location",
            "reason": "You need a clearer location before anyone can be dispatched.",
        })
    if not _looks_like_specific_vehicle(schema.get("vehicle")):
        gaps.append({
            "field": "vehicle",
            "reason": "You still need the vehicle make and model.",
        })
    if not _looks_like_full_name(schema.get("name")):
        gaps.append({
            "field": "name",
            "reason": "You only have a partial name or no name yet.",
        })

    return {
        "ready": len(gaps) == 0,
        "gaps": gaps,
        "next_field": gaps[0]["field"] if gaps else None,
        "next_reason": gaps[0]["reason"] if gaps else None,
    }


def _default_follow_up(next_field: str | None) -> str:
    fallback_map = {
        "issue_type": "What exactly is wrong with the car?",
        "location": "What's your exact location right now?",
        "vehicle": "Which car is it, make and model?",
        "name": "What's your full name?",
    }
    return fallback_map.get(next_field or "", "Tell me a bit more about what's happened.")


def _follow_up_is_usable(line: str) -> bool:
    if not line:
        return False
    if len(line.split()) > 18:
        return False
    lowered = line.lower()
    if any(phrase in lowered for phrase in ROBOTIC_FOLLOWUP_PHRASES):
        return False
    return True


async def extract_schema(transcript: str) -> tuple[dict, str | None]:
    text = _strip_fences(await _call(EXTRACT_PROMPT.format(
        transcript=transcript,
        issue_types=ISSUE_TYPES,
        urgency_types=URGENCY_TYPES,
    )))

    try:
        schema = json.loads(text)
    except json.JSONDecodeError:
        schema = {f: None for f in SCHEMA_FIELDS}

    for f in SCHEMA_FIELDS:
        schema.setdefault(f, None)
    schema = _normalize_schema(schema)
    if schema.get("issue_type") in (None, "other"):
        inferred_issue_type = infer_issue_type(transcript)
        if inferred_issue_type:
            schema["issue_type"] = inferred_issue_type

    if not schema.get("urgency"):
        inferred_urgency = infer_urgency(schema, transcript)
        if inferred_urgency:
            schema["urgency"] = inferred_urgency

    intake_review = review_intake(schema, transcript)
    if intake_review["ready"]:
        return schema, None

    follow_up = await _call(FOLLOWUP_PROMPT.format(
        schema=json.dumps(schema, indent=2),
        next_field=intake_review["next_field"],
        reason=intake_review["next_reason"],
        transcript=transcript,
    ))
    line = follow_up.strip()
    if not _follow_up_is_usable(line):
        line = _default_follow_up(intake_review["next_field"])
    return schema, line

"""Seed dashboard with 3 deterministic demo claims — one per outcome:

  1. APPROVED  — clean covered case (battery dead, well-formed claim)
  2. REJECTED  — clear policy exclusion (cosmetic damage)
  3. ESCALATED — uninsured third-party hit-and-run (low confidence)

Use as a fallback / setup helper if a live voice run fails to demo all three
paths. The rows are inserted directly into claims.db and will appear on the
agent dashboard immediately (no LLM cost).

Run from repo root:
    python -m scripts.seed_demo
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import db


SCENARIOS: list[dict] = [
    {
        "label": "APPROVED — Battery dead, dispatch tow",
        "state": {
            "schema": {
                "name": "Olivia Bennett",
                "location": "23 King's Cross Road, London N1C 4AB",
                "vehicle": "2024 Ford Focus Titanium",
                "issue_type": "battery",
                "urgency": "high",
            },
            "transcript": (
                "Olivia Bennett at 23 King's Cross Road, London N1C 4AB. My 2024 "
                "Ford Focus Titanium will not start at all. Dashboard lights "
                "flicker then nothing — the battery seems completely dead. I "
                "have an important meeting in two hours."
            ),
            "conversation_transcript": (
                "Customer: Hi, I'm Olivia Bennett. I'm at 23 King's Cross Road, "
                "London N1C 4AB. My 2024 Ford Focus Titanium will not start.\n"
                "Assistant: I'm sorry to hear that. What happens when you turn the key?\n"
                "Customer: Dashboard lights flicker then nothing. Battery looks dead. "
                "I have a meeting in two hours.\n"
                "Assistant: Thanks Olivia, I have everything I need. We'll take it from here."
            ),
            "damage": {
                "type": "battery",
                "severity": "moderate",
                "ambiguous": False,
                "reason": (
                    "Caller explicitly described 'dashboard lights flicker then nothing' which is "
                    "the textbook symptom of a fully discharged or faulty battery. Severity is "
                    "moderate because the vehicle is immobile but undamaged."
                ),
            },
            "coverage": {
                "covered": True,
                "confidence": 0.93,
                "reasoning": (
                    "Battery failure is explicitly covered under SECTION 2.4 (Battery and Electrical "
                    "Failure Coverage). Vehicle is listed on the policy schedule (no exclusions "
                    "apply). High confidence — symptoms match policy verbatim."
                ),
                "escalate": False,
            },
            "action": {
                "type": "tow_truck",
                "garage": {"name": "City Tow Services", "eta_minutes": 12},
                "taxi": {"name": "CityRide London", "eta_minutes": 8, "pickup": "King's Cross Road"},
                "rental": None,
            },
            "policy_chunks": [
                "SECTION 2.4 Battery and Electrical Failure Coverage. Coverage applies when the "
                "vehicle battery is fully discharged, faulty, or when an electrical fault prevents "
                "engine start. ClaimBuddy dispatches a repair technician to attempt a jump-start "
                "or battery replacement at the roadside.",
            ],
            "summary": (
                "Olivia Bennett reported a dead battery on her 2024 Ford Focus at King's Cross. "
                "Issue is covered under SECTION 2.4. Tow truck dispatched (ETA 12 min) and taxi "
                "arranged (ETA 8 min) so she can make her meeting."
            ),
            "sms_text": (
                "ClaimBuddy: Hi Olivia Bennett, roadside assistance is confirmed. Tow truck from "
                "City Tow Services — ETA 12 min. Taxi arranged (CityRide London) — ETA 8 min."
            ),
            "stage": "complete",
        },
    },
    {
        "label": "REJECTED — Cosmetic damage exclusion",
        "state": {
            "schema": {
                "name": "Daniel Hughes",
                "location": "14 Sloane Avenue, London SW3 3JD",
                "vehicle": "2022 Tesla Model 3 Long Range",
                "issue_type": "other",
                "urgency": "low",
            },
            "transcript": (
                "Daniel Hughes calling. I'm at 14 Sloane Avenue, London SW3 3JD with my 2022 "
                "Tesla Model 3 Long Range. Someone scratched the paint on the driver's door "
                "while it was parked overnight. The car drives totally fine — I just want it "
                "fixed."
            ),
            "conversation_transcript": (
                "Customer: Daniel Hughes, 14 Sloane Avenue, SW3 3JD. My 2022 Tesla Model 3 "
                "Long Range got scratched overnight.\n"
                "Assistant: Sorry to hear that. Is the car drivable?\n"
                "Customer: Yes, totally fine to drive. Just a scratch on the driver's door I "
                "want repaired.\n"
                "Assistant: Thanks Daniel, I'll get this assessed and get back to you."
            ),
            "damage": {
                "type": "other",
                "severity": "minor",
                "ambiguous": False,
                "reason": (
                    "Caller described 'scratched the paint' on a parked vehicle that 'drives totally "
                    "fine'. This is purely cosmetic with no impact on safe operation."
                ),
            },
            "coverage": {
                "covered": False,
                "confidence": 0.91,
                "reasoning": (
                    "Claim falls squarely under SECTION 3.1 (Cosmetic Damage exclusion). 'Scratches, "
                    "dents, paint chips, or any damage that is purely cosmetic and does not affect "
                    "the safe operation of the vehicle are not covered.' Caller confirmed the "
                    "vehicle drives fine. High confidence — direct policy match."
                ),
                "escalate": False,
            },
            "action": {"type": None, "garage": None, "eta_minutes": None, "taxi": None, "rental": None},
            "policy_chunks": [
                "SECTION 3.1 Cosmetic Damage. Scratches, dents, paint chips, or any damage that is "
                "purely cosmetic and does not affect the safe operation of the vehicle are not "
                "covered. Cosmetic damage claims will be declined at the assessment stage.",
            ],
            "summary": (
                "Daniel Hughes reported a paint scratch on his parked 2022 Tesla Model 3. "
                "Vehicle is fully drivable. Claim declined under SECTION 3.1 (cosmetic damage "
                "exclusion)."
            ),
            "sms_text": (
                "ClaimBuddy: Hi Daniel, this incident is not covered under your policy "
                "(cosmetic damage exclusion). A claims handler will contact you within 2 hours."
            ),
            "stage": "complete",
        },
    },
    {
        "label": "ESCALATED — Uninsured third-party hit-and-run",
        "state": {
            "schema": {
                "name": "Aisha Khan",
                "location": "Junction 4, North Circular Road A406",
                "vehicle": "2023 Volkswagen Golf GTI",
                "issue_type": "accident",
                "urgency": "critical",
            },
            "transcript": (
                "Aisha Khan, Junction 4 on the North Circular A406 in a 2023 VW Golf GTI. "
                "I was rear-ended hard by a van that drove off without stopping. No plate "
                "captured, no witnesses I can see, no police report yet. Bumper is hanging "
                "off and there's a fluid leak underneath. I might have been in the wrong lane "
                "but I'm not sure."
            ),
            "conversation_transcript": (
                "Customer: This is Aisha Khan. I'm at Junction 4 of the North Circular A406 in a "
                "2023 Volkswagen Golf GTI. A van rear-ended me and drove off.\n"
                "Assistant: Are you injured?\n"
                "Customer: No, I'm shaken but okay. Bumper is hanging off, fluid leaking underneath. "
                "I didn't get the plate. No witnesses. I'm not even sure I was in the right lane.\n"
                "Assistant: Thanks Aisha, I have the details. We'll review and update you shortly."
            ),
            "damage": {
                "type": "accident",
                "severity": "severe",
                "ambiguous": True,
                "reason": (
                    "Description includes a rear-end impact (clearly accident damage) with severe "
                    "indicators (fluid leak, bumper detached). Marked ambiguous because the caller "
                    "is uncertain about her own lane positioning, which materially affects liability."
                ),
            },
            "coverage": {
                "covered": None,
                "confidence": 0.42,
                "reasoning": (
                    "SECTION 2.3 (Accident Damage) covers a road traffic accident that renders the "
                    "vehicle unsafe to drive — fluid leak and detached bumper meet that bar. However "
                    "the caller is uncertain about her own lane position, the third party left the "
                    "scene with no plate captured, and no police reference number is available — all "
                    "three usually required by SECTION 2.3 for accident coverage. Confidence is below "
                    "the 70% threshold so a senior handler must review per SECTION 5."
                ),
                "escalate": True,
            },
            "action": {"type": None, "garage": None, "eta_minutes": None, "taxi": None, "rental": None},
            "policy_chunks": [
                "SECTION 2.3 Accident Damage. Coverage applies following a road traffic accident "
                "that has rendered the insured vehicle immobile or unsafe to drive. ClaimBuddy will "
                "arrange towing from the incident scene to the nearest authorised bodywork or "
                "mechanical repair facility. Accident coverage requires the policyholder to provide "
                "a valid incident reference number where applicable.",
                "SECTION 5 Service Standards. In cases where coverage confidence is below the "
                "required threshold, a senior claims handler will be consulted before any service "
                "is dispatched.",
            ],
            "summary": (
                "Aisha Khan reported a rear-end hit-and-run on the A406 in a 2023 VW Golf GTI. "
                "Damage is severe (fluid leak, detached bumper). Liability is unclear and no "
                "police report is available — coverage held for human review."
            ),
            "stage": "escalation",
        },
    },
]


def seed() -> None:
    db.init_db()
    for scenario in SCENARIOS:
        claim_id = str(uuid.uuid4())
        print(f"  {scenario['label']} → {claim_id}")
        db.create_stub(claim_id)
        db.save(claim_id, scenario["state"])


if __name__ == "__main__":
    print("Seeding 3 demo claims (covered / not covered / escalated)…")
    seed()
    print("Done. Open the dashboard to see them.")

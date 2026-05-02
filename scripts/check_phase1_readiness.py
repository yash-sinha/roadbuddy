"""For each demo transcript, check if Phase 1 (voice intake) would consider
the schema 'ready' for Phase 2.

If ready=False, the live bot will keep asking follow-ups and never reach the
post-call pipeline — so no escalation can fire.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from backend import extraction


SCENARIOS = [
    (
        "Sam — vague",
        "Customer: Hi this is Sam. Something happened to my car and I'm not "
        "sure what's wrong. I'm somewhere on the highway. Can you help?\n"
        "Assistant: Tell me more about the issue.\n"
        "Customer: I don't know, it just stopped working.",
    ),
    (
        "Priya — grinding noise + thump",
        "Customer: This is Priya Shah at Junction 12 on the M25 in a 2021 "
        "Toyota Corolla. The car made a strange grinding noise then a thump, "
        "now it pulls hard to the left. I'm not sure if something broke or "
        "if I hit something.\n"
        "Assistant: Are you safe?\n"
        "Customer: Yes I'm pulled over.",
    ),
    (
        "Marcus — uninsured hit-and-run",
        "Customer: My name is Marcus Lee. I'm in the underground car park at "
        "Westfield Stratford in a 2019 Audi A3. Another driver scraped my "
        "bumper and drove off. There's no police report yet and the other "
        "driver was uninsured as far as I know. The car can still drive but "
        "the bumper is hanging off.",
    ),
    (
        "James (seed) — uninsured collision",
        "I was hit by a driver who has no insurance. My car is badly damaged "
        "and I'm near the DLR station in Canary Wharf. The other driver has "
        "left the scene. My name is James Okafor and the car is a 2021 BMW "
        "3 Series.",
    ),
]


async def main() -> None:
    for label, transcript in SCENARIOS:
        schema, follow_up = await extraction.extract_schema(transcript)
        review = extraction.review_intake(schema, transcript)
        print("=" * 70)
        print(f"Scenario: {label}")
        print(f"  schema: {schema}")
        print(f"  ready_for_phase2: {review['ready']}")
        if not review["ready"]:
            print(f"  next_gap: field={review.get('next_field')} reason={review.get('next_reason')}")
        print(f"  follow_up_text: {follow_up!r}")


if __name__ == "__main__":
    asyncio.run(main())

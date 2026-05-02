"""Seed dashboard with escalated sample claims by running the real Phase 2 pipeline.

Run from repo root:
    python -m scripts.seed_escalations

For each scenario, the script:
- builds a synthetic session_state (no live call / no audio)
- runs `run_post_call_pipeline`
- supplies an unresolved escalation future, then cancels the task once the
  pipeline parks at the escalation gate, so the row stays visible on the
  dashboard for human review.
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from backend import agent as agent_module, db, rag


SCENARIOS: list[dict] = [
    {
        "label": "intake_incomplete",
        "schema": {
            "name": "Sam",
            "location": "somewhere on the highway",
            "vehicle": "my car",
            "issue_type": "other",
            "urgency": "medium",
        },
        "transcript": (
            "Customer: Hi this is Sam. Something happened to my car and I'm not "
            "sure what's wrong. I'm somewhere on the highway. Can you help?\n"
            "Assistant: Tell me more about the issue.\n"
            "Customer: I don't know, it just stopped working."
        ),
    },
    {
        "label": "ambiguous_damage",
        "schema": {
            "name": "Priya Shah",
            "location": "Junction 12, M25",
            "vehicle": "2021 Toyota Corolla",
            "issue_type": "other",
            "urgency": "high",
        },
        "transcript": (
            "Customer: This is Priya Shah at Junction 12 on the M25 in a 2021 "
            "Toyota Corolla. The car made a strange grinding noise then a thump, "
            "now it pulls hard to the left. I'm not sure if something broke or "
            "if I hit something.\n"
            "Assistant: Are you safe?\n"
            "Customer: Yes I'm pulled over."
        ),
    },
    {
        "label": "low_confidence_coverage",
        "schema": {
            "name": "Marcus Lee",
            "location": "Underground car park, Westfield Stratford",
            "vehicle": "2019 Audi A3",
            "issue_type": "accident",
            "urgency": "medium",
        },
        "transcript": (
            "Customer: My name is Marcus Lee. I'm in the underground car park at "
            "Westfield Stratford in a 2019 Audi A3. Another driver scraped my "
            "bumper and drove off. There's no police report yet and the other "
            "driver was uninsured as far as I know. The car can still drive but "
            "the bumper is hanging off."
        ),
    },
]


def _build_session_state(scenario: dict) -> dict:
    return {
        "claim_id": str(uuid.uuid4()),
        "schema": scenario["schema"],
        "transcript": scenario["transcript"],
        "conversation_transcript": scenario["transcript"],
    }


def _persist_broadcast_factory(claim_id: str, escalation_seen: asyncio.Event):
    """Mimic main.broadcast: persist any message that has a stage."""

    async def _broadcast(message: dict, *, persist: bool = True) -> None:
        message = {**message, "claim_id": claim_id}
        stage = message.get("stage")
        print(f"[{claim_id[:8]}] stage={stage}")
        if stage and persist:
            try:
                db.save(claim_id, message)
            except Exception as e:
                print(f"[db save error] {e}")
        if stage == "escalation":
            escalation_seen.set()

    return _broadcast


async def _run_scenario(scenario: dict, gate_timeout: float = 120.0) -> None:
    state = _build_session_state(scenario)
    claim_id = state["claim_id"]
    label = scenario["label"]
    print(f"\n=== Scenario: {label} → claim {claim_id} ===")

    db.create_stub(claim_id)

    escalation_future: asyncio.Future = asyncio.get_running_loop().create_future()
    escalation_seen = asyncio.Event()

    def _get_future() -> asyncio.Future:
        return escalation_future

    broadcast = _persist_broadcast_factory(claim_id, escalation_seen)
    pipeline_task = asyncio.create_task(
        agent_module.run_post_call_pipeline(broadcast, state, _get_future)
    )

    try:
        # Wait for pipeline to either reach escalation or finish on its own.
        done, _ = await asyncio.wait(
            [pipeline_task, asyncio.create_task(escalation_seen.wait())],
            timeout=gate_timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if escalation_seen.is_set():
            print(f"[{claim_id[:8]}] parked at escalation gate ✓")
        elif pipeline_task in done:
            print(f"[{claim_id[:8]}] pipeline finished without escalation")
        else:
            print(f"[{claim_id[:8]}] timed out before reaching escalation")
    finally:
        if not pipeline_task.done():
            pipeline_task.cancel()
            try:
                await pipeline_task
            except asyncio.CancelledError:
                pass


async def main() -> None:
    rag.init()
    db.init_db()
    for scenario in SCENARIOS:
        await _run_scenario(scenario)


if __name__ == "__main__":
    asyncio.run(main())

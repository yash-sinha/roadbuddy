# ClaimBuddy — Roadside Assistance Co-Pilot

An AI-powered prototype that takes a customer's roadside assistance call end to end:
voice intake → policy coverage check → next-best-action → human handoff when uncertain.

Built as a take-home for the Insurance Co-Pilot case study. The system replaces the
human dispatcher's manual workflow (data gathering, coverage lookup, action selection,
client update) with an AI pipeline that hands control back to a human only when
confidence is low.

---

## What you get

- **Customer voice flow** — a browser page where a caller describes their incident, the
  AI agent asks clarifying questions, and they receive a final outcome.
- **Coverage decision** — retrieved policy clauses + LLM reasoning produce a covered /
  not-covered verdict with a calibrated confidence score.
- **Dispatch** — for covered claims, the system picks a tow or repair truck, a taxi, and
  a rental car (mocked).
- **Human agent dashboard** — observability over every claim: live transcript,
  extracted fields, damage assessment with reasoning, retrieved policy chunks, coverage
  reasoning, and Approve / Reject controls (with notes) for escalations.
- **Customer history** — previous claims, click-through detail page, callback flow that
  starts a new call seeded with prior context.

---

## Architecture

```
Phase 1 — Voice intake (caller on the line)
  Mic → Deepgram STT → LLM extraction → follow-up TTS loop
  Repeats until required fields are captured → goodbye TTS → call_ended

Phase 2 — Post-call pipeline (caller off the line)
  Damage assessment (LLM)
    → Policy retrieval (Chroma + sentence-transformers)
    → Coverage decision (LLM, calibrated confidence)
    → Escalation gate (if confidence < 0.7 → human review)
    → Action selection (deterministic rules)
    → Customer notification (simulated SMS)
```

The escalation gate pauses the customer notification, not the call. While it waits, the
internal dashboard shows the case so a human handler can resolve it via Approve / Reject
with optional notes.

### Stack

| Layer       | Technology                                                  |
|-------------|-------------------------------------------------------------|
| Backend     | FastAPI + WebSockets                                        |
| STT         | Deepgram (`nova-2`)                                         |
| LLM         | Groq (OpenAI-compatible API)                                |
| TTS         | Cartesia                                                    |
| RAG         | ChromaDB + `sentence-transformers/all-MiniLM-L6-v2`         |
| Persistence | SQLite (`claims.db`) + Chroma vector cache (`chroma_db/`)   |
| Frontend    | Next.js 16 + React 19 + Tailwind 4                          |

### Intake schema

```json
{
  "name":       "",
  "location":   "",
  "vehicle":    "",
  "issue_type": "engine_failure | flat_tyre | accident | battery | other",
  "urgency":    "low | medium | high | critical"
}
```

---

## Prerequisites

- Python 3.10+ (3.11+ preferred)
- Node.js 18+ and `pnpm`
- [`uv`](https://docs.astral.sh/uv/) (optional but recommended)
- API keys: `DEEPGRAM_API_KEY`, `GROQ_API_KEY`, `CARTESIA_API_KEY`

## Setup

```bash
# 1. Configure secrets
cp .env.example .env
# edit .env and fill in your keys

# 2. Install backend dependencies
uv venv
source venv/bin/activate
uv pip install -r requirements.lock

# 3. Install frontend dependencies
cd client
pnpm install
cd ..
```

The backend creates `policy.txt` and rebuilds the `chroma_db/` vector index on first
boot, so you do not need to seed anything manually.

## Run

Two terminals from the repo root:

**Terminal 1 — backend**
```bash
source venv/bin/activate
uvicorn backend.main:app --reload --port 8000
```

**Terminal 2 — frontend**
```bash
cd client
pnpm dev
```

The frontend reads `NEXT_PUBLIC_API_BASE` and `NEXT_PUBLIC_WS_URL` from
`client/.env.local` (defaults to `localhost:8000`). If you run the backend on a different
port, create that file and override.

### Routes

| URL                                   | Purpose                                |
|---------------------------------------|----------------------------------------|
| `http://localhost:3000/call`          | customer claim flow                    |
| `http://localhost:3000/`              | human agent observation dashboard      |
| `http://localhost:3000/claims`        | customer claim history                 |
| `http://localhost:3000/claims/{id}`   | customer claim detail + callback entry |

---

## Demo

Open `/call` and `/` side by side. Speak each script aloud at `/call` while watching `/`
for the agent's reasoning, confidence score, and decision.

### 1. Approved — covered claim, dispatch confirmed
> "Hi, I'm Olivia Bennett. I'm at 23 King's Cross Road, London N1C 4AB. My 2024 Ford
> Focus Titanium will not start. The dashboard lights flicker then nothing — I think the
> battery is dead. I have a meeting in two hours."

Expected: damage = battery / moderate / not ambiguous. Coverage covered=true,
confidence ≈ 0.9 (SECTION 2.4 match). Tow truck and taxi dispatched.

### 2. Rejected — clear policy exclusion
> "Daniel Hughes calling from 14 Sloane Avenue, London SW3 3JD. My 2022 Tesla Model 3
> Long Range was parked overnight and someone scratched the paint on the driver's door.
> The car drives totally fine — I just want it fixed."

Expected: damage = other / minor / not ambiguous. Coverage covered=false,
confidence ≈ 0.9 (SECTION 3.1 cosmetic damage exclusion). No dispatch.

### 3. Escalated — uncertain liability needs human review
> "Aisha Khan, Junction 4 on the North Circular A406 in a 2023 VW Golf GTI. A van
> rear-ended me hard and drove off without stopping. I didn't get the plate, no
> witnesses, no police report yet. The bumper is hanging off and there's a fluid leak. I
> might have been in the wrong lane but I'm not sure."

Expected: damage = accident / severe / ambiguous. Coverage confidence < 0.7. Pipeline
pauses at the escalation gate; the dashboard shows Approve / Reject with a notes field.

### Fallback: pre-cooked demo rows

If a live voice run flakes, populate the dashboard with deterministic rows that hit each
path:

```bash
source venv/bin/activate
python -m scripts.seed_demo
```

---

## How escalation works

The post-call pipeline forces `coverage.escalate = true` when **any** of:

1. The coverage LLM returns `confidence < 0.7`.
2. The coverage LLM output cannot be parsed as JSON.
3. `extraction.review_intake` flags missing or low-quality required fields (specific
   issue, dispatchable location, specific vehicle, full name).
4. The damage classifier returns `ambiguous = true`.

When escalated, Phase 2 parks at the `escalation` stage and waits for a human resolution
via `POST /escalation/resolve`. The dashboard surfaces the Approve / Reject buttons plus
a notes textarea; the override + notes are persisted to the audit trail in the claim's
`reasoning` field.

For historical / seeded escalations (no live future to await), the same endpoint accepts
a `claim_id` and applies the resolution directly to the persisted row.

---

## Stale claim sweep

Customers sometimes hang up mid-intake. A background task in the FastAPI lifespan runs
every `STALE_CLAIM_SWEEP_INTERVAL_SEC` seconds (default 60). It marks any `active` claim
older than `STALE_CLAIM_TIMEOUT_MIN` minutes (default 5) as `cancelled`, skipping the
in-flight session id. The dashboard renders these as a separate "Cancelled" state.

Agents can also archive a stuck or unwanted claim manually from the dashboard
(Archive button on the claim detail panel) which moves it into the "Archived" queue.

---

## API

### HTTP endpoints

| Method | Path                                | Description                              |
|--------|-------------------------------------|------------------------------------------|
| GET    | `/health`                           | health check                             |
| GET    | `/claims`                           | list persisted claims                    |
| GET    | `/claims/recent-customer`           | most recent caller name                  |
| GET    | `/claims/{claim_id}`                | fetch a single claim                    |
| POST   | `/claims/{claim_id}/archive`        | mark a claim as archived                 |
| POST   | `/escalation/resolve`               | resolve a low-confidence escalation      |
| POST   | `/policy/upload`                    | replace policy text and rebuild RAG      |
| GET    | `/policy`                           | fetch current policy text                |

#### `POST /escalation/resolve`

```json
{
  "approved": true,
  "override": "covered",
  "claim_id": "uuid",
  "notes":    "optional reviewer notes appended to audit trail"
}
```

`override` may be `"covered"` or `"not_covered"`. `claim_id` is required when no live
pipeline is currently waiting on the escalation gate (e.g. resolving a historical row
from the dashboard).

### WebSocket — `/ws`

Client → server:

```json
{ "type": "start_session" }
{ "type": "start_session", "callback_claim_id": "seed-001" }
{ "type": "subscribe_claim", "claim_id": "uuid" }
{ "type": "stop_recording" }
{ "type": "proactive_check" }
```

Binary frames are raw `webm/opus` audio chunks.

Server → client (representative shape):

```json
{
  "claim_id": "uuid",
  "stage": "intake | call_ended | damage_assessment | rag | coverage | escalation | decision | complete | cancelled | archived",
  "transcript": "...",
  "schema": { "name": "", "location": "", "vehicle": "", "issue_type": "", "urgency": "" },
  "damage": { "type": "", "severity": "", "ambiguous": false, "reason": "" },
  "coverage": { "covered": null, "confidence": null, "reasoning": "", "escalate": false },
  "action": { "type": "", "garage": {}, "eta_minutes": null, "taxi": {}, "rental": null },
  "policy_chunks": ["..."],
  "audio": "<base64 wav or null>",
  "sms_text": "ClaimBuddy: ..."
}
```

---

## Tests

```bash
source venv/bin/activate
python -m pytest backend/tests -q
```

Coverage includes intake extraction, damage assessment, decision routing, the two-phase
pipeline, the no-downgrade schema merge, the follow-up retry cap, urgency inference,
the stale-claim sweep, the archive endpoint, and the escalation resolve endpoint
(both live and historical modes).

---

## Project layout

```
backend/
  main.py            FastAPI app, WebSocket, lifespan + sweep loop
  agent.py           Phase 1 voice intake + Phase 2 post-call pipeline
  extraction.py      Schema extraction prompt + intake review gates
  damage.py          Damage classification prompt
  decision.py        Action selection + mock dispatch (taxi / rental / garage)
  rag.py             Chroma index init + retrieval
  db.py              SQLite persistence + sweep + archive helpers
  synthetic_data.py  Mock policy text + garages + postcode lookup
  tests/             pytest suite

client/
  app/
    page.tsx              Agent observation dashboard
    call/page.tsx         Customer voice call UI
    claims/page.tsx       Customer claim history
    claims/[id]/page.tsx  Customer claim detail
  components/
    agent-card.tsx        Queue card on the dashboard
    agent-detail.tsx      Right pane (reasoning + Approve / Reject + Archive)
    header.tsx            Top bar
  lib/
    api.ts                NEXT_PUBLIC_API_BASE + WS_URL helpers

scripts/
  seed_demo.py             Deterministic 3-row demo fixture
  seed_escalations.py      Live pipeline runs that park at escalation
  check_phase1_readiness.py  Probe whether transcripts pass intake gating
```

---

## Notes for reviewers

- The customer-facing pages intentionally hide internal reasoning, policy section
  references, and confidence scores — that detail is restricted to the agent dashboard.
- Coverage prompts use a calibrated confidence rubric (0.9+ direct match, 0.7–0.89 minor
  gap, 0.4–0.69 mixed signals, < 0.4 insufficient evidence) plus an explicit list of
  signals that must NOT trigger escalation (missing incident reference, hit-and-run on
  its own, missing policy number) so the system does not over-escalate routine claims.
- The dispatch picker (taxi / rental) is intentionally a stable hash-of-location mock —
  not real geo — to keep the demo deterministic and small.
- The single-process `_escalation_future` is a known prototype constraint; production
  would key futures by claim id (the `/escalation/resolve` historical mode is already
  per-claim).

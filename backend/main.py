import asyncio
import json
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from . import rag, agent as agent_module, db

connected_clients: dict[WebSocket, dict[str, str | None]] = {}
_session_state: dict = {}
_escalation_future: asyncio.Future | None = None


def _decorate_message(message: dict) -> dict:
    enriched = {"event_time": datetime.utcnow().isoformat(), **message}
    claim_id = enriched.get("claim_id") or _session_state.get("claim_id")
    if claim_id:
        enriched = {**enriched, "claim_id": claim_id}
    return enriched


def _should_send_to_client(client_info: dict[str, str | None], claim_id: str | None) -> bool:
    role = client_info.get("role")
    if role in {"dashboard", "claims_list"}:
        return True
    if role in {"call", "claim"}:
        return bool(claim_id and client_info.get("claim_id") == claim_id)
    return False


async def _send_to_clients(message: dict) -> None:
    data = json.dumps(message)
    disconnected: list[WebSocket] = []
    claim_id = message.get("claim_id")
    for ws, client_info in list(connected_clients.items()):
        if not _should_send_to_client(client_info, claim_id):
            continue
        try:
            await ws.send_text(data)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        connected_clients.pop(ws, None)


async def broadcast(message: dict, *, persist: bool = True) -> None:
    message = _decorate_message(message)
    claim_id = message.get("claim_id")
    if claim_id and persist and message.get("stage"):
        try:
            db.save(claim_id, {**_session_state, **message})
        except Exception as e:
            print(f"[db save error] {e}")
    await _send_to_clients(message)


def _create_escalation_future() -> asyncio.Future:
    global _escalation_future
    _escalation_future = asyncio.get_running_loop().create_future()
    return _escalation_future


def _task_error_handler(task: asyncio.Task) -> None:
    if not task.cancelled() and (exc := task.exception()):
        import traceback
        print(f"[pipeline error] {type(exc).__name__}: {exc}")
        traceback.print_exception(type(exc), exc, exc.__traceback__)


async def _handle_voice_turn(audio_bytes: bytes) -> None:
    global _session_state
    try:
        phase1_done = await agent_module.run_voice_turn(audio_bytes, broadcast, _session_state)
    except Exception as e:
        print(f"[phase 1 error] {type(e).__name__}: {e}")
        await broadcast({"stage": "error", "message": str(e)})
        return
    if phase1_done and not _session_state.get("phase2_started"):
        if _session_state.get("skip_phase2"):
            if _session_state.get("callback_resolved") and _session_state.get("claim_id"):
                db.delete_claim(_session_state["claim_id"])
                await _send_to_clients({
                    "claim_id": _session_state["claim_id"],
                    "remove_from_dashboard": True,
                    "callback_status_only": True,
                })
            return
        _session_state["phase2_started"] = True
        task = asyncio.create_task(
            agent_module.run_post_call_pipeline(broadcast, _session_state, _create_escalation_future)
        )
        task.add_done_callback(_task_error_handler)


STALE_CLAIM_TIMEOUT_MIN = int(os.environ.get("STALE_CLAIM_TIMEOUT_MIN", "5"))
STALE_CLAIM_SWEEP_INTERVAL_SEC = int(os.environ.get("STALE_CLAIM_SWEEP_INTERVAL_SEC", "60"))


async def _stale_claim_sweep_loop() -> None:
    while True:
        try:
            in_flight = {_session_state.get("claim_id")} - {None}
            cancelled = db.cancel_stale_active_claims(STALE_CLAIM_TIMEOUT_MIN, in_flight)
            for claim_id in cancelled:
                await _send_to_clients({
                    "claim_id": claim_id,
                    "stage": "cancelled",
                    "status": "cancelled",
                })
        except Exception as e:
            print(f"[stale sweep error] {type(e).__name__}: {e}")
        await asyncio.sleep(STALE_CLAIM_SWEEP_INTERVAL_SEC)


@asynccontextmanager
async def lifespan(app: FastAPI):
    rag.init()
    db.init_db()
    db.cleanup_transient_claims()
    db.cleanup_empty_pending_claims()
    db.cleanup_denied_claim_actions()
    db.seed()
    sweep_task = asyncio.create_task(_stale_claim_sweep_loop())
    try:
        yield
    finally:
        sweep_task.cancel()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/claims")
async def list_claims(caller_name: str | None = None):
    return db.list_claims(caller_name=caller_name)


@app.get("/claims/recent-customer")
async def latest_customer_endpoint():
    return {"caller_name": db.latest_customer_name()}


@app.get("/claims/{claim_id}")
async def get_claim_endpoint(claim_id: str):
    claim = db.get_claim(claim_id)
    if not claim:
        return JSONResponse({"error": "not found"}, status_code=404)
    return claim


class EscalationResolve(BaseModel):
    approved: bool
    override: str | None = None
    notes: str | None = None
    claim_id: str | None = None


@app.post("/escalation/resolve")
async def resolve_escalation(body: EscalationResolve):
    """Resolve an escalation. Two paths:
    1. A live pipeline is awaiting `_escalation_future` — set the result and the
       pipeline finishes the dispatch / SMS itself.
    2. No live future (e.g. resolving a historical or seeded escalation row from
       the dashboard) — apply the decision directly to the persisted claim and
       broadcast the update so the dashboard refreshes.
    """
    global _escalation_future
    if _escalation_future and not _escalation_future.done():
        _escalation_future.set_result(body)
        return {"status": "resolved", "mode": "live"}

    if not body.claim_id:
        return JSONResponse(
            {"status": "no_pending_escalation", "detail": "Live pipeline not waiting; pass claim_id to resolve a historical row."},
            status_code=409,
        )

    claim = db.get_claim(body.claim_id)
    if not claim:
        return JSONResponse({"status": "not_found"}, status_code=404)

    covered = body.override == "covered" if body.override else body.approved
    note_suffix = f" [Human review: {body.notes.strip()}]" if body.notes and body.notes.strip() else " [Human reviewed]"
    new_reasoning = (claim.get("reasoning") or "").strip() + note_suffix
    db.save(body.claim_id, {
        **claim,
        "schema": {
            "name": claim.get("caller_name"),
            "location": claim.get("location"),
            "vehicle": claim.get("vehicle"),
            "issue_type": claim.get("issue_type"),
            "urgency": claim.get("urgency"),
        },
        "damage": {
            "type": claim.get("damage_type"),
            "severity": claim.get("damage_severity"),
            "ambiguous": bool(claim.get("damage_ambiguous")),
            "reason": claim.get("damage_reason"),
        },
        "coverage": {
            "covered": bool(covered),
            "confidence": 1.0,
            "reasoning": new_reasoning,
            "escalate": False,
        },
        "stage": "complete",
    })
    await _send_to_clients({
        "claim_id": body.claim_id,
        "stage": "complete",
        "coverage": {"covered": bool(covered), "confidence": 1.0, "reasoning": new_reasoning, "escalate": False},
        "human_resolved": True,
    })
    return {"status": "resolved", "mode": "historical", "covered": bool(covered)}


@app.post("/claims/{claim_id}/archive")
async def archive_claim_endpoint(claim_id: str):
    if not db.archive_claim(claim_id):
        return JSONResponse({"status": "not_found"}, status_code=404)
    await _send_to_clients({
        "claim_id": claim_id,
        "stage": "archived",
        "status": "archived",
        "archived": True,
    })
    return {"status": "archived"}


@app.post("/policy/upload")
async def upload_policy(file: UploadFile = File(...)):
    content = await file.read()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return JSONResponse({"error": "File must be plain text (UTF-8)"}, status_code=400)
    if not text.strip():
        return JSONResponse({"error": "File is empty"}, status_code=400)
    rag.reinit(text)
    return {"status": "ok", "message": "Policy document updated and index rebuilt"}


@app.get("/policy")
async def get_policy():
    return {"text": rag.get_policy_text()}


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    global _session_state, _escalation_future

    await websocket.accept()
    connected_clients[websocket] = {"role": "unknown", "claim_id": None}
    audio_buffer = bytearray()

    try:
        while True:
            data = await websocket.receive()

            if "bytes" in data and data["bytes"]:
                audio_buffer.extend(data["bytes"])

            elif "text" in data and data["text"]:
                msg = json.loads(data["text"])
                msg_type = msg.get("type", "")

                if msg_type == "subscribe_dashboard":
                    connected_clients[websocket] = {"role": "dashboard", "claim_id": None}

                elif msg_type == "subscribe_claims":
                    connected_clients[websocket] = {"role": "claims_list", "claim_id": None}

                elif msg_type == "subscribe_claim":
                    claim_id = str(msg.get("claim_id") or "").strip()
                    connected_clients[websocket] = {"role": "claim", "claim_id": claim_id or None}

                elif msg_type == "start_session":
                    claim_id = str(uuid.uuid4())
                    _session_state = {"claim_id": claim_id}
                    _escalation_future = None
                    audio_buffer.clear()
                    db.create_stub(claim_id)
                    connected_clients[websocket] = {"role": "call", "claim_id": claim_id}

                    callback_claim_id = msg.get("callback_claim_id")
                    if callback_claim_id:
                        callback_data = db.get_claim(callback_claim_id)
                        if callback_data:
                            _session_state["callback_context"] = callback_data

                    async def _send_greeting():
                        ctx = _session_state.get("callback_context")
                        if ctx:
                            issue = (ctx.get('issue_type') or 'claim').replace('_', ' ')
                            loc = ctx.get('location') or ''
                            stage_phrase = agent_module._claim_stage_phrase(ctx)
                            greeting = (
                                f"Hi, I can see you're calling about your recent "
                                f"{issue} claim{f' from {loc}' if loc else ''}. "
                                f"{stage_phrase} What do you need help with today?"
                            )
                        else:
                            greeting = "You're through to ClaimBuddy. Tell me what happened."
                        agent_module._append_conversation(_session_state, "Assistant", greeting)
                        audio = await agent_module._tts(greeting)
                        await broadcast({
                            "stage": "intake",
                            "follow_up": greeting,
                            "audio": agent_module._b64(audio),
                            "callback_context": ctx,
                            "conversation_transcript": _session_state.get("conversation_transcript", ""),
                        })
                    asyncio.create_task(_send_greeting())

                elif msg_type == "transcript_partial":
                    partial_text = (msg.get("text") or "").strip()
                    if partial_text and _session_state.get("claim_id") and not _session_state.get("phase2_started"):
                        await broadcast(
                            agent_module._make_state(
                                "intake",
                                transcript=_session_state.get("transcript", ""),
                                turn_transcript_partial=partial_text,
                                schema=_session_state.get("schema"),
                                **agent_module._dashboard_context(_session_state),
                            ),
                            persist=False,
                        )

                elif msg_type == "stop_recording":
                    audio_bytes = bytes(audio_buffer)
                    audio_buffer.clear()
                    if audio_bytes and not _session_state.get("phase2_started"):
                        asyncio.create_task(_handle_voice_turn(audio_bytes))

                elif msg_type == "proactive_check":
                    async def _send_proactive():
                        prompt = "I'm here when you're ready. Tell me what happened."
                        agent_module._append_conversation(_session_state, "Assistant", prompt)
                        audio = await agent_module._tts(prompt)
                        await broadcast({
                            "stage": "intake",
                            "proactive": True,
                            "audio": agent_module._b64(audio),
                            "message": prompt,
                            "conversation_transcript": _session_state.get("conversation_transcript", ""),
                        })
                    asyncio.create_task(_send_proactive())

    except WebSocketDisconnect:
        connected_clients.pop(websocket, None)
    except Exception:
        connected_clients.pop(websocket, None)

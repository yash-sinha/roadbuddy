import sqlite3
import os
import re
import json
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'claims.db')

_COLS = (
    'id', 'created_at', 'caller_name', 'location', 'vehicle', 'issue_type', 'urgency',
    'transcript', 'conversation_transcript', 'damage_type', 'damage_severity', 'damage_reason', 'damage_ambiguous',
    'covered', 'confidence', 'reasoning',
    'policy_chunks', 'escalated', 'action_type', 'garage_name', 'garage_eta', 'taxi_name', 'taxi_eta',
    'rental_name', 'rental_address', 'sms_text', 'summary', 'stage', 'status',
)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as conn:
        conn.execute(f"""
        CREATE TABLE IF NOT EXISTS claims (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            caller_name TEXT,
            location TEXT,
            vehicle TEXT,
            issue_type TEXT,
            urgency TEXT,
            transcript TEXT,
            conversation_transcript TEXT,
            damage_type TEXT,
            damage_severity TEXT,
            covered INTEGER,
            confidence REAL,
            reasoning TEXT,
            policy_chunks TEXT,
            escalated INTEGER DEFAULT 0,
            action_type TEXT,
            garage_name TEXT,
            garage_eta INTEGER,
            taxi_name TEXT,
            taxi_eta INTEGER,
            rental_name TEXT,
            rental_address TEXT,
            sms_text TEXT,
            summary TEXT,
            stage TEXT DEFAULT 'intake',
            status TEXT DEFAULT 'processing'
        )
        """)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(claims)").fetchall()}
        if 'stage' not in columns:
            conn.execute("ALTER TABLE claims ADD COLUMN stage TEXT DEFAULT 'intake'")
        if 'conversation_transcript' not in columns:
            conn.execute("ALTER TABLE claims ADD COLUMN conversation_transcript TEXT")
        if 'policy_chunks' not in columns:
            conn.execute("ALTER TABLE claims ADD COLUMN policy_chunks TEXT")
        if 'damage_reason' not in columns:
            conn.execute("ALTER TABLE claims ADD COLUMN damage_reason TEXT")
        if 'damage_ambiguous' not in columns:
            conn.execute("ALTER TABLE claims ADD COLUMN damage_ambiguous INTEGER")
        conn.commit()


def create_stub(claim_id: str) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO claims (id, created_at, stage, status) VALUES (?,?,?,?)",
            (claim_id, datetime.utcnow().isoformat(), 'intake', 'active'),
        )
        conn.commit()


def _stage_to_status(stage: str | None) -> str:
    if stage in (None, '', 'intake'):
        return 'active'
    if stage == 'complete':
        return 'complete'
    return 'reviewing'


def _looks_like_callback_placeholder(claim: dict) -> bool:
    transcript = (claim.get('transcript') or '').lower()
    if claim.get('status') != 'active':
        return False
    if claim.get('issue_type') or claim.get('location') or claim.get('urgency'):
        return False
    keywords = (
        'why was',
        'why was it not covered',
        'why was that',
        'what is the status',
        'when will i get the results',
        'when would i get the results',
    )
    return any(keyword in transcript for keyword in keywords)


def _claimant_key(name: str | None) -> str:
    normalized = re.sub(r'\s+', ' ', (name or '').strip().lower())
    if not normalized:
        return ''
    return normalized.split(' ')[0]


def _claimant_matches(claim: dict, caller_name: str | None) -> bool:
    key = _claimant_key(caller_name)
    if not key:
        return True
    return _claimant_key(claim.get('caller_name')) == key


def _looks_like_empty_pending_request(claim: dict) -> bool:
    if claim.get('status') != 'active':
        return False
    if (claim.get('stage') or 'intake') != 'intake':
        return False
    if any(
        claim.get(field)
        for field in ('caller_name', 'location', 'vehicle', 'issue_type', 'urgency', 'summary', 'reasoning', 'sms_text')
    ):
        return False
    if (claim.get('transcript') or '').strip() or (claim.get('conversation_transcript') or '').strip():
        return False

    created_at = claim.get('created_at')
    if not created_at:
        return True
    try:
        created = datetime.fromisoformat(created_at)
    except ValueError:
        return False
    return (datetime.utcnow() - created) >= timedelta(minutes=5)


def cleanup_transient_claims() -> None:
    with _conn() as conn:
        rows = [dict(row) for row in conn.execute("SELECT id, status, issue_type, location, vehicle, transcript FROM claims").fetchall()]
        claim_ids = [row['id'] for row in rows if _looks_like_callback_placeholder(row)]
        if claim_ids:
            conn.executemany("DELETE FROM claims WHERE id=?", [(claim_id,) for claim_id in claim_ids])
            conn.commit()


def cleanup_empty_pending_claims() -> None:
    with _conn() as conn:
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT id, created_at, status, stage, caller_name, location, vehicle, issue_type,
                       urgency, transcript, conversation_transcript, summary, reasoning, sms_text
                FROM claims
                """
            ).fetchall()
        ]
        claim_ids = [row['id'] for row in rows if _looks_like_empty_pending_request(row)]
        if claim_ids:
            conn.executemany("DELETE FROM claims WHERE id=?", [(claim_id,) for claim_id in claim_ids])
            conn.commit()


def _strip_dispatch_sentences(summary: str | None) -> str | None:
    if not summary:
        return summary
    sentences = re.split(r'(?<=[.!?])\s+', summary.strip())
    filtered = [
        sentence for sentence in sentences
        if not any(
            marker in sentence.lower()
            for marker in ("tow truck", "repair truck", "taxi", "rental car", "dispatched", "arranged")
        )
    ]
    return " ".join(filtered).strip() if filtered else summary


def cleanup_denied_claim_actions() -> None:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id, summary FROM claims WHERE covered = 0 AND (action_type IS NOT NULL OR garage_name IS NOT NULL OR taxi_name IS NOT NULL OR rental_name IS NOT NULL OR summary IS NOT NULL)"
        ).fetchall()
        for row in rows:
            conn.execute(
                """
                UPDATE claims
                SET action_type = NULL,
                    garage_name = NULL,
                    garage_eta = NULL,
                    taxi_name = NULL,
                    taxi_eta = NULL,
                    rental_name = NULL,
                    rental_address = NULL,
                    summary = ?
                WHERE id = ?
                """,
                (_strip_dispatch_sentences(row["summary"]), row["id"]),
            )
        if rows:
            conn.commit()


def save(claim_id: str, state: dict) -> None:
    schema = state.get('schema') or {}
    damage = state.get('damage') or {}
    coverage = state.get('coverage') or {}
    action = state.get('action') or {}
    garage = action.get('garage') or {}
    taxi = action.get('taxi') or {}
    rental = action.get('rental') or {}

    covered = coverage.get('covered')
    covered_int = 1 if covered is True else 0 if covered is False else None
    stage = state.get('stage') or ('complete' if covered is not None else 'intake')
    status = _stage_to_status(stage)
    policy_chunks = state.get('policy_chunks') or []

    vals = (
        schema.get('name'), schema.get('location'), schema.get('vehicle'),
        schema.get('issue_type'), schema.get('urgency'),
        state.get('transcript'), state.get('conversation_transcript'),
        damage.get('type'), damage.get('severity'),
        damage.get('reason'), 1 if damage.get('ambiguous') else 0 if damage.get('ambiguous') is False else None,
        covered_int, coverage.get('confidence'), coverage.get('reasoning'),
        json.dumps(policy_chunks) if policy_chunks else None,
        1 if coverage.get('escalate') else 0,
        action.get('type'), garage.get('name'), garage.get('eta_minutes'),
        taxi.get('name') if taxi else None, taxi.get('eta_minutes') if taxi else None,
        rental.get('name') if rental else None, rental.get('address') if rental else None,
        state.get('sms_text'), state.get('summary'), stage, status,
    )

    with _conn() as conn:
        exists = conn.execute("SELECT id FROM claims WHERE id=?", (claim_id,)).fetchone()
        if exists:
            set_clause = ', '.join(f"{c}=?" for c in _COLS[2:])
            conn.execute(f"UPDATE claims SET {set_clause} WHERE id=?", (*vals, claim_id))
        else:
            placeholders = ','.join(['?'] * len(_COLS))
            conn.execute(
                f"INSERT INTO claims ({','.join(_COLS)}) VALUES ({placeholders})",
                (claim_id, datetime.utcnow().isoformat(), *vals),
            )
        conn.commit()


def delete_claim(claim_id: str) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM claims WHERE id=?", (claim_id,))
        conn.commit()


def archive_claim(claim_id: str) -> bool:
    """Mark a claim as archived. Returns True if a row was updated."""
    with _conn() as conn:
        cursor = conn.execute(
            "UPDATE claims SET status='archived', stage='archived' WHERE id=?",
            (claim_id,),
        )
        conn.commit()
        return cursor.rowcount > 0


def cancel_stale_active_claims(threshold_minutes: int, skip_claim_ids: set[str] | None = None) -> list[str]:
    cutoff = (datetime.utcnow() - timedelta(minutes=threshold_minutes)).isoformat()
    skip = skip_claim_ids or set()
    with _conn() as conn:
        rows = conn.execute(
            "SELECT id FROM claims WHERE status='active' AND created_at < ?",
            (cutoff,),
        ).fetchall()
        ids = [row['id'] for row in rows if row['id'] not in skip]
        if ids:
            conn.executemany(
                "UPDATE claims SET status='cancelled', stage='cancelled' WHERE id=?",
                [(cid,) for cid in ids],
            )
            conn.commit()
        return ids


def list_claims(caller_name: str | None = None) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM claims ORDER BY created_at DESC"
        ).fetchall()
    claims = [dict(r) for r in rows]
    return [
        claim for claim in claims
        if (
            not _looks_like_callback_placeholder(claim)
            and not _looks_like_empty_pending_request(claim)
            and _claimant_matches(claim, caller_name)
        )
    ]


def latest_customer_name() -> str | None:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM claims WHERE caller_name IS NOT NULL AND TRIM(caller_name) != '' ORDER BY created_at DESC"
        ).fetchall()
    for row in rows:
        claim = dict(row)
        if claim["id"].startswith("seed-"):
            continue
        if _looks_like_callback_placeholder(claim) or _looks_like_empty_pending_request(claim):
            continue
        return claim.get("caller_name")
    return None


def get_claim(claim_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM claims WHERE id=?", (claim_id,)).fetchone()
    return dict(row) if row else None


def seed() -> None:
    with _conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM claims WHERE id LIKE 'seed-%'"
        ).fetchone()[0]
    if count > 0:
        return

    now = datetime.utcnow()
    seeds = [
        dict(
            id='seed-001', created_at=(now - timedelta(days=3)).isoformat(),
            caller_name='Sarah Chen', location='M25 Junction 12', vehicle='2022 Honda Civic',
            issue_type='flat_tyre', urgency='high',
            transcript=(
                "I have a flat tyre on the M25 near Junction 12. I've got no spare and "
                "I'm on the hard shoulder. It's really dangerous with all this traffic. "
                "My name is Sarah Chen. The car is a 2022 Honda Civic."
            ),
            damage_type='flat_tyre', damage_severity='moderate',
            covered=1, confidence=0.95,
            reasoning='Flat tyre covered under Section 2.2. No spare available — tow to nearest tyre centre.',
            escalated=0, action_type='tow_truck',
            garage_name='Central Auto Recovery', garage_eta=28,
            taxi_name='City Cabs', taxi_eta=15,
            rental_name='Enterprise Rent-A-Car', rental_address='42 High Street, Slough',
            sms_text=(
                'ClaimBuddy: Hi Sarah, your claim is approved. '
                'Tow truck from Central Auto Recovery — ETA 28 min. '
                'Taxi arranged (City Cabs) — ETA 15 min. Rental car at Enterprise Rent-A-Car.'
            ),
            summary=(
                'Sarah Chen reported a flat tyre on the M25 near Junction 12 in her 2022 Honda Civic '
                'with no spare available. Claim approved under Section 2.2. '
                'Tow truck dispatched from Central Auto Recovery with 28-minute ETA.'
            ),
            stage='complete',
            status='complete',
        ),
        dict(
            id='seed-002', created_at=(now - timedelta(days=7)).isoformat(),
            caller_name='James Okafor', location='Canary Wharf, E14', vehicle='2021 BMW 3 Series',
            issue_type='accident', urgency='critical',
            transcript=(
                "I was hit by a driver who has no insurance. My car is badly damaged and "
                "I'm near the DLR station in Canary Wharf. The other driver has left the scene. "
                "My name is James Okafor and the car is a 2021 BMW 3 Series."
            ),
            damage_type='collision', damage_severity='severe',
            covered=0, confidence=0.38,
            reasoning='Ambiguous liability — third-party uninsured vehicle involvement. Low confidence requires escalation.',
            escalated=1, action_type=None,
            garage_name=None, garage_eta=None,
            taxi_name=None, taxi_eta=None, rental_name=None, rental_address=None,
            sms_text=(
                "ClaimBuddy: Hi James, we're unable to cover this claim under your current policy. "
                "A claims handler will contact you within 2 hours."
            ),
            summary=(
                'James Okafor reported a collision with an uninsured third party who fled the scene '
                'in Canary Wharf. Claim escalated (38% confidence). Coverage denied pending investigation.'
            ),
            stage='complete',
            status='complete',
        ),
        dict(
            id='seed-003', created_at=(now - timedelta(days=14)).isoformat(),
            caller_name='Emma Williams', location='Oxford Street, W1', vehicle='2020 Volkswagen Golf',
            issue_type='battery_failure', urgency='medium',
            transcript=(
                "My car won't start. Battery is completely dead. I'm parked on Oxford Street "
                "near Bond Street tube. I need to get to a meeting. I'm Emma Williams, "
                "driving a 2020 Volkswagen Golf."
            ),
            damage_type='battery', damage_severity='minor',
            covered=1, confidence=0.97,
            reasoning='Battery failure covered under Section 2.4. Repair technician dispatched for jump-start.',
            escalated=0, action_type='repair_truck',
            garage_name='City Tow Services', garage_eta=19,
            taxi_name='Addison Lee', taxi_eta=8,
            rental_name=None, rental_address=None,
            sms_text=(
                'ClaimBuddy: Hi Emma, your claim is approved. '
                'Repair truck from City Tow Services — ETA 19 min. Taxi arranged (Addison Lee) — ETA 8 min.'
            ),
            summary=(
                'Emma Williams reported a complete battery failure on Oxford Street in her 2020 VW Golf. '
                'Claim approved under Section 2.4. Repair technician dispatched with 19-minute ETA.'
            ),
            stage='complete',
            status='complete',
        ),
        dict(
            id='seed-004', created_at=(now - timedelta(days=21)).isoformat(),
            caller_name='Marcus Thompson', location='M4 Junction 8', vehicle='2019 Ford Focus',
            issue_type='engine_failure', urgency='high',
            transcript=(
                "Engine just cut out on the M4 near Junction 8. Car won't restart and "
                "there's smoke coming from under the bonnet. I'm on the hard shoulder. "
                "Marcus Thompson here, 2019 Ford Focus."
            ),
            damage_type='engine', damage_severity='severe',
            covered=1, confidence=0.91,
            reasoning='Engine failure with visible smoke covered under Section 2.1. Tow truck dispatched.',
            escalated=0, action_type='tow_truck',
            garage_name='South Bank Garage', garage_eta=35,
            taxi_name='City Cabs', taxi_eta=20,
            rental_name='Enterprise Rent-A-Car', rental_address='Unit 5 Heathrow Retail Park',
            sms_text=(
                'ClaimBuddy: Hi Marcus, your claim is approved. '
                'Tow truck from South Bank Garage — ETA 35 min. '
                'Taxi arranged (City Cabs) — ETA 20 min. Rental car at Enterprise Rent-A-Car.'
            ),
            summary=(
                'Marcus Thompson reported severe engine failure with smoke on the M4 near Junction 8 '
                'in his 2019 Ford Focus. Claim approved under Section 2.1. Tow truck dispatched with 35-minute ETA.'
            ),
            stage='complete',
            status='complete',
        ),
        dict(
            id='seed-005', created_at=(now - timedelta(days=30)).isoformat(),
            caller_name='Lisa Patel', location='Westfield London, E20', vehicle='2023 Audi A3',
            issue_type='cosmetic_damage', urgency='low',
            transcript=(
                "Someone scratched my car in the car park at Westfield. There's a long scratch "
                "along the driver door and a dent on the wing mirror. I'm Lisa Patel, "
                "driving a 2023 Audi A3."
            ),
            damage_type='cosmetic', damage_severity='minor',
            covered=0, confidence=0.98,
            reasoning='Cosmetic damage expressly excluded under Section 3.1. Does not affect safe operation.',
            escalated=0, action_type=None,
            garage_name=None, garage_eta=None,
            taxi_name=None, taxi_eta=None, rental_name=None, rental_address=None,
            sms_text=(
                "ClaimBuddy: Hi Lisa, we're unable to cover this claim under your current policy. "
                "A claims handler will contact you within 2 hours."
            ),
            summary=(
                'Lisa Patel reported cosmetic damage (scratch and dent) to her 2023 Audi A3 '
                'at Westfield car park. Claim denied under Section 3.1 cosmetic damage exclusion.'
            ),
            stage='complete',
            status='complete',
        ),
    ]

    placeholders = ','.join(['?'] * len(_COLS))
    col_list = ','.join(_COLS)
    with _conn() as conn:
        for s in seeds:
            conn.execute(
                f"INSERT OR IGNORE INTO claims ({col_list}) VALUES ({placeholders})",
                [s.get(c) for c in _COLS],
            )
        conn.commit()

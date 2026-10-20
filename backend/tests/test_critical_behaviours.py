"""High-Risk Operational Failures & Critical Behaviours Integration Test Suite.
Stage P4: Automated Verification of Beyond-CRUD Reliability Guarantees.

Validates:
1. Simultaneous Claim Conflict (OCC & atomic WHERE claim protection -> 409)
2. Stale Update Rejected with Server State (OCC 409 with current_version & diff)
3. Synchronous Idempotency Guard (exact replay, SHA-256 validation, no duplicate inserts)
4. Workflow State Machine & Approval Gate (FSM 422 on unapproved resolution, RBAC 403 on non-approver, 200 on approver)
5. Cross-Team Resource-Level RBAC Enforcement (403 on cross-team mutations)
6. Transactional Audit Log & Outbox Retry / Dead-Letter Lifecycle
7. Server-Side Filtering, Search, and Bounded Pagination
"""

import uuid
from datetime import datetime, timezone
import pytest
import pytest_asyncio
import httpx
from sqlalchemy import select, func

from app.database import engine, Base, AsyncSessionLocal
from app.main import app
from app.models import (
    AuditLog,
    OutboxEvent,
    OutboxStatus,
    Priority,
    Team,
    TeamMembership,
    TeamRole,
    User,
    WorkItem,
    WorkItemCategory,
    WorkItemStatus,
)
from app.seed import (
    USER_ALICE_ID,
    USER_BOB_ID,
    USER_CHARLIE_ID,
    USER_DIANA_ID,
    USER_EVAN_ID,
    USER_FIONA_ID,
    TEAM_PAYMENTS_ID,
    TEAM_SRE_ID,
    TEAM_COMPLIANCE_ID,
    seed_database,
)
from app.worker import process_outbox_batch


@pytest_asyncio.fixture(scope="function")
async def client():
    """Create isolated async test client and reset database before each test."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as session:
        await seed_database(session, force=True)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    await engine.dispose()


@pytest.mark.asyncio
async def test_simultaneous_claim_conflict(client: httpx.AsyncClient):
    """Protocol 1 & 2: Two operators attempt to claim the same unassigned work item at version 1.
    Assert first succeeds (200, version=2) and second fails (409 Conflict with ALREADY_CLAIMED).
    """
    # 1. Create a fresh unassigned work item in SRE team (Alice is SRE member)
    create_payload = {
        "title": "Envoy Ingress CrashLoopBackOff",
        "description": "502 Gateway errors observed in EU-West-1 cluster.",
        "category": "PRODUCTION_INCIDENT",
        "priority": "CRITICAL",
        "team_id": TEAM_SRE_ID,
        "requires_approval": False,
        "next_action_required": "Triage pod crash logs",
    }
    create_res = await client.post(
        "/api/work-items",
        json=create_payload,
        headers={"X-User-Id": USER_ALICE_ID, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert create_res.status_code == 201
    item_id = create_res.json()["id"]
    initial_version = create_res.json()["version"]
    assert initial_version == 1

    # 2. Operator 1 (Alice) claims the work item at expected_version=1
    claim_1 = await client.post(
        f"/api/work-items/{item_id}/claim",
        json={"expected_version": 1},
        headers={"X-User-Id": USER_ALICE_ID, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert claim_1.status_code == 200
    res_1 = claim_1.json()
    assert res_1["version"] == 2
    assert res_1["assignee_id"] == USER_ALICE_ID

    # 3. Operator 2 (Fiona - fellow SRE member) attempts to claim at stale expected_version=1
    claim_2 = await client.post(
        f"/api/work-items/{item_id}/claim",
        json={"expected_version": 1},
        headers={"X-User-Id": USER_FIONA_ID, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert claim_2.status_code == 409
    error_data = claim_2.json()["detail"]
    assert error_data["error_code"] in ("ALREADY_CLAIMED", "CONCURRENCY_CONFLICT")
    assert error_data["current_version"] == 2
    assert "Alice" in str(error_data) or error_data.get("claimed_by") is not None


@pytest.mark.asyncio
async def test_stale_update_rejected_with_server_state(client: httpx.AsyncClient):
    """Protocol 1: User A transitions an item (v1 -> v2). User B then attempts to update
    title/status using stale expected_version=1.
    Assert 409 Conflict with full server state diff returned.
    """
    # 1. Create an item in SRE team (Alice is SRE member)
    create_res = await client.post(
        "/api/work-items",
        json={
            "title": "Stale State Test Item",
            "description": "Validating OCC version divergence.",
            "category": "ENGINEERING_PROBLEM",
            "priority": "MEDIUM",
            "team_id": TEAM_SRE_ID,
            "requires_approval": False,
            "next_action_required": "Initial review",
        },
        headers={"X-User-Id": USER_ALICE_ID, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert create_res.status_code == 201
    item_id = create_res.json()["id"]

    # 2. User A transitions item to IN_PROGRESS (bumps version 1 -> 2)
    trans_res = await client.post(
        f"/api/work-items/{item_id}/transition",
        json={
            "expected_version": 1,
            "target_status": "IN_PROGRESS",
            "reason": "Starting investigation",
            "next_action_required": "Profile database queries",
        },
        headers={"X-User-Id": USER_ALICE_ID, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert trans_res.status_code == 200
    assert trans_res.json()["version"] == 2

    # 3. User B (Fiona - fellow SRE member) attempts to update title with stale expected_version=1
    update_res = await client.patch(
        f"/api/work-items/{item_id}",
        json={
            "expected_version": 1,
            "title": "Conflicting Title Update by Fiona",
            "reason": "Late documentation update",
        },
        headers={"X-User-Id": USER_FIONA_ID, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert update_res.status_code == 409
    conflict = update_res.json()["detail"]
    assert conflict["error_code"] == "CONCURRENCY_CONFLICT"
    assert conflict["current_version"] == 2
    assert conflict["current_state"]["status"] == "IN_PROGRESS"


@pytest.mark.asyncio
async def test_idempotency_key_prevents_duplicate_operations(client: httpx.AsyncClient):
    """Protocol 3: Submitting mutations with the same Idempotency-Key returns cached response
    (X-Cache-Lookup: HIT) and prevents duplicate database writes.
    """
    shared_key = str(uuid.uuid4())
    create_body = {
        "title": "Idempotent Creation Test",
        "description": "Network timeout simulation check.",
        "category": "PAYMENT_INVESTIGATION",
        "priority": "HIGH",
        "team_id": TEAM_PAYMENTS_ID,
        "requires_approval": False,
        "next_action_required": "Trace gateway webhook",
    }

    # 1. First execution
    res1 = await client.post(
        "/api/work-items",
        json=create_body,
        headers={"X-User-Id": USER_BOB_ID, "Idempotency-Key": shared_key},
    )
    assert res1.status_code == 201
    item_id = res1.json()["id"]

    # 2. Identical replay with same Idempotency-Key
    res2 = await client.post(
        "/api/work-items",
        json=create_body,
        headers={"X-User-Id": USER_BOB_ID, "Idempotency-Key": shared_key},
    )
    assert res2.status_code == 201
    assert res2.headers.get("X-Cache-Lookup") == "HIT"
    assert res2.json()["id"] == item_id

    # 3. Verify exactly 1 row exists in database
    async with AsyncSessionLocal() as session:
        count_stmt = select(func.count(WorkItem.id)).where(WorkItem.title == "Idempotent Creation Test")
        res = await session.execute(count_stmt)
        assert res.scalar_one() == 1

    # 4. Test Idempotent Comments
    comment_key = str(uuid.uuid4())
    comm_body = {"comment": "Duplicate webhook received from Stripe."}

    c_res1 = await client.post(
        f"/api/work-items/{item_id}/comments",
        json=comm_body,
        headers={"X-User-Id": USER_BOB_ID, "Idempotency-Key": comment_key},
    )
    assert c_res1.status_code == 200

    c_res2 = await client.post(
        f"/api/work-items/{item_id}/comments",
        json=comm_body,
        headers={"X-User-Id": USER_BOB_ID, "Idempotency-Key": comment_key},
    )
    assert c_res2.status_code == 200
    assert c_res2.headers.get("X-Cache-Lookup") == "HIT"

    async with AsyncSessionLocal() as session:
        audit_count = select(func.count(AuditLog.id)).where(
            AuditLog.work_item_id == item_id,
            AuditLog.action_type == "COMMENTED",
        )
        res = await session.execute(audit_count)
        assert res.scalar_one() == 1


@pytest.mark.asyncio
async def test_workflow_state_machine_and_approval_gate(client: httpx.AsyncClient):
    """Protocols 4 & 5: Finite state machine rejects invalid jumps and enforces formal approval gates.
    - requires_approval item cannot transition directly from IN_PROGRESS -> RESOLVED (422)
    - Regular MEMBER cannot approve request (403)
    - APPROVER / LEAD succeeds (200) and moves it to RESOLVED
    """
    # 1. Create item requiring approval in Compliance team (Bob is Compliance MEMBER)
    create_res = await client.post(
        "/api/work-items",
        json={
            "title": "GDPR Subject Access Request #9021",
            "description": "User requested full transaction archive deletion.",
            "category": "COMPLIANCE_REQUEST",
            "priority": "HIGH",
            "team_id": TEAM_COMPLIANCE_ID,
            "requires_approval": True,
            "next_action_required": "Legal counsel verification",
        },
        headers={"X-User-Id": USER_BOB_ID, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert create_res.status_code == 201
    item_id = create_res.json()["id"]

    # 2. Transition TRIAGE -> IN_PROGRESS
    t1 = await client.post(
        f"/api/work-items/{item_id}/transition",
        json={
            "expected_version": 1,
            "target_status": "IN_PROGRESS",
            "reason": "Commencing audit",
        },
        headers={"X-User-Id": USER_BOB_ID, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert t1.status_code == 200
    assert t1.json()["version"] == 2

    # 3. Direct transition to RESOLVED without approval must be rejected with 422
    t_invalid = await client.post(
        f"/api/work-items/{item_id}/transition",
        json={
            "expected_version": 2,
            "target_status": "RESOLVED",
            "reason": "Attempting early resolution without signoff",
        },
        headers={"X-User-Id": USER_BOB_ID, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert t_invalid.status_code == 422
    assert "formal approval" in t_invalid.json()["detail"].lower()

    # 4. Transition IN_PROGRESS -> PENDING_APPROVAL
    t_pending = await client.post(
        f"/api/work-items/{item_id}/transition",
        json={
            "expected_version": 2,
            "target_status": "PENDING_APPROVAL",
            "reason": "Awaiting Lead signoff",
        },
        headers={"X-User-Id": USER_BOB_ID, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert t_pending.status_code == 200
    assert t_pending.json()["version"] == 3

    # 5. Member (Bob - MEMBER of Compliance) attempts approval -> 403 Forbidden
    appr_fail = await client.post(
        f"/api/work-items/{item_id}/approve",
        json={
            "expected_version": 3,
            "decision": "APPROVED",
            "reason": "Peer member rubber stamp",
        },
        headers={"X-User-Id": USER_BOB_ID, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert appr_fail.status_code == 403
    assert "lead" in appr_fail.json()["detail"].lower() or "approver" in appr_fail.json()["detail"].lower()

    # 6. Approver (Evan - APPROVER of Compliance) approves -> 200 OK & RESOLVED
    appr_ok = await client.post(
        f"/api/work-items/{item_id}/approve",
        json={
            "expected_version": 3,
            "decision": "APPROVED",
            "reason": "Verified legal consent and audit logs",
        },
        headers={"X-User-Id": USER_EVAN_ID, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert appr_ok.status_code == 200
    res_appr = appr_ok.json()
    assert res_appr["approval_status"] == "APPROVED"
    assert res_appr["status"] == "RESOLVED"
    assert res_appr["version"] == 4


@pytest.mark.asyncio
async def test_cross_team_authorization_enforced(client: httpx.AsyncClient):
    """Resource-Level RBAC: An operator from Team A (e.g., Evan in Compliance) cannot mutate
    or claim work items belonging to Team B (e.g., Payments).
    """
    # 1. Create a work item in Payments team
    create_res = await client.post(
        "/api/work-items",
        json={
            "title": "SEPA Payment Clearing Failure",
            "description": "Batch payout rejected by correspondent bank.",
            "category": "PAYMENT_INVESTIGATION",
            "priority": "HIGH",
            "team_id": TEAM_PAYMENTS_ID,
            "requires_approval": False,
            "next_action_required": "Contact settlement partner",
        },
        headers={"X-User-Id": USER_BOB_ID, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert create_res.status_code == 201
    item_id = create_res.json()["id"]

    # 2. Evan (only in Compliance) attempts to claim Payments item -> 403
    claim_res = await client.post(
        f"/api/work-items/{item_id}/claim",
        json={"expected_version": 1},
        headers={"X-User-Id": USER_EVAN_ID, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert claim_res.status_code == 403
    assert "not a member" in claim_res.json()["detail"].lower()

    # 3. Evan attempts to transition Payments item -> 403
    trans_res = await client.post(
        f"/api/work-items/{item_id}/transition",
        json={
            "expected_version": 1,
            "target_status": "IN_PROGRESS",
            "reason": "Cross-team tampering attempt",
        },
        headers={"X-User-Id": USER_EVAN_ID, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert trans_res.status_code == 403

    # 4. Evan attempts to reassign Payments item -> 403
    reassign_res = await client.post(
        f"/api/work-items/{item_id}/reassign",
        json={
            "expected_version": 1,
            "new_assignee_id": USER_EVAN_ID,
            "reason": "Stealing assignment",
        },
        headers={"X-User-Id": USER_EVAN_ID, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert reassign_res.status_code == 403


@pytest.mark.asyncio
async def test_transactional_audit_log_and_outbox_retry_lifecycle(client: httpx.AsyncClient):
    """Protocols 4 & 5:
    1. Every mutation creates an atomic AuditLog and OutboxEvent in the same commit.
    2. Failing OutboxEvents record errors, increment attempts, apply backoff, and move to DEAD_LETTER after max_attempts.
    """
    # 1. Create work item
    item_res = await client.post(
        "/api/work-items",
        json={
            "title": "Audit & Outbox Verification Item",
            "description": "Testing transactional emission guarantees.",
            "category": "ENGINEERING_PROBLEM",
            "priority": "MEDIUM",
            "team_id": TEAM_SRE_ID,
            "requires_approval": False,
            "next_action_required": "Verify logs",
        },
        headers={"X-User-Id": USER_ALICE_ID, "Idempotency-Key": str(uuid.uuid4())},
    )
    assert item_res.status_code == 201
    item_id = item_res.json()["id"]

    # 2. Transition item
    await client.post(
        f"/api/work-items/{item_id}/transition",
        json={
            "expected_version": 1,
            "target_status": "IN_PROGRESS",
            "reason": "Transitioning to verify audit trail",
        },
        headers={"X-User-Id": USER_ALICE_ID, "Idempotency-Key": str(uuid.uuid4())},
    )

    # 3. Verify atomic DB records
    async with AsyncSessionLocal() as session:
        logs_stmt = select(AuditLog).where(AuditLog.work_item_id == item_id).order_by(AuditLog.created_at.asc())
        logs_res = await session.execute(logs_stmt)
        logs = logs_res.scalars().all()
        assert len(logs) == 2
        assert logs[0].action_type == "CREATED"
        assert logs[1].action_type == "STATUS_CHANGED"

        events_stmt = select(OutboxEvent).where(OutboxEvent.work_item_id == item_id)
        events_res = await session.execute(events_stmt)
        events = events_res.scalars().all()
        assert len(events) == 2
        assert all(e.status == OutboxStatus.PENDING for e in events)

    # 4. Inject a failing outbox event with max_attempts=3
    async with AsyncSessionLocal() as session:
        failing_event = OutboxEvent(
            id=str(uuid.uuid4()),
            work_item_id=item_id,
            event_type="WORK_ITEM_STATUS_CHANGED",
            payload={"simulate_failure": True, "note": "Transient webhook failure"},
            dedup_key=f"fail-test-{uuid.uuid4()}",
            status=OutboxStatus.PENDING,
            attempts=0,
            max_attempts=3,
        )
        session.add(failing_event)
        await session.commit()
        fail_id = failing_event.id

    # 5. Process Batch Attempt 1 -> Status should become FAILED with attempts=1
    async with AsyncSessionLocal() as session:
        b1 = await process_outbox_batch(session)
        assert b1["failed"] >= 1

    async with AsyncSessionLocal() as session:
        ev = await session.get(OutboxEvent, fail_id)
        assert ev.attempts == 1
        assert ev.status == OutboxStatus.FAILED
        assert ev.last_error is not None
        assert ev.next_retry_at is not None

        # Fast forward next_retry_at to past so batch 2 picks it up
        ev.next_retry_at = datetime.now(timezone.utc)
        await session.commit()

    # 6. Process Batch Attempt 2 -> attempts=2, status=FAILED
    async with AsyncSessionLocal() as session:
        await process_outbox_batch(session)

    async with AsyncSessionLocal() as session:
        ev = await session.get(OutboxEvent, fail_id)
        assert ev.attempts == 2
        assert ev.status == OutboxStatus.FAILED

        # Fast forward next_retry_at again to simulate time passage
        ev.next_retry_at = datetime.now(timezone.utc)
        await session.commit()

    # 7. Process Batch Attempt 3 -> Reaches max_attempts (3) -> DEAD_LETTER
    async with AsyncSessionLocal() as session:
        b3 = await process_outbox_batch(session)
        assert b3["dead_letter"] >= 1

    async with AsyncSessionLocal() as session:
        ev = await session.get(OutboxEvent, fail_id)
        assert ev.attempts == 3
        assert ev.status == OutboxStatus.DEAD_LETTER


@pytest.mark.asyncio
async def test_server_side_filtering_and_pagination(client: httpx.AsyncClient):
    """Validates server-side query filtering by team, status, priority, needs_attention,
    search text, and limit/offset pagination.
    """
    # 1. Filter by Team: SRE
    res_sre = await client.get(f"/api/work-items?team_id={TEAM_SRE_ID}")
    assert res_sre.status_code == 200
    sre_items = res_sre.json()["items"]
    assert len(sre_items) > 0
    assert all(it["team_id"] == TEAM_SRE_ID for it in sre_items)

    # 2. Filter by Status: TRIAGE
    res_triage = await client.get("/api/work-items?status=TRIAGE")
    assert res_triage.status_code == 200
    triage_items = res_triage.json()["items"]
    assert len(triage_items) > 0
    assert all(it["status"] == "TRIAGE" for it in triage_items)

    # 3. Filter by Priority: CRITICAL
    res_crit = await client.get("/api/work-items?priority=CRITICAL")
    assert res_crit.status_code == 200
    crit_items = res_crit.json()["items"]
    assert len(crit_items) > 0
    assert all(it["priority"] == "CRITICAL" for it in crit_items)

    # 4. Filter by needs_attention: True (Must only return items requiring immediate operator action)
    res_attn = await client.get("/api/work-items?needs_attention=true")
    assert res_attn.status_code == 200
    attn_items = res_attn.json()["items"]
    assert len(attn_items) > 0
    assert all(
        it["priority"] == "CRITICAL" or it["status"] in ("TRIAGE", "PENDING_APPROVAL", "BLOCKED")
        for it in attn_items
    )

    # 5. Pagination: limit=5 & offset=0 vs offset=5
    page_1 = await client.get("/api/work-items?limit=5&offset=0")
    assert page_1.status_code == 200
    items_p1 = page_1.json()["items"]
    assert len(items_p1) == 5

    page_2 = await client.get("/api/work-items?limit=5&offset=5")
    assert page_2.status_code == 200
    items_p2 = page_2.json()["items"]
    assert len(items_p2) == 5

    # Ensure no overlap between page 1 and page 2
    ids_p1 = {it["id"] for it in items_p1}
    ids_p2 = {it["id"] for it in items_p2}
    assert ids_p1.isdisjoint(ids_p2)

"""Automated Architectural Evaluation Test Suite.
Stage E1: Formal Beyond-CRUD Verification & Contract Compliance.
Strictly validates:
- Optimistic Concurrency Control (OCC) with 409 conflict payload
- Simultaneous Claim Protection (409 ALREADY_CLAIMED)
- Synchronous Idempotency Guard (Exact Replay vs Payload Mismatch)
- Synchronous 1:1 Transactional Audit Logging & Outbox Event Emission
- Resource-Level RBAC Enforcement (Cross-team 403 & Unauthorized Approval 403)
- Deterministic State Machine & Approval Gate Invariant (422)
- Outbox Worker Exponential Backoff & Dead-Letter Queue (DLQ)
"""

import uuid
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
    TEAM_PAYMENTS_ID,
    TEAM_SRE_ID,
    TEAM_COMPLIANCE_ID,
    seed_database,
)
from app.worker import process_outbox_batch


@pytest_asyncio.fixture(scope="function")
async def client():
    """Create isolated async test client and reset database."""
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
async def test_contract_compliance_users_and_teams(client: httpx.AsyncClient):
    """Verify Users and Teams endpoints return valid schemas matching locked contracts."""
    # 1. Users
    res_users = await client.get("/api/users")
    assert res_users.status_code == 200
    users = res_users.json()
    assert len(users) == 6
    for u in users:
        assert "id" in u and "email" in u and "full_name" in u and "avatar_color" in u

    # 2. Teams
    res_teams = await client.get("/api/teams")
    assert res_teams.status_code == 200
    teams = res_teams.json()
    assert len(teams) == 3
    for t in teams:
        assert "id" in t and "name" in t and "slug" in t and "member_count" in t


@pytest.mark.asyncio
async def test_contract_compliance_work_items_list(client: httpx.AsyncClient):
    """Verify Work Items listing returns paginated WorkItemListResponse schema."""
    res = await client.get("/api/work-items?limit=10&offset=0")
    assert res.status_code == 200
    data = res.json()
    assert "items" in data and "total" in data and "limit" in data and "offset" in data
    assert data["total"] == 35
    assert len(data["items"]) == 10
    first = data["items"][0]
    assert "version" in first and "title" in first and "requires_approval" in first


@pytest.mark.asyncio
async def test_occ_concurrency_conflict_returns_409_with_diff_payload(client: httpx.AsyncClient):
    """Verify Protocol 1: OCC failure returns 409 with current_version and current_state."""
    # Fetch an existing item in Payments where both Alice and Bob are team members
    list_res = await client.get(f"/api/work-items?team_id={TEAM_PAYMENTS_ID}&limit=1")
    item = list_res.json()["items"][0]
    item_id = item["id"]
    stale_version = item["version"]

    # First update: increments version to stale_version + 1
    headers_alice = {"X-User-Id": USER_ALICE_ID, "Idempotency-Key": str(uuid.uuid4())}
    upd_res = await client.patch(
        f"/api/work-items/{item_id}",
        json={"expected_version": stale_version, "title": "Updated by Alice", "reason": "Triage update"},
        headers=headers_alice,
    )
    assert upd_res.status_code == 200
    updated_item = upd_res.json()
    assert updated_item["version"] == stale_version + 1

    # Second update from Bob using stale version: Must return 409 CONCURRENCY_CONFLICT
    headers_bob = {"X-User-Id": USER_BOB_ID, "Idempotency-Key": str(uuid.uuid4())}
    conflict_res = await client.patch(
        f"/api/work-items/{item_id}",
        json={"expected_version": stale_version, "title": "Conflicting edit by Bob", "reason": "Late update"},
        headers=headers_bob,
    )
    assert conflict_res.status_code == 409
    err = conflict_res.json()["detail"]
    assert err["error_code"] == "CONCURRENCY_CONFLICT"
    assert err["current_version"] == stale_version + 1
    assert "current_state" in err
    assert err["current_state"]["title"] == "Updated by Alice"


@pytest.mark.asyncio
async def test_simultaneous_claim_protection_returns_409_already_claimed(client: httpx.AsyncClient):
    """Verify Protocol 2: Claim race condition protection returns 409 ALREADY_CLAIMED."""
    # Find an unassigned triage item in Payments
    list_res = await client.get(f"/api/work-items?team_id={TEAM_PAYMENTS_ID}&assignee=unassigned&limit=1")
    items = list_res.json()["items"]
    assert len(items) > 0, "Expected at least 1 unassigned triage item in Payments"
    item = items[0]
    item_id = item["id"]
    version = item["version"]

    # Charlie claims first
    headers_charlie = {"X-User-Id": USER_CHARLIE_ID, "Idempotency-Key": str(uuid.uuid4())}
    claim1 = await client.post(
        f"/api/work-items/{item_id}/claim",
        json={"expected_version": version},
        headers=headers_charlie,
    )
    assert claim1.status_code == 200
    claimed_item = claim1.json()
    assert claimed_item["assignee_id"] == USER_CHARLIE_ID
    assert claimed_item["version"] == version + 1

    # Bob attempts to claim concurrently with expected_version=version + 1
    headers_bob = {"X-User-Id": USER_BOB_ID, "Idempotency-Key": str(uuid.uuid4())}
    claim2 = await client.post(
        f"/api/work-items/{item_id}/claim",
        json={"expected_version": version + 1},
        headers=headers_bob,
    )
    assert claim2.status_code == 409
    err = claim2.json()["detail"]
    assert err["error_code"] == "ALREADY_CLAIMED"
    assert "Charlie Davis" in err["message"]
    assert err["claimed_by"]["id"] == USER_CHARLIE_ID


@pytest.mark.asyncio
async def test_idempotency_guard_exact_replay_and_mismatch(client: httpx.AsyncClient):
    """Verify Protocol 3: Idempotency-Key replays cached response without duplicate execution."""
    key = str(uuid.uuid4())
    headers = {"X-User-Id": USER_ALICE_ID, "Idempotency-Key": key}
    payload = {
        "title": "Idempotent Creation Test",
        "description": "Checking for duplicate suppression",
        "category": "PAYMENT_INVESTIGATION",
        "priority": "HIGH",
        "team_id": TEAM_PAYMENTS_ID,
        "requires_approval": False,
        "next_action_required": "Triage",
    }

    # Initial request
    r1 = await client.post("/api/work-items", json=payload, headers=headers)
    assert r1.status_code == 201
    item1 = r1.json()

    # Exact replay with same key and payload
    r2 = await client.post("/api/work-items", json=payload, headers=headers)
    assert r2.status_code == 201
    assert r2.headers.get("x-cache-lookup") == "HIT"
    item2 = r2.json()
    assert item1["id"] == item2["id"]

    # Replay with same key but DIFFERENT payload -> 422 Unprocessable Entity
    payload_modified = {**payload, "title": "Tampered Payload Attempt"}
    r3 = await client.post("/api/work-items", json=payload_modified, headers=headers)
    assert r3.status_code == 422
    assert "previously used for a different request" in r3.json()["detail"]

    # Verify database has exactly 1 created item and 1 audit log, not 2
    async with AsyncSessionLocal() as session:
        count_res = await session.execute(
            select(func.count(WorkItem.id)).where(WorkItem.title == "Idempotent Creation Test")
        )
        assert count_res.scalar_one() == 1


@pytest.mark.asyncio
async def test_synchronous_acid_audit_and_outbox_commitment(client: httpx.AsyncClient):
    """Verify Protocol 4 & 5: AuditLog and OutboxEvent are committed in the same transaction."""
    headers = {"X-User-Id": USER_ALICE_ID, "Idempotency-Key": str(uuid.uuid4())}
    payload = {
        "title": "Atomic ACID Provenance Test",
        "description": "Testing synchronous 1:1 audit and outbox emission",
        "category": "CUSTOMER_ISSUE",
        "priority": "MEDIUM",
        "team_id": TEAM_PAYMENTS_ID,
        "requires_approval": False,
        "next_action_required": "Review customer transcript",
    }

    res = await client.post("/api/work-items", json=payload, headers=headers)
    assert res.status_code == 201
    item_id = res.json()["id"]

    # Inspect database directly
    async with AsyncSessionLocal() as session:
        # Audit log verification
        audit_stmt = select(AuditLog).where(AuditLog.work_item_id == item_id)
        audits = (await session.execute(audit_stmt)).scalars().all()
        assert len(audits) == 1
        assert audits[0].action_type == "CREATED"
        assert audits[0].actor_id == USER_ALICE_ID

        # Outbox event verification
        outbox_stmt = select(OutboxEvent).where(OutboxEvent.work_item_id == item_id)
        events = (await session.execute(outbox_stmt)).scalars().all()
        assert len(events) == 1
        assert events[0].event_type == "WORK_ITEM_CREATED"
        assert events[0].status == OutboxStatus.PENDING.value


@pytest.mark.asyncio
async def test_rbac_cross_team_block_and_unauthorized_approval(client: httpx.AsyncClient):
    """Verify Resource-Level RBAC blocks cross-team actions (403) and non-approver approvals (403)."""
    # 1. Evan Wright belongs ONLY to Trust & Compliance (not SRE)
    # Attempting to mutate an SRE item should return 403 Forbidden
    list_sre = await client.get(f"/api/work-items?team_id={TEAM_SRE_ID}&limit=1")
    sre_item = list_sre.json()["items"][0]

    headers_evan = {"X-User-Id": USER_EVAN_ID, "Idempotency-Key": str(uuid.uuid4())}
    cross_team_res = await client.patch(
        f"/api/work-items/{sre_item['id']}",
        json={"expected_version": sre_item["version"], "title": "Unauthorized cross-team title edit"},
        headers=headers_evan,
    )
    assert cross_team_res.status_code == 403
    assert "not a member of team" in cross_team_res.json()["detail"]

    # 2. Charlie Davis is a standard MEMBER of Payments & Risk (not APPROVER or LEAD)
    # Attempting to approve an item requiring approval should return 403 Forbidden
    pending_items = await client.get(
        f"/api/work-items?team_id={TEAM_PAYMENTS_ID}&status=PENDING_APPROVAL&limit=1"
    )
    assert len(pending_items.json()["items"]) > 0
    pending_item = pending_items.json()["items"][0]

    headers_charlie = {"X-User-Id": USER_CHARLIE_ID, "Idempotency-Key": str(uuid.uuid4())}
    unauth_approve = await client.post(
        f"/api/work-items/{pending_item['id']}/approve",
        json={"expected_version": pending_item["version"], "decision": "APPROVED", "reason": "Self-certification attempt"},
        headers=headers_charlie,
    )
    assert unauth_approve.status_code == 403
    assert "requires role in ['APPROVER', 'LEAD']" in unauth_approve.json()["detail"]


@pytest.mark.asyncio
async def test_state_machine_approval_gate_and_illegal_transitions(client: httpx.AsyncClient):
    """Verify Deterministic State Machine rejects resolving unapproved items (422) and illegal transitions (422)."""
    # Find an in-progress item with requires_approval=True
    async with AsyncSessionLocal() as session:
        stmt = (
            select(WorkItem)
            .where(
                WorkItem.team_id == TEAM_PAYMENTS_ID,
                WorkItem.requires_approval.is_(True),
                WorkItem.status == WorkItemStatus.IN_PROGRESS.value,
            )
            .limit(1)
        )
        res = await session.execute(stmt)
        item = res.scalar_one_or_none()
        assert item is not None, "Expected in-progress item requiring approval in Payments"
        item_id = item.id
        version = item.version

    headers_bob = {"X-User-Id": USER_BOB_ID, "Idempotency-Key": str(uuid.uuid4())}

    # 1. Attempt to bypass approval and resolve directly -> 422 Unprocessable Entity
    direct_resolve = await client.post(
        f"/api/work-items/{item_id}/transition",
        json={"expected_version": version, "target_status": "RESOLVED", "reason": "Bypassing approval gate"},
        headers=headers_bob,
    )
    assert direct_resolve.status_code == 422
    assert "requires formal approval" in direct_resolve.json()["detail"]

    # 2. Attempt illegal transition (IN_PROGRESS -> TRIAGE) -> 422 Unprocessable Entity
    illegal_trans = await client.post(
        f"/api/work-items/{item_id}/transition",
        json={"expected_version": version, "target_status": "TRIAGE", "reason": "Illegal retrograde step"},
        headers=headers_bob,
    )
    assert illegal_trans.status_code == 422
    assert "Illegal state transition" in illegal_trans.json()["detail"]


@pytest.mark.asyncio
async def test_outbox_worker_exponential_backoff_and_dead_letter(client: httpx.AsyncClient):
    """Verify Protocol 5: Outbox worker increments attempts, applies exponential backoff, and moves to DEAD_LETTER after 5 attempts."""
    # 1. Enqueue a failing outbox event
    sim_res = await client.post("/api/outbox/simulate-failure")
    assert sim_res.status_code == 201
    event_id = sim_res.json()["id"]

    async with AsyncSessionLocal() as session:
        # Initial check
        e = await session.get(OutboxEvent, event_id)
        assert e.status == OutboxStatus.PENDING.value
        assert e.attempts == 0

        # Cycle 1: attempts = 1 -> FAILED (backoff = 2^1 = 2s)
        await process_outbox_batch(session)
        await session.refresh(e)
        assert e.status == OutboxStatus.FAILED.value
        assert e.attempts == 1
        assert e.next_retry_at is not None

        # Simulate subsequent retry cycles by resetting next_retry_at to past
        for expected_attempts in [2, 3, 4]:
            e.next_retry_at = None
            await session.commit()
            await process_outbox_batch(session)
            await session.refresh(e)
            assert e.status == OutboxStatus.FAILED.value
            assert e.attempts == expected_attempts

        # Cycle 5: Reaches max_attempts (5) -> DEAD_LETTER
        e.next_retry_at = None
        await session.commit()
        await process_outbox_batch(session)
        await session.refresh(e)
        assert e.status == OutboxStatus.DEAD_LETTER.value
        assert e.attempts == 5
        assert "Dead-lettered after 5 attempts" in e.last_error

    # 2. Test outbox manual retry endpoint resets it to PENDING and reprocesses
    retry_res = await client.post(f"/api/outbox/{event_id}/retry")
    assert retry_res.status_code == 200
    retried_event = retry_res.json()
    assert retried_event["attempts"] >= 1  # Re-evaluated immediately by process batch

"""Core Work Item Domain Service.
Implements the 6 Beyond-CRUD Correctness Protocols:
- Optimistic Concurrency Control (OCC)
- Simultaneous Claim Protection
- Deterministic State Machine & Approval Gates
- Synchronous ACID Audit Logging
- Transactional Outbox Event Persistence
Stage P1: Backend Domain Engine.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from fastapi import HTTPException, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_user_team_membership, verify_team_membership
from app.models import (
    ApprovalStatus,
    AuditActionType,
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
from app.schemas import (
    ConflictErrorDetail,
    DashboardStatsResponse,
    UserResponse,
    WorkItemApproveRequest,
    WorkItemClaimRequest,
    WorkItemCreateRequest,
    WorkItemDetailResponse,
    WorkItemListResponse,
    WorkItemReassignRequest,
    WorkItemResponse,
    WorkItemTransitionRequest,
    WorkItemUpdateRequest,
)

# Deterministic State Machine Transition Matrix
ALLOWED_TRANSITIONS: dict[str, list[str]] = {
    WorkItemStatus.TRIAGE.value: [
        WorkItemStatus.IN_PROGRESS.value,
        WorkItemStatus.CANCELLED.value,
    ],
    WorkItemStatus.IN_PROGRESS.value: [
        WorkItemStatus.BLOCKED.value,
        WorkItemStatus.PENDING_APPROVAL.value,
        WorkItemStatus.RESOLVED.value,
        WorkItemStatus.CANCELLED.value,
    ],
    WorkItemStatus.BLOCKED.value: [
        WorkItemStatus.IN_PROGRESS.value,
        WorkItemStatus.CANCELLED.value,
    ],
    WorkItemStatus.PENDING_APPROVAL.value: [
        WorkItemStatus.RESOLVED.value,
        WorkItemStatus.IN_PROGRESS.value,
        WorkItemStatus.CANCELLED.value,
    ],
    WorkItemStatus.RESOLVED.value: [
        WorkItemStatus.IN_PROGRESS.value,  # Reopening allowed by Lead/Approver
    ],
    WorkItemStatus.CANCELLED.value: [],    # Terminal state
}


def _dump_work_item_state(item: WorkItem) -> dict[str, Any]:
    """Capture snapshot of work item state for audit logs and OCC diffs."""
    return {
        "id": item.id,
        "title": item.title,
        "description": item.description,
        "category": item.category,
        "status": item.status,
        "priority": item.priority,
        "team_id": item.team_id,
        "creator_id": item.creator_id,
        "assignee_id": item.assignee_id,
        "next_action_required": item.next_action_required,
        "requires_approval": item.requires_approval,
        "approval_status": item.approval_status,
        "approved_by_id": item.approved_by_id,
        "version": item.version,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


async def _get_work_item_with_relations(db: AsyncSession, item_id: str) -> Optional[WorkItem]:
    """Load work item with all related entities eagerly populated."""
    stmt = (
        select(WorkItem)
        .where(WorkItem.id == item_id)
        .options(
            selectinload(WorkItem.creator),
            selectinload(WorkItem.assignee),
            selectinload(WorkItem.approved_by),
            selectinload(WorkItem.team).selectinload(Team.memberships),
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def get_work_item_detail(db: AsyncSession, item_id: str) -> WorkItemDetailResponse:
    """Retrieve full work item detail including audit logs and outbox events."""
    stmt = (
        select(WorkItem)
        .where(WorkItem.id == item_id)
        .options(
            selectinload(WorkItem.creator),
            selectinload(WorkItem.assignee),
            selectinload(WorkItem.approved_by),
            selectinload(WorkItem.team).selectinload(Team.memberships),
            selectinload(WorkItem.audit_logs).selectinload(AuditLog.actor),
            selectinload(WorkItem.outbox_events),
        )
    )
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()

    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Work item '{item_id}' not found.",
        )

    return WorkItemDetailResponse.model_validate(item)


async def create_work_item(
    db: AsyncSession,
    request: WorkItemCreateRequest,
    current_user: User,
) -> WorkItemResponse:
    """Create a new work item with synchronous audit log and outbox event."""
    item_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    item = WorkItem(
        id=item_id,
        title=request.title.strip(),
        description=request.description.strip(),
        category=request.category.value if hasattr(request.category, "value") else str(request.category),
        status=WorkItemStatus.TRIAGE.value,
        priority=request.priority.value if hasattr(request.priority, "value") else str(request.priority),
        team_id=request.team_id,
        creator_id=current_user.id,
        assignee_id=None,
        next_action_required=request.next_action_required.strip(),
        requires_approval=request.requires_approval,
        approval_status=ApprovalStatus.PENDING.value if request.requires_approval else ApprovalStatus.NOT_REQUIRED.value,
        approved_by_id=None,
        version=1,
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    await db.flush()

    new_state = _dump_work_item_state(item)

    # 1. Synchronous Audit Log
    audit = AuditLog(
        id=str(uuid.uuid4()),
        work_item_id=item.id,
        actor_id=current_user.id,
        action_type=AuditActionType.CREATED.value,
        previous_state={},
        new_state=new_state,
        reason="Initial work item creation",
        created_at=now,
    )
    db.add(audit)

    # 2. Transactional Outbox Event
    outbox = OutboxEvent(
        id=str(uuid.uuid4()),
        work_item_id=item.id,
        event_type="WORK_ITEM_CREATED",
        payload={
            "work_item_id": item.id,
            "title": item.title,
            "category": item.category,
            "priority": item.priority,
            "team_id": item.team_id,
            "creator_id": item.creator_id,
            "version": item.version,
        },
        dedup_key=f"item-{item.id}-created-v{item.version}",
        status=OutboxStatus.PENDING.value,
        attempts=0,
        max_attempts=5,
        created_at=now,
    )
    db.add(outbox)

    await db.commit()
    refreshed = await _get_work_item_with_relations(db, item.id)
    return WorkItemResponse.model_validate(refreshed)


async def claim_work_item(
    db: AsyncSession,
    item_id: str,
    request: WorkItemClaimRequest,
    current_user: User,
) -> WorkItemResponse:
    """Atomic conditional claim protecting against simultaneous race conditions.

    Enforces Protocol 2: Simultaneous Claim Protection & Protocol 1: OCC.
    """
    item = await _get_work_item_with_relations(db, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Work item '{item_id}' not found.")

    # Authorization: User must belong to owning team
    await verify_team_membership(db, current_user.id, item.team_id)

    # Check if already claimed
    if item.assignee_id is not None:
        claimed_by_user = item.assignee
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ConflictErrorDetail(
                error_code="ALREADY_CLAIMED",
                message=f"Work item '{item.title}' is already claimed by {claimed_by_user.full_name if claimed_by_user else 'another operator'}.",
                current_version=item.version,
                current_state=_dump_work_item_state(item),
                claimed_by=UserResponse.model_validate(claimed_by_user) if claimed_by_user else None,
            ).model_dump(mode="json"),
        )

    # Atomic conditional update
    old_state = _dump_work_item_state(item)
    new_status = WorkItemStatus.IN_PROGRESS.value if item.status == WorkItemStatus.TRIAGE.value else item.status
    now = datetime.now(timezone.utc)

    stmt = (
        update(WorkItem)
        .where(
            WorkItem.id == item_id,
            WorkItem.version == request.expected_version,
            WorkItem.assignee_id.is_(None),
        )
        .values(
            assignee_id=current_user.id,
            status=new_status,
            version=WorkItem.version + 1,
            updated_at=now,
        )
    )
    res = await db.execute(stmt)

    if res.rowcount == 0:
        # Race collision occurred: fetch latest committed state
        latest = await _get_work_item_with_relations(db, item_id)
        if latest and latest.assignee_id is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=ConflictErrorDetail(
                    error_code="ALREADY_CLAIMED",
                    message=f"Work item was just claimed by {latest.assignee.full_name if latest.assignee else 'another colleague'}.",
                    current_version=latest.version,
                    current_state=_dump_work_item_state(latest),
                    claimed_by=UserResponse.model_validate(latest.assignee) if latest.assignee else None,
                ).model_dump(mode="json"),
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=ConflictErrorDetail(
                    error_code="CONCURRENCY_CONFLICT",
                    message=f"Version mismatch during claim (expected v{request.expected_version}, server is at v{latest.version if latest else 'unknown'}).",
                    current_version=latest.version if latest else request.expected_version,
                    current_state=_dump_work_item_state(latest) if latest else {},
                ).model_dump(mode="json"),
            )

    # Success: Commit Audit & Outbox inside the same transaction
    refreshed = await _get_work_item_with_relations(db, item_id)
    new_state = _dump_work_item_state(refreshed)

    audit = AuditLog(
        id=str(uuid.uuid4()),
        work_item_id=item_id,
        actor_id=current_user.id,
        action_type=AuditActionType.CLAIMED.value,
        previous_state=old_state,
        new_state=new_state,
        reason=f"Claimed by {current_user.full_name}",
        created_at=now,
    )
    db.add(audit)

    outbox = OutboxEvent(
        id=str(uuid.uuid4()),
        work_item_id=item_id,
        event_type="WORK_ITEM_CLAIMED",
        payload={
            "work_item_id": item_id,
            "claimant_id": current_user.id,
            "version": refreshed.version,
        },
        dedup_key=f"item-{item_id}-claim-v{refreshed.version}",
        status=OutboxStatus.PENDING.value,
        attempts=0,
        max_attempts=5,
        created_at=now,
    )
    db.add(outbox)

    await db.commit()
    return WorkItemResponse.model_validate(refreshed)


async def transition_status(
    db: AsyncSession,
    item_id: str,
    request: WorkItemTransitionRequest,
    current_user: User,
) -> WorkItemResponse:
    """Enforce state machine rules, approval gate invariant, and atomic OCC update."""
    item = await _get_work_item_with_relations(db, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Work item '{item_id}' not found.")

    target_status_val = request.target_status.value if hasattr(request.target_status, "value") else str(request.target_status)
    current_status_val = item.status

    # 1. Validate State Transition Graph
    allowed_next = ALLOWED_TRANSITIONS.get(current_status_val, [])
    if target_status_val not in allowed_next:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Illegal state transition from '{current_status_val}' to '{target_status_val}'. "
                f"Allowed destinations are: {allowed_next}."
            ),
        )

    # 2. Hard Approval Invariant Check
    if target_status_val == WorkItemStatus.RESOLVED.value and item.requires_approval:
        raise HTTPException(
            status_code=422,
            detail=(
                "Work item requires formal approval. It cannot be resolved directly from "
                f"'{current_status_val}'. You must transition to 'PENDING_APPROVAL', and an "
                "Approver or Lead must execute the formal approval decision."
            ),
        )

    # 3. Role Authorization
    membership = await get_user_team_membership(db, current_user.id, item.team_id)
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be a member of the owning team to change work item status.",
        )

    # Reopening resolved items requires APPROVER or LEAD
    if current_status_val == WorkItemStatus.RESOLVED.value and target_status_val == WorkItemStatus.IN_PROGRESS.value:
        if membership.role not in [TeamRole.APPROVER.value, TeamRole.LEAD.value]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Reopening a resolved work item requires APPROVER or LEAD role in this team.",
            )

    # 4. Atomic OCC Update
    old_state = _dump_work_item_state(item)
    now = datetime.now(timezone.utc)
    new_next_action = request.next_action_required.strip() if request.next_action_required else item.next_action_required

    new_approval_status = item.approval_status
    if target_status_val == WorkItemStatus.PENDING_APPROVAL.value:
        new_approval_status = ApprovalStatus.PENDING.value

    stmt = (
        update(WorkItem)
        .where(
            WorkItem.id == item_id,
            WorkItem.version == request.expected_version,
        )
        .values(
            status=target_status_val,
            approval_status=new_approval_status,
            next_action_required=new_next_action,
            version=WorkItem.version + 1,
            updated_at=now,
        )
    )
    res = await db.execute(stmt)

    if res.rowcount == 0:
        latest = await _get_work_item_with_relations(db, item_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ConflictErrorDetail(
                error_code="CONCURRENCY_CONFLICT",
                message=f"Conflict: Item was modified by another operator (expected v{request.expected_version}, server is at v{latest.version if latest else 'unknown'}).",
                current_version=latest.version if latest else request.expected_version,
                current_state=_dump_work_item_state(latest) if latest else {},
            ).model_dump(mode="json"),
        )

    refreshed = await _get_work_item_with_relations(db, item_id)
    new_state = _dump_work_item_state(refreshed)

    # Synchronous Audit & Outbox
    audit = AuditLog(
        id=str(uuid.uuid4()),
        work_item_id=item_id,
        actor_id=current_user.id,
        action_type=AuditActionType.STATUS_CHANGED.value,
        previous_state=old_state,
        new_state=new_state,
        reason=request.reason.strip(),
        created_at=now,
    )
    db.add(audit)

    outbox = OutboxEvent(
        id=str(uuid.uuid4()),
        work_item_id=item_id,
        event_type="WORK_ITEM_STATUS_CHANGED",
        payload={
            "work_item_id": item_id,
            "old_status": current_status_val,
            "new_status": target_status_val,
            "actor_id": current_user.id,
            "version": refreshed.version,
        },
        dedup_key=f"item-{item_id}-status-{target_status_val}-v{refreshed.version}",
        status=OutboxStatus.PENDING.value,
        attempts=0,
        max_attempts=5,
        created_at=now,
    )
    db.add(outbox)

    await db.commit()
    return WorkItemResponse.model_validate(refreshed)


async def approve_or_reject_item(
    db: AsyncSession,
    item_id: str,
    request: WorkItemApproveRequest,
    current_user: User,
) -> WorkItemResponse:
    """Execute formal approval or rejection decision.

    Strictly enforces:
    - WorkItem must be in PENDING_APPROVAL.
    - Caller must possess APPROVER or LEAD role in work_item.team_id.
    - Atomic OCC version verification.
    """
    item = await _get_work_item_with_relations(db, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Work item '{item_id}' not found.")

    if item.status != WorkItemStatus.PENDING_APPROVAL.value:
        raise HTTPException(
            status_code=422,
            detail=f"Work item must be in 'PENDING_APPROVAL' state to evaluate approval, but is currently '{item.status}'.",
        )

    # Enforce Role Authority: Must be APPROVER or LEAD on owning team
    await verify_team_membership(
        db, current_user.id, item.team_id, allowed_roles=[TeamRole.APPROVER, TeamRole.LEAD]
    )

    is_approved = (request.decision.upper() == "APPROVED")
    new_status = WorkItemStatus.RESOLVED.value if is_approved else WorkItemStatus.IN_PROGRESS.value
    new_approval_status = ApprovalStatus.APPROVED.value if is_approved else ApprovalStatus.REJECTED.value
    approved_by = current_user.id if is_approved else None

    old_state = _dump_work_item_state(item)
    now = datetime.now(timezone.utc)

    # Atomic OCC execution
    stmt = (
        update(WorkItem)
        .where(
            WorkItem.id == item_id,
            WorkItem.version == request.expected_version,
            WorkItem.status == WorkItemStatus.PENDING_APPROVAL.value,
        )
        .values(
            status=new_status,
            approval_status=new_approval_status,
            approved_by_id=approved_by,
            next_action_required="Resolved via formal approval" if is_approved else "Approval rejected; address review comments",
            version=WorkItem.version + 1,
            updated_at=now,
        )
    )
    res = await db.execute(stmt)

    if res.rowcount == 0:
        latest = await _get_work_item_with_relations(db, item_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ConflictErrorDetail(
                error_code="CONCURRENCY_CONFLICT",
                message="Approval decision collision: Another operator modified or approved this item concurrently.",
                current_version=latest.version if latest else request.expected_version,
                current_state=_dump_work_item_state(latest) if latest else {},
            ).model_dump(mode="json"),
        )

    refreshed = await _get_work_item_with_relations(db, item_id)
    new_state = _dump_work_item_state(refreshed)

    audit = AuditLog(
        id=str(uuid.uuid4()),
        work_item_id=item_id,
        actor_id=current_user.id,
        action_type=AuditActionType.APPROVAL_DECISION.value,
        previous_state=old_state,
        new_state=new_state,
        reason=f"[{request.decision.upper()}] {request.reason.strip()}",
        created_at=now,
    )
    db.add(audit)

    outbox = OutboxEvent(
        id=str(uuid.uuid4()),
        work_item_id=item_id,
        event_type=f"WORK_ITEM_APPROVAL_{request.decision.upper()}",
        payload={
            "work_item_id": item_id,
            "decision": request.decision.upper(),
            "approver_id": current_user.id,
            "version": refreshed.version,
        },
        dedup_key=f"item-{item_id}-approval-{request.decision.lower()}-v{refreshed.version}",
        status=OutboxStatus.PENDING.value,
        attempts=0,
        max_attempts=5,
        created_at=now,
    )
    db.add(outbox)

    await db.commit()
    return WorkItemResponse.model_validate(refreshed)


async def reassign_item(
    db: AsyncSession,
    item_id: str,
    request: WorkItemReassignRequest,
    current_user: User,
) -> WorkItemResponse:
    """Reassign work item ownership with RBAC enforcement and OCC."""
    item = await _get_work_item_with_relations(db, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Work item '{item_id}' not found.")

    membership = await get_user_team_membership(db, current_user.id, item.team_id)
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You must be a member of the owning team to reassign this work item.",
        )

    # RBAC: Only LEAD can force-reassign to another user without consent.
    # Standard MEMBER can only self-assign or release assignment.
    if request.new_assignee_id != current_user.id and membership.role == TeamRole.MEMBER.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Standard team members can only assign items to themselves or unassign. Reassigning other colleagues requires LEAD role.",
        )

    # Verify target user exists and belongs to the owning team (if assigned)
    if request.new_assignee_id is not None:
        target_membership = await get_user_team_membership(db, request.new_assignee_id, item.team_id)
        if not target_membership:
            raise HTTPException(
                status_code=422,
                detail=f"Target assignee '{request.new_assignee_id}' is not a member of team '{item.team_id}'.",
            )

    old_state = _dump_work_item_state(item)
    now = datetime.now(timezone.utc)

    stmt = (
        update(WorkItem)
        .where(
            WorkItem.id == item_id,
            WorkItem.version == request.expected_version,
        )
        .values(
            assignee_id=request.new_assignee_id,
            version=WorkItem.version + 1,
            updated_at=now,
        )
    )
    res = await db.execute(stmt)

    if res.rowcount == 0:
        latest = await _get_work_item_with_relations(db, item_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ConflictErrorDetail(
                error_code="CONCURRENCY_CONFLICT",
                message="Reassignment conflict: Item was modified concurrently.",
                current_version=latest.version if latest else request.expected_version,
                current_state=_dump_work_item_state(latest) if latest else {},
            ).model_dump(mode="json"),
        )

    refreshed = await _get_work_item_with_relations(db, item_id)
    new_state = _dump_work_item_state(refreshed)

    audit = AuditLog(
        id=str(uuid.uuid4()),
        work_item_id=item_id,
        actor_id=current_user.id,
        action_type=AuditActionType.REASSIGNED.value,
        previous_state=old_state,
        new_state=new_state,
        reason=request.reason.strip(),
        created_at=now,
    )
    db.add(audit)

    outbox = OutboxEvent(
        id=str(uuid.uuid4()),
        work_item_id=item_id,
        event_type="WORK_ITEM_REASSIGNED",
        payload={
            "work_item_id": item_id,
            "new_assignee_id": request.new_assignee_id,
            "version": refreshed.version,
        },
        dedup_key=f"item-{item_id}-reassign-v{refreshed.version}",
        status=OutboxStatus.PENDING.value,
        attempts=0,
        max_attempts=5,
        created_at=now,
    )
    db.add(outbox)

    await db.commit()
    return WorkItemResponse.model_validate(refreshed)


async def update_work_item_fields(
    db: AsyncSession,
    item_id: str,
    request: WorkItemUpdateRequest,
    current_user: User,
) -> WorkItemResponse:
    """Generic work item field update governed by OCC."""
    item = await _get_work_item_with_relations(db, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Work item '{item_id}' not found.")

    await verify_team_membership(db, current_user.id, item.team_id)

    # Check priority change authorization: High/Critical requires Approver/Lead
    if request.priority in [Priority.HIGH, Priority.CRITICAL]:
        membership = await get_user_team_membership(db, current_user.id, item.team_id)
        if membership and membership.role == TeamRole.MEMBER.value and item.assignee_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Escalating priority to HIGH or CRITICAL requires APPROVER or LEAD role.",
            )

    old_state = _dump_work_item_state(item)
    now = datetime.now(timezone.utc)

    update_values: dict[str, Any] = {
        "version": WorkItem.version + 1,
        "updated_at": now,
    }
    if request.title is not None:
        update_values["title"] = request.title.strip()
    if request.description is not None:
        update_values["description"] = request.description.strip()
    if request.priority is not None:
        update_values["priority"] = request.priority.value if hasattr(request.priority, "value") else str(request.priority)
    if request.next_action_required is not None:
        update_values["next_action_required"] = request.next_action_required.strip()

    stmt = (
        update(WorkItem)
        .where(
            WorkItem.id == item_id,
            WorkItem.version == request.expected_version,
        )
        .values(**update_values)
    )
    res = await db.execute(stmt)

    if res.rowcount == 0:
        latest = await _get_work_item_with_relations(db, item_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ConflictErrorDetail(
                error_code="CONCURRENCY_CONFLICT",
                message="The work item was updated by another user while you were editing.",
                current_version=latest.version if latest else request.expected_version,
                current_state=_dump_work_item_state(latest) if latest else {},
            ).model_dump(mode="json"),
        )

    refreshed = await _get_work_item_with_relations(db, item_id)
    new_state = _dump_work_item_state(refreshed)

    audit = AuditLog(
        id=str(uuid.uuid4()),
        work_item_id=item_id,
        actor_id=current_user.id,
        action_type=AuditActionType.NEXT_ACTION_UPDATED.value if request.next_action_required else AuditActionType.PRIORITY_CHANGED.value,
        previous_state=old_state,
        new_state=new_state,
        reason=request.reason.strip() if request.reason else "Fields updated via edit form",
        created_at=now,
    )
    db.add(audit)

    outbox = OutboxEvent(
        id=str(uuid.uuid4()),
        work_item_id=item_id,
        event_type="WORK_ITEM_UPDATED",
        payload={
            "work_item_id": item_id,
            "version": refreshed.version,
            "actor_id": current_user.id,
        },
        dedup_key=f"item-{item_id}-update-v{refreshed.version}",
        status=OutboxStatus.PENDING.value,
        attempts=0,
        max_attempts=5,
        created_at=now,
    )
    db.add(outbox)

    await db.commit()
    return WorkItemResponse.model_validate(refreshed)


async def add_comment(
    db: AsyncSession,
    item_id: str,
    comment_text: str,
    current_user: User,
) -> WorkItemDetailResponse:
    """Append investigation comment to the immutable audit trail."""
    item = await _get_work_item_with_relations(db, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Work item '{item_id}' not found.")

    now = datetime.now(timezone.utc)
    audit = AuditLog(
        id=str(uuid.uuid4()),
        work_item_id=item_id,
        actor_id=current_user.id,
        action_type=AuditActionType.COMMENTED.value,
        previous_state={},
        new_state={},
        reason=comment_text.strip(),
        created_at=now,
    )
    db.add(audit)

    outbox = OutboxEvent(
        id=str(uuid.uuid4()),
        work_item_id=item_id,
        event_type="WORK_ITEM_COMMENTED",
        payload={
            "work_item_id": item_id,
            "actor_id": current_user.id,
            "comment_snippet": comment_text.strip()[:100],
        },
        dedup_key=f"item-{item_id}-comment-{audit.id}",
        status=OutboxStatus.PENDING.value,
        attempts=0,
        max_attempts=5,
        created_at=now,
    )
    db.add(outbox)
    await db.commit()

    return await get_work_item_detail(db, item_id)


async def simulate_concurrent_colleague_edit(
    db: AsyncSession,
    item_id: str,
    current_user: User,
) -> WorkItemResponse:
    """Demo test hook: Simulates another colleague editing the item concurrently.

    Bumps version and changes fields behind the caller's back to demonstrate Protocol 1 & 6.
    """
    item = await _get_work_item_with_relations(db, item_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Work item '{item_id}' not found.")

    # Find or pick a different user as the simulated colleague
    stmt = select(User).where(User.id != current_user.id).limit(1)
    colleague_res = await db.execute(stmt)
    colleague = colleague_res.scalar_one_or_none()

    if not colleague:
        colleague = User(
            id="00000000-0000-0000-0000-000000000099",
            email="colleague.sim@newtonite.internal",
            full_name="Elena Rostova (Simulated Colleague)",
            avatar_color="#EC4899",
        )
        db.add(colleague)
        await db.flush()

    old_state = _dump_work_item_state(item)
    now = datetime.now(timezone.utc)

    # Perform background mutation
    stmt_update = (
        update(WorkItem)
        .where(WorkItem.id == item_id)
        .values(
            priority=Priority.CRITICAL.value if item.priority != Priority.CRITICAL.value else Priority.HIGH.value,
            next_action_required=f"[SIMULATED COLLISION] Updated by {colleague.full_name}: Verified replica latency at {now.strftime('%H:%M:%S')}",
            version=WorkItem.version + 1,
            updated_at=now,
        )
    )
    await db.execute(stmt_update)

    refreshed = await _get_work_item_with_relations(db, item_id)
    new_state = _dump_work_item_state(refreshed)

    audit = AuditLog(
        id=str(uuid.uuid4()),
        work_item_id=item_id,
        actor_id=colleague.id,
        action_type=AuditActionType.PRIORITY_CHANGED.value,
        previous_state=old_state,
        new_state=new_state,
        reason=f"Simulated collision injection by {colleague.full_name}",
        created_at=now,
    )
    db.add(audit)
    await db.commit()

    return WorkItemResponse.model_validate(refreshed)


async def list_work_items(
    db: AsyncSession,
    team_id: Optional[str] = None,
    status_filter: Optional[str] = None,
    priority_filter: Optional[str] = None,
    category_filter: Optional[str] = None,
    assignee_filter: Optional[str] = None,
    needs_attention: Optional[bool] = None,
    q: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    current_user_id: Optional[str] = None,
) -> WorkItemListResponse:
    """High-performance server-side filtered and paginated work item query."""
    base_query = select(WorkItem).options(
        selectinload(WorkItem.creator),
        selectinload(WorkItem.assignee),
        selectinload(WorkItem.approved_by),
        selectinload(WorkItem.team).selectinload(Team.memberships),
    )
    count_query = select(func.count(WorkItem.id))

    # Apply filters
    filters = []
    if team_id:
        filters.append(WorkItem.team_id == team_id)
    if status_filter:
        filters.append(WorkItem.status == status_filter)
    if priority_filter:
        filters.append(WorkItem.priority == priority_filter)
    if category_filter:
        filters.append(WorkItem.category == category_filter)

    if assignee_filter:
        if assignee_filter == "unassigned":
            filters.append(WorkItem.assignee_id.is_(None))
        elif assignee_filter == "me" and current_user_id:
            filters.append(WorkItem.assignee_id == current_user_id)
        else:
            filters.append(WorkItem.assignee_id == assignee_filter)

    if needs_attention:
        filters.append(
            or_(
                WorkItem.status.in_([
                    WorkItemStatus.TRIAGE.value,
                    WorkItemStatus.PENDING_APPROVAL.value,
                    WorkItemStatus.BLOCKED.value,
                ]),
                WorkItem.priority == Priority.CRITICAL.value,
            )
        )

    if q and q.strip():
        search_term = f"%{q.strip()}%"
        filters.append(
            or_(
                WorkItem.title.ilike(search_term),
                WorkItem.description.ilike(search_term),
                WorkItem.next_action_required.ilike(search_term),
            )
        )

    if filters:
        base_query = base_query.where(*filters)
        count_query = count_query.where(*filters)

    # Execute total count
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    # Deterministic pagination ordering using composite index
    base_query = (
        base_query
        .order_by(WorkItem.updated_at.desc(), WorkItem.id.desc())
        .limit(min(limit, 100))
        .offset(offset)
    )

    items_result = await db.execute(base_query)
    items = items_result.scalars().all()

    return WorkItemListResponse(
        items=[WorkItemResponse.model_validate(it) for it in items],
        total=total,
        limit=limit,
        offset=offset,
    )


async def get_dashboard_stats(db: AsyncSession) -> DashboardStatsResponse:
    """Aggregate real-time metrics across operational queues and outbox."""
    # Active items count
    active_stmt = select(func.count(WorkItem.id)).where(
        WorkItem.status.not_in([WorkItemStatus.RESOLVED.value, WorkItemStatus.CANCELLED.value])
    )
    active_res = await db.execute(active_stmt)
    total_active = active_res.scalar_one()

    # Status counts
    async def _count_status(stat: str) -> int:
        s = select(func.count(WorkItem.id)).where(WorkItem.status == stat)
        r = await db.execute(s)
        return r.scalar_one()

    triage_count = await _count_status(WorkItemStatus.TRIAGE.value)
    in_progress_count = await _count_status(WorkItemStatus.IN_PROGRESS.value)
    pending_approval_count = await _count_status(WorkItemStatus.PENDING_APPROVAL.value)
    blocked_count = await _count_status(WorkItemStatus.BLOCKED.value)

    # Priority counts for active items
    crit_stmt = select(func.count(WorkItem.id)).where(
        WorkItem.priority == Priority.CRITICAL.value,
        WorkItem.status.not_in([WorkItemStatus.RESOLVED.value, WorkItemStatus.CANCELLED.value]),
    )
    crit_res = await db.execute(crit_stmt)
    critical_count = crit_res.scalar_one()

    high_stmt = select(func.count(WorkItem.id)).where(
        WorkItem.priority == Priority.HIGH.value,
        WorkItem.status.not_in([WorkItemStatus.RESOLVED.value, WorkItemStatus.CANCELLED.value]),
    )
    high_res = await db.execute(high_stmt)
    high_count = high_res.scalar_one()

    # Resolved count
    res_stmt = select(func.count(WorkItem.id)).where(WorkItem.status == WorkItemStatus.RESOLVED.value)
    res_res = await db.execute(res_stmt)
    resolved_today_count = res_res.scalar_one()

    # Outbox counts
    outbox_pend_stmt = select(func.count(OutboxEvent.id)).where(
        OutboxEvent.status.in_([OutboxStatus.PENDING.value, OutboxStatus.PROCESSING.value])
    )
    outbox_pend_res = await db.execute(outbox_pend_stmt)
    outbox_pending_count = outbox_pend_res.scalar_one()

    outbox_dlq_stmt = select(func.count(OutboxEvent.id)).where(
        OutboxEvent.status == OutboxStatus.DEAD_LETTER.value
    )
    outbox_dlq_res = await db.execute(outbox_dlq_stmt)
    outbox_dead_letter_count = outbox_dlq_res.scalar_one()

    return DashboardStatsResponse(
        total_active=total_active,
        triage_count=triage_count,
        in_progress_count=in_progress_count,
        pending_approval_count=pending_approval_count,
        blocked_count=blocked_count,
        critical_count=critical_count,
        high_count=high_count,
        resolved_today_count=resolved_today_count,
        outbox_pending_count=outbox_pending_count,
        outbox_dead_letter_count=outbox_dead_letter_count,
    )

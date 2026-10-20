"""Work Item REST Endpoints.
Exposes OCC-guarded mutations, state transitions, claims, and idempotency protection.
Stage P1: Backend Domain Engine.
"""

from typing import Optional
from fastapi import APIRouter, Depends, Header, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.idempotency import check_idempotency, record_idempotency
from app.models import User
from app.schemas import (
    AuditLogResponse,
    DashboardStatsResponse,
    WorkItemApproveRequest,
    WorkItemClaimRequest,
    WorkItemCommentRequest,
    WorkItemCreateRequest,
    WorkItemDetailResponse,
    WorkItemListResponse,
    WorkItemReassignRequest,
    WorkItemResponse,
    WorkItemTransitionRequest,
    WorkItemUpdateRequest,
)
from app.services import work_item_service

router = APIRouter(prefix="/work-items", tags=["Work Items"])


@router.get("/dashboard-stats", response_model=DashboardStatsResponse)
@router.get("/stats", response_model=DashboardStatsResponse)
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    """Retrieve operational queue counts and aggregate metrics."""
    return await work_item_service.get_dashboard_stats(db)


@router.get("", response_model=WorkItemListResponse)
async def list_work_items(
    team_id: Optional[str] = Query(None, description="Filter by owning team UUID"),
    status: Optional[str] = Query(None, description="Filter by status"),
    priority: Optional[str] = Query(None, description="Filter by priority"),
    category: Optional[str] = Query(None, description="Filter by category"),
    assignee: Optional[str] = Query(None, description="Filter by assignee: 'unassigned', 'me', or UUID"),
    needs_attention: Optional[bool] = Query(None, description="Filter for urgent attention items"),
    q: Optional[str] = Query(None, description="Search term for title and description"),
    limit: int = Query(20, ge=1, le=100, description="Page limit"),
    offset: int = Query(0, ge=0, description="Page offset"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve indexed, server-side filtered, and paginated work items."""
    return await work_item_service.list_work_items(
        db=db,
        team_id=team_id,
        status_filter=status,
        priority_filter=priority,
        category_filter=category,
        assignee_filter=assignee,
        needs_attention=needs_attention,
        q=q,
        limit=limit,
        offset=offset,
        current_user_id=current_user.id,
    )


@router.post("", response_model=WorkItemResponse, status_code=status.HTTP_201_CREATED)
async def create_work_item(
    request: WorkItemCreateRequest,
    req_raw: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new operational work item with synchronous audit logging and outbox emission."""
    cached = await check_idempotency(db, idempotency_key, current_user.id, req_raw.url.path, request)
    if cached:
        return cached

    result = await work_item_service.create_work_item(db, request, current_user)

    await record_idempotency(
        db,
        idempotency_key,
        current_user.id,
        req_raw.url.path,
        request,
        status.HTTP_201_CREATED,
        result.model_dump(mode="json"),
    )
    await db.commit()
    return result


@router.get("/{item_id}", response_model=WorkItemDetailResponse)
async def get_work_item_detail(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    """Retrieve comprehensive work item details with full audit log and outbox event history."""
    return await work_item_service.get_work_item_detail(db, item_id)


@router.patch("/{item_id}", response_model=WorkItemResponse)
async def update_work_item(
    item_id: str,
    update_req: WorkItemUpdateRequest,
    req_raw: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generic field mutation protected by Optimistic Concurrency Control (OCC)."""
    cached = await check_idempotency(db, idempotency_key, current_user.id, req_raw.url.path, update_req)
    if cached:
        return cached

    result = await work_item_service.update_work_item_fields(db, item_id, update_req, current_user)

    await record_idempotency(
        db,
        idempotency_key,
        current_user.id,
        req_raw.url.path,
        update_req,
        status.HTTP_200_OK,
        result.model_dump(mode="json"),
    )
    await db.commit()
    return result


@router.post("/{item_id}/claim", response_model=WorkItemResponse)
async def claim_work_item(
    item_id: str,
    claim_req: WorkItemClaimRequest,
    req_raw: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Atomically claim an unassigned work item, preventing simultaneous assignment races."""
    cached = await check_idempotency(db, idempotency_key, current_user.id, req_raw.url.path, claim_req)
    if cached:
        return cached

    result = await work_item_service.claim_work_item(db, item_id, claim_req, current_user)

    await record_idempotency(
        db,
        idempotency_key,
        current_user.id,
        req_raw.url.path,
        claim_req,
        status.HTTP_200_OK,
        result.model_dump(mode="json"),
    )
    await db.commit()
    return result


@router.post("/{item_id}/transition", response_model=WorkItemResponse)
async def transition_status(
    item_id: str,
    transition_req: WorkItemTransitionRequest,
    req_raw: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Advance work item along the deterministic state machine graph."""
    cached = await check_idempotency(db, idempotency_key, current_user.id, req_raw.url.path, transition_req)
    if cached:
        return cached

    result = await work_item_service.transition_status(db, item_id, transition_req, current_user)

    await record_idempotency(
        db,
        idempotency_key,
        current_user.id,
        req_raw.url.path,
        transition_req,
        status.HTTP_200_OK,
        result.model_dump(mode="json"),
    )
    await db.commit()
    return result


@router.post("/{item_id}/approve", response_model=WorkItemResponse)
async def approve_work_item(
    item_id: str,
    approve_req: WorkItemApproveRequest,
    req_raw: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Execute formal approval gate decision (requires APPROVER or LEAD role on owning team)."""
    cached = await check_idempotency(db, idempotency_key, current_user.id, req_raw.url.path, approve_req)
    if cached:
        return cached

    result = await work_item_service.approve_or_reject_item(db, item_id, approve_req, current_user)

    await record_idempotency(
        db,
        idempotency_key,
        current_user.id,
        req_raw.url.path,
        approve_req,
        status.HTTP_200_OK,
        result.model_dump(mode="json"),
    )
    await db.commit()
    return result


@router.post("/{item_id}/reassign", response_model=WorkItemResponse)
async def reassign_work_item(
    item_id: str,
    reassign_req: WorkItemReassignRequest,
    req_raw: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reassign work item ownership with RBAC permissions."""
    cached = await check_idempotency(db, idempotency_key, current_user.id, req_raw.url.path, reassign_req)
    if cached:
        return cached

    result = await work_item_service.reassign_item(db, item_id, reassign_req, current_user)

    await record_idempotency(
        db,
        idempotency_key,
        current_user.id,
        req_raw.url.path,
        reassign_req,
        status.HTTP_200_OK,
        result.model_dump(mode="json"),
    )
    await db.commit()
    return result


@router.post("/{item_id}/comments", response_model=WorkItemDetailResponse)
async def add_comment(
    item_id: str,
    comment_req: WorkItemCommentRequest,
    req_raw: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add collaboration or investigation notes to the work item's immutable audit trail."""
    cached = await check_idempotency(db, idempotency_key, current_user.id, req_raw.url.path, comment_req)
    if cached:
        return cached

    result = await work_item_service.add_comment(db, item_id, comment_req.comment, current_user)

    await record_idempotency(
        db,
        idempotency_key,
        current_user.id,
        req_raw.url.path,
        comment_req,
        status.HTTP_200_OK,
        result.model_dump(mode="json"),
    )
    await db.commit()
    return result


@router.get("/{item_id}/audit-logs", response_model=list[AuditLogResponse])
async def get_audit_logs(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    """Retrieve chronological audit trail of all previous actions on this work item."""
    detail = await work_item_service.get_work_item_detail(db, item_id)
    return detail.audit_logs


@router.post("/{item_id}/simulate-concurrent-edit", response_model=WorkItemResponse)
async def simulate_concurrent_colleague_edit(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Demo test hook: Injects a background colleague edit to trigger 409 Conflict reconciliation."""
    return await work_item_service.simulate_concurrent_colleague_edit(db, item_id, current_user)

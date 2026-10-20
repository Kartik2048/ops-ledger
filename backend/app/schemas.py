"""Pydantic v2 Request, Response, and Error Schemas.
Strictly mapped to ARCHITECTURE.md specifications.
Stage A: Approved & Locked Contract.
"""

from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field
from app.models import (
    ApprovalStatus,
    AuditActionType,
    OutboxStatus,
    Priority,
    TeamRole,
    WorkItemCategory,
    WorkItemStatus,
)


# =====================================================================
# USER & TEAM SCHEMAS
# =====================================================================

class UserResponse(BaseModel):
    """User representation response."""
    id: str
    email: str
    full_name: str
    avatar_color: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TeamMembershipResponse(BaseModel):
    """Team membership representation."""
    id: str
    user_id: str
    team_id: str
    role: TeamRole
    created_at: datetime
    user: UserResponse | None = None

    model_config = ConfigDict(from_attributes=True)


class TeamResponse(BaseModel):
    """Operational team representation."""
    id: str
    name: str
    slug: str
    description: str
    created_at: datetime
    memberships: list[TeamMembershipResponse] = []
    member_count: int | None = None

    model_config = ConfigDict(from_attributes=True)


class UserDetailResponse(UserResponse):
    """Authenticated user context with team memberships."""
    memberships: list[TeamMembershipResponse] = []

    model_config = ConfigDict(from_attributes=True)


# =====================================================================
# WORK ITEM REQUEST SCHEMAS (MUTATIONS REQUIRE expected_version)
# =====================================================================

class WorkItemCreateRequest(BaseModel):
    """Payload to create a new operational work item."""
    title: str = Field(..., min_length=3, max_length=255, description="Brief summary of the issue or task")
    description: str = Field(..., min_length=1, description="Exhaustive description, context, or reproduction steps")
    category: WorkItemCategory = Field(..., description="Operational category")
    priority: Priority = Field(default=Priority.MEDIUM, description="Initial priority level")
    team_id: str = Field(..., description="UUID of the owning operational team")
    requires_approval: bool = Field(default=False, description="Whether resolution requires formal approval")
    next_action_required: str = Field(
        default="Initial triage required",
        max_length=500,
        description="Explicit description of the next action needed",
    )


class WorkItemClaimRequest(BaseModel):
    """Atomic conditional claim request."""
    expected_version: int = Field(..., ge=1, description="Expected current version for OCC verification")


class WorkItemTransitionRequest(BaseModel):
    """Deterministic status transition request."""
    expected_version: int = Field(..., ge=1, description="Expected current version for OCC verification")
    target_status: WorkItemStatus = Field(..., description="Target status in the state machine")
    next_action_required: str | None = Field(
        default=None, max_length=500, description="Updated next action or blocker description"
    )
    reason: str = Field(..., min_length=1, description="Audit reason justifying the transition")


class WorkItemApproveRequest(BaseModel):
    """Formal approval decision by team approver or lead."""
    expected_version: int = Field(..., ge=1, description="Expected current version for OCC verification")
    decision: str = Field(..., pattern="^(APPROVED|REJECTED)$", description="'APPROVED' or 'REJECTED'")
    reason: str = Field(..., min_length=1, description="Mandatory justification for audit provenance")


class WorkItemReassignRequest(BaseModel):
    """Reassign work item to a new owner or release to unassigned."""
    expected_version: int = Field(..., ge=1, description="Expected current version for OCC verification")
    new_assignee_id: str | None = Field(default=None, description="UUID of target user, or null to unassign")
    reason: str = Field(..., min_length=1, description="Audit reason for reassignment")


class WorkItemUpdateRequest(BaseModel):
    """Generic work item field update governed by OCC."""
    expected_version: int = Field(..., ge=1, description="Expected current version for OCC verification")
    title: str | None = Field(default=None, min_length=3, max_length=255)
    description: str | None = Field(default=None, min_length=1)
    priority: Priority | None = None
    next_action_required: str | None = Field(default=None, max_length=500)
    reason: str = Field(default="", description="Audit reason explaining edits")


class WorkItemCommentRequest(BaseModel):
    """Append investigation notes or collaboration comments."""
    comment: str = Field(..., min_length=1, description="Comment text")


# =====================================================================
# AUDIT & OUTBOX SCHEMAS
# =====================================================================

class AuditLogResponse(BaseModel):
    """Immutable audit trail entry."""
    id: str
    work_item_id: str
    actor_id: str
    action_type: AuditActionType
    previous_state: dict[str, Any]
    new_state: dict[str, Any]
    reason: str
    created_at: datetime
    actor: UserResponse | None = None

    model_config = ConfigDict(from_attributes=True)


class OutboxEventResponse(BaseModel):
    """Transactional outbox event."""
    id: str
    work_item_id: str
    event_type: str
    payload: dict[str, Any]
    dedup_key: str
    status: OutboxStatus
    attempts: int
    max_attempts: int
    next_retry_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OutboxQueueSummaryResponse(BaseModel):
    """Aggregate outbox queue metrics and event list."""
    events: list[OutboxEventResponse]
    total: int
    counts_by_status: dict[str, int]


class OutboxBatchResultResponse(BaseModel):
    """Summary of batch processing execution."""
    processed: int
    completed: int
    failed: int
    dead_letter: int
    timestamp: datetime


# =====================================================================
# WORK ITEM RESPONSE SCHEMAS
# =====================================================================

class WorkItemResponse(BaseModel):
    """Standard work item response representation."""
    id: str
    title: str
    description: str
    category: WorkItemCategory
    status: WorkItemStatus
    priority: Priority
    team_id: str
    creator_id: str
    assignee_id: str | None = None
    next_action_required: str
    requires_approval: bool
    approval_status: ApprovalStatus
    approved_by_id: str | None = None
    version: int
    created_at: datetime
    updated_at: datetime

    creator: UserResponse | None = None
    assignee: UserResponse | None = None
    approved_by: UserResponse | None = None
    team: TeamResponse | None = None

    model_config = ConfigDict(from_attributes=True)


class WorkItemDetailResponse(WorkItemResponse):
    """Detailed work item view including full audit log trail and outbox events."""
    audit_logs: list[AuditLogResponse] = []
    outbox_events: list[OutboxEventResponse] = []

    model_config = ConfigDict(from_attributes=True)


class WorkItemListResponse(BaseModel):
    """Paginated list envelope for high-scale triage views."""
    items: list[WorkItemResponse]
    total: int
    limit: int
    offset: int


class DashboardStatsResponse(BaseModel):
    """Real-time operational dashboard aggregate metrics."""
    total_active: int
    triage_count: int
    in_progress_count: int
    pending_approval_count: int
    blocked_count: int
    critical_count: int
    high_count: int
    resolved_today_count: int
    outbox_pending_count: int
    outbox_dead_letter_count: int


# =====================================================================
# ERROR & CONFLICT SCHEMAS
# =====================================================================

class ConflictErrorDetail(BaseModel):
    """Structured HTTP 409 conflict detail for OCC and claim collisions."""
    error_code: str = Field(..., description="'CONCURRENCY_CONFLICT' or 'ALREADY_CLAIMED'")
    message: str
    current_version: int
    current_state: dict[str, Any]
    claimed_by: UserResponse | None = None


class StandardErrorResponse(BaseModel):
    """Standardized API error envelope."""
    error_code: str
    message: str
    details: dict[str, Any] = {}
    timestamp: datetime = Field(default_factory=datetime.utcnow)

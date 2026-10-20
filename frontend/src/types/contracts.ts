/**
 * Locked TypeScript Contracts for Newtonite Operations Platform.
 * Strict 1:1 parity with backend/app/schemas.py and backend/app/models.py.
 * Stage A: Approved & Locked Contract.
 */

// =====================================================================
// ENUMS & STRING LITERAL UNIONS
// =====================================================================

export type TeamRole = 'MEMBER' | 'APPROVER' | 'LEAD';

export type WorkItemCategory =
  | 'CUSTOMER_ISSUE'
  | 'ENGINEERING_PROBLEM'
  | 'PAYMENT_INVESTIGATION'
  | 'PRODUCTION_INCIDENT'
  | 'COMPLIANCE_REQUEST'
  | 'OPERATIONAL_APPROVAL';

export type Priority = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

export type WorkItemStatus =
  | 'TRIAGE'
  | 'IN_PROGRESS'
  | 'PENDING_APPROVAL'
  | 'BLOCKED'
  | 'RESOLVED'
  | 'CANCELLED';

export type ApprovalStatus =
  | 'NOT_REQUIRED'
  | 'PENDING'
  | 'APPROVED'
  | 'REJECTED';

export type AuditActionType =
  | 'CREATED'
  | 'CLAIMED'
  | 'REASSIGNED'
  | 'STATUS_CHANGED'
  | 'PRIORITY_CHANGED'
  | 'APPROVAL_DECISION'
  | 'COMMENTED'
  | 'NEXT_ACTION_UPDATED';

export type OutboxStatus =
  | 'PENDING'
  | 'PROCESSING'
  | 'COMPLETED'
  | 'FAILED'
  | 'DEAD_LETTER';

// =====================================================================
// USER & TEAM INTERFACES
// =====================================================================

export interface UserResponse {
  id: string;
  email: string;
  full_name: string;
  avatar_color: string;
  created_at: string;
}

export interface TeamMembershipResponse {
  id: string;
  user_id: string;
  team_id: string;
  role: TeamRole;
  created_at: string;
  user?: UserResponse | null;
}

export interface TeamResponse {
  id: string;
  name: string;
  slug: string;
  description: string;
  created_at: string;
  memberships?: TeamMembershipResponse[];
  member_count?: number | null;
}

export interface UserDetailResponse extends UserResponse {
  memberships: TeamMembershipResponse[];
}

// =====================================================================
// WORK ITEM MUTATION REQUESTS (REQUIRE expected_version)
// =====================================================================

export interface WorkItemCreateRequest {
  title: string;
  description: string;
  category: WorkItemCategory;
  priority: Priority;
  team_id: string;
  requires_approval: boolean;
  next_action_required: string;
}

export interface WorkItemClaimRequest {
  expected_version: number;
}

export interface WorkItemTransitionRequest {
  expected_version: number;
  target_status: WorkItemStatus;
  next_action_required?: string | null;
  reason: string;
}

export interface WorkItemApproveRequest {
  expected_version: number;
  decision: 'APPROVED' | 'REJECTED';
  reason: string;
}

export interface WorkItemReassignRequest {
  expected_version: number;
  new_assignee_id?: string | null;
  reason: string;
}

export interface WorkItemUpdateRequest {
  expected_version: number;
  title?: string | null;
  description?: string | null;
  priority?: Priority | null;
  next_action_required?: string | null;
  reason?: string;
}

export interface WorkItemCommentRequest {
  comment: string;
}

// =====================================================================
// AUDIT & OUTBOX INTERFACES
// =====================================================================

export interface AuditLogResponse {
  id: string;
  work_item_id: string;
  actor_id: string;
  action_type: AuditActionType;
  previous_state: Record<string, unknown>;
  new_state: Record<string, unknown>;
  reason: string;
  created_at: string;
  actor?: UserResponse | null;
}

export interface OutboxEventResponse {
  id: string;
  work_item_id: string;
  event_type: string;
  payload: Record<string, unknown>;
  dedup_key: string;
  status: OutboxStatus;
  attempts: number;
  max_attempts: number;
  next_retry_at?: string | null;
  last_error?: string | null;
  created_at: string;
}

export interface OutboxQueueSummaryResponse {
  events: OutboxEventResponse[];
  total: number;
  counts_by_status: Record<string, number>;
}

export interface OutboxBatchResultResponse {
  processed: number;
  completed: number;
  failed: number;
  dead_letter: number;
  timestamp: string;
}

// =====================================================================
// WORK ITEM RESPONSE INTERFACES
// =====================================================================

export interface WorkItemResponse {
  id: string;
  title: string;
  description: string;
  category: WorkItemCategory;
  status: WorkItemStatus;
  priority: Priority;
  team_id: string;
  creator_id: string;
  assignee_id?: string | null;
  next_action_required: string;
  requires_approval: boolean;
  approval_status: ApprovalStatus;
  approved_by_id?: string | null;
  version: number;
  created_at: string;
  updated_at: string;

  creator?: UserResponse | null;
  assignee?: UserResponse | null;
  approved_by?: UserResponse | null;
  team?: TeamResponse | null;
}

export interface WorkItemDetailResponse extends WorkItemResponse {
  audit_logs: AuditLogResponse[];
  outbox_events: OutboxEventResponse[];
}

export interface WorkItemListResponse {
  items: WorkItemResponse[];
  total: number;
  limit: number;
  offset: number;
}

export interface DashboardStatsResponse {
  total_active: number;
  triage_count: number;
  in_progress_count: number;
  pending_approval_count: number;
  blocked_count: number;
  critical_count: number;
  high_count: number;
  resolved_today_count: number;
  outbox_pending_count: number;
  outbox_dead_letter_count: number;
}

// =====================================================================
// ERROR & CONFLICT INTERFACES
// =====================================================================

export interface ConflictErrorDetail {
  error_code: 'CONCURRENCY_CONFLICT' | 'ALREADY_CLAIMED';
  message: string;
  current_version: number;
  current_state: Partial<WorkItemResponse> | Record<string, unknown>;
  claimed_by?: UserResponse | null;
}

export interface StandardErrorResponse {
  error_code: string;
  message: string;
  details: Record<string, unknown>;
  timestamp: string;
}

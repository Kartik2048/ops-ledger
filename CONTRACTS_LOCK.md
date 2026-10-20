# Stage A: Contract Lock Manifest
**Lock Date:** 2026-10-20  
**Status:** LOCKED & SEALED  
**Framework Stage:** Stage A (Approval & Contract Lock)

---

## 1. Locked System Enums & Literal Types

| Enum / Type | Values | Backend Location | Frontend Location |
| :--- | :--- | :--- | :--- |
| **`TeamRole`** | `MEMBER`, `APPROVER`, `LEAD` | `app.models.TeamRole` | `TeamRole` in `contracts.ts` |
| **`WorkItemCategory`** | `CUSTOMER_ISSUE`, `ENGINEERING_PROBLEM`, `PAYMENT_INVESTIGATION`, `PRODUCTION_INCIDENT`, `COMPLIANCE_REQUEST`, `OPERATIONAL_APPROVAL` | `app.models.WorkItemCategory` | `WorkItemCategory` in `contracts.ts` |
| **`Priority`** | `LOW`, `MEDIUM`, `HIGH`, `CRITICAL` | `app.models.Priority` | `Priority` in `contracts.ts` |
| **`WorkItemStatus`** | `TRIAGE`, `IN_PROGRESS`, `PENDING_APPROVAL`, `BLOCKED`, `RESOLVED`, `CANCELLED` | `app.models.WorkItemStatus` | `WorkItemStatus` in `contracts.ts` |
| **`ApprovalStatus`** | `NOT_REQUIRED`, `PENDING`, `APPROVED`, `REJECTED` | `app.models.ApprovalStatus` | `ApprovalStatus` in `contracts.ts` |
| **`AuditActionType`** | `CREATED`, `CLAIMED`, `REASSIGNED`, `STATUS_CHANGED`, `PRIORITY_CHANGED`, `APPROVAL_DECISION`, `COMMENTED`, `NEXT_ACTION_UPDATED` | `app.models.AuditActionType` | `AuditActionType` in `contracts.ts` |
| **`OutboxStatus`** | `PENDING`, `PROCESSING`, `COMPLETED`, `FAILED`, `DEAD_LETTER` | `app.models.OutboxStatus` | `OutboxStatus` in `contracts.ts` |

---

## 2. Locked Relational Models (`backend/app/models.py`)

- **`User`**: `id`, `email`, `full_name`, `avatar_color`, `created_at`
- **`Team`**: `id`, `name`, `slug`, `description`, `created_at`
- **`TeamMembership`**: `id`, `user_id`, `team_id`, `role`, `created_at` (Unique: `user_id, team_id`)
- **`WorkItem`**: `id`, `title`, `description`, `category`, `status`, `priority`, `team_id`, `creator_id`, `assignee_id`, `next_action_required`, `requires_approval`, `approval_status`, `approved_by_id`, `version`, `created_at`, `updated_at`
  - *Indexes:* `idx_work_items_team_status_prio`, `idx_work_items_assignee_status`, `idx_work_items_pagination`, `idx_work_items_category`
- **`AuditLog`**: `id`, `work_item_id`, `actor_id`, `action_type`, `previous_state`, `new_state`, `reason`, `created_at`
  - *Indexes:* `idx_audit_logs_item_created`, `idx_audit_logs_actor`
- **`IdempotencyRecord`**: `key`, `user_id`, `endpoint`, `request_hash`, `status_code`, `response_body`, `created_at`
  - *Indexes:* `idx_idempotency_user`, `idx_idempotency_created`
- **`OutboxEvent`**: `id`, `work_item_id`, `event_type`, `payload`, `dedup_key`, `status`, `attempts`, `max_attempts`, `next_retry_at`, `last_error`, `created_at`
  - *Indexes:* `idx_outbox_processing`

---

## 3. Locked Request & Response DTOs

| DTO Name | Purpose | Concurrency Guard |
| :--- | :--- | :--- |
| **`UserResponse` / `UserDetailResponse`** | User context & team memberships | N/A |
| **`TeamResponse` / `TeamMembershipResponse`** | Team details & membership directory | N/A |
| **`WorkItemCreateRequest`** | Initial item creation | Header: `Idempotency-Key` |
| **`WorkItemClaimRequest`** | Atomic claim | **`expected_version: int`** + Header: `Idempotency-Key` |
| **`WorkItemTransitionRequest`** | State transition | **`expected_version: int`** + Header: `Idempotency-Key` |
| **`WorkItemApproveRequest`** | Approval / Rejection | **`expected_version: int`** + Header: `Idempotency-Key` |
| **`WorkItemReassignRequest`** | Owner reassignment | **`expected_version: int`** + Header: `Idempotency-Key` |
| **`WorkItemUpdateRequest`** | Field mutations | **`expected_version: int`** + Header: `Idempotency-Key` |
| **`WorkItemCommentRequest`** | Investigation notes | Synchronous audit logging |
| **`WorkItemResponse` / `WorkItemDetailResponse`** | Single item projection & detail | Contains `version: int` |
| **`WorkItemListResponse`** | High-scale paginated envelope | Contains `items`, `total`, `limit`, `offset` |
| **`DashboardStatsResponse`** | Real-time queue metrics | N/A |
| **`AuditLogResponse`** | Immutable provenance item | N/A |
| **`OutboxEventResponse`** | Asynchronous outbox item | Contains `attempts`, `max_attempts`, `dedup_key` |
| **`ConflictErrorDetail`** | HTTP 409 diff payload | Contains `error_code`, `current_version`, `current_state` |
| **`StandardErrorResponse`** | Structured API error payload | `error_code`, `message`, `details`, `timestamp` |

---

## 4. Invariant Rule of Engagement

> **CRITICAL ARCHITECTURAL RULE:**  
> All subsequent Phase Development (P1–P4) modules must import directly from `backend/app/models.py`, `backend/app/schemas.py`, and `frontend/src/types/contracts.ts` without renaming fields or bypassing `expected_version` and `Idempotency-Key` requirements.

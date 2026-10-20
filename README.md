# Newtonite: Operations Under Pressure Platform

> **A mission-critical operational coordination console built with React 18, TypeScript, FastAPI, and SQLite WAL.**  
> Designed to replace unstructured chat messages, shared spreadsheets, and direct emails with enforceable operational rigor, deterministic concurrency controls, and verifiable audit trails.

---

## Table of Contents
1. [System Architecture](#system-architecture)
2. [The 6 Beyond-CRUD Correctness Protocols](#the-6-beyond-crud-correctness-protocols)
3. [Quickstart & Running Instructions](#quickstart--running-instructions)
4. [2-Minute Evaluator Tour & Interactive Demo Guide](#2-minute-evaluator-tour--interactive-demo-guide)
5. [Automated Test Suite Verification](#automated-test-suite-verification)
6. [Known Limitations & Architectural Trade-Offs](#known-limitations--architectural-trade-offs)
7. [Comprehensive Architectural Discussion](#comprehensive-architectural-discussion)
   - [1. How the Architecture Works](#1-how-the-architecture-works)
   - [2. What Happens When Things Fail](#2-what-happens-when-things-fail)
   - [3. Key Assumptions](#3-key-assumptions)
   - [4. The Most Important Components](#4-the-most-important-components)
   - [5. What Changes at 100x Scale](#5-what-changes-at-100x-scale)
   - [6. What to Build Given Another Week](#6-what-to-build-given-another-week)

---

## System Architecture

```
                      +-------------------------------------------------------+
                      |         REACT 18 + TYPESCRIPT OPERATIONAL UI          |
                      |   (Vite, TanStack Query, Tailwind CSS, Lucide React)  |
                      +-------------------------------------------------------+
                                  |                               |
                   X-User-Id / Persona Switcher       Idempotency-Key Header
                   (Alice, Bob, Charlie, etc.)        & OCC expected_version
                                  |                               |
                                  v                               v
                      +-------------------------------------------------------+
                      |                   FASTAPI GATEWAY                     |
                      |           /api/work-items  |  /api/outbox             |
                      +-------------------------------------------------------+
                                  |                               |
            +---------------------+-------------------+           |
            |                                         |           |
            v                                         v           v
+-----------------------+                 +-------------------------------+
|  RESOURCE-LEVEL RBAC  |                 |      IDEMPOTENCY GUARD        |
| verify_team_membership|                 | SHA-256 Hash + Replay Cache   |
| Lead / Approver / Mem |                 | Returns cached X-Cache-Lookup |
+-----------------------+                 +-------------------------------+
            |                                         |
            +---------------------+-------------------+
                                  |
                                  v
                      +-------------------------------------------------------+
                      |               CORE DOMAIN SERVICE ENGINE              |
                      |          work_item_service.py (OCC Engine)            |
                      +-------------------------------------------------------+
                                  |
                                  | Atomic Single-Commit Transaction
                                  | (WorkItem + AuditLog + OutboxEvent)
                                  v
+-----------------------------------------------------------------------------------------------+
|                             SQLITE 3 WITH WAL (Write-Ahead-Logging)                          |
|  - PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000; PRAGMA foreign_keys=ON;                 |
|                                                                                               |
|  +--------------------+     +------------------------+     +-------------------------------+  |
|  |    work_items      |     |       audit_logs       |     |        outbox_events          |  |
|  | - id, title        |     | - work_item_id         |     | - work_item_id                |  |
|  | - status, version  |     | - actor_id, action_type|     | - event_type, payload (JSON)  |  |
|  | - next_action      |     | - prev_state, new_state|     | - dedup_key, status (PENDING) |  |
|  | - assignee_id      |     | - reason (mandatory)   |     | - attempts, max_attempts (5)  |  |
|  +--------------------+     +------------------------+     +-------------------------------+  |
+-----------------------------------------------------------------------------------------------+
                                                              |
                                                              | Polls PENDING / FAILED
                                                              v
                                              +-------------------------------+
                                              |   TRANSACTIONAL OUTBOX WORKER |
                                              |       worker.py (Async Task)  |
                                              | - Exponential Backoff: 2^n s  |
                                              | - Max 5 attempts -> DLQ       |
                                              | - Idempotent Dispatch via dedup|
                                              +-------------------------------+
```

---

## The 6 Beyond-CRUD Correctness Protocols

The application strictly implements 6 beyond-CRUD operational correctness protocols:

| Protocol | Operational Problem | Engineering Mechanism | Verifiable Behavior |
| :--- | :--- | :--- | :--- |
| **1. Optimistic Concurrency Control (OCC)** | Two operators open the same incident; Operator B overwrites Operator A's work without knowing. | Every mutation requires `expected_version`. DB updates execute `WHERE id=:id AND version=:expected_version`. | Mismatched version aborts update and returns **`HTTP 409 Conflict`** with full `current_version` and `current_state` diff payload. |
| **2. Simultaneous Claim Protection** | Multiple operators race to claim an unassigned triage item. | Conditional atomic SQL: `WHERE id=:id AND version=:expected_version AND assignee_id IS NULL`. | Only the first winner claims the item; second receives **`HTTP 409 Conflict (ALREADY_CLAIMED)`** with identity of current assignee. |
| **3. Synchronous Idempotency Guard** | Unreliable networks cause retry storms, duplicate item creation, or duplicated comments. | Mutating endpoints require `Idempotency-Key` header. Requests are hashed with SHA-256 and cached in `idempotency_records`. | Replaying identical payload returns cached `200/201` response with **`X-Cache-Lookup: HIT`** and zero duplicate DB rows. Reusing key with different payload returns **`422 Unprocessable Entity`**. |
| **4. Synchronous ACID Audit Logging** | Unclear accountability; mutations lack explanation or history. | Every state mutation writes an immutable `AuditLog` row containing `actor_id`, `action_type`, `previous_state`, `new_state`, and mandatory `reason` text in the **same database commit**. | Every work item provides a verifiable, immutable timeline. Discrepancies between logs and item state are mathematically impossible. |
| **5. Reliable Asynchronous Outbox** | Downstream dispatch (webhooks, email alerts, partner notifications) fails or blocks synchronous HTTP requests. | Transactional Outbox pattern: `OutboxEvent` committed synchronously with the domain entity. Background worker polls events with exponential backoff (`2^attempts` seconds). | Survives downstream failures. Events dead-letter after 5 failed attempts (`DEAD_LETTER`) for operator inspection and retry. |
| **6. Frontend 409 Visual Diff & Reconciliation** | The frontend silently overwrites or crashes when a concurrency conflict occurs. | Frontend intercepts `ApiError` 409 and displays a side-by-side reconciliation modal showing Local vs. Server version differences. | Evaluators can trigger an in-app collision, inspect colleague changes, and reconcile with one click (`"Reconcile & Load Latest Server State"`). |

---

## Quickstart & Running Instructions

### Prerequisites
- **Python**: 3.10+ (tested on Python 3.14)
- **Node.js**: 18+ (tested on Node 24.15)
- **Package Managers**: `pip` and `npm`

---

### Step 1: Start the Backend Service
The backend auto-creates SQLite database tables, runs seed routines, and initializes the transactional outbox loop:

```bash
cd backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
*Backend API will run at:* `http://127.0.0.1:8000`  
*Interactive Swagger Documentation:* `http://127.0.0.1:8000/docs`

---

### Step 2: Start the Frontend Application
The frontend is built with Vite and proxies all `/api` traffic directly to `:8000`:

```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```
*Frontend UI will run at:* `http://127.0.0.1:5173`

---

## 2-Minute Evaluator Tour & Interactive Demo Guide

To experience all beyond-CRUD mechanics under 2 minutes:

1. **Load Console**: Navigate to `http://127.0.0.1:5173`. Notice the high-density operational layout, dark-mode styling, 5 interactive KPI cards, and 35 seeded operational records.
2. **Switch Operator Personas**: In the top-right header, click the operator switcher dropdown:
   - Select **Alice Chen** (`Payments LEAD`) — Notice full lead authority over Payments.
   - Select **Diana Prince** (`SRE LEAD`) — Notice full lead authority over Core Infrastructure.
   - Select **Bob Smith** (`Payments APPROVER & Compliance MEMBER`) — Notice split-role permissions across teams.
3. **Trigger the Concurrency Conflict Simulator (OCC Test)**:
   - Click on the first work item in the table: *"Production Database Replica Lag > 450s in us-east-1"*.
   - In the drawer, locate the **Concurrency & Conflict Simulator** box.
   - Click **"Simulate Colleague Edit (Stale State Test)"**. The backend modifies the item to a higher version, but your browser view intentionally stays at the old version.
   - Now click **"Claim Responsibility"** or **"Update Priority"**.
   - **Result**: The backend returns `HTTP 409 Conflict`. A rich visual **Conflict Reconciliation Modal** opens, highlighting the local version vs. colleague's server version. Click **"Reconcile & Load Latest Server State"** to update smoothly!
4. **Test Simultaneous Claim Protection**:
   - Filter by `Assignee: Unassigned` and `Status: TRIAGE`.
   - Open an unassigned incident.
   - Click "Claim Responsibility". Notice instant assignment, version increment (`v1 -> v2`), and creation of an atomic audit log.
5. **Test Idempotency & Replay Protection**:
   - In the header, click the **"Replay Key Demo"** pill (indicator turns amber).
   - Perform any mutation (e.g. post an investigation comment or update status).
   - The frontend replays the exact same `Idempotency-Key` UUID.
   - Inspect the network tab or toast notification: **`X-Cache-Lookup: HIT`** is returned, proving duplicate request suppression without redundant DB rows!
6. **Inspect the Outbox Queue & DLQ Failure Simulator**:
   - In the header, click the **"Outbox Queue"** button.
   - A real-time drawer slides out showing `PENDING`, `COMPLETED`, `FAILED`, and `DEAD_LETTER` events.
   - Click **"Simulate Failing Async Task"** to enqueue an event flagged for failure.
   - Click **"Trigger Worker Batch"** to step through retry attempts (`attempts 1 -> 2 -> 3`), observing exponential backoff and dead-lettering.

---

## Automated Test Suite Verification

The backend includes a comprehensive async test suite covering contract compliance and operational edge cases:

```bash
cd backend
python -m pytest -v
```

### Test Suite Execution Output
```
============================= test session starts =============================
platform win32 -- Python 3.14.3, pytest-9.1.1, pluggy-1.6.0
rootdir: c:\Users\karti\Documents\Newtonite Assessment Task\backend
collected 16 items

tests/test_critical_behaviours.py::test_simultaneous_claim_conflict PASSED           [  6%]
tests/test_critical_behaviours.py::test_stale_update_rejected_with_server_state PASSED [ 12%]
tests/test_critical_behaviours.py::test_idempotency_key_prevents_duplicate_operations PASSED [ 18%]
tests/test_critical_behaviours.py::test_workflow_state_machine_and_approval_gate PASSED [ 25%]
tests/test_critical_behaviours.py::test_cross_team_authorization_enforced PASSED     [ 31%]
tests/test_critical_behaviours.py::test_transactional_audit_log_and_outbox_retry_lifecycle PASSED [ 37%]
tests/test_critical_behaviours.py::test_server_side_filtering_and_pagination PASSED   [ 43%]
tests/test_evaluation.py::test_contract_compliance_users_and_teams PASSED            [ 50%]
tests/test_evaluation.py::test_contract_compliance_work_items_list PASSED            [ 56%]
tests/test_evaluation.py::test_occ_concurrency_conflict_returns_409_with_diff_payload PASSED [ 62%]
tests/test_evaluation.py::test_simultaneous_claim_protection_returns_409_already_claimed PASSED [ 68%]
tests/test_evaluation.py::test_idempotency_guard_exact_replay_and_mismatch PASSED    [ 75%]
tests/test_evaluation.py::test_synchronous_acid_audit_and_outbox_commitment PASSED   [ 81%]
tests/test_evaluation.py::test_rbac_cross_team_block_and_unauthorized_approval PASSED [ 87%]
tests/test_evaluation.py::test_state_machine_approval_gate_and_illegal_transitions PASSED [ 93%]
tests/test_evaluation.py::test_outbox_worker_exponential_backoff_and_dead_letter PASSED [100%]

============================= 16 passed in 7.56s ==============================
```

---

## Known Limitations & Architectural Trade-Offs

1. **Database Engine (SQLite vs. PostgreSQL)**:
   - *Trade-off*: SQLite in WAL mode was chosen for zero-dependency local evaluator execution.
   - *Limitation*: SQLite allows concurrent reads, but writes are serialized per database file. Under extreme write contention (>500 writes/sec), transactions queue up behind `PRAGMA busy_timeout=5000`. In high-scale production, this should migrate to PostgreSQL with read replicas.
2. **Synchronous Idempotency Retention**:
   - *Limitation*: Idempotency records are currently retained indefinitely in `idempotency_records`. In production, records should have a TTL (e.g., 24–48 hours) managed via Redis or automated table partition pruning.
3. **Simulated Authentication**:
   - *Limitation*: Identity is passed via the `X-User-Id` header to allow instant evaluator persona switching without an OAuth2/SSO provider. In production, this would be replaced with JWT validation from an identity provider (Okta/Auth0).

---

## Comprehensive Architectural Discussion

### 1. How the Architecture Works
The system follows a domain-driven, contract-first design:
- **Locked Contracts**: Schemas defined in `backend/app/schemas.py` and `frontend/src/types/contracts.ts` share 1:1 typing parity, preventing interface drift.
- **Optimistic Concurrency Control (OCC)**: Every mutation requires an `expected_version` integer. The SQL layer executes an atomic conditional update:
  ```sql
  UPDATE work_items 
  SET version = version + 1, ...
  WHERE id = :id AND version = :expected_version;
  ```
  If `rowcount == 0`, another transaction committed first. The server catches this, queries the latest server state, and raises `HTTP 409 Conflict` with a diff payload.
- **Atomic Single-Commit Invariant**: Mutations write the `WorkItem`, the `AuditLog` entry, and the `OutboxEvent` in a **single synchronous transaction**. A failure rollbacks all three, ensuring audit logs and outbox events can never diverge from entity state.

---

### 2. What Happens When Things Fail
- **Network Drop / Client Retry**: Client retries the same operation with the same `Idempotency-Key`. The backend detects the SHA-256 hash match, skips business execution, and returns the cached response with `X-Cache-Lookup: HIT`.
- **Concurrent Colleague Edits**: If Operator A updates an item while Operator B has it open, Operator B's mutation fails with `409 Conflict`. Operator B receives the fresh server state and can reconcile without silent data corruption.
- **Downstream Dispatch Failure**: The async worker isolates downstream failures. If a webhook or integration fails, the main transaction is unaffected. The worker increments `attempts`, computes exponential backoff (`2 ** attempts` seconds), and retries. After 5 failed attempts, the event transitions to `DEAD_LETTER` for human triage.
- **Process Crash Mid-Batch**: Outbox events remain in `PENDING` or `PROCESSING`. Upon restart, events whose `next_retry_at <= now` are picked up again. Dedup keys protect downstream endpoints from duplicate execution.

---

### 3. Key Assumptions
1. **User Identity Authenticity**: In this prototype, `X-User-Id` is trusted to facilitate evaluation.
2. **Operational Priority on Hand-Offs**: Operational friction often occurs during shifts or reassignment. Requiring `next_action_required` and `reason` on every transition ensures state handoffs remain explicit.
3. **Read-Heavy Workload**: The operational console undergoes high read traffic (filtering, live status polling, dashboard inspection) relative to state mutations. SQLite WAL mode provides concurrent, non-blocking reads during active writes.

---

### 4. The Most Important Components
1. **`work_item_service.py` (Domain Core)**: Encapsulates all state machine rules, atomic OCC SQL statements, claim protection, and synchronous audit/outbox coupling.
2. **`idempotency.py`**: Intercepts requests before business logic, verifies SHA-256 payload checksums, and guarantees zero duplicate inserts.
3. **`worker.py` (Transactional Outbox Engine)**: Solves the dual-write problem by guaranteeing reliable, asynchronous event dispatch with exponential backoff and DLQ dead-lettering.
4. **`WorkItemDetail.tsx` & `ConflictDiffModal.tsx`**: Transforms raw 409 backend conflicts into an intuitive visual reconciliation workflow.

---

### 5. What Changes at 100x Scale
If the company grows from hundreds to tens of thousands of employees (100x volume):
- **Database Architecture**: Migrate from SQLite to **PostgreSQL with connection pooling (PgBouncer)**. Partition `audit_logs` and `outbox_events` by month. Implement read replicas for dashboard queries.
- **Distributed Caching & Idempotency**: Offload the idempotency replay cache and deduplication locks to a **Redis cluster** with Redis TTLs (e.g., 24 hours).
- **Outbox Queue Stream**: Replace SQLite polling with an event-driven queue like **Apache Kafka** or **AWS SQS** with Change Data Capture (Debezium reading Postgres WAL) to achieve microsecond outbox dispatch.
- **Search Engine**: Replace SQL `ilike` substring searches with **Elasticsearch** or PostgreSQL `tsvector` full-text search indexing with fuzzy matching.
- **Live Collaborative WebSockets**: Upgrade 5-second polling to real-time WebSockets / Server-Sent Events (SSE) so users see changes occur live.

---

### 6. What to Build Given Another Week
1. **Real-Time Push Updates (WebSockets / SSE)**: Broadcast work item updates to all connected browser sessions so colleagues see colleague edits without having to trigger a conflict manually.
2. **Configurable Workflow State Machine Builder**: Allow team leads to define custom status transitions and mandatory fields per category without changing backend code.
3. **SLA Breach Warning Engine**: Background daemon monitoring `next_action_required` and time spent in `IN_PROGRESS`, automatically escalating priority or alerting team leads before SLA thresholds breach.
4. **Automated Conflict 3-Way Auto-Merge**: Allow non-overlapping field updates (e.g., Operator A updates description, Operator B adds a tag) to merge automatically, only requiring manual reconciliation on direct field collisions.
5. **Rich Text & Artifact Attachments**: Support file uploads (log files, stack traces, screenshots) stored in S3-compatible object storage with signed download URLs.

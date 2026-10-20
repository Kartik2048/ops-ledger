# Engineering Decisions & Architectural Trade-offs
**Document Version:** 1.0.0-LOCKED  
**Methodology Stage:** M — Master Architecture (MAPE Framework)  
**System Classification:** High-Integrity Distributed Operations Management Engine  
**Author:** Principal Systems Architect

---

## Overview

Software architecture is not the pursuit of an imaginary "perfect" system; it is the discipline of making deliberate, well-reasoned trade-offs under concrete constraints. In the Newtonite Operations Platform, our primary constraints are:
1. **High Concurrency & Contention:** Multiple human operators interacting with shared, urgent operational items simultaneously.
2. **Strict Correctness over Simplicity:** Operational tasks involve financial investigations, compliance gates, and production outages where silent failures or lost updates have direct business liability.
3. **Operational Simplicity & Deployment Velocity:** The system must run flawlessly in a zero-dependency local evaluation environment while preserving an uncompromised path to enterprise-scale cloud infrastructure.

This document records the five foundational architectural decisions, the alternatives considered, and the trade-offs accepted.

---

## Decision 1: Optimistic Concurrency Control (OCC) vs. Pessimistic Row Locking

### The Context & Problem
In operational workflows, work items (such as customer issues or production incidents) are frequently reviewed by multiple operators at the same time. A classic failure mode is the **stale-read lost-update**: Operator Alice opens an incident at 10:00 AM; Operator Bob opens the same incident at 10:01 AM. Bob changes the priority to `CRITICAL` at 10:02 AM. At 10:05 AM, Alice finishes typing her investigation notes and clicks "Save", sending a blind `UPDATE` that overwrites Bob's priority change back to `MEDIUM`.

### Alternatives Evaluated

| Strategy | Mechanism | Pros | Cons / Rejection Rationale |
| :--- | :--- | :--- | :--- |
| **Pessimistic Locking (`SELECT FOR UPDATE`)** | Acquires exclusive row lock in the database when a user opens the item in edit mode. | Guarantees mutual exclusion; no user ever encounters an update collision. | **Fatal Flaw in Web Applications:** HTTP is stateless. Holding a database transaction open while a human reads or types (human think-time: 30 seconds to 10 minutes) exhausts the database connection pool, introduces severe distributed deadlocks, and fails completely if the user closes their laptop lid or loses internet connection without releasing the lock. |
| **Distributed Mutex (Redis Locks with TTL)** | Acquires a Redis key with a lease expiration (e.g., 60 seconds) renewed by heartbeats. | Prevents DB connection pool starvation. | Introduces a hard dependency on an external caching tier. If a user's network drops during an incident, teammates are artificially locked out until the TTL expires, delaying urgent production triage. |
| **Last-Write-Wins (LWW)** | Naive unconditional SQL update with timestamps. | Simplest implementation. | **Unacceptable:** Causes silent data loss, overwriting critical triage decisions and investigation notes. |
| **Optimistic Concurrency Control (OCC)** *(Selected)* | Each row tracks an integer `version`. Mutations conditionally update `WHERE version = :expected_version` and increment `version`. | Zero lock overhead, non-blocking reads, handles human think-time gracefully, scales effortlessly across stateless API replicas. | Requires frontend reconciliation handling when a collision occurs (HTTP 409 Conflict). |

### The Chosen Design & Trade-off
We selected **Optimistic Concurrency Control with atomic conditional database updates**.
- **Database Layer:** Mutations execute `UPDATE work_items SET ..., version = version + 1 WHERE id = :id AND version = :expected_version RETURNING *;`. If `rowcount == 0`, a conflict is raised.
- **API Layer:** Catches the zero-row update, fetches the newly committed state, and returns HTTP `409 Conflict` containing both `expected_version` and `current_state`.
- **Frontend Layer:** The React client catches the 409 and triggers an interactive **Visual 409 Conflict Reconciliation Modal**. The user is presented with a side-by-side diff comparing their local draft against the server's current reality, with options to "Overwrite with My Changes", "Discard & Refresh", or "Merge Fields".
- **Trade-off Accepted:** We accept the development complexity of building frontend diff and reconciliation UI in exchange for complete immunity to connection exhaustion, deadlocks, and stale data loss.

---

## Decision 2: Transactional Outbox Pattern vs. Direct External Message Broker

### The Context & Problem
When a work item undergoes state changes (e.g., entering `PENDING_APPROVAL` or escalating to `CRITICAL`), secondary asynchronous tasks must fire: alerting on-call engineers via Slack/PagerDuty, sending emails to compliance officers, or updating external data warehouses.

A common anti-pattern is the **Dual-Write Hazard**:
```python
# ANTI-PATTERN: Dual-Write Hazard
async def update_work_item(item_id, ...):
    await db.commit()             # Step 1: Database Commit
    await message_bus.publish(...) # Step 2: Publish to Kafka / RabbitMQ
```
If Step 1 succeeds but Step 2 crashes (network timeout, broker restart), the alert is permanently lost. If Step 2 is performed before Step 1, and Step 1 fails on a database constraint, phantom messages are dispatched for transactions that never existed. Distributed Two-Phase Commit (2PC) is notoriously fragile and universally avoided in modern web systems.

### Alternatives Evaluated

| Strategy | Mechanism | Pros | Cons / Rejection Rationale |
| :--- | :--- | :--- | :--- |
| **Synchronous In-Band External Calls** | API controller directly calls Slack/Email HTTP endpoints inside the request handler. | Immediate feedback to the caller. | High latency (adds 200–2000ms to API response), cascades external outages into internal operational downtime, and cannot guarantee atomic commits. |
| **Direct External Broker (RabbitMQ / Kafka)** | Controller writes to external message broker after DB commit. | High throughput, decoupled subscribers. | Suffers from the Dual-Write Hazard. Additionally introduces severe infrastructure overhead (managing ZooKeeper/Kafka or RabbitMQ clusters) unsuitable for lean deployment. |
| **Transactional Outbox via RDBMS** *(Selected)* | Secondary events are written to an `outbox_events` table within the **exact same ACID database transaction** as the entity mutation. A background worker polls and dispatches them. | 100% guarantee that events are recorded if and only if the business transaction commits. Zero external infrastructure dependencies. Native idempotency via unique deduplication keys. | Introduces asynchronous event lag (typically 200–500ms) and requires an outbox table sweeper/poller. |

### The Chosen Design & Trade-off
We selected the **Transactional Outbox Pattern backed by primary relational storage**.
- **Atomic Persistence:** In the same `session.commit()` block that modifies `work_items`, an `OutboxEvent` row is inserted with a unique `dedup_key` (e.g., `item-{id}-status-{status}-{version}`).
- **Asynchronous Dispatcher:** An asynchronous background worker polls pending events, marks them `PROCESSING`, and dispatches them to simulated/real notification adapters.
- **Resiliency & Dead-Lettering:** Handlers follow exponential backoff ($2^\text{attempts} \times 2\text{s}$). If a handler fails 5 consecutive times, it is moved to `DEAD_LETTER` with the stack trace persisted in `last_error`.
- **Trade-off Accepted:** We accept slight eventual consistency (sub-second notification latency) in exchange for bulletproof delivery guarantees and zero external messaging infrastructure dependencies.

---

## Decision 3: Synchronous Transactional Audit Logging vs. Asynchronous Event Projections

### The Context & Problem
In high-pressure operational environments, understanding "who did what, when, and why" is non-negotiable. Management and compliance officers require an immutable provenance trail for security reviews, incident post-mortems, and financial audits.

Architects often debate whether audit logs should be written synchronously within the main database transaction or asynchronously reconstructed via event projections or log tailing.

### Alternatives Evaluated

| Strategy | Mechanism | Pros | Cons / Rejection Rationale |
| :--- | :--- | :--- | :--- |
| **Fire-and-Forget Asynchronous Logging** | Pushes audit logs to a background task or message queue without awaiting response. | Near-zero overhead on the main API request latency. | **Fatal Flaw:** If the background worker fails, crashes, or suffers memory pressure, the state mutation commits to the database but the audit entry is permanently lost. This produces **Audit Drift**, violating compliance standards. |
| **Full Event Sourcing (CQRS)** | The work item table is eliminated; the system only stores events, and current state is projected on the fly. | Complete audit fidelity by design; time-travel debugging. | Massive architectural complexity: schema evolution is painful, snapshotting is required for performance, and simple relational queries (filtering by team, status, and priority) require complex read-model projections. |
| **Synchronous Transactional Audit Log** *(Selected)* | The `audit_logs` record is inserted into the relational database within the **exact same ACID transaction** as the work item mutation. | Absolute 1:1 parity between state changes and audit provenance. Zero audit drift. Simple relational schema with foreign keys and indexes. | Minor write overhead (two table writes per transaction instead of one). |

### The Chosen Design & Trade-off
We selected **Synchronous Transactional Audit Logging**.
- **Atomicity:** `work_items` update and `audit_logs` insert share a single `session.begin()` boundary. If disk I/O, constraints, or serialization fail, both roll back.
- **Immutability:** The `audit_logs` table has no `UPDATE` or `DELETE` API endpoints or triggers. It is strictly append-only.
- **Context Richness:** Each audit log records `actor_id`, `action_type`, `previous_state` (JSON), `new_state` (JSON), and human `reason`.
- **Trade-off Accepted:** We accept approximately 2–3 milliseconds of additional database write latency on mutating requests in exchange for uncompromised regulatory and forensic audit integrity.

---

## Decision 4: Resource-Scoped Team RBAC & Deterministic State Machine vs. Ad-hoc Permission Flags

### The Context & Problem
A multi-team organization requires clear boundaries of responsibility. For example, an engineer in the Billing team should not be able to approve a production infrastructure change in the Core Platform team, nor should an unassigned customer issue jump directly to `RESOLVED` without triage.

A common failure in rapid application development is scattering permission checks across frontend UI components (e.g., `if (user.role === 'ADMIN') showButton()`) and leaving API endpoints loosely protected.

### Alternatives Evaluated

| Strategy | Mechanism | Pros | Cons / Rejection Rationale |
| :--- | :--- | :--- | :--- |
| **Client-Only Authorization** | UI hides action buttons based on user attributes; API endpoints perform minimal or no checks. | Fast to develop. | **Security Disaster:** Any user can open Chrome DevTools or Postman and trigger forbidden state transitions (e.g. self-approving compliance waivers). |
| **Global Role-Based Access Control (Global RBAC)** | Users have static global roles like `ADMIN`, `MANAGER`, `USER`. | Simple user model. | Inadequate for multi-department organizations: a user may be a senior `LEAD` in Customer Support but should only have `NON_MEMBER` or `MEMBER` read-only access to Platform Engineering incident tickets. |
| **Resource-Scoped RBAC + Domain State Machine** *(Selected)* | Roles (`MEMBER`, `APPROVER`, `LEAD`) are scoped specifically to each `team_id`. A domain service enforces both role authority and strict state transition invariants before writing to the database. | Mathematically sound authorization model; prevents privilege escalation; guarantees that business rules (e.g. approval requirements) cannot be bypassed. | Requires looking up team membership on every mutating request and maintaining an explicit state transition matrix. |

### The Chosen Design & Trade-off
We selected **Resource-Scoped Team RBAC paired with a Deterministic Domain State Machine**.
- **Team-Scoped Roles:** A user has distinct roles per team stored in `team_memberships`. An actor's rights on a work item are computed dynamically based on `work_item.team_id`.
- **Hard Approval Invariant:** If `work_item.requires_approval == True`, the system **strictly prohibits** transitioning to `RESOLVED` directly from `IN_PROGRESS`. The item must transition to `PENDING_APPROVAL`, and only a user with `APPROVER` or `LEAD` role in that item's owning team can execute `/approve`.
- **Domain Service Enforcement:** Authorization and state machine rules are encapsulated in a single backend domain service layer, completely decoupled from HTTP controllers and frontend presentation logic.
- **Trade-off Accepted:** We accept the requirement of team-membership query joins on mutations in exchange for airtight security and auditable workflow integrity.

---

## Decision 5: Compound Indexed Server-Side Pagination & Query Filtering vs. Client-Side In-Memory Filtering & Intentional Day-1 Scope Cut-offs

### The Context & Problem
The system is designed to support rapid corporate growth: thousands of users, hundreds of simultaneous operators, and tens of thousands of active work items with an ever-expanding audit history.

Many early-stage applications fetch all records (`SELECT * FROM work_items`) into the browser and use JavaScript `array.filter()` for filtering and sorting. While functional with 50 items, this approach catastrophically degrades at 10,000 items: multi-megabyte JSON payloads freeze mobile and laptop browsers, exhaust client memory, and saturate API network bandwidth.

### Alternatives Evaluated

| Strategy | Mechanism | Pros | Cons / Rejection Rationale |
| :--- | :--- | :--- | :--- |
| **Client-Side In-Memory Grid** | Backend returns entire database table; client handles pagination, search, and filtering. | Trivial backend endpoints; instant client-side tab switching for tiny datasets. | **Catastrophic at Scale:** Fails completely beyond a few hundred records. 50,000 items with audit data would exceed 40MB of transfer per page load, causing browser thread freezing and high egress costs. |
| **Elasticsearch / Dedicated Search Cluster** | Sync DB changes to external Lucene/Elasticsearch cluster for all filtering and search queries. | Sub-millisecond full-text fuzzy search; faceting at massive scale. | Massive operational overhead: cluster management, index sync lag, split-brain risk, and high resource costs that are unnecessary for tens of thousands of operational items. |
| **Compound Indexed Server-Side SQL Filtering** *(Selected)* | Server exposes parameterized `limit`/`offset`/cursor pagination with compound SQL indexes on primary query vectors. | Handles tens of thousands of active items with sub-10ms query execution times. Zero external search infrastructure required. Constant client memory footprint. | Requires designing and maintaining specialized composite indexes in the schema. |

### The Chosen Design & Composite Index Architecture
We selected **Compound Indexed Server-Side SQL Filtering**:
1. **Primary Operational Triage Index:**
   ```sql
   CREATE INDEX idx_work_items_team_status_prio ON work_items(team_id, status, priority);
   ```
   *Rationale:* Operational teams live in filtered views: "Show me Team X's TRIAGE or IN_PROGRESS items sorted by PRIORITY". This index satisfies this query pattern directly from B-Tree index pages without scanning table heaps.
2. **Assignee Queue Index:**
   ```sql
   CREATE INDEX idx_work_items_assignee_status ON work_items(assignee_id, status);
   ```
   *Rationale:* Accelerates the personal operator dashboard ("My Active Items").
3. **Deterministic Pagination Index:**
   ```sql
   CREATE INDEX idx_work_items_pagination ON work_items(updated_at DESC, id DESC);
   ```
   *Rationale:* Eliminates table sort overhead and prevents pagination drifting when items are updated concurrently.

### Intentional Day-1 Scope Cut-offs (What We Intentionally Did NOT Build)
In accordance with engineering rigor, we explicitly identify features deliberately excluded on Day 1 to maximize core reliability:
1. **WebSockets / Server-Sent Events (SSE) for Real-Time Streaming:**
   - *Why Cut:* WebSocket connection state across multiple server instances requires Redis Pub/Sub, heartbeats, and reconnect storms. For an operational queue, TanStack Query's window-focus refetching, mutation invalidation, and configurable short-interval polling (5–10s) provide an indistinguishable user experience with zero stateful connection overhead.
2. **Elasticsearch / OpenSearch Integration:**
   - *Why Cut:* Relational SQL `LIKE`/`ILIKE` with targeted column constraints and prefix indexing easily handles title/description search across tens of thousands of rows at sub-15ms latency, avoiding dual-index desynchronization.
3. **GraphQL API Layer:**
   - *Why Cut:* Adds substantial schema complexity, N+1 query vulnerability, and complicates HTTP-level caching and idempotency headers. REST with Pydantic v2 schemas gives explicit, verifiable contracts.
4. **Third-Party Identity Provider (Okta/SAML/Auth0) Dependencies:**
   - *Why Cut:* For the assessment evaluation environment, requiring external OAuth/SAML credentials creates friction. We architected a simulated header-driven identity model (`X-User-Id`) with a built-in interactive User Switcher that demonstrates role-scoped access control immediately while keeping the interface cleanly swappable for JWT bearer tokens in production.

---

## Summary of Architectural Trade-offs Matrix

| Architectural Dimension | Chosen Approach | Alternative Rejected | Core Trade-off Justification |
| :--- | :--- | :--- | :--- |
| **Concurrency Control** | Optimistic (OCC Versioning) | Pessimistic Row Locking | Prevents connection starvation & deadlocks during human think time; diff reconciliation UX handles collisions cleanly. |
| **Asynchronous Effects** | Transactional Outbox Pattern | Direct Broker (Kafka/RabbitMQ) | Eliminates dual-write hazard; guarantees at-least-once delivery with zero external infrastructure overhead. |
| **Audit Provenance** | Synchronous ACID Transaction | Asynchronous Event Streaming | Eliminates audit drift; guarantees 100% legal & operational compliance trail. |
| **Authorization** | Resource-Scoped Team RBAC | Global Admin Flags & UI Hiding | Accurately models departmental boundaries; enforces state machine gates at domain boundary. |
| **Data Scalability** | Server-Side Indexed Pagination | In-Memory Client Filtering | Guarantees bounded client memory and sub-15ms API response at tens of thousands of work items. |
| **Real-time Synchronization** | Smart Polling + Query Invalidation | WebSockets / Socket.io | Eliminates stateful socket connection management and reconnect storms while preserving responsive UI. |

---
**DECISIONS STATUS:** Awaiting Stage A Approval.

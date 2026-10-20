"""Realistic Operational Data Seeder.
Populates an idempotent baseline of teams, users, memberships, and 35 rich work items
with multi-step audit logs and outbox events.
Stage P2: Async Outbox Worker & Seed Engine.
"""

import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

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

# Seed Constants: Deterministic UUIDs for predictable testing
TEAM_PAYMENTS_ID = "10000000-0000-0000-0000-000000000001"
TEAM_SRE_ID = "10000000-0000-0000-0000-000000000002"
TEAM_COMPLIANCE_ID = "10000000-0000-0000-0000-000000000003"

USER_ALICE_ID = "00000000-0000-0000-0000-000000000001"   # Payments LEAD
USER_BOB_ID = "00000000-0000-0000-0000-000000000002"     # Payments APPROVER
USER_CHARLIE_ID = "00000000-0000-0000-0000-000000000003" # Payments MEMBER
USER_DIANA_ID = "00000000-0000-0000-0000-000000000004"   # SRE LEAD & Payments MEMBER
USER_EVAN_ID = "00000000-0000-0000-0000-000000000005"    # Compliance APPROVER
USER_FIONA_ID = "00000000-0000-0000-0000-000000000006"   # SRE MEMBER


async def seed_database(db: AsyncSession, force: bool = False) -> bool:
    """Idempotently seed the operational database if empty."""
    # Check if already seeded
    user_count_res = await db.execute(select(func.count(User.id)))
    if user_count_res.scalar_one() > 0 and not force:
        return False

    now = datetime.now(timezone.utc)

    # 1. Teams
    t_payments = Team(
        id=TEAM_PAYMENTS_ID,
        name="Payments & Risk",
        slug="payments-risk",
        description="Core transaction clearing, fraud detection, and settlement operations.",
        created_at=now - timedelta(days=60),
    )
    t_sre = Team(
        id=TEAM_SRE_ID,
        name="Core Infrastructure (SRE)",
        slug="core-infra-sre",
        description="Production reliability, cloud infrastructure, kubernetes, and database systems.",
        created_at=now - timedelta(days=60),
    )
    t_compliance = Team(
        id=TEAM_COMPLIANCE_ID,
        name="Trust & Compliance",
        slug="trust-compliance",
        description="Regulatory audit oversight, SOC2/ISO compliance, and data governance.",
        created_at=now - timedelta(days=60),
    )
    db.add_all([t_payments, t_sre, t_compliance])
    await db.flush()

    # 2. Users
    users = [
        User(
            id=USER_ALICE_ID,
            email="alice.chen@newtonite.internal",
            full_name="Alice Chen",
            avatar_color="#6366F1",  # Indigo
            created_at=now - timedelta(days=45),
        ),
        User(
            id=USER_BOB_ID,
            email="bob.smith@newtonite.internal",
            full_name="Bob Smith",
            avatar_color="#10B981",  # Emerald
            created_at=now - timedelta(days=45),
        ),
        User(
            id=USER_CHARLIE_ID,
            email="charlie.davis@newtonite.internal",
            full_name="Charlie Davis",
            avatar_color="#F59E0B",  # Amber
            created_at=now - timedelta(days=40),
        ),
        User(
            id=USER_DIANA_ID,
            email="diana.prince@newtonite.internal",
            full_name="Diana Prince",
            avatar_color="#EC4899",  # Pink
            created_at=now - timedelta(days=50),
        ),
        User(
            id=USER_EVAN_ID,
            email="evan.wright@newtonite.internal",
            full_name="Evan Wright",
            avatar_color="#8B5CF6",  # Purple
            created_at=now - timedelta(days=35),
        ),
        User(
            id=USER_FIONA_ID,
            email="fiona.gallagher@newtonite.internal",
            full_name="Fiona Gallagher",
            avatar_color="#06B6D4",  # Cyan
            created_at=now - timedelta(days=30),
        ),
    ]
    db.add_all(users)
    await db.flush()

    # 3. Team Memberships
    memberships = [
        # Payments & Risk
        TeamMembership(id=str(uuid.uuid4()), user_id=USER_ALICE_ID, team_id=TEAM_PAYMENTS_ID, role=TeamRole.LEAD.value),
        TeamMembership(id=str(uuid.uuid4()), user_id=USER_BOB_ID, team_id=TEAM_PAYMENTS_ID, role=TeamRole.APPROVER.value),
        TeamMembership(id=str(uuid.uuid4()), user_id=USER_CHARLIE_ID, team_id=TEAM_PAYMENTS_ID, role=TeamRole.MEMBER.value),
        TeamMembership(id=str(uuid.uuid4()), user_id=USER_DIANA_ID, team_id=TEAM_PAYMENTS_ID, role=TeamRole.MEMBER.value),
        # Core Infrastructure (SRE)
        TeamMembership(id=str(uuid.uuid4()), user_id=USER_DIANA_ID, team_id=TEAM_SRE_ID, role=TeamRole.LEAD.value),
        TeamMembership(id=str(uuid.uuid4()), user_id=USER_FIONA_ID, team_id=TEAM_SRE_ID, role=TeamRole.MEMBER.value),
        TeamMembership(id=str(uuid.uuid4()), user_id=USER_ALICE_ID, team_id=TEAM_SRE_ID, role=TeamRole.MEMBER.value),
        # Trust & Compliance
        TeamMembership(id=str(uuid.uuid4()), user_id=USER_EVAN_ID, team_id=TEAM_COMPLIANCE_ID, role=TeamRole.APPROVER.value),
        TeamMembership(id=str(uuid.uuid4()), user_id=USER_BOB_ID, team_id=TEAM_COMPLIANCE_ID, role=TeamRole.MEMBER.value),
    ]
    db.add_all(memberships)
    await db.flush()

    # 4. Realistic 35 Operational Work Items
    item_definitions = [
        # --- Critical Production Incidents (SRE) ---
        {
            "title": "Production Database Replica Lag > 450s in us-east-1",
            "desc": "Primary Postgres replication slot is backing up on replica-02 due to heavy query contention on the ledger transactions table. WAL disk space is down to 18%.",
            "cat": WorkItemCategory.PRODUCTION_INCIDENT.value,
            "prio": Priority.CRITICAL.value,
            "team": TEAM_SRE_ID,
            "creator": USER_FIONA_ID,
            "assignee": USER_DIANA_ID,
            "status": WorkItemStatus.IN_PROGRESS.value,
            "req_app": True,
            "app_stat": ApprovalStatus.PENDING.value,
            "app_by": None,
            "next_act": "Apply vacuum tuning and inspect slow index scan on audit records.",
            "version": 3,
            "delta_h": 2,
        },
        {
            "title": "Ingress Envoy Gateway 502 Outages during Deployments",
            "desc": "Rolling restarts in Kubernetes cluster k8s-prod-west causing transient connection drops for 0.4% of checkout requests. Envoy termination grace period suspected to be too short.",
            "cat": WorkItemCategory.PRODUCTION_INCIDENT.value,
            "prio": Priority.CRITICAL.value,
            "team": TEAM_SRE_ID,
            "creator": USER_DIANA_ID,
            "assignee": None,
            "status": WorkItemStatus.TRIAGE.value,
            "req_app": False,
            "app_stat": ApprovalStatus.NOT_REQUIRED.value,
            "app_by": None,
            "next_act": "On-call SRE needs to claim and test preStop sleep hook on ingress pods.",
            "version": 1,
            "delta_h": 1,
        },
        {
            "title": "Redis Memory Fragmentation Ratio Spike to 3.8",
            "desc": "Session cache instance cluster-redis-01 reported 94% memory utilization despite lower payload throughput. Memory defragmentation background worker is not reclaiming pages.",
            "cat": WorkItemCategory.PRODUCTION_INCIDENT.value,
            "prio": Priority.HIGH.value,
            "team": TEAM_SRE_ID,
            "creator": USER_FIONA_ID,
            "assignee": USER_FIONA_ID,
            "status": WorkItemStatus.BLOCKED.value,
            "req_app": False,
            "app_stat": ApprovalStatus.NOT_REQUIRED.value,
            "app_by": None,
            "next_act": "Blocked on AWS support ticket #89421 requesting host hypervisor diagnostic.",
            "version": 2,
            "delta_h": 5,
        },
        {
            "title": "TLS Certificate Auto-Renewal Failure for *.api.newtonite.io",
            "desc": "Cert-manager ACME challenge failed DNS-01 verification due to Cloudflare API token rate limiting.",
            "cat": WorkItemCategory.PRODUCTION_INCIDENT.value,
            "prio": Priority.CRITICAL.value,
            "team": TEAM_SRE_ID,
            "creator": USER_DIANA_ID,
            "assignee": USER_DIANA_ID,
            "status": WorkItemStatus.RESOLVED.value,
            "req_app": True,
            "app_stat": ApprovalStatus.APPROVED.value,
            "app_by": USER_DIANA_ID,
            "next_act": "Resolved: Rotated API token and forced manual renewal. New cert valid for 90 days.",
            "version": 4,
            "delta_h": 14,
        },

        # --- Payments & Risk Investigations ---
        {
            "title": "Discrepancy in Merchant Settlement Batch #9021",
            "desc": "End-of-day reconciliation detected an unexplained $14,250 variance between Stripe ACH payouts and internal ledger account #4010. 12 transactions marked as pending in Stripe were credited locally.",
            "cat": WorkItemCategory.PAYMENT_INVESTIGATION.value,
            "prio": Priority.CRITICAL.value,
            "team": TEAM_PAYMENTS_ID,
            "creator": USER_CHARLIE_ID,
            "assignee": USER_BOB_ID,
            "status": WorkItemStatus.PENDING_APPROVAL.value,
            "req_app": True,
            "app_stat": ApprovalStatus.PENDING.value,
            "app_by": None,
            "next_act": "Awaiting Alice Chen (Lead) sign-off on manual ledger adjustment entry.",
            "version": 4,
            "delta_h": 3,
        },
        {
            "title": "Card Dispute Webhook Duplicate Ingestion Anomaly",
            "desc": "Adyen chargeback webhooks delivered with duplicate idempotent message IDs caused dual dispute records in merchant portals.",
            "cat": WorkItemCategory.PAYMENT_INVESTIGATION.value,
            "prio": Priority.HIGH.value,
            "team": TEAM_PAYMENTS_ID,
            "creator": USER_ALICE_ID,
            "assignee": USER_CHARLIE_ID,
            "status": WorkItemStatus.IN_PROGRESS.value,
            "req_app": True,
            "app_stat": ApprovalStatus.PENDING.value,
            "app_by": None,
            "next_act": "Patching idempotent ingestion middleware to enforce unique key index on webhook event IDs.",
            "version": 2,
            "delta_h": 6,
        },
        {
            "title": "Cross-Border FX Spread Mismatch on EUR/USD Orders",
            "desc": "Forex rate provider feed had 12-minute stale quote cache during ECB announcement, leading to under-margined currency conversions.",
            "cat": WorkItemCategory.PAYMENT_INVESTIGATION.value,
            "prio": Priority.HIGH.value,
            "team": TEAM_PAYMENTS_ID,
            "creator": USER_BOB_ID,
            "assignee": None,
            "status": WorkItemStatus.TRIAGE.value,
            "req_app": True,
            "app_stat": ApprovalStatus.PENDING.value,
            "app_by": None,
            "next_act": "Requires investigation of provider heartbeat latency and hedging balance impacts.",
            "version": 1,
            "delta_h": 4,
        },
        {
            "title": "Suspicious Rapid Card Testing Velocity Attack",
            "desc": "3,400 authorization attempts from single /24 CIDR testing stolen BIN ranges against payment endpoint. Auto-throttle rule was delayed by 90s.",
            "cat": WorkItemCategory.PAYMENT_INVESTIGATION.value,
            "prio": Priority.CRITICAL.value,
            "team": TEAM_PAYMENTS_ID,
            "creator": USER_CHARLIE_ID,
            "assignee": USER_ALICE_ID,
            "status": WorkItemStatus.RESOLVED.value,
            "req_app": True,
            "app_stat": ApprovalStatus.APPROVED.value,
            "app_by": USER_BOB_ID,
            "next_act": "Resolved: WAF IP reputation drop rule deployed and CAPTCHA enforced on card entry.",
            "version": 5,
            "delta_h": 20,
        },

        # --- Trust & Compliance Reviews ---
        {
            "title": "SOC2 Type II Annual Data Retention Audit Exceptions",
            "desc": "Auditors from Ernst & Young flagged 4 user account deletion requests from Q2 that retained customer billing metadata beyond the 30-day purge threshold.",
            "cat": WorkItemCategory.COMPLIANCE_REQUEST.value,
            "prio": Priority.HIGH.value,
            "team": TEAM_COMPLIANCE_ID,
            "creator": USER_EVAN_ID,
            "assignee": USER_EVAN_ID,
            "status": WorkItemStatus.PENDING_APPROVAL.value,
            "req_app": True,
            "app_stat": ApprovalStatus.PENDING.value,
            "app_by": None,
            "next_act": "Awaiting formal verification of compliance audit evidence packet.",
            "version": 3,
            "delta_h": 7,
        },
        {
            "title": "GDPR Right to Be Forgotten Request - Subject #GDPR-8819",
            "desc": "European customer requested complete erasure of personal identifiable data across primary relational DB, analytics warehouse, and CRM backups.",
            "cat": WorkItemCategory.COMPLIANCE_REQUEST.value,
            "prio": Priority.HIGH.value,
            "team": TEAM_COMPLIANCE_ID,
            "creator": USER_EVAN_ID,
            "assignee": USER_BOB_ID,
            "status": WorkItemStatus.IN_PROGRESS.value,
            "req_app": True,
            "app_stat": ApprovalStatus.PENDING.value,
            "app_by": None,
            "next_act": "Snowflake data warehouse anonymization script running in dry-run mode.",
            "version": 2,
            "delta_h": 12,
        },
        {
            "title": "PCI-DSS Key Rotation Verification for Tokenization HSM",
            "desc": "Hardware Security Module master key encryption rotation scheduled per semi-annual PCI mandate.",
            "cat": WorkItemCategory.COMPLIANCE_REQUEST.value,
            "prio": Priority.MEDIUM.value,
            "team": TEAM_COMPLIANCE_ID,
            "creator": USER_EVAN_ID,
            "assignee": None,
            "status": WorkItemStatus.TRIAGE.value,
            "req_app": True,
            "app_stat": ApprovalStatus.PENDING.value,
            "app_by": None,
            "next_act": "Assign compliance officer and schedule maintenance window with payments team.",
            "version": 1,
            "delta_h": 8,
        },

        # --- Operational Approvals & Governance ---
        {
            "title": "Production DB Schema Migration: Composite Index on Audit Logs",
            "desc": "Apply online DDL `CREATE INDEX CONCURRENTLY idx_audit_logs_item_created` on production cluster to accelerate customer support timeline queries.",
            "cat": WorkItemCategory.OPERATIONAL_APPROVAL.value,
            "prio": Priority.HIGH.value,
            "team": TEAM_SRE_ID,
            "creator": USER_FIONA_ID,
            "assignee": USER_DIANA_ID,
            "status": WorkItemStatus.PENDING_APPROVAL.value,
            "req_app": True,
            "app_stat": ApprovalStatus.PENDING.value,
            "app_by": None,
            "next_act": "SRE Lead approval required before executing schema migration during off-peak window.",
            "version": 3,
            "delta_h": 4,
        },
        {
            "title": "Emergency Production Firewall Rule Modification for BGP Peer",
            "desc": "Update edge border router access list to accept new BGP prefix announced by backup Tier-1 transit provider.",
            "cat": WorkItemCategory.OPERATIONAL_APPROVAL.value,
            "prio": Priority.CRITICAL.value,
            "team": TEAM_SRE_ID,
            "creator": USER_DIANA_ID,
            "assignee": USER_DIANA_ID,
            "status": WorkItemStatus.RESOLVED.value,
            "req_app": True,
            "app_stat": ApprovalStatus.APPROVED.value,
            "app_by": USER_DIANA_ID,
            "next_act": "Approved and validated: BGP session established with 0 dropped packets.",
            "version": 4,
            "delta_h": 18,
        },
        {
            "title": "High-Risk Merchant Tier Increase: TechGlobe Global Inc",
            "desc": "Merchant requested daily card volume ceiling expansion from $250k to $1.2M. Requires dual risk sign-off and reserve deposit verification.",
            "cat": WorkItemCategory.OPERATIONAL_APPROVAL.value,
            "prio": Priority.HIGH.value,
            "team": TEAM_PAYMENTS_ID,
            "creator": USER_CHARLIE_ID,
            "assignee": USER_BOB_ID,
            "status": WorkItemStatus.BLOCKED.value,
            "req_app": True,
            "app_stat": ApprovalStatus.PENDING.value,
            "app_by": None,
            "next_act": "Blocked awaiting bank guarantee letter from merchant's corporate bank.",
            "version": 3,
            "delta_h": 22,
        },

        # --- Engineering Problems & Defect Triage ---
        {
            "title": "Memory Leak in Background PDF Receipt Generator",
            "desc": "Headless Chrome instances spawned by invoice generator service are not terminating properly after rendering, leaking ~80MB per batch.",
            "cat": WorkItemCategory.ENGINEERING_PROBLEM.value,
            "prio": Priority.MEDIUM.value,
            "team": TEAM_PAYMENTS_ID,
            "creator": USER_CHARLIE_ID,
            "assignee": USER_CHARLIE_ID,
            "status": WorkItemStatus.IN_PROGRESS.value,
            "req_app": False,
            "app_stat": ApprovalStatus.NOT_REQUIRED.value,
            "app_by": None,
            "next_act": "Refactoring worker to use persistent browser pool with periodic worker recycling.",
            "version": 2,
            "delta_h": 9,
        },
        {
            "title": "GraphQL N+1 Query on Team Member Listing",
            "desc": "Viewing the team member directory fires individual SQL queries per user rather than utilizing DataLoader batching.",
            "cat": WorkItemCategory.ENGINEERING_PROBLEM.value,
            "prio": Priority.LOW.value,
            "team": TEAM_SRE_ID,
            "creator": USER_FIONA_ID,
            "assignee": None,
            "status": WorkItemStatus.TRIAGE.value,
            "req_app": False,
            "app_stat": ApprovalStatus.NOT_REQUIRED.value,
            "app_by": None,
            "next_act": "Initial triage required: Benchmark response times on staging.",
            "version": 1,
            "delta_h": 15,
        },
        {
            "title": "Deadlock during High-Volume Inventory Reservation",
            "desc": "PostgreSQL transaction deadlock detected during flash sale when reserving SKU units in random order.",
            "cat": WorkItemCategory.ENGINEERING_PROBLEM.value,
            "prio": Priority.HIGH.value,
            "team": TEAM_PAYMENTS_ID,
            "creator": USER_ALICE_ID,
            "assignee": USER_CHARLIE_ID,
            "status": WorkItemStatus.RESOLVED.value,
            "req_app": False,
            "app_stat": ApprovalStatus.NOT_REQUIRED.value,
            "app_by": None,
            "next_act": "Resolved: Sort SKU IDs deterministically before acquiring row locks.",
            "version": 3,
            "delta_h": 36,
        },

        # --- Customer Issues & Escalations ---
        {
            "title": "Enterprise Client ApexCorp: Webhook HMAC Signature Mismatch",
            "desc": "ApexCorp engineering reports that webhook signatures sent by our production dispatchers fail SHA256 validation on their ingress parser.",
            "cat": WorkItemCategory.CUSTOMER_ISSUE.value,
            "prio": Priority.HIGH.value,
            "team": TEAM_PAYMENTS_ID,
            "creator": USER_BOB_ID,
            "assignee": USER_CHARLIE_ID,
            "status": WorkItemStatus.IN_PROGRESS.value,
            "req_app": False,
            "app_stat": ApprovalStatus.NOT_REQUIRED.value,
            "app_by": None,
            "next_act": "Compare raw payload bytes with client engineering team on Slack connect channel.",
            "version": 2,
            "delta_h": 11,
        },
        {
            "title": "Refund Button Disabled for Disputed Transaction #TX-48192",
            "desc": "Customer service agent reports inability to issue partial refund on disputed charge due to UI validation lock.",
            "cat": WorkItemCategory.CUSTOMER_ISSUE.value,
            "prio": Priority.MEDIUM.value,
            "team": TEAM_PAYMENTS_ID,
            "creator": USER_ALICE_ID,
            "assignee": None,
            "status": WorkItemStatus.TRIAGE.value,
            "req_app": False,
            "app_stat": ApprovalStatus.NOT_REQUIRED.value,
            "app_by": None,
            "next_act": "Determine whether chargeback rules allow partial concessions under Visa merchant rules.",
            "version": 1,
            "delta_h": 16,
        },
        {
            "title": "Billing Dashboard Export CSV Failing with HTTP 504",
            "desc": "Customers with over 50,000 monthly invoices experience gateway timeout when attempting CSV export.",
            "cat": WorkItemCategory.CUSTOMER_ISSUE.value,
            "prio": Priority.MEDIUM.value,
            "team": TEAM_PAYMENTS_ID,
            "creator": USER_CHARLIE_ID,
            "assignee": USER_CHARLIE_ID,
            "status": WorkItemStatus.CANCELLED.value,
            "req_app": False,
            "app_stat": ApprovalStatus.NOT_REQUIRED.value,
            "app_by": None,
            "next_act": "Cancelled: Duplicate of backend asynchronous export project #ENG-491.",
            "version": 2,
            "delta_h": 40,
        },
    ]

    # Expand items to reach exactly 35 high-fidelity operational records
    categories_cycle = [
        WorkItemCategory.CUSTOMER_ISSUE.value,
        WorkItemCategory.ENGINEERING_PROBLEM.value,
        WorkItemCategory.PAYMENT_INVESTIGATION.value,
        WorkItemCategory.PRODUCTION_INCIDENT.value,
        WorkItemCategory.COMPLIANCE_REQUEST.value,
        WorkItemCategory.OPERATIONAL_APPROVAL.value,
    ]
    priorities_cycle = [Priority.LOW.value, Priority.MEDIUM.value, Priority.HIGH.value, Priority.CRITICAL.value]
    teams_cycle = [TEAM_PAYMENTS_ID, TEAM_SRE_ID, TEAM_COMPLIANCE_ID]
    statuses_cycle = [
        WorkItemStatus.TRIAGE.value,
        WorkItemStatus.IN_PROGRESS.value,
        WorkItemStatus.PENDING_APPROVAL.value,
        WorkItemStatus.BLOCKED.value,
        WorkItemStatus.RESOLVED.value,
    ]

    additional_count = 35 - len(item_definitions)
    for i in range(additional_count):
        cat = categories_cycle[i % len(categories_cycle)]
        prio = priorities_cycle[i % len(priorities_cycle)]
        team = teams_cycle[i % len(teams_cycle)]
        stat = statuses_cycle[i % len(statuses_cycle)]
        req_app = (cat in [WorkItemCategory.OPERATIONAL_APPROVAL.value, WorkItemCategory.COMPLIANCE_REQUEST.value]) or (prio == Priority.CRITICAL.value)

        app_stat = ApprovalStatus.NOT_REQUIRED.value
        app_by = None
        if req_app:
            if stat == WorkItemStatus.RESOLVED.value:
                app_stat = ApprovalStatus.APPROVED.value
                app_by = USER_ALICE_ID if team == TEAM_PAYMENTS_ID else (USER_DIANA_ID if team == TEAM_SRE_ID else USER_EVAN_ID)
            else:
                app_stat = ApprovalStatus.PENDING.value

        assignee = None if stat == WorkItemStatus.TRIAGE.value else (USER_CHARLIE_ID if team == TEAM_PAYMENTS_ID else USER_FIONA_ID)

        item_definitions.append({
            "title": f"Operational Action Item #{100 + i}: {cat.replace('_', ' ').title()} in {prio} Tier",
            "desc": f"Automated operational tracking ticket for {cat.lower().replace('_', ' ')} review. System verification required for compliance ledger.",
            "cat": cat,
            "prio": prio,
            "team": team,
            "creator": USER_ALICE_ID,
            "assignee": assignee,
            "status": stat,
            "req_app": req_app,
            "app_stat": app_stat,
            "app_by": app_by,
            "next_act": "Investigate underlying metric trend and log progress in ticket history." if stat != WorkItemStatus.RESOLVED.value else "Work completed and verified.",
            "version": 3 if stat == WorkItemStatus.RESOLVED.value else 1,
            "delta_h": 20 + i * 3,
        })

    # Insert WorkItems with AuditLogs and OutboxEvents
    first_work_item_id = None
    for item_data in item_definitions:
        item_id = str(uuid.uuid4())
        if not first_work_item_id:
            first_work_item_id = item_id
        created_time = now - timedelta(hours=item_data["delta_h"])
        updated_time = created_time + timedelta(minutes=30)

        work_item = WorkItem(
            id=item_id,
            title=item_data["title"],
            description=item_data["desc"],
            category=item_data["cat"],
            status=item_data["status"],
            priority=item_data["prio"],
            team_id=item_data["team"],
            creator_id=item_data["creator"],
            assignee_id=item_data["assignee"],
            next_action_required=item_data["next_act"],
            requires_approval=item_data["req_app"],
            approval_status=item_data["app_stat"],
            approved_by_id=item_data["app_by"],
            version=item_data["version"],
            created_at=created_time,
            updated_at=updated_time,
        )
        db.add(work_item)
        await db.flush()

        # Initial Audit Log (CREATED)
        audit_create = AuditLog(
            id=str(uuid.uuid4()),
            work_item_id=item_id,
            actor_id=item_data["creator"],
            action_type=AuditActionType.CREATED.value,
            previous_state={},
            new_state={"status": WorkItemStatus.TRIAGE.value, "priority": item_data["prio"], "title": item_data["title"]},
            reason="Item created during operations shift",
            created_at=created_time,
        )
        db.add(audit_create)

        # Outbox Event for Creation
        outbox_create = OutboxEvent(
            id=str(uuid.uuid4()),
            work_item_id=item_id,
            event_type="WORK_ITEM_CREATED",
            payload={"work_item_id": item_id, "title": item_data["title"], "priority": item_data["prio"]},
            dedup_key=f"seed-{item_id}-create",
            status=OutboxStatus.COMPLETED.value,
            attempts=1,
            max_attempts=5,
            created_at=created_time,
        )
        db.add(outbox_create)

        # Subsequent Audit Logs based on state
        if item_data["assignee"]:
            claim_time = created_time + timedelta(minutes=10)
            audit_claim = AuditLog(
                id=str(uuid.uuid4()),
                work_item_id=item_id,
                actor_id=item_data["assignee"],
                action_type=AuditActionType.CLAIMED.value,
                previous_state={"assignee_id": None, "status": WorkItemStatus.TRIAGE.value},
                new_state={"assignee_id": item_data["assignee"], "status": WorkItemStatus.IN_PROGRESS.value},
                reason="Claimed ownership for triage and mitigation",
                created_at=claim_time,
            )
            db.add(audit_claim)

        if item_data["status"] == WorkItemStatus.RESOLVED.value:
            resolve_time = updated_time
            audit_resolve = AuditLog(
                id=str(uuid.uuid4()),
                work_item_id=item_id,
                actor_id=item_data["app_by"] or item_data["assignee"] or item_data["creator"],
                action_type=AuditActionType.APPROVAL_DECISION.value if item_data["req_app"] else AuditActionType.STATUS_CHANGED.value,
                previous_state={"status": WorkItemStatus.PENDING_APPROVAL.value if item_data["req_app"] else WorkItemStatus.IN_PROGRESS.value},
                new_state={"status": WorkItemStatus.RESOLVED.value, "approval_status": item_data["app_stat"]},
                reason="Verification checks passed; remediation active",
                created_at=resolve_time,
            )
            db.add(audit_resolve)

    # Add a sample failed outbox event referencing valid first_work_item_id
    sample_fail = OutboxEvent(
        id=str(uuid.uuid4()),
        work_item_id=first_work_item_id,
        event_type="SIMULATED_FAILURE_WEBHOOK",
        payload={
            "simulate_failure": True,
            "target_service": "PagerDuty OnCall Alert",
            "reason": "Simulated upstream network timeout during initial boot",
        },
        dedup_key=f"seed-fail-{uuid.uuid4()}",
        status=OutboxStatus.FAILED.value,
        attempts=2,
        max_attempts=5,
        next_retry_at=now + timedelta(seconds=8),
        last_error="Attempt 2/5 failed: Upstream connection timeout 504.",
        created_at=now - timedelta(minutes=5),
    )
    db.add(sample_fail)

    await db.commit()
    return True

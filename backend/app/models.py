"""SQLAlchemy 2.0 ORM Models and System Enums.
Strictly mapped to ARCHITECTURE.md specifications.
Stage A: Approved & Locked Contract.
"""

from datetime import datetime
from enum import Enum
from typing import Any
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


# =====================================================================
# SYSTEM ENUMS
# =====================================================================

class TeamRole(str, Enum):
    """Team membership role hierarchy."""
    MEMBER = "MEMBER"
    APPROVER = "APPROVER"
    LEAD = "LEAD"


class WorkItemCategory(str, Enum):
    """Operational categories of work items."""
    CUSTOMER_ISSUE = "CUSTOMER_ISSUE"
    ENGINEERING_PROBLEM = "ENGINEERING_PROBLEM"
    PAYMENT_INVESTIGATION = "PAYMENT_INVESTIGATION"
    PRODUCTION_INCIDENT = "PRODUCTION_INCIDENT"
    COMPLIANCE_REQUEST = "COMPLIANCE_REQUEST"
    OPERATIONAL_APPROVAL = "OPERATIONAL_APPROVAL"


class Priority(str, Enum):
    """Work item operational priority levels."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class WorkItemStatus(str, Enum):
    """Deterministic state machine status values."""
    TRIAGE = "TRIAGE"
    IN_PROGRESS = "IN_PROGRESS"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    BLOCKED = "BLOCKED"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class ApprovalStatus(str, Enum):
    """Formal approval gate status values."""
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AuditActionType(str, Enum):
    """Immutable audit trail action identifiers."""
    CREATED = "CREATED"
    CLAIMED = "CLAIMED"
    REASSIGNED = "REASSIGNED"
    STATUS_CHANGED = "STATUS_CHANGED"
    PRIORITY_CHANGED = "PRIORITY_CHANGED"
    APPROVAL_DECISION = "APPROVAL_DECISION"
    COMMENTED = "COMMENTED"
    NEXT_ACTION_UPDATED = "NEXT_ACTION_UPDATED"


class OutboxStatus(str, Enum):
    """Transactional outbox lifecycle states."""
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DEAD_LETTER = "DEAD_LETTER"


# =====================================================================
# RELATIONAL MODELS
# =====================================================================

class User(Base):
    """User account entity."""
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    avatar_color: Mapped[str] = mapped_column(String(32), default="#6366F1", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    team_memberships: Mapped[list["TeamMembership"]] = relationship(
        "TeamMembership", back_populates="user", cascade="all, delete-orphan"
    )
    created_items: Mapped[list["WorkItem"]] = relationship(
        "WorkItem", back_populates="creator", foreign_keys="WorkItem.creator_id"
    )
    assigned_items: Mapped[list["WorkItem"]] = relationship(
        "WorkItem", back_populates="assignee", foreign_keys="WorkItem.assignee_id"
    )
    approved_items: Mapped[list["WorkItem"]] = relationship(
        "WorkItem", back_populates="approved_by", foreign_keys="WorkItem.approved_by_id"
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship("AuditLog", back_populates="actor")


class Team(Base):
    """Operational team entity."""
    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    memberships: Mapped[list["TeamMembership"]] = relationship(
        "TeamMembership", back_populates="team", cascade="all, delete-orphan", lazy="selectin"
    )
    work_items: Mapped[list["WorkItem"]] = relationship("WorkItem", back_populates="team")


class TeamMembership(Base):
    """User membership and role within a team."""
    __tablename__ = "team_memberships"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    team_id: Mapped[str] = mapped_column(String(36), ForeignKey("teams.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "team_id", name="uq_team_membership"),
        Index("idx_team_memberships_user", "user_id"),
        Index("idx_team_memberships_team", "team_id"),
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="team_memberships", lazy="selectin")
    team: Mapped["Team"] = relationship("Team", back_populates="memberships", lazy="selectin")


class WorkItem(Base):
    """Core operational work item entity."""
    __tablename__ = "work_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=WorkItemStatus.TRIAGE.value, nullable=False)
    priority: Mapped[str] = mapped_column(String(32), default=Priority.MEDIUM.value, nullable=False)
    team_id: Mapped[str] = mapped_column(String(36), ForeignKey("teams.id", ondelete="RESTRICT"), nullable=False)
    creator_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    assignee_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    next_action_required: Mapped[str] = mapped_column(
        String(500), default="Initial triage required", nullable=False
    )
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approval_status: Mapped[str] = mapped_column(
        String(32), default=ApprovalStatus.NOT_REQUIRED.value, nullable=False
    )
    approved_by_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_work_items_team_status_prio", "team_id", "status", "priority"),
        Index("idx_work_items_assignee_status", "assignee_id", "status"),
        Index("idx_work_items_pagination", "updated_at", "id"),
        Index("idx_work_items_category", "category"),
    )

    # Relationships
    team: Mapped["Team"] = relationship("Team", back_populates="work_items", lazy="selectin")
    creator: Mapped["User"] = relationship("User", foreign_keys=[creator_id], back_populates="created_items", lazy="selectin")
    assignee: Mapped["User | None"] = relationship("User", foreign_keys=[assignee_id], back_populates="assigned_items", lazy="selectin")
    approved_by: Mapped["User | None"] = relationship(
        "User", foreign_keys=[approved_by_id], back_populates="approved_items", lazy="selectin"
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(
        "AuditLog", back_populates="work_item", cascade="all, delete-orphan", order_by="AuditLog.created_at.desc()"
    )
    outbox_events: Mapped[list["OutboxEvent"]] = relationship(
        "OutboxEvent", back_populates="work_item", cascade="all, delete-orphan"
    )


class AuditLog(Base):
    """Immutable, append-only operational audit trail."""
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    work_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False
    )
    actor_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    previous_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    new_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_audit_logs_item_created", "work_item_id", "created_at"),
        Index("idx_audit_logs_actor", "actor_id"),
    )

    # Relationships
    work_item: Mapped["WorkItem"] = relationship("WorkItem", back_populates="audit_logs")
    actor: Mapped["User"] = relationship("User", back_populates="audit_logs", lazy="selectin")


class IdempotencyRecord(Base):
    """Deduplication and cached response store for state-mutating requests."""
    __tablename__ = "idempotency_records"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_idempotency_user", "user_id"),
        Index("idx_idempotency_created", "created_at"),
    )


class OutboxEvent(Base):
    """Reliable secondary side-effect store for transactional outbox dispatching."""
    __tablename__ = "outbox_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    work_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default=OutboxStatus.PENDING.value, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_outbox_processing", "status", "next_retry_at", "created_at"),
    )

    # Relationships
    work_item: Mapped["WorkItem"] = relationship("WorkItem", back_populates="outbox_events")

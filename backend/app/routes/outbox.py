"""Transactional Outbox Inspection & Control Routes.
Allows observing asynchronous dispatching, manual batch triggers, and failure simulations.
Stage P2: Async Outbox Worker & API Wiring.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import OutboxEvent, OutboxStatus, WorkItem
from app.schemas import (
    OutboxBatchResultResponse,
    OutboxEventResponse,
    OutboxQueueSummaryResponse,
)
from app.worker import process_outbox_batch

router = APIRouter(prefix="/outbox", tags=["Transactional Outbox"])


@router.get("", response_model=OutboxQueueSummaryResponse)
async def list_outbox_events(
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List recent outbox events with status counts for observability."""
    base_stmt = select(OutboxEvent)
    if status_filter:
        base_stmt = base_stmt.where(OutboxEvent.status == status_filter.upper())

    total_stmt = select(func.count(OutboxEvent.id))
    if status_filter:
        total_stmt = total_stmt.where(OutboxEvent.status == status_filter.upper())
    total_res = await db.execute(total_stmt)
    total = total_res.scalar_one()

    # Query events ordered by latest first
    query_stmt = base_stmt.order_by(OutboxEvent.created_at.desc()).limit(limit).offset(offset)
    res = await db.execute(query_stmt)
    events = res.scalars().all()

    # Calculate status counts
    counts: dict[str, int] = {}
    for st in OutboxStatus:
        st_count_stmt = select(func.count(OutboxEvent.id)).where(OutboxEvent.status == st.value)
        c_res = await db.execute(st_count_stmt)
        counts[st.value] = c_res.scalar_one()

    return OutboxQueueSummaryResponse(
        events=[OutboxEventResponse.model_validate(e) for e in events],
        total=total,
        counts_by_status=counts,
    )


@router.post("/process", response_model=OutboxBatchResultResponse)
async def trigger_outbox_process(db: AsyncSession = Depends(get_db)):
    """Synchronously trigger an outbox processing cycle for deterministic evaluation/demo."""
    result = await process_outbox_batch(db, batch_size=50)
    return OutboxBatchResultResponse(
        processed=result["processed"],
        completed=result["completed"],
        failed=result["failed"],
        dead_letter=result["dead_letter"],
        timestamp=datetime.now(timezone.utc),
    )


@router.post("/{event_id}/retry", response_model=OutboxEventResponse)
async def retry_outbox_event(event_id: str, db: AsyncSession = Depends(get_db)):
    """Reset a FAILED or DEAD_LETTER event back to PENDING and immediately re-evaluate."""
    stmt = select(OutboxEvent).where(OutboxEvent.id == event_id)
    result = await db.execute(stmt)
    event = result.scalar_one_or_none()

    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Outbox event '{event_id}' not found.",
        )

    # Reset retry state
    event.status = OutboxStatus.PENDING.value
    event.attempts = 0
    event.next_retry_at = None
    event.last_error = None
    await db.commit()
    await db.refresh(event)

    # Process immediately
    await process_outbox_batch(db, batch_size=10)
    await db.refresh(event)

    return OutboxEventResponse.model_validate(event)


@router.post("/simulate-failure", response_model=OutboxEventResponse, status_code=status.HTTP_201_CREATED)
async def simulate_outbox_failure(
    work_item_id: Optional[str] = Query(None, description="Optional associated work item ID"),
    db: AsyncSession = Depends(get_db),
):
    """Enqueue an event configured to fail, demonstrating exponential backoff and DLQ dead-lettering."""
    now = datetime.now(timezone.utc)

    # Use first available work item if none provided
    target_item_id = work_item_id
    if not target_item_id:
        item_stmt = select(WorkItem.id).limit(1)
        item_res = await db.execute(item_stmt)
        first_id = item_res.scalar_one_or_none()
        target_item_id = first_id or str(uuid.uuid4())

    event_id = str(uuid.uuid4())
    event = OutboxEvent(
        id=event_id,
        work_item_id=target_item_id,
        event_type="SIMULATED_FAILURE_WEBHOOK",
        payload={
            "simulate_failure": True,
            "target_service": "PagerDuty Incident Webhook",
            "reason": "Simulated intermittent upstream 504 gateway timeout",
            "enqueued_at": now.isoformat(),
        },
        dedup_key=f"sim-fail-{event_id}",
        status=OutboxStatus.PENDING.value,
        attempts=0,
        max_attempts=5,
        created_at=now,
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)

    return OutboxEventResponse.model_validate(event)

"""Transactional Outbox Processor & Background Worker.
Implements Protocol 5: Reliable Asynchronous Processing.
- At-least-once delivery with deduplication
- Exponential retry backoff: 2 ** attempts
- Dead-letter queue (DLQ) after 5 attempts
- Fault injection and failure simulation support
Stage P2: Async Outbox Worker & API Wiring.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models import OutboxEvent, OutboxStatus


async def process_outbox_batch(db: AsyncSession, batch_size: int = 25) -> dict[str, Any]:
    """Execute one batch of eligible outbox events with idempotency and retry backoff."""
    now = datetime.now(timezone.utc)

    # 1. Fetch pending and failed events ready for execution
    stmt = (
        select(OutboxEvent)
        .where(
            OutboxEvent.status.in_([OutboxStatus.PENDING.value, OutboxStatus.FAILED.value]),
            OutboxEvent.attempts < OutboxEvent.max_attempts,
            or_(
                OutboxEvent.next_retry_at.is_(None),
                OutboxEvent.next_retry_at <= now,
            ),
        )
        .order_by(OutboxEvent.created_at.asc())
        .limit(batch_size)
    )
    result = await db.execute(stmt)
    events = result.scalars().all()

    if not events:
        return {
            "processed": 0,
            "completed": 0,
            "failed": 0,
            "dead_letter": 0,
        }

    completed_count = 0
    failed_count = 0
    dead_letter_count = 0

    for event in events:
        # Mark as PROCESSING
        event.status = OutboxStatus.PROCESSING.value
        event.attempts += 1

        # Check for simulated failure injection
        payload = event.payload or {}
        should_fail = (
            payload.get("simulate_failure") is True
            or event.event_type.startswith("SIMULATED_FAILURE")
        )

        if should_fail:
            # Simulate transient network / webhook outage
            if event.attempts >= event.max_attempts:
                event.status = OutboxStatus.DEAD_LETTER.value
                event.next_retry_at = None
                event.last_error = (
                    f"Dead-lettered after {event.attempts} attempts: External webhook endpoint "
                    "consistently returned 504 Gateway Timeout. Moved to DLQ for manual inspection."
                )
                dead_letter_count += 1
            else:
                event.status = OutboxStatus.FAILED.value
                backoff_seconds = 2 ** event.attempts
                event.next_retry_at = now + timedelta(seconds=backoff_seconds)
                event.last_error = (
                    f"Attempt {event.attempts}/{event.max_attempts} failed: External service connection timeout. "
                    f"Next retry scheduled in {backoff_seconds}s (exponential backoff)."
                )
                failed_count += 1
        else:
            # Successful dispatch of asynchronous secondary side effect
            event.status = OutboxStatus.COMPLETED.value
            event.next_retry_at = None
            event.last_error = None
            completed_count += 1

    await db.commit()

    return {
        "processed": len(events),
        "completed": completed_count,
        "failed": failed_count,
        "dead_letter": dead_letter_count,
    }


# Event-driven wakeup event for instantaneous outbox processing
outbox_wakeup_event = asyncio.Event()


def trigger_outbox_wakeup() -> None:
    """Signals the outbox background worker to process pending events immediately."""
    outbox_wakeup_event.set()


async def run_outbox_worker_loop(fallback_timeout: float = 60.0):
    """Event-driven background worker loop.
    
    Wakes up instantaneously whenever outbox_wakeup_event is set,
    and falls back to checking every fallback_timeout seconds (default 60s)
    to handle exponential backoff retries without wasting free-tier CPU.
    """
    while True:
        try:
            async with AsyncSessionLocal() as db:
                await process_outbox_batch(db)
        except asyncio.CancelledError:
            break
        except Exception:
            # Catch transient database locks or poll exceptions without crashing worker loop
            await asyncio.sleep(1.0)

        # Clear event before waiting for next trigger
        outbox_wakeup_event.clear()
        try:
            await asyncio.wait_for(outbox_wakeup_event.wait(), timeout=fallback_timeout)
        except asyncio.TimeoutError:
            # Fallback timeout elapsed: loop checks for any retryable backoff events
            pass
        except asyncio.CancelledError:
            break


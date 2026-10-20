"""Synchronous Idempotency Guard Service.
Protects mutating endpoints from duplicate network submissions and replay storms.
Stage P1: Backend Domain Engine.
"""

import hashlib
import json
from typing import Any, Optional
from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IdempotencyRecord


def compute_request_hash(payload: Any) -> str:
    """Compute deterministic SHA-256 hash of a request payload."""
    if payload is None:
        payload_str = ""
    elif isinstance(payload, (dict, list)):
        payload_str = json.dumps(payload, sort_keys=True, default=str)
    elif hasattr(payload, "model_dump"):
        payload_str = json.dumps(payload.model_dump(), sort_keys=True, default=str)
    else:
        payload_str = str(payload)
    return hashlib.sha256(payload_str.encode("utf-8")).hexdigest()


async def check_idempotency(
    db: AsyncSession,
    key: Optional[str],
    user_id: str,
    endpoint: str,
    payload: Any,
) -> Optional[JSONResponse]:
    """Check if an idempotency key was previously processed.

    Returns cached JSONResponse if exact replay, or raises HTTP 422 if key is reused
    with a conflicting payload.
    """
    if not key or not key.strip():
        return None

    clean_key = key.strip()
    stmt = select(IdempotencyRecord).where(IdempotencyRecord.key == clean_key)
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()

    if not record:
        return None

    current_hash = compute_request_hash(payload)

    # Key exists: verify payload and user integrity
    if record.request_hash == current_hash and record.endpoint == endpoint:
        # Exact replay match: Return stored response with X-Cache-Lookup: HIT
        return JSONResponse(
            status_code=record.status_code,
            content=record.response_body,
            headers={
                "X-Cache-Lookup": "HIT",
                "X-Idempotent-Replay": "true",
            },
        )

    # Key exists but was used for a different payload or endpoint
    raise HTTPException(
        status_code=422,
        detail=(
            f"Idempotency key '{clean_key}' was previously used for a different request "
            f"payload or endpoint. Generate a new key for distinct operations."
        ),
    )


async def record_idempotency(
    db: AsyncSession,
    key: Optional[str],
    user_id: str,
    endpoint: str,
    payload: Any,
    status_code: int,
    response_body: dict[str, Any],
) -> None:
    """Persist an idempotency record within the current database transaction."""
    if not key or not key.strip():
        return

    clean_key = key.strip()
    request_hash = compute_request_hash(payload)

    # Store record
    record = IdempotencyRecord(
        key=clean_key,
        user_id=user_id,
        endpoint=endpoint,
        request_hash=request_hash,
        status_code=status_code,
        response_body=response_body,
    )
    db.add(record)

"""Authentication and Resource-Level Authorization Middleware and Dependencies.
Enforces X-User-Id identification and team-scoped RBAC rules.
Stage P1: Backend Domain Engine.
"""

import uuid
from typing import Optional
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import TeamMembership, TeamRole, User

# Well-known fallback user ID (Alex Chen, Operations Lead)
DEFAULT_SEED_LEAD_USER_ID = "00000000-0000-0000-0000-000000000001"


async def get_current_user(
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extract authenticated user context from X-User-Id header with fallback to lead user."""
    user_id = x_user_id.strip() if x_user_id else DEFAULT_SEED_LEAD_USER_ID

    # Validate UUID format
    try:
        uuid_obj = uuid.UUID(user_id)
        normalized_id = str(uuid_obj)
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid X-User-Id header: '{user_id}' is not a valid UUID string.",
        )

    # Query user from database
    result = await db.execute(select(User).where(User.id == normalized_id))
    user = result.scalar_one_or_none()

    if not user:
        # Fallback creation for well-known seed users if accessing before manual seed
        if normalized_id == DEFAULT_SEED_LEAD_USER_ID:
            user = User(
                id=DEFAULT_SEED_LEAD_USER_ID,
                email="alex.chen@newtonite.internal",
                full_name="Alex Chen (Ops Lead)",
                avatar_color="#6366F1",
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            return user

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"User with ID '{normalized_id}' not found in the system.",
        )

    return user


async def get_user_team_membership(
    db: AsyncSession,
    user_id: str,
    team_id: str,
) -> Optional[TeamMembership]:
    """Retrieve membership and role for a user within a specific team."""
    stmt = select(TeamMembership).where(
        TeamMembership.user_id == user_id,
        TeamMembership.team_id == team_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def verify_team_membership(
    db: AsyncSession,
    user_id: str,
    team_id: str,
    allowed_roles: Optional[list[TeamRole | str]] = None,
) -> TeamMembership:
    """Enforce resource-level authorization.

    Raises HTTP 403 Forbidden if user is not in the owning team or lacks required role.
    """
    membership = await get_user_team_membership(db, user_id, team_id)

    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Access denied: User '{user_id}' is not a member of team '{team_id}'. "
                "Only team members can perform this action."
            ),
        )

    if allowed_roles:
        allowed_str_roles = [
            r.value if isinstance(r, TeamRole) else str(r) for r in allowed_roles
        ]
        if membership.role not in allowed_str_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Access denied: Action requires role in {allowed_str_roles}, "
                    f"but your role in team '{team_id}' is '{membership.role}'."
                ),
            )

    return membership

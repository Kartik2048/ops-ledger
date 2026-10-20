"""User and Team Identity Management Endpoints.
Provides simulated multi-operator switching and team hierarchy inspection.
Stage P1: Backend Domain Engine.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.auth import get_current_user
from app.database import get_db
from app.models import Team, TeamMembership, User
from app.schemas import TeamResponse, UserDetailResponse, UserResponse

router = APIRouter(tags=["Identity & Teams"])


@router.get("/users", response_model=list[UserResponse])
async def list_users(db: AsyncSession = Depends(get_db)):
    """List all registered users for role-switching and assignment selection."""
    stmt = select(User).order_by(User.full_name.asc())
    result = await db.execute(stmt)
    users = result.scalars().all()
    return [UserResponse.model_validate(u) for u in users]


@router.get("/users/me", response_model=UserDetailResponse)
async def get_current_user_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve currently active user context with all associated team memberships."""
    stmt = (
        select(User)
        .where(User.id == current_user.id)
        .options(
            selectinload(User.team_memberships).selectinload(TeamMembership.team)
        )
    )
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User profile not found.")
    return UserDetailResponse.model_validate(user)


@router.get("/teams", response_model=list[TeamResponse])
async def list_teams(db: AsyncSession = Depends(get_db)):
    """List all operational teams with their memberships and member counts."""
    stmt = (
        select(Team)
        .options(
            selectinload(Team.memberships).selectinload(TeamMembership.user)
        )
        .order_by(Team.name.asc())
    )
    result = await db.execute(stmt)
    teams = result.scalars().all()

    response = []
    for t in teams:
        item = TeamResponse.model_validate(t)
        item.member_count = len(t.memberships)
        response.append(item)
    return response


@router.get("/teams/{team_id}", response_model=TeamResponse)
async def get_team(team_id: str, db: AsyncSession = Depends(get_db)):
    """Retrieve details for a specific operational team."""
    stmt = (
        select(Team)
        .where(Team.id == team_id)
        .options(
            selectinload(Team.memberships).selectinload(TeamMembership.user)
        )
    )
    result = await db.execute(stmt)
    team = result.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Team '{team_id}' not found.")

    response = TeamResponse.model_validate(team)
    response.member_count = len(team.memberships)
    return response

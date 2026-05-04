from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.deps import require_user
from app.models.user import User
from app.schemas.onboarding import OnboardingIn, OnboardingOut

router = APIRouter()


@router.get("/me/onboarding", response_model=OnboardingOut)
async def get_onboarding(
    current_user: User = Depends(require_user),
) -> OnboardingOut:
    data = json.loads(current_user.onboarding_data) if current_user.onboarding_data else {}
    return OnboardingOut(
        onboarding_complete=current_user.onboarding_complete,
        skill_level=data.get("skill_level"),
        goal=data.get("goal"),
    )


@router.post("/me/onboarding", response_model=OnboardingOut)
async def complete_onboarding(
    body: OnboardingIn,
    current_user: User = Depends(require_user),
    session: AsyncSession = Depends(get_db),
) -> OnboardingOut:
    current_user.onboarding_data = json.dumps({"skill_level": body.skill_level, "goal": body.goal})
    current_user.onboarding_complete = True
    await session.commit()
    return OnboardingOut(
        onboarding_complete=True,
        skill_level=body.skill_level,
        goal=body.goal,
    )

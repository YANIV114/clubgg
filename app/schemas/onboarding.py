from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class OnboardingIn(BaseModel):
    skill_level: Literal["beginner", "intermediate", "advanced"]
    goal: Literal["learn_fundamentals", "improve_tournament", "analyze_hands"]


class OnboardingOut(BaseModel):
    onboarding_complete: bool
    skill_level: str | None = None
    goal: str | None = None

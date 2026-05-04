from __future__ import annotations

import uuid
from datetime import UTC, datetime

import stripe as _stripe
from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.session import get_db
from app.deps import require_user
from app.models.billing import Subscription, SubscriptionPlan
from app.models.user import User

# ── Plan feature definitions ──────────────────────────────────────────────────

_FREE_FEATURES: list[str] = [
    "basic_dashboard",
    "beginner_courses",
    "practice_basic",
]

_STARTER_FEATURES: list[str] = _FREE_FEATURES + [
    "intermediate_courses",
    "practice_full",
    "hand_replay",
    "progress_dashboard",
]

_PRO_FEATURES: list[str] = _STARTER_FEATURES + [
    "advanced_courses",
    "elite_courses",
    "replay_drills",
    "leak_tracker",
    "full_skill_map",
    "tournament_plan",
]

_ELITE_FEATURES: list[str] = _PRO_FEATURES + [
    "ai_coach",
    "advanced_analysis",
    "cash_games_future",
]

PLAN_DEFINITIONS: list[dict] = [
    {
        "slug": "free",
        "name": "Free",
        "price_cents": 0,
        "sort_order": 0,
        "features": _FREE_FEATURES,
    },
    {
        "slug": "starter",
        "name": "Starter",
        "price_cents": 900,
        "sort_order": 1,
        "features": _STARTER_FEATURES,
    },
    {
        "slug": "pro",
        "name": "Tournament Pro",
        "price_cents": 1900,
        "sort_order": 2,
        "features": _PRO_FEATURES,
    },
    {
        "slug": "elite",
        "name": "Elite",
        "price_cents": 3900,
        "sort_order": 3,
        "features": _ELITE_FEATURES,
    },
]

_FREE_PLAN_FEATURES: list[str] = _FREE_FEATURES


# ── Queries ───────────────────────────────────────────────────────────────────


async def list_plans(session: AsyncSession) -> list[SubscriptionPlan]:
    result = await session.execute(select(SubscriptionPlan).order_by(SubscriptionPlan.sort_order))
    return list(result.scalars().all())


async def get_plan_by_slug(session: AsyncSession, slug: str) -> SubscriptionPlan | None:
    return await session.scalar(select(SubscriptionPlan).where(SubscriptionPlan.slug == slug))


async def get_user_subscription(session: AsyncSession, user_id: uuid.UUID) -> Subscription | None:
    return await session.scalar(
        select(Subscription).where(
            Subscription.user_id == user_id,
            Subscription.status == "active",
        )
    )


async def get_user_features(session: AsyncSession, user_id: uuid.UUID) -> list[str]:
    sub = await get_user_subscription(session, user_id)
    if sub is None:
        return _FREE_PLAN_FEATURES
    return list(sub.plan.features)


async def get_user_plan_slug(session: AsyncSession, user_id: uuid.UUID) -> str:
    sub = await get_user_subscription(session, user_id)
    if sub is None:
        return "free"
    return sub.plan.slug


async def user_has_feature(session: AsyncSession, user_id: uuid.UUID, feature: str) -> bool:
    features = await get_user_features(session, user_id)
    return feature in features


async def set_user_plan(session: AsyncSession, user_id: uuid.UUID, plan_slug: str) -> Subscription:
    plan = await get_plan_by_slug(session, plan_slug)
    if plan is None:
        raise ValueError(f"Unknown plan slug: {plan_slug!r}")

    sub = await get_user_subscription(session, user_id)
    if sub is None:
        sub = Subscription(
            user_id=user_id,
            plan_id=plan.id,
            status="active",
            started_at=datetime.now(tz=UTC),
        )
        session.add(sub)
    else:
        sub.plan_id = plan.id
        sub.started_at = datetime.now(tz=UTC)

    await session.flush()
    await session.refresh(sub, ["plan"])
    return sub


# ── Feature gate dependency factory ──────────────────────────────────────────


def require_feature(feature: str):
    async def _dep(
        user: User = Depends(require_user),
        session: AsyncSession = Depends(get_db),
    ) -> None:
        if not await user_has_feature(session, user.id, feature):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Feature '{feature}' requires a higher subscription plan.",
            )

    return _dep


# ── Stripe helpers ────────────────────────────────────────────────────────────


def _stripe_client() -> _stripe.StripeClient:
    return _stripe.StripeClient(settings.STRIPE_SECRET_KEY)


async def get_or_create_stripe_customer(session: AsyncSession, user: User) -> str:
    """Return stripe_customer_id, creating one via Stripe API if needed."""
    sub = await get_user_subscription(session, user.id)
    if sub and sub.stripe_customer_id:
        return sub.stripe_customer_id
    client = _stripe_client()
    customer = client.customers.create(
        params={"email": user.email, "metadata": {"user_id": str(user.id)}}
    )
    return customer.id


async def set_user_plan_from_stripe(
    session: AsyncSession,
    user_id: uuid.UUID,
    plan_slug: str,
    stripe_customer_id: str,
    stripe_subscription_id: str,
) -> Subscription:
    plan = await get_plan_by_slug(session, plan_slug)
    if plan is None:
        raise ValueError(f"Unknown plan slug: {plan_slug!r}")
    sub = await get_user_subscription(session, user_id)
    if sub is None:
        sub = Subscription(
            user_id=user_id,
            plan_id=plan.id,
            status="active",
            started_at=datetime.now(tz=UTC),
            stripe_customer_id=stripe_customer_id,
            stripe_subscription_id=stripe_subscription_id,
        )
        session.add(sub)
    else:
        sub.plan_id = plan.id
        sub.started_at = datetime.now(tz=UTC)
        sub.status = "active"
        sub.stripe_customer_id = stripe_customer_id
        sub.stripe_subscription_id = stripe_subscription_id
    await session.flush()
    await session.refresh(sub, ["plan"])
    return sub


async def cancel_subscription_by_stripe_id(
    session: AsyncSession,
    stripe_subscription_id: str,
) -> None:
    sub = await session.scalar(
        select(Subscription).where(Subscription.stripe_subscription_id == stripe_subscription_id)
    )
    if sub:
        sub.status = "cancelled"
        sub.cancelled_at = datetime.now(tz=UTC)
        await session.flush()

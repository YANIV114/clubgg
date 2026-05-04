"""
Seed subscription plans — idempotent, safe to run multiple times.

Usage:
    uv run python -m app.seed_plans
"""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from app.db.session import AsyncSessionFactory
from app.models.billing import SubscriptionPlan
from app.services.billing_service import PLAN_DEFINITIONS


async def seed_plans() -> None:
    async with AsyncSessionFactory() as session:
        for defn in PLAN_DEFINITIONS:
            existing = await session.scalar(
                select(SubscriptionPlan).where(SubscriptionPlan.slug == defn["slug"])
            )
            if existing is None:
                plan = SubscriptionPlan(**defn)
                session.add(plan)
                print(f"  + inserted plan: {defn['slug']}")
            else:
                existing.name = defn["name"]
                existing.price_cents = defn["price_cents"]
                existing.sort_order = defn["sort_order"]
                existing.features = defn["features"]
                print(f"  ~ updated plan:  {defn['slug']}")
        await session.commit()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(seed_plans())

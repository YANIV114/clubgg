from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class PlanOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    price_cents: int
    sort_order: int
    features: list[str]


class BillingMeOut(BaseModel):
    plan_slug: str
    plan_name: str
    features: list[str]
    subscription_id: uuid.UUID | None = None
    started_at: datetime | None = None


class MockUpgradeRequest(BaseModel):
    plan_slug: str


class CheckoutSessionRequest(BaseModel):
    plan_slug: str


class CheckoutSessionOut(BaseModel):
    url: str


class PortalSessionOut(BaseModel):
    url: str

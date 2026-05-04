from __future__ import annotations

import stripe as _stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings as _settings
from app.db.session import get_db
from app.dependencies import require_tester
from app.deps import require_user
from app.models.user import User
from app.schemas.billing import (
    BillingMeOut,
    CheckoutSessionOut,
    CheckoutSessionRequest,
    MockUpgradeRequest,
    PlanOut,
    PortalSessionOut,
)
from app.services import billing_service

router = APIRouter()


@router.get("/billing/plans", response_model=list[PlanOut])
async def list_plans(session: AsyncSession = Depends(get_db)) -> list[PlanOut]:
    plans = await billing_service.list_plans(session)
    return [
        PlanOut(
            id=p.id,
            slug=p.slug,
            name=p.name,
            price_cents=p.price_cents,
            sort_order=p.sort_order,
            features=p.features,
        )
        for p in plans
    ]


@router.get("/billing/me", response_model=BillingMeOut)
async def get_my_billing(
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_tester),
) -> BillingMeOut:
    sub = await billing_service.get_user_subscription(session, current_user.id)
    if sub is None:
        return BillingMeOut(
            plan_slug="free",
            plan_name="Free",
            features=billing_service._FREE_PLAN_FEATURES,
        )
    return BillingMeOut(
        plan_slug=sub.plan.slug,
        plan_name=sub.plan.name,
        features=list(sub.plan.features),
        subscription_id=sub.id,
        started_at=sub.started_at,
    )


@router.post("/billing/mock-upgrade", response_model=BillingMeOut)
async def mock_upgrade(
    body: MockUpgradeRequest,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
) -> BillingMeOut:
    if _settings.ENVIRONMENT == "production":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Mock upgrade not available in production.",
        )
    valid_slugs = {"free", "starter", "pro", "elite"}
    if body.plan_slug not in valid_slugs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid plan slug. Must be one of: {sorted(valid_slugs)}",
        )
    try:
        sub = await billing_service.set_user_plan(session, current_user.id, body.plan_slug)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    await session.commit()
    return BillingMeOut(
        plan_slug=sub.plan.slug,
        plan_name=sub.plan.name,
        features=list(sub.plan.features),
        subscription_id=sub.id,
        started_at=sub.started_at,
    )


@router.post("/billing/create-checkout-session", response_model=CheckoutSessionOut)
async def create_checkout_session(
    body: CheckoutSessionRequest,
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
) -> CheckoutSessionOut:
    price_id = _settings.stripe_price_map.get(body.plan_slug)
    if not price_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No Stripe price configured for plan: {body.plan_slug!r}",
        )
    try:
        customer_id = await billing_service.get_or_create_stripe_customer(session, current_user)
        client = _stripe.StripeClient(_settings.STRIPE_SECRET_KEY)
        checkout = client.checkout.sessions.create(
            params={
                "customer": customer_id,
                "mode": "subscription",
                "line_items": [{"price": price_id, "quantity": 1}],
                "success_url": _settings.BILLING_SUCCESS_URL,
                "cancel_url": _settings.BILLING_CANCEL_URL,
                "metadata": {
                    "user_id": str(current_user.id),
                    "plan_slug": body.plan_slug,
                },
                "subscription_data": {
                    "metadata": {
                        "user_id": str(current_user.id),
                        "plan_slug": body.plan_slug,
                    }
                },
            }
        )
    except _stripe.StripeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Stripe error: {exc.user_message or str(exc)}",
        ) from exc
    return CheckoutSessionOut(url=checkout.url)


@router.post("/billing/create-customer-portal-session", response_model=PortalSessionOut)
async def create_portal_session(
    session: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_user),
) -> PortalSessionOut:
    sub = await billing_service.get_user_subscription(session, current_user.id)
    if not sub or not sub.stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active Stripe subscription found.",
        )
    try:
        client = _stripe.StripeClient(_settings.STRIPE_SECRET_KEY)
        portal = client.billing_portal.sessions.create(
            params={
                "customer": sub.stripe_customer_id,
                "return_url": _settings.BILLING_CANCEL_URL,
            }
        )
    except _stripe.StripeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Stripe error: {exc.user_message or str(exc)}",
        ) from exc
    return PortalSessionOut(url=portal.url)


async def _handle_stripe_event(session: AsyncSession, event: dict) -> None:
    import uuid as _uuid

    event_type = event["type"]

    if event_type == "checkout.session.completed":
        obj = event["data"]["object"]
        user_id_str = (obj.get("metadata") or {}).get("user_id")
        plan_slug = (obj.get("metadata") or {}).get("plan_slug")
        stripe_customer_id = obj.get("customer")
        stripe_subscription_id = obj.get("subscription")
        if user_id_str and plan_slug and stripe_subscription_id:
            await billing_service.set_user_plan_from_stripe(
                session,
                _uuid.UUID(user_id_str),
                plan_slug,
                stripe_customer_id,
                stripe_subscription_id,
            )

    elif event_type in ("customer.subscription.updated", "customer.subscription.created"):
        obj = event["data"]["object"]
        stripe_sub_id = obj.get("id")
        price_id = None
        items = (obj.get("items") or {}).get("data") or []
        if items:
            price_id = items[0].get("price", {}).get("id")
        user_id_str = (obj.get("metadata") or {}).get("user_id")
        plan_slug = (obj.get("metadata") or {}).get("plan_slug")
        if not plan_slug and price_id:
            reverse = {v: k for k, v in _settings.stripe_price_map.items()}
            plan_slug = reverse.get(price_id)
        stripe_customer_id = obj.get("customer")
        if user_id_str and plan_slug and stripe_sub_id:
            await billing_service.set_user_plan_from_stripe(
                session,
                _uuid.UUID(user_id_str),
                plan_slug,
                stripe_customer_id,
                stripe_sub_id,
            )

    elif event_type == "customer.subscription.deleted":
        obj = event["data"]["object"]
        stripe_sub_id = obj.get("id")
        if stripe_sub_id:
            await billing_service.cancel_subscription_by_stripe_id(session, stripe_sub_id)


@router.post("/billing/webhook", include_in_schema=False)
async def stripe_webhook(
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict:
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    try:
        if _settings.STRIPE_WEBHOOK_SECRET:
            event = _stripe.Webhook.construct_event(
                payload, sig_header, _settings.STRIPE_WEBHOOK_SECRET
            )
        else:
            import json

            event = json.loads(payload)
    except (_stripe.SignatureVerificationError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook signature",
        ) from exc

    await _handle_stripe_event(session, event)
    await session.commit()
    return {"received": True}

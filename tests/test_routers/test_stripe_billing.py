"""
Integration tests for Stripe billing endpoints.
All Stripe network calls are mocked — no real API keys needed.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import SubscriptionPlan
from app.services.billing_service import PLAN_DEFINITIONS
from tests.conftest import TEST_INVITE_CODE

pytestmark = pytest.mark.usefixtures("beta_gate")


def _unique_email(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


async def _register(client: AsyncClient, email: str) -> tuple[str, str]:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "testpass123", "invite_code": TEST_INVITE_CODE},
    )
    assert resp.status_code == 201
    data = resp.json()
    return data["access_token"], data["user"]["id"]


@pytest.fixture(autouse=True)
async def seed_plans(db_session: AsyncSession) -> None:
    for defn in PLAN_DEFINITIONS:
        db_session.add(SubscriptionPlan(**defn))
    await db_session.flush()


# ── Checkout session ──────────────────────────────────────────────────────────


@pytest.mark.integration
class TestCheckoutSession:
    async def test_requires_auth(self, async_client: AsyncClient) -> None:
        resp = await async_client.post(
            "/api/v1/billing/create-checkout-session",
            json={"plan_slug": "pro"},
        )
        assert resp.status_code == 401

    async def test_no_stripe_price_configured_rejected(self, async_client: AsyncClient) -> None:
        # No Stripe prices are configured by default (env vars empty) → 400
        token, _ = await _register(async_client, _unique_email("stripe_co1"))
        resp = await async_client.post(
            "/api/v1/billing/create-checkout-session",
            json={"plan_slug": "pro"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400

    async def test_returns_checkout_url(self, async_client: AsyncClient) -> None:
        token, _ = await _register(async_client, _unique_email("stripe_co2"))

        mock_customer = MagicMock(id="cus_test123")
        mock_checkout = MagicMock(url="https://checkout.stripe.com/pay/test_session")
        mock_stripe_client = MagicMock()
        mock_stripe_client.customers.create.return_value = mock_customer
        mock_stripe_client.checkout.sessions.create.return_value = mock_checkout

        mock_settings = MagicMock()
        mock_settings.stripe_price_map = {"pro": "price_test_pro"}
        mock_settings.STRIPE_SECRET_KEY = ""
        mock_settings.BILLING_SUCCESS_URL = "http://localhost:8000/success"
        mock_settings.BILLING_CANCEL_URL = "http://localhost:8000/cancel"
        mock_settings.ENVIRONMENT = "development"

        with (
            patch("app.routers.billing._settings", mock_settings),
            patch("app.routers.billing._stripe.StripeClient", return_value=mock_stripe_client),
            patch("app.services.billing_service._stripe_client", return_value=mock_stripe_client),
        ):
            resp = await async_client.post(
                "/api/v1/billing/create-checkout-session",
                json={"plan_slug": "pro"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200
        assert resp.json()["url"] == "https://checkout.stripe.com/pay/test_session"


# ── Mock upgrade production gate ──────────────────────────────────────────────


@pytest.mark.integration
class TestMockUpgradeProductionGate:
    async def test_mock_upgrade_blocked_in_production(self, async_client: AsyncClient) -> None:
        token, _ = await _register(async_client, _unique_email("stripe_mu1"))
        with patch("app.routers.billing._settings.ENVIRONMENT", "production"):
            resp = await async_client.post(
                "/api/v1/billing/mock-upgrade",
                json={"plan_slug": "pro"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert resp.status_code == 403

    async def test_mock_upgrade_allowed_in_development(self, async_client: AsyncClient) -> None:
        token, _ = await _register(async_client, _unique_email("stripe_mu2"))
        resp = await async_client.post(
            "/api/v1/billing/mock-upgrade",
            json={"plan_slug": "pro"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["plan_slug"] == "pro"


# ── Webhook ───────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestWebhook:
    async def test_invalid_signature_rejected(self, async_client: AsyncClient) -> None:
        # When STRIPE_WEBHOOK_SECRET is set, bad sig → 400
        with patch("app.routers.billing._settings.STRIPE_WEBHOOK_SECRET", "whsec_test"):
            import stripe

            with patch(
                "stripe.Webhook.construct_event",
                side_effect=stripe.SignatureVerificationError("bad", "sig"),
            ):
                resp = await async_client.post(
                    "/api/v1/billing/webhook",
                    content=b'{"type":"test"}',
                    headers={"stripe-signature": "bad_sig"},
                )
        assert resp.status_code == 400

    async def test_checkout_completed_updates_subscription(self, async_client: AsyncClient) -> None:
        # Register a user
        resp = await async_client.post(
            "/api/v1/auth/register",
            json={
                "email": _unique_email("webhook_co1"),
                "password": "testpass123",
                "invite_code": TEST_INVITE_CODE,
            },
        )
        user_id = resp.json()["user"]["id"]
        token = resp.json()["access_token"]
        stripe_sub_id = f"sub_{uuid.uuid4().hex[:8]}"

        payload = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_abc",
                    "customer": "cus_test123",
                    "subscription": stripe_sub_id,
                    "metadata": {"user_id": user_id, "plan_slug": "pro"},
                }
            },
        }
        payload_bytes = json.dumps(payload).encode()

        # No webhook secret → raw JSON path (no signature verification)
        with patch("app.routers.billing._settings.STRIPE_WEBHOOK_SECRET", ""):
            resp = await async_client.post(
                "/api/v1/billing/webhook",
                content=payload_bytes,
                headers={"content-type": "application/json", "stripe-signature": ""},
            )
        assert resp.status_code == 200

        # Verify plan updated to pro
        me_resp = await async_client.get(
            "/api/v1/billing/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert me_resp.json()["plan_slug"] == "pro"

    async def test_subscription_deleted_cancels(self, async_client: AsyncClient) -> None:
        resp = await async_client.post(
            "/api/v1/auth/register",
            json={
                "email": _unique_email("webhook_del1"),
                "password": "testpass123",
                "invite_code": TEST_INVITE_CODE,
            },
        )
        user_id = resp.json()["user"]["id"]
        token = resp.json()["access_token"]
        stripe_sub_id = f"sub_{uuid.uuid4().hex[:8]}"

        # First subscribe via checkout webhook
        checkout_payload = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "customer": "cus_del123",
                    "subscription": stripe_sub_id,
                    "metadata": {"user_id": user_id, "plan_slug": "starter"},
                }
            },
        }
        with patch("app.routers.billing._settings.STRIPE_WEBHOOK_SECRET", ""):
            await async_client.post(
                "/api/v1/billing/webhook",
                content=json.dumps(checkout_payload).encode(),
            )

        # Now send deletion event
        delete_payload = {
            "type": "customer.subscription.deleted",
            "data": {"object": {"id": stripe_sub_id}},
        }
        with patch("app.routers.billing._settings.STRIPE_WEBHOOK_SECRET", ""):
            resp = await async_client.post(
                "/api/v1/billing/webhook",
                content=json.dumps(delete_payload).encode(),
            )
        assert resp.status_code == 200

        # Plan reverts to free (cancelled subscription not returned by get_user_subscription)
        me_resp = await async_client.get(
            "/api/v1/billing/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert me_resp.json()["plan_slug"] == "free"


# ── Customer portal ───────────────────────────────────────────────────────────


@pytest.mark.integration
class TestPortalSession:
    async def test_portal_requires_auth(self, async_client: AsyncClient) -> None:
        resp = await async_client.post("/api/v1/billing/create-customer-portal-session")
        assert resp.status_code == 401

    async def test_portal_requires_stripe_subscription(self, async_client: AsyncClient) -> None:
        token, _ = await _register(async_client, _unique_email("stripe_po1"))
        resp = await async_client.post(
            "/api/v1/billing/create-customer-portal-session",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400

    async def test_portal_returns_url(self, async_client: AsyncClient) -> None:
        # Set up a user with a Stripe subscription via webhook
        resp = await async_client.post(
            "/api/v1/auth/register",
            json={
                "email": _unique_email("stripe_po2"),
                "password": "testpass123",
                "invite_code": TEST_INVITE_CODE,
            },
        )
        user_id = resp.json()["user"]["id"]
        token = resp.json()["access_token"]
        stripe_sub_id = f"sub_{uuid.uuid4().hex[:8]}"

        checkout_payload = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "customer": "cus_portal123",
                    "subscription": stripe_sub_id,
                    "metadata": {"user_id": user_id, "plan_slug": "pro"},
                }
            },
        }
        with patch("app.routers.billing._settings.STRIPE_WEBHOOK_SECRET", ""):
            await async_client.post(
                "/api/v1/billing/webhook",
                content=json.dumps(checkout_payload).encode(),
            )

        mock_portal = MagicMock(url="https://billing.stripe.com/session/test")
        mock_client = MagicMock()
        mock_client.billing_portal.sessions.create.return_value = mock_portal

        with patch("app.routers.billing._stripe.StripeClient", return_value=mock_client):
            resp = await async_client.post(
                "/api/v1/billing/create-customer-portal-session",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 200
        assert resp.json()["url"] == "https://billing.stripe.com/session/test"

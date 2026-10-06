"""
Integration tests for /api/v1/billing/* endpoints.

Requires a live PostgreSQL database — skipped when DATABASE_URL is unset.
Plans must be seeded before these tests run (seed_plans fixture does this).
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import SubscriptionPlan
from app.services.billing_service import PLAN_DEFINITIONS
from tests.conftest import TEST_INVITE_CODE

pytestmark = pytest.mark.usefixtures("beta_gate")

# ── Fixtures ──────────────────────────────────────────────────────────────────


async def _register(client: AsyncClient, email: str) -> str:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "testpass123", "invite_code": TEST_INVITE_CODE},
    )
    assert resp.status_code == 201
    return resp.json()["access_token"]


@pytest.fixture(autouse=True)
async def seed_plans(db_session: AsyncSession) -> None:
    """Insert plan rows into the test transaction."""
    for defn in PLAN_DEFINITIONS:
        plan = SubscriptionPlan(**defn)
        db_session.add(plan)
    await db_session.flush()


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestBillingPlans:
    async def test_list_plans_returns_four_plans(self, async_client: AsyncClient) -> None:
        resp = await async_client.get("/api/v1/billing/plans")
        assert resp.status_code == 200
        plans = resp.json()
        slugs = {p["slug"] for p in plans}
        assert slugs == {"free", "starter", "pro", "elite"}

    async def test_plans_ordered_by_sort_order(self, async_client: AsyncClient) -> None:
        resp = await async_client.get("/api/v1/billing/plans")
        orders = [p["sort_order"] for p in resp.json()]
        assert orders == sorted(orders)


@pytest.mark.integration
class TestBillingMe:
    async def test_unauthenticated_returns_401(self, async_client: AsyncClient) -> None:
        resp = await async_client.get("/api/v1/billing/me")
        assert resp.status_code == 401

    async def test_new_user_gets_free_plan(self, async_client: AsyncClient) -> None:
        token = await _register(async_client, "billing1@example.com")
        resp = await async_client.get(
            "/api/v1/billing/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["plan_slug"] == "free"
        assert "beginner_courses" in data["features"]
        assert "leak_tracker" not in data["features"]


@pytest.mark.integration
class TestMockUpgrade:
    async def test_mock_upgrade_changes_plan(self, async_client: AsyncClient) -> None:
        token = await _register(async_client, "billing2@example.com")

        resp = await async_client.post(
            "/api/v1/billing/mock-upgrade",
            json={"plan_slug": "pro"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["plan_slug"] == "pro"
        assert "leak_tracker" in data["features"]
        assert "replay_drills" in data["features"]

    async def test_mock_upgrade_invalid_slug_rejected(self, async_client: AsyncClient) -> None:
        token = await _register(async_client, "billing3@example.com")
        resp = await async_client.post(
            "/api/v1/billing/mock-upgrade",
            json={"plan_slug": "diamond"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400

    async def test_mock_upgrade_unauthenticated_rejected(self, async_client: AsyncClient) -> None:
        resp = await async_client.post(
            "/api/v1/billing/mock-upgrade",
            json={"plan_slug": "pro"},
        )
        assert resp.status_code == 401


@pytest.mark.integration
class TestFeatureGate:
    async def test_leaks_endpoint_blocked_for_free_user(self, async_client: AsyncClient) -> None:
        token = await _register(async_client, "billing4@example.com")
        resp = await async_client.get(
            "/api/v1/me/leaks",
            headers={"Authorization": f"Bearer {token}"},
        )
        # 404 (no player) is acceptable — means the gate passed but no player linked
        # 403 means the feature gate rejected — also valid for free users
        # We expect 403 since no plan = free, and free doesn't have leak_tracker
        assert resp.status_code == 403

    async def test_leaks_endpoint_allowed_for_pro_user(self, async_client: AsyncClient) -> None:
        token = await _register(async_client, "billing5@example.com")
        # Upgrade first
        await async_client.post(
            "/api/v1/billing/mock-upgrade",
            json={"plan_slug": "pro"},
            headers={"Authorization": f"Bearer {token}"},
        )
        # Now leaks should get through (404 = no player, not 403)
        resp = await async_client.get(
            "/api/v1/me/leaks",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404  # no player linked, but gate passed

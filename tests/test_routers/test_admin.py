"""
Integration tests for /api/v1/admin/* endpoints.

Requires a live PostgreSQL database — skipped when DATABASE_URL is unset.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing import SubscriptionPlan
from app.models.user import User
from app.services.billing_service import PLAN_DEFINITIONS

# ── Helpers ───────────────────────────────────────────────────────────────────


async def _register(client: AsyncClient, email: str, role: str = "player") -> tuple[str, str]:
    """Register user and return (token, user_id)."""
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "testpass123"},
    )
    assert resp.status_code == 201
    data = resp.json()
    return data["access_token"], data["user"]["id"]


async def _make_admin(session: AsyncSession, user_id: str) -> None:
    """Promote a user to admin directly in the DB session."""

    user = await session.get(User, user_id)
    assert user is not None
    user.role = "admin"
    await session.flush()


@pytest.fixture(autouse=True)
async def seed_plans(db_session: AsyncSession) -> None:
    for defn in PLAN_DEFINITIONS:
        plan = SubscriptionPlan(**defn)
        db_session.add(plan)
    await db_session.flush()


# ── Access control ────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestAdminAccessControl:
    async def test_unauthenticated_blocked(self, async_client: AsyncClient) -> None:
        resp = await async_client.get("/api/v1/admin/overview")
        assert resp.status_code == 401

    async def test_player_role_blocked(self, async_client: AsyncClient) -> None:
        token, _ = await _register(async_client, "player1@example.com")
        resp = await async_client.get(
            "/api/v1/admin/overview",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    async def test_admin_role_allowed(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token, uid = await _register(async_client, "admin1@example.com")
        await _make_admin(db_session, uid)

        resp = await async_client.get(
            "/api/v1/admin/overview",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200


# ── Overview ──────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestAdminOverview:
    async def test_overview_returns_expected_fields(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token, uid = await _register(async_client, "admin2@example.com")
        await _make_admin(db_session, uid)

        resp = await async_client.get(
            "/api/v1/admin/overview",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "total_users" in data
        assert "active_users" in data
        assert "paying_users" in data
        assert "total_hands" in data
        assert "plan_distribution" in data
        assert data["total_users"] >= 1


# ── Users ─────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestAdminUsers:
    async def test_list_users(self, async_client: AsyncClient, db_session: AsyncSession) -> None:
        token, uid = await _register(async_client, "admin3@example.com")
        await _make_admin(db_session, uid)

        resp = await async_client.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        users = resp.json()
        assert isinstance(users, list)
        assert len(users) >= 1
        assert all("email" in u and "plan_slug" in u and "role" in u for u in users)

    async def test_set_plan_changes_plan(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token, uid = await _register(async_client, "admin4@example.com")
        await _make_admin(db_session, uid)

        target_token, target_uid = await _register(async_client, "target1@example.com")

        resp = await async_client.post(
            f"/api/v1/admin/users/{target_uid}/set-plan",
            json={"plan_slug": "pro"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["plan_slug"] == "pro"

    async def test_set_role_promotes_user(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token, uid = await _register(async_client, "admin5@example.com")
        await _make_admin(db_session, uid)

        target_token, target_uid = await _register(async_client, "target2@example.com")

        # Verify target cannot access admin initially
        pre = await async_client.get(
            "/api/v1/admin/overview",
            headers={"Authorization": f"Bearer {target_token}"},
        )
        assert pre.status_code == 403

        # Promote target to admin
        resp = await async_client.post(
            f"/api/v1/admin/users/{target_uid}/set-role",
            json={"role": "admin"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"

    async def test_set_invalid_role_rejected(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token, uid = await _register(async_client, "admin6@example.com")
        await _make_admin(db_session, uid)

        _, target_uid = await _register(async_client, "target3@example.com")
        resp = await async_client.post(
            f"/api/v1/admin/users/{target_uid}/set-role",
            json={"role": "superuser"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400


# ── Courses ───────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestAdminCourses:
    async def test_create_and_list_course(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token, uid = await _register(async_client, "admin7@example.com")
        await _make_admin(db_session, uid)

        resp = await async_client.post(
            "/api/v1/admin/courses",
            json={
                "slug": "test-admin-course",
                "title": "Admin Test Course",
                "description": "Created by admin",
                "level": "beginner",
                "estimated_minutes": 45,
                "is_published": True,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201
        course = resp.json()
        assert course["slug"] == "test-admin-course"
        assert course["title"] == "Admin Test Course"

        list_resp = await async_client.get(
            "/api/v1/admin/courses",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert list_resp.status_code == 200
        slugs = [c["slug"] for c in list_resp.json()]
        assert "test-admin-course" in slugs

    async def test_update_course(self, async_client: AsyncClient, db_session: AsyncSession) -> None:
        token, uid = await _register(async_client, "admin8@example.com")
        await _make_admin(db_session, uid)

        create = await async_client.post(
            "/api/v1/admin/courses",
            json={
                "slug": "update-me",
                "title": "Old Title",
                "level": "beginner",
                "estimated_minutes": 30,
                "is_published": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        course_id = create.json()["id"]

        update = await async_client.put(
            f"/api/v1/admin/courses/{course_id}",
            json={"title": "New Title", "is_published": True},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert update.status_code == 200
        assert update.json()["title"] == "New Title"
        assert update.json()["is_published"] is True

    async def test_delete_course(self, async_client: AsyncClient, db_session: AsyncSession) -> None:
        token, uid = await _register(async_client, "admin9@example.com")
        await _make_admin(db_session, uid)

        create = await async_client.post(
            "/api/v1/admin/courses",
            json={
                "slug": "delete-me",
                "title": "Delete Me",
                "level": "beginner",
                "estimated_minutes": 10,
                "is_published": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        course_id = create.json()["id"]

        delete = await async_client.delete(
            f"/api/v1/admin/courses/{course_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert delete.status_code == 204

    async def test_publish_course(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token, uid = await _register(async_client, "admin10@example.com")
        await _make_admin(db_session, uid)

        create = await async_client.post(
            "/api/v1/admin/courses",
            json={
                "slug": "publish-me",
                "title": "Publish Me",
                "level": "beginner",
                "estimated_minutes": 20,
                "is_published": False,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        course_id = create.json()["id"]

        pub = await async_client.post(
            f"/api/v1/admin/courses/{course_id}/publish?publish=true",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert pub.status_code == 200
        assert pub.json()["is_published"] is True

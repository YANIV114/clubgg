"""
Integration tests for course and progress endpoints.

Requires a live PostgreSQL database — skipped when DATABASE_URL is unset.
Each test runs in a rolled-back transaction (see conftest.py).

Tests seed their own course/module/lesson data directly into the DB so they
do not depend on the seed script or external state.
"""


import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course, Lesson, Module
from tests.conftest import TEST_INVITE_CODE

pytestmark = pytest.mark.usefixtures("beta_gate")

# ── Helpers ───────────────────────────────────────────────────────────────────


async def _seed_course(session: AsyncSession) -> tuple[Course, Module, Lesson]:
    """Insert a minimal published course with one module and one lesson."""
    course = Course(
        slug="test-course",
        title="Test Course",
        description="A test course",
        level="beginner",
        estimated_minutes=30,
        is_published=True,
    )
    session.add(course)
    await session.flush()

    module = Module(
        course_id=course.id,
        title="Test Module",
        sort_order=0,
    )
    session.add(module)
    await session.flush()

    lesson = Lesson(
        module_id=module.id,
        slug="test-lesson",
        title="Test Lesson",
        content="Lesson content here.",
        video_url=None,
        sort_order=0,
    )
    session.add(lesson)
    await session.flush()

    return course, module, lesson


async def _register_and_token(client: AsyncClient, email: str) -> str:
    """Register a user and return the access token."""
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "testpass123", "invite_code": TEST_INVITE_CODE},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestEnrollInCourse:
    async def test_enroll_in_course(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _seed_course(db_session)
        token = await _register_and_token(async_client, "enroll@example.com")

        resp = await async_client.post(
            "/api/v1/courses/test-course/enroll",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["slug"] == "test-course"
        assert data["enrolled"] is True


@pytest.mark.integration
class TestCompleteLesson:
    async def test_complete_lesson(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        _course, _module, lesson = await _seed_course(db_session)
        token = await _register_and_token(async_client, "complete@example.com")

        # Enroll first
        enroll_resp = await async_client.post(
            "/api/v1/courses/test-course/enroll",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert enroll_resp.status_code == 200, enroll_resp.text

        # Complete the lesson
        resp = await async_client.post(
            f"/api/v1/lessons/{lesson.id}/complete",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["is_completed"] is True
        assert data["slug"] == "test-lesson"


@pytest.mark.integration
class TestMeProgressOwnData:
    async def test_me_progress_own_data(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _seed_course(db_session)

        token_a = await _register_and_token(async_client, "user_a@example.com")
        token_b = await _register_and_token(async_client, "user_b@example.com")

        # Only user_a enrolls
        enroll_resp = await async_client.post(
            "/api/v1/courses/test-course/enroll",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert enroll_resp.status_code == 200

        # user_a sees their progress
        resp_a = await async_client.get(
            "/api/v1/me/progress",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp_a.status_code == 200
        data_a = resp_a.json()
        assert len(data_a) == 1
        assert data_a[0]["course_slug"] == "test-course"

        # user_b sees empty progress (not enrolled)
        resp_b = await async_client.get(
            "/api/v1/me/progress",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert resp_b.status_code == 200
        data_b = resp_b.json()
        assert data_b == []


@pytest.mark.integration
class TestMeProgressRequiresAuth:
    async def test_me_progress_requires_auth(self, async_client: AsyncClient) -> None:
        resp = await async_client.get("/api/v1/me/progress")
        assert resp.status_code == 401

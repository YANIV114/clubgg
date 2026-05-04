"""Integration tests for /api/v1/me/onboarding."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


def _unique_email(prefix: str = "ob") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}@example.com"


async def _register(client: AsyncClient, email: str) -> tuple[str, dict]:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "testpass123"},
    )
    assert resp.status_code == 201
    data = resp.json()
    return data["access_token"], data["user"]


@pytest.mark.integration
class TestOnboardingState:
    async def test_new_user_has_onboarding_complete_false(self, async_client: AsyncClient) -> None:
        _, user = await _register(async_client, _unique_email())
        assert user["onboarding_complete"] is False

    async def test_get_onboarding_requires_auth(self, async_client: AsyncClient) -> None:
        resp = await async_client.get("/api/v1/me/onboarding")
        assert resp.status_code == 401

    async def test_get_onboarding_returns_incomplete_for_new_user(
        self, async_client: AsyncClient
    ) -> None:
        token, _ = await _register(async_client, _unique_email())
        resp = await async_client.get(
            "/api/v1/me/onboarding",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["onboarding_complete"] is False
        assert data["skill_level"] is None
        assert data["goal"] is None


@pytest.mark.integration
class TestCompleteOnboarding:
    async def test_post_onboarding_requires_auth(self, async_client: AsyncClient) -> None:
        resp = await async_client.post(
            "/api/v1/me/onboarding",
            json={"skill_level": "beginner", "goal": "learn_fundamentals"},
        )
        assert resp.status_code == 401

    async def test_post_onboarding_saves_choices(self, async_client: AsyncClient) -> None:
        token, _ = await _register(async_client, _unique_email())
        resp = await async_client.post(
            "/api/v1/me/onboarding",
            json={"skill_level": "intermediate", "goal": "improve_tournament"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["onboarding_complete"] is True
        assert data["skill_level"] == "intermediate"
        assert data["goal"] == "improve_tournament"

    async def test_post_onboarding_persists_via_get(self, async_client: AsyncClient) -> None:
        token, _ = await _register(async_client, _unique_email())
        await async_client.post(
            "/api/v1/me/onboarding",
            json={"skill_level": "advanced", "goal": "analyze_hands"},
            headers={"Authorization": f"Bearer {token}"},
        )
        resp = await async_client.get(
            "/api/v1/me/onboarding",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["onboarding_complete"] is True
        assert data["skill_level"] == "advanced"
        assert data["goal"] == "analyze_hands"

    async def test_invalid_skill_level_rejected(self, async_client: AsyncClient) -> None:
        token, _ = await _register(async_client, _unique_email())
        resp = await async_client.post(
            "/api/v1/me/onboarding",
            json={"skill_level": "expert", "goal": "learn_fundamentals"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    async def test_invalid_goal_rejected(self, async_client: AsyncClient) -> None:
        token, _ = await _register(async_client, _unique_email())
        resp = await async_client.post(
            "/api/v1/me/onboarding",
            json={"skill_level": "beginner", "goal": "win_money"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    async def test_onboarding_can_be_updated(self, async_client: AsyncClient) -> None:
        token, _ = await _register(async_client, _unique_email())
        await async_client.post(
            "/api/v1/me/onboarding",
            json={"skill_level": "beginner", "goal": "learn_fundamentals"},
            headers={"Authorization": f"Bearer {token}"},
        )
        resp = await async_client.post(
            "/api/v1/me/onboarding",
            json={"skill_level": "advanced", "goal": "analyze_hands"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["skill_level"] == "advanced"

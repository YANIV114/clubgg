"""
Integration tests for /api/v1/auth endpoints.

Requires a live PostgreSQL database — skipped when DATABASE_URL is unset.
Each test runs in a rolled-back transaction (see conftest.py).
"""

import pytest
from httpx import AsyncClient


@pytest.mark.integration
class TestAuthRegister:
    async def test_register_returns_token_and_user(self, async_client: AsyncClient) -> None:
        resp = await async_client.post(
            "/api/v1/auth/register",
            json={"email": "alice@example.com", "password": "password123"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["email"] == "alice@example.com"
        assert data["user"]["role"] == "player"
        assert data["user"]["is_active"] is True

    async def test_duplicate_email_rejected(self, async_client: AsyncClient) -> None:
        payload = {"email": "bob@example.com", "password": "password123"}
        r1 = await async_client.post("/api/v1/auth/register", json=payload)
        assert r1.status_code == 201
        r2 = await async_client.post("/api/v1/auth/register", json=payload)
        assert r2.status_code == 409


@pytest.mark.integration
class TestAuthLogin:
    async def test_login_valid_user(self, async_client: AsyncClient) -> None:
        await async_client.post(
            "/api/v1/auth/register",
            json={"email": "carol@example.com", "password": "securepass"},
        )
        resp = await async_client.post(
            "/api/v1/auth/login",
            json={"email": "carol@example.com", "password": "securepass"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["user"]["email"] == "carol@example.com"

    async def test_login_invalid_password_rejected(self, async_client: AsyncClient) -> None:
        await async_client.post(
            "/api/v1/auth/register",
            json={"email": "dave@example.com", "password": "correctpass"},
        )
        resp = await async_client.post(
            "/api/v1/auth/login",
            json={"email": "dave@example.com", "password": "wrongpass"},
        )
        assert resp.status_code == 401


@pytest.mark.integration
class TestAuthMe:
    async def test_me_requires_token(self, async_client: AsyncClient) -> None:
        resp = await async_client.get("/api/v1/auth/me")
        assert resp.status_code == 401

    async def test_me_returns_current_user_with_valid_token(
        self, async_client: AsyncClient
    ) -> None:
        reg = await async_client.post(
            "/api/v1/auth/register",
            json={"email": "eve@example.com", "password": "mypassword"},
        )
        token = reg.json()["access_token"]
        resp = await async_client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200
        assert resp.json()["email"] == "eve@example.com"

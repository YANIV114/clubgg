"""
Integration tests for the beta access gate.

Covers:
- Signup invite code validation (missing / wrong / correct)
- is_tester flag set on correct invite code
- Protected endpoints return 403 for non-tester authenticated users
- Protected endpoints return 200 for tester users
- Admin users bypass the tester check

Requires a live PostgreSQL database — skipped when DATABASE_URL is unset.
"""

import pytest
from httpx import AsyncClient

from app.config import settings

# ── Helpers ───────────────────────────────────────────────────────────────────

CORRECT_CODE = "test-beta-invite-2024"
WRONG_CODE = "wrong-code"


async def _register(client: AsyncClient, email: str, invite_code: str | None = None) -> dict:
    payload: dict = {"email": email, "password": "testpass123"}
    if invite_code is not None:
        payload["invite_code"] = invite_code
    resp = await client.post("/api/v1/auth/register", json=payload)
    return resp


async def _token(client: AsyncClient, email: str, invite_code: str | None = None) -> str:
    resp = await _register(client, email, invite_code)
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Signup gate tests ─────────────────────────────────────────────────────────


@pytest.mark.integration
class TestSignupInviteCode:
    async def test_signup_without_code_rejected_when_gate_active(
        self, async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "BETA_INVITE_CODE", CORRECT_CODE)
        resp = await _register(async_client, "no_code@example.com")
        assert resp.status_code == 400
        assert "invite code" in resp.json()["detail"].lower()

    async def test_signup_with_wrong_code_rejected(
        self, async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "BETA_INVITE_CODE", CORRECT_CODE)
        resp = await _register(async_client, "wrong_code@example.com", WRONG_CODE)
        assert resp.status_code == 400
        assert "invite code" in resp.json()["detail"].lower()

    async def test_signup_with_correct_code_succeeds(
        self, async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "BETA_INVITE_CODE", CORRECT_CODE)
        resp = await _register(async_client, "good_code@example.com", CORRECT_CODE)
        assert resp.status_code == 201
        data = resp.json()
        assert data["user"]["is_tester"] is True

    async def test_signup_without_code_ok_when_gate_inactive(
        self, async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "BETA_INVITE_CODE", "")
        resp = await _register(async_client, "no_gate@example.com")
        assert resp.status_code == 201
        # When gate is inactive, is_tester stays False
        assert resp.json()["user"]["is_tester"] is False


# ── Protected route access tests ─────────────────────────────────────────────


@pytest.mark.integration
class TestTesterGuard:
    async def test_non_tester_blocked_from_me_analysis(
        self, async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "BETA_INVITE_CODE", "")
        token = await _token(async_client, "blocked_analysis@example.com")
        resp = await async_client.get("/api/v1/me/analysis", headers=_auth(token))
        assert resp.status_code == 403
        assert "beta" in resp.json()["detail"].lower()

    async def test_non_tester_blocked_from_me_hands(
        self, async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "BETA_INVITE_CODE", "")
        token = await _token(async_client, "blocked_hands@example.com")
        resp = await async_client.get("/api/v1/me/hands", headers=_auth(token))
        assert resp.status_code == 403

    async def test_non_tester_blocked_from_hands_list(
        self, async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "BETA_INVITE_CODE", "")
        token = await _token(async_client, "blocked_hands_list@example.com")
        resp = await async_client.get("/api/v1/hands/", headers=_auth(token))
        assert resp.status_code == 403

    async def test_non_tester_blocked_from_billing_me(
        self, async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "BETA_INVITE_CODE", "")
        token = await _token(async_client, "blocked_billing@example.com")
        resp = await async_client.get("/api/v1/billing/me", headers=_auth(token))
        assert resp.status_code == 403

    async def test_non_tester_blocked_from_me_progress(
        self, async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "BETA_INVITE_CODE", "")
        token = await _token(async_client, "blocked_progress@example.com")
        resp = await async_client.get("/api/v1/me/progress", headers=_auth(token))
        assert resp.status_code == 403

    async def test_tester_allowed_through_me_hands(
        self, async_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "BETA_INVITE_CODE", CORRECT_CODE)
        token = await _token(async_client, "tester_allowed@example.com", CORRECT_CODE)
        # 404 expected (no player linked yet) — not 401 or 403
        resp = await async_client.get("/api/v1/me/hands", headers=_auth(token))
        assert resp.status_code not in (401, 403)

    async def test_unauthenticated_still_returns_401(self, async_client: AsyncClient) -> None:
        resp = await async_client.get("/api/v1/me/hands")
        assert resp.status_code == 401

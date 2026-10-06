"""
Integration tests for /api/v1/me/* endpoints.

Requires a live PostgreSQL database — skipped when DATABASE_URL is unset.
Each test runs in a rolled-back transaction (see conftest.py).
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.player import Club, Player
from tests.conftest import TEST_INVITE_CODE

pytestmark = pytest.mark.usefixtures("beta_gate")

# ── Helpers ───────────────────────────────────────────────────────────────────


async def _register(client: AsyncClient, email: str) -> str:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "testpass123", "invite_code": TEST_INVITE_CODE},
    )
    assert resp.status_code == 201
    return resp.json()["access_token"]


async def _seed_player(session: AsyncSession, username: str = "testplayer") -> Player:
    club = Club(external_id=uuid.uuid4().int % 10**9, name="Test Club")
    session.add(club)
    await session.flush()

    player = Player(
        external_id=int(uuid.uuid4().int % 10**9),
        club_id=club.id,
        username=username,
        is_active=True,
        is_stub=False,
    )
    session.add(player)
    await session.flush()
    return player


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.integration
class TestLinkPlayer:
    async def test_link_player_works(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register(async_client, "link1@example.com")
        player = await _seed_player(db_session)

        resp = await async_client.post(
            "/api/v1/me/players/link",
            json={"player_id": str(player.id), "is_primary": True},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["player_id"] == str(player.id)
        assert data["is_primary"] is True
        assert data["player_username"] == player.username

    async def test_link_nonexistent_player_returns_404(self, async_client: AsyncClient) -> None:
        token = await _register(async_client, "link2@example.com")
        resp = await async_client.post(
            "/api/v1/me/players/link",
            json={"player_id": str(uuid.uuid4()), "is_primary": True},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404


@pytest.mark.integration
class TestMeAnalysis:
    async def test_me_analysis_no_player_returns_404(self, async_client: AsyncClient) -> None:
        token = await _register(async_client, "analysis1@example.com")
        resp = await async_client.get(
            "/api/v1/me/analysis",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404
        assert "No player linked" in resp.json()["detail"]

    async def test_me_analysis_returns_user_data(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register(async_client, "analysis2@example.com")
        player = await _seed_player(db_session, "alice")

        await async_client.post(
            "/api/v1/me/players/link",
            json={"player_id": str(player.id)},
            headers={"Authorization": f"Bearer {token}"},
        )

        resp = await async_client.get(
            "/api/v1/me/analysis",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["player_id"] == str(player.id)
        assert data["player_username"] == "alice"
        assert "summary" in data
        assert "stats" in data
        assert "leaks" in data

    async def test_me_requires_auth(self, async_client: AsyncClient) -> None:
        resp = await async_client.get("/api/v1/me/analysis")
        assert resp.status_code == 401


@pytest.mark.integration
class TestMeHands:
    async def test_me_hands_returns_only_user_data(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token_a = await _register(async_client, "hands_a@example.com")
        token_b = await _register(async_client, "hands_b@example.com")

        player_a = await _seed_player(db_session, "player_a")
        player_b = await _seed_player(db_session, "player_b")

        for tok, pl in [(token_a, player_a), (token_b, player_b)]:
            await async_client.post(
                "/api/v1/me/players/link",
                json={"player_id": str(pl.id)},
                headers={"Authorization": f"Bearer {tok}"},
            )

        resp_a = await async_client.get(
            "/api/v1/me/hands",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert resp_a.status_code == 200
        assert resp_a.json()["player_id"] == str(player_a.id)

        resp_b = await async_client.get(
            "/api/v1/me/hands",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert resp_b.status_code == 200
        assert resp_b.json()["player_id"] == str(player_b.id)

        # User A's player_id must not appear in User B's response
        assert resp_b.json()["player_id"] != str(player_a.id)

    async def test_me_hands_response_shape(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Response includes hero identity and all_players even when no hands exist."""
        token = await _register(async_client, "hands_shape@example.com")
        player = await _seed_player(db_session, "shapeplayer")
        await async_client.post(
            "/api/v1/me/players/link",
            json={"player_id": str(player.id)},
            headers={"Authorization": f"Bearer {token}"},
        )

        resp = await async_client.get(
            "/api/v1/me/hands",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["player_id"] == str(player.id)
        assert data["total"] == 0
        assert data["hands"] == []

    async def test_me_hands_no_player_returns_404(self, async_client: AsyncClient) -> None:
        token = await _register(async_client, "hands_nopl@example.com")
        resp = await async_client.get(
            "/api/v1/me/hands",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

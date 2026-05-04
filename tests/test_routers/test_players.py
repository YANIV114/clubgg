"""
Integration tests for GET /api/v1/players/{id}/stats.

These tests use the async_client fixture (real DB, transaction rollback)
and exercise the full stack: HTTP → router → hand_records_for_player()
→ compute_player_stats() → PlayerStatsOut JSON.

Requires DATABASE_URL to be set (marked integration).
"""
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.hand_parser import HandHistoryParser, _HAND_BLOCK_RE
from app.ingestion.normalizer import normalize_file_hand
from app.features.normalize_hand import normalize_hand_players
from app.models.player import Club, Player
from app.services.hand_service import upsert_hand
from app.services.player_service import upsert_club


# ── Shared fixtures ───────────────────────────────────────────────────────────


async def _ingest_fixture_hands(
    db_session: AsyncSession, club: Club, hand_text: str
) -> None:
    """Parse and ingest all hands in hand_text through the service layer."""
    parser = HandHistoryParser()
    blocks = [b.strip() for b in _HAND_BLOCK_RE.split(hand_text) if b.strip()]
    for block in blocks:
        raw = parser.parse(block)
        normalize_hand_players(
            raw["players"],  # type: ignore[arg-type]
            Decimal(str(raw["stakes_bb"])),
            raw.get("button_seat"),
        )
        payload = normalize_file_hand(raw, str(club.external_id))
        await upsert_hand(db_session, payload)
    await db_session.flush()


import pytest_asyncio


@pytest_asyncio.fixture
async def club(db_session: AsyncSession) -> Club:
    await upsert_club(db_session, external_id=42, name="TestClub", currency="USD")
    await db_session.flush()
    result = await db_session.execute(select(Club).where(Club.external_id == 42))
    return result.scalar_one()


@pytest_asyncio.fixture
async def ingested(
    db_session: AsyncSession, club: Club, sample_hand_history_text: str
) -> None:
    await _ingest_fixture_hands(db_session, club, sample_hand_history_text)


@pytest_asyncio.fixture
async def alice(db_session: AsyncSession, ingested: None) -> Player:
    result = await db_session.execute(select(Player).where(Player.username == "Alice"))
    return result.scalar_one()


@pytest_asyncio.fixture
async def bob(db_session: AsyncSession, ingested: None) -> Player:
    result = await db_session.execute(select(Player).where(Player.username == "Bob"))
    return result.scalar_one()


# ── Happy path ────────────────────────────────────────────────────────────────


@pytest.mark.integration
async def test_stats_200_for_player_with_hands(
    async_client: AsyncClient, alice: Player
) -> None:
    """GET /players/{id}/stats returns 200 with valid JSON for a known player."""
    resp = await async_client.get(f"/api/v1/players/{alice.id}/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["player_id"] == str(alice.id)
    assert data["hand_count"] == 4  # Alice in hands 1, 3, 4, 5


@pytest.mark.integration
async def test_stats_has_required_fields(
    async_client: AsyncClient, alice: Player
) -> None:
    resp = await async_client.get(f"/api/v1/players/{alice.id}/stats")
    data = resp.json()
    for field in ("vpip", "pfr", "three_bet_pct", "fold_to_3bet", "wtsd", "wsd"):
        assert field in data, f"Missing field: {field}"
        assert "value" in data[field]
        assert "label" in data[field]
        assert "n" in data[field]
    assert "positional" in data


@pytest.mark.integration
async def test_stats_vpip_100_for_alice(
    async_client: AsyncClient, alice: Player
) -> None:
    """Alice voluntarily puts money in preflop in all 4 hands → VPIP = 1.0."""
    resp = await async_client.get(f"/api/v1/players/{alice.id}/stats")
    data = resp.json()
    vpip = data["vpip"]
    assert vpip["n"] == 4
    assert Decimal(vpip["value"]) == Decimal("1.0")


@pytest.mark.integration
async def test_stats_pfr_for_alice(
    async_client: AsyncClient, alice: Player
) -> None:
    """Alice raises preflop in hands 1, 3, 4 but calls in hand 5 → PFR = 0.75."""
    resp = await async_client.get(f"/api/v1/players/{alice.id}/stats")
    data = resp.json()
    pfr = data["pfr"]
    assert pfr["n"] == 4
    assert Decimal(pfr["value"]) == Decimal("0.75")


@pytest.mark.integration
async def test_stats_wtsd_for_alice(
    async_client: AsyncClient, alice: Player
) -> None:
    """Alice saw flop in all 4 hands. Reached showdown in hands 3, 4, 5 → wtsd = 0.75."""
    resp = await async_client.get(f"/api/v1/players/{alice.id}/stats")
    data = resp.json()
    wtsd = data["wtsd"]
    # n is saw_flop count = 4
    assert wtsd["n"] == 4
    assert Decimal(wtsd["value"]) == Decimal("0.75")


@pytest.mark.integration
async def test_stats_wsd_for_alice(
    async_client: AsyncClient, alice: Player
) -> None:
    """Alice reached SD in hands 3,4,5 and won all → wsd = 1.0."""
    resp = await async_client.get(f"/api/v1/players/{alice.id}/stats")
    data = resp.json()
    wsd = data["wsd"]
    assert wsd["n"] == 3
    assert Decimal(wsd["value"]) == Decimal("1.0")


@pytest.mark.integration
async def test_stats_label_is_inferred(
    async_client: AsyncClient, alice: Player
) -> None:
    """All rate metrics carry label='inferred' (computed from a sample)."""
    resp = await async_client.get(f"/api/v1/players/{alice.id}/stats")
    data = resp.json()
    for field in ("vpip", "pfr", "wtsd", "wsd"):
        assert data[field]["label"] == "inferred", f"{field} label mismatch"


@pytest.mark.integration
async def test_stats_positional_breakdown_present(
    async_client: AsyncClient, alice: Player
) -> None:
    """positional dict has at least one position key with hand_count > 0."""
    resp = await async_client.get(f"/api/v1/players/{alice.id}/stats")
    data = resp.json()
    positional = data["positional"]
    assert len(positional) > 0
    for pos_data in positional.values():
        assert pos_data["n_hands"] > 0
        assert "vpip" in pos_data


# ── 404 handling ──────────────────────────────────────────────────────────────


@pytest.mark.integration
async def test_stats_404_for_unknown_player(
    async_client: AsyncClient, ingested: None
) -> None:
    """GET /players/{id}/stats returns 404 for a UUID that doesn't exist."""
    resp = await async_client.get(
        "/api/v1/players/00000000-0000-0000-0000-000000000000/stats"
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Player not found"


# ── Empty hands ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def player_no_hands(db_session: AsyncSession, club: Club) -> Player:
    """A real player record with no associated hands."""
    from app.models.player import Player as PlayerModel

    p = PlayerModel(
        external_id=999999,
        club_id=club.id,
        username="NoHandsPlayer",
        display_name="NoHandsPlayer",
        is_active=True,
        is_stub=False,
    )
    db_session.add(p)
    await db_session.flush()
    return p


@pytest.mark.integration
async def test_stats_empty_player_returns_zero_hands(
    async_client: AsyncClient, player_no_hands: Player
) -> None:
    """A player with no ingested hands returns hand_count=0 and null rates."""
    resp = await async_client.get(f"/api/v1/players/{player_no_hands.id}/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["hand_count"] == 0
    assert data["vpip"]["value"] is None
    assert data["vpip"]["n"] == 0


# ── from_date / to_date filtering ─────────────────────────────────────────────


@pytest.mark.integration
async def test_stats_limit_param(
    async_client: AsyncClient, alice: Player
) -> None:
    """?limit=1 returns stats computed over only 1 hand."""
    resp = await async_client.get(
        f"/api/v1/players/{alice.id}/stats?limit=1"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["hand_count"] == 1


@pytest.mark.integration
async def test_stats_from_date_excludes_older_hands(
    async_client: AsyncClient, alice: Player
) -> None:
    """
    All 5 fixture hands are timestamped 2024-01-15.
    A from_date after that date should return hand_count=0.
    """
    resp = await async_client.get(
        f"/api/v1/players/{alice.id}/stats?from_date=2025-01-01T00:00:00"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["hand_count"] == 0
    assert data["vpip"]["value"] is None


@pytest.mark.integration
async def test_stats_to_date_excludes_newer_hands(
    async_client: AsyncClient, alice: Player
) -> None:
    """
    A to_date before the fixture hands should return hand_count=0.
    """
    resp = await async_client.get(
        f"/api/v1/players/{alice.id}/stats?to_date=2023-01-01T00:00:00"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["hand_count"] == 0


# ── Bob (only in hand 2) ──────────────────────────────────────────────────────


@pytest.mark.integration
async def test_stats_bob_all_hands(
    async_client: AsyncClient, bob: Player
) -> None:
    """Bob appears in all 5 fixture hands."""
    resp = await async_client.get(f"/api/v1/players/{bob.id}/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["hand_count"] == 5

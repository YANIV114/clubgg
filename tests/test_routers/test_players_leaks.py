"""
Integration tests for GET /api/v1/players/{id}/leaks.

Uses the real DB (transaction-rolled-back per test) via async_client fixture.
The 5 fixture hands give Alice only 4 hands — most leaks will be
insufficient_data.  Tests focus on:
  - Response structure (correct fields, types, ordering)
  - 404 handling
  - Empty player (no hands) returns empty leaks
  - Confidence notes reflect small sample
  - Fixture-based player surfaces at least structure-correct response
"""
from decimal import Decimal

import pytest
import pytest_asyncio
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
    parser = HandHistoryParser()
    blocks = [b.strip() for b in _HAND_BLOCK_RE.split(sample_hand_history_text) if b.strip()]
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


@pytest_asyncio.fixture
async def alice(db_session: AsyncSession, ingested: None) -> Player:
    result = await db_session.execute(select(Player).where(Player.username == "Alice"))
    return result.scalar_one()


@pytest_asyncio.fixture
async def player_no_hands(db_session: AsyncSession, club: Club) -> Player:
    p = Player(
        external_id=99999,
        club_id=club.id,
        username="EmptyPlayer",
        display_name="EmptyPlayer",
        is_active=True,
        is_stub=False,
    )
    db_session.add(p)
    await db_session.flush()
    return p


# ── 404 handling ──────────────────────────────────────────────────────────────


@pytest.mark.integration
async def test_leaks_404_unknown_player(
    async_client: AsyncClient, ingested: None
) -> None:
    resp = await async_client.get(
        "/api/v1/players/00000000-0000-0000-0000-000000000000/leaks"
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Player not found"


# ── Empty player ──────────────────────────────────────────────────────────────


@pytest.mark.integration
async def test_leaks_empty_player_returns_200(
    async_client: AsyncClient, player_no_hands: Player
) -> None:
    resp = await async_client.get(f"/api/v1/players/{player_no_hands.id}/leaks")
    assert resp.status_code == 200


@pytest.mark.integration
async def test_leaks_empty_player_zero_hands(
    async_client: AsyncClient, player_no_hands: Player
) -> None:
    data = (await async_client.get(f"/api/v1/players/{player_no_hands.id}/leaks")).json()
    assert data["hand_count"] == 0
    assert data["leaks"] == []


@pytest.mark.integration
async def test_leaks_empty_player_analysis_note_mentions_no_hands(
    async_client: AsyncClient, player_no_hands: Player
) -> None:
    data = (await async_client.get(f"/api/v1/players/{player_no_hands.id}/leaks")).json()
    assert "No hands" in data["analysis_note"] or "no hands" in data["analysis_note"].lower()


# ── Response structure ────────────────────────────────────────────────────────


@pytest.mark.integration
async def test_leaks_response_has_required_top_level_fields(
    async_client: AsyncClient, alice: Player
) -> None:
    data = (await async_client.get(f"/api/v1/players/{alice.id}/leaks")).json()
    for field in ("player_id", "hand_count", "leaks", "analysis_note"):
        assert field in data, f"Missing top-level field: {field}"


@pytest.mark.integration
async def test_leaks_player_id_matches(
    async_client: AsyncClient, alice: Player
) -> None:
    data = (await async_client.get(f"/api/v1/players/{alice.id}/leaks")).json()
    assert data["player_id"] == str(alice.id)


@pytest.mark.integration
async def test_leaks_hand_count_is_four_for_alice(
    async_client: AsyncClient, alice: Player
) -> None:
    data = (await async_client.get(f"/api/v1/players/{alice.id}/leaks")).json()
    assert data["hand_count"] == 4


@pytest.mark.integration
async def test_leaks_list_is_list(
    async_client: AsyncClient, alice: Player
) -> None:
    data = (await async_client.get(f"/api/v1/players/{alice.id}/leaks")).json()
    assert isinstance(data["leaks"], list)


@pytest.mark.integration
async def test_leaks_small_sample_produces_empty_list_or_low_confidence_only(
    async_client: AsyncClient, alice: Player
) -> None:
    """
    Alice has only 4 hands.  The leak engine should not emit high/medium
    confidence leaks because the minimum sample sizes are not met.
    If any leaks are emitted, they must have confidence='low'.
    """
    data = (await async_client.get(f"/api/v1/players/{alice.id}/leaks")).json()
    for leak in data["leaks"]:
        assert leak["confidence"] in ("low",), (
            f"Leak {leak['leak_id']} emitted with confidence={leak['confidence']} "
            f"on only 4 hands — should not happen"
        )


@pytest.mark.integration
async def test_leaks_each_leak_has_all_required_fields(
    async_client: AsyncClient, alice: Player
) -> None:
    data = (await async_client.get(f"/api/v1/players/{alice.id}/leaks")).json()
    required = {
        "leak_id", "category", "title", "explanation", "evidence",
        "confidence", "severity", "frequency", "priority",
        "sample_size", "limitations", "suggested_fix",
    }
    for leak in data["leaks"]:
        missing = required - leak.keys()
        assert not missing, f"Leak missing fields: {missing}"


@pytest.mark.integration
async def test_leaks_sorted_by_priority_descending(
    async_client: AsyncClient, alice: Player
) -> None:
    data = (await async_client.get(f"/api/v1/players/{alice.id}/leaks")).json()
    priorities = [l["priority"] for l in data["leaks"]]
    assert priorities == sorted(priorities, reverse=True)


@pytest.mark.integration
async def test_leaks_priority_in_valid_range(
    async_client: AsyncClient, alice: Player
) -> None:
    data = (await async_client.get(f"/api/v1/players/{alice.id}/leaks")).json()
    for leak in data["leaks"]:
        assert 1 <= leak["priority"] <= 10, f"priority={leak['priority']} out of range"


@pytest.mark.integration
async def test_leaks_analysis_note_present_and_non_empty(
    async_client: AsyncClient, alice: Player
) -> None:
    data = (await async_client.get(f"/api/v1/players/{alice.id}/leaks")).json()
    assert isinstance(data["analysis_note"], str)
    assert len(data["analysis_note"]) > 0


@pytest.mark.integration
async def test_leaks_analysis_note_mentions_hand_count(
    async_client: AsyncClient, alice: Player
) -> None:
    data = (await async_client.get(f"/api/v1/players/{alice.id}/leaks")).json()
    # Small sample note should contain the hand count
    assert "4" in data["analysis_note"]


# ── Date filtering ────────────────────────────────────────────────────────────


@pytest.mark.integration
async def test_leaks_from_date_filters_out_all_hands(
    async_client: AsyncClient, alice: Player
) -> None:
    """from_date after fixture hands → hand_count=0 → empty leaks."""
    resp = await async_client.get(
        f"/api/v1/players/{alice.id}/leaks?from_date=2025-01-01T00:00:00"
    )
    data = resp.json()
    assert resp.status_code == 200
    assert data["hand_count"] == 0
    assert data["leaks"] == []


@pytest.mark.integration
async def test_leaks_limit_param(
    async_client: AsyncClient, alice: Player
) -> None:
    """?limit=1 caps the hand window used for leak analysis."""
    resp = await async_client.get(f"/api/v1/players/{alice.id}/leaks?limit=1")
    data = resp.json()
    assert resp.status_code == 200
    assert data["hand_count"] == 1


# ── Per-hand leak report ──────────────────────────────────────────────────────


@pytest.mark.integration
async def test_leak_report_404_unknown_player(
    async_client: AsyncClient, ingested: None
) -> None:
    resp = await async_client.get(
        "/api/v1/players/00000000-0000-0000-0000-000000000000/leak-report"
    )
    assert resp.status_code == 404


@pytest.mark.integration
async def test_leak_report_shape(async_client: AsyncClient, alice: Player) -> None:
    resp = await async_client.get(f"/api/v1/players/{alice.id}/leak-report")
    assert resp.status_code == 200
    data = resp.json()
    assert data["player_id"] == str(alice.id)
    assert data["total_hands_analyzed"] == 4
    assert isinstance(data["leaks"], list)
    assert isinstance(data["summary"], str) and data["summary"]


@pytest.mark.integration
async def test_leak_report_empty_player(
    async_client: AsyncClient, player_no_hands: Player
) -> None:
    data = (await async_client.get(f"/api/v1/players/{player_no_hands.id}/leak-report")).json()
    assert data["total_hands_analyzed"] == 0
    assert data["leaks"] == []


# ── Results ───────────────────────────────────────────────────────────────────


@pytest.mark.integration
async def test_results_404_unknown_player(async_client: AsyncClient, ingested: None) -> None:
    resp = await async_client.get("/api/v1/players/00000000-0000-0000-0000-000000000000/results")
    assert resp.status_code == 404


@pytest.mark.integration
async def test_results_shape(async_client: AsyncClient, alice: Player) -> None:
    resp = await async_client.get(f"/api/v1/players/{alice.id}/results")
    assert resp.status_code == 200
    data = resp.json()
    # Every fixture hand is counted, with or without a reconciled result.
    assert data["hand_count"] + data["hands_without_result"] == 4
    assert len(data["cumulative_bb"]) == data["hand_count"]
    for key in ("value", "n", "margin", "significant", "label"):
        assert key in data["bb_per_100"]
    assert data["bb_per_100"]["label"] == "derived"


@pytest.mark.integration
async def test_results_empty_player(async_client: AsyncClient, player_no_hands: Player) -> None:
    data = (await async_client.get(f"/api/v1/players/{player_no_hands.id}/results")).json()
    assert data["hand_count"] == 0
    assert data["by_position"] == []
    assert data["cumulative_bb"] == []

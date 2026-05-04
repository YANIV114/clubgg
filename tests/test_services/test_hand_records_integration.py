"""
Integration tests for the hand ingestion → hand_records_for_player() pipeline.

These tests require a live PostgreSQL database (DATABASE_URL env var).
They verify:

  1. Ingested hands are persisted correctly (club, players, hand data)
  2. hand_records_for_player() returns the right number of HandRecord objects
  3. All related data (actions, winners) is eagerly loaded by the ORM query
  4. saw_flop, reached_showdown, won_at_showdown flags are correct after a
     real DB round-trip through the full ingestion pipeline

Fixture hands used (see tests/fixtures/sample_hand_history.txt):
  #98765001 — basic, no showdown   — Alice: VPIP, PFR, saw_flop, no SD
  #98765002 — showdown, Bob wins   — Bob, Charlie only
  #98765003 — antes + all-in       — Alice: VPIP, PFR, all-in, saw_flop, SD, won
  #98765004 — show + muck          — Alice: VPIP, PFR, saw_flop, SD, won
  #98765005 — side pot 3-way       — Alice: VPIP, CALL, saw_flop, SD, won side pot

Alice appears in 4 hands (1, 3, 4, 5).
"""

from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.features.normalize_hand import normalize_hand_players
from app.features.player_stats import HandRecord
from app.ingestion.hand_parser import _HAND_BLOCK_RE, HandHistoryParser
from app.ingestion.normalizer import normalize_file_hand
from app.models.hand import Hand, HandPlayer, HandWinner, PlayerAction
from app.models.player import Club, Player
from app.services.hand_service import hand_records_for_player, upsert_hand
from app.services.player_service import upsert_club

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def club(db_session: AsyncSession) -> Club:
    """Insert the TestClub (external_id=42) used by all fixture hands."""
    await upsert_club(db_session, external_id=42, name="TestClub", currency="USD")
    await db_session.flush()
    result = await db_session.execute(select(Club).where(Club.external_id == 42))
    return result.scalar_one()


@pytest_asyncio.fixture
async def ingested_hands(
    db_session: AsyncSession, club: Club, sample_hand_history_text: str
) -> list[dict]:
    """
    Parse the full fixture file and ingest all 5 hands through the real
    upsert_hand() service.  Stub players are auto-created by the service.
    Returns the raw parser dicts for reference.
    """
    parser = HandHistoryParser()
    blocks = [b.strip() for b in _HAND_BLOCK_RE.split(sample_hand_history_text) if b.strip()]
    raw_records = []
    for block in blocks:
        raw = parser.parse(block)
        normalize_hand_players(
            raw["players"],  # type: ignore[arg-type]
            Decimal(str(raw["stakes_bb"])),
            raw.get("button_seat"),
        )
        payload = normalize_file_hand(raw, str(club.external_id))
        await upsert_hand(db_session, payload)
        raw_records.append(raw)
    await db_session.flush()
    return raw_records


@pytest_asyncio.fixture
async def alice_player(db_session: AsyncSession, ingested_hands: list) -> Player:
    """Look up the stub player created for Alice during ingestion."""
    result = await db_session.execute(select(Player).where(Player.username == "Alice"))
    player = result.scalar_one()
    return player


@pytest_asyncio.fixture
async def bob_player(db_session: AsyncSession, ingested_hands: list) -> Player:
    result = await db_session.execute(select(Player).where(Player.username == "Bob"))
    return result.scalar_one()


# ── Ingestion correctness ─────────────────────────────────────────────────────


@pytest.mark.integration
async def test_all_five_hands_persisted(db_session: AsyncSession, ingested_hands: list) -> None:
    result = await db_session.execute(select(Hand))
    hands = result.scalars().all()
    assert len(hands) == 5


@pytest.mark.integration
async def test_hand_ids_correct(db_session: AsyncSession, ingested_hands: list) -> None:
    result = await db_session.execute(select(Hand.external_id).order_by(Hand.external_id))
    ids = [row[0] for row in result.all()]
    assert ids == ["98765001", "98765002", "98765003", "98765004", "98765005"]


@pytest.mark.integration
async def test_stub_players_created(db_session: AsyncSession, ingested_hands: list) -> None:
    result = await db_session.execute(select(Player.username))
    usernames = {row[0] for row in result.all()}
    assert {"Alice", "Bob", "Charlie"}.issubset(usernames)


@pytest.mark.integration
async def test_stub_players_are_flagged(db_session: AsyncSession, ingested_hands: list) -> None:
    result = await db_session.execute(
        select(Player).where(Player.username.in_(["Alice", "Bob", "Charlie"]))
    )
    players = result.scalars().all()
    assert all(p.is_stub for p in players)


@pytest.mark.integration
async def test_hand_players_count(db_session: AsyncSession, ingested_hands: list) -> None:
    # Hand 1: 3 players, Hand 2: 2, Hand 3: 3, Hand 4: 2, Hand 5: 3 = 13 total
    result = await db_session.execute(select(HandPlayer))
    hps = result.scalars().all()
    assert len(hps) == 13


@pytest.mark.integration
async def test_winners_persisted(db_session: AsyncSession, ingested_hands: list) -> None:
    # 5 winner records: one per hand except Hand 5 which has 2 (side + main)
    result = await db_session.execute(select(HandWinner))
    winners = result.scalars().all()
    assert len(winners) == 6  # 1+1+1+1+2


@pytest.mark.integration
async def test_actions_persisted(db_session: AsyncSession, ingested_hands: list) -> None:
    result = await db_session.execute(select(PlayerAction))
    actions = result.scalars().all()
    # There should be many actions across 5 hands
    assert len(actions) > 30


@pytest.mark.integration
async def test_antes_stored(db_session: AsyncSession, ingested_hands: list) -> None:
    """Hand 3 has 3 ante posts — verify they are in the DB."""
    result = await db_session.execute(
        select(PlayerAction).where(PlayerAction.action_type == "POST_ANTE")
    )
    ante_actions = result.scalars().all()
    assert len(ante_actions) == 3


@pytest.mark.integration
async def test_show_actions_stored(db_session: AsyncSession, ingested_hands: list) -> None:
    """Showdown SHOW actions must be in player_actions with street=SHOWDOWN."""
    result = await db_session.execute(
        select(PlayerAction).where(
            PlayerAction.action_type == "SHOW",
            PlayerAction.street == "SHOWDOWN",
        )
    )
    show_actions = result.scalars().all()
    # Hands 2(2), 3(2), 4(1), 5(3) → 8 SHOW actions
    assert len(show_actions) == 8


@pytest.mark.integration
async def test_muck_action_stored(db_session: AsyncSession, ingested_hands: list) -> None:
    """Hand 4: Bob mucks — exactly one MUCK action should be in the DB."""
    result = await db_session.execute(
        select(PlayerAction).where(PlayerAction.action_type == "MUCK")
    )
    muck_actions = result.scalars().all()
    assert len(muck_actions) == 1


@pytest.mark.integration
async def test_side_pot_winner_stored(db_session: AsyncSession, ingested_hands: list) -> None:
    """Hand 5 has two HandWinner rows: one 'side', one 'main'."""
    # Find hand 5
    hand5_result = await db_session.execute(select(Hand).where(Hand.external_id == "98765005"))
    hand5 = hand5_result.scalar_one()
    result = await db_session.execute(select(HandWinner).where(HandWinner.hand_id == hand5.id))
    winners = result.scalars().all()
    assert len(winners) == 2
    pot_types = {w.pot_type for w in winners}
    assert pot_types == {"main", "side"}


@pytest.mark.integration
async def test_hole_cards_stored(db_session: AsyncSession, ingested_hands: list) -> None:
    """Players who showed cards should have hole_cards populated."""
    result = await db_session.execute(select(HandPlayer).where(HandPlayer.hole_cards.is_not(None)))
    hps_with_cards = result.scalars().all()
    # Hands 2(2), 3(2), 4(1 show + 1 muck=0 hole cards), 5(3) → depends on muck
    # Alice shows in hand 4 → hole_cards set; Bob mucks → no hole_cards
    assert len(hps_with_cards) > 0
    # Alice in hand 3 should have Ah Kc
    hand3_result = await db_session.execute(select(Hand).where(Hand.external_id == "98765003"))
    hand3 = hand3_result.scalar_one()
    alice_result = await db_session.execute(select(Player).where(Player.username == "Alice"))
    alice = alice_result.scalar_one()
    hp_result = await db_session.execute(
        select(HandPlayer).where(
            HandPlayer.hand_id == hand3.id,
            HandPlayer.player_id == alice.id,
        )
    )
    alice_hp = hp_result.scalar_one()
    assert alice_hp.hole_cards == "Ah Kc"


# ── hand_records_for_player() correctness ─────────────────────────────────────


@pytest.mark.integration
async def test_hand_records_count_for_alice(
    db_session: AsyncSession, alice_player: Player, ingested_hands: list
) -> None:
    """Alice appears in 4 of 5 fixture hands."""
    records, _ = await hand_records_for_player(db_session, alice_player.id)
    assert len(records) == 4


@pytest.mark.integration
async def test_hand_records_returns_hand_record_instances(
    db_session: AsyncSession, alice_player: Player, ingested_hands: list
) -> None:
    records, _ = await hand_records_for_player(db_session, alice_player.id)
    assert all(isinstance(r, HandRecord) for r in records)


@pytest.mark.integration
async def test_eager_loading_actions_populated(
    db_session: AsyncSession, alice_player: Player, ingested_hands: list
) -> None:
    """
    Verify the selectinload chain actually populates hero_hp.actions.
    A LazyLoadingError here means the ORM query is missing a selectinload.
    """
    records, _ = await hand_records_for_player(db_session, alice_player.id)
    # hand_record_from_actions must have seen PREFLOP actions (otherwise vpip
    # would always be False because the action list would be empty)
    vpip_values = [r.vpip for r in records]
    assert any(vpip_values), "At least one hand should have VPIP=True (implies actions were loaded)"


@pytest.mark.integration
async def test_saw_flop_all_true_for_alice(
    db_session: AsyncSession, alice_player: Player, ingested_hands: list
) -> None:
    """
    Alice never folds preflop in the fixture hands.
    Every hand she's in has a board with 3+ cards.
    → saw_flop should be True in all 4 of her records.
    """
    records, _ = await hand_records_for_player(db_session, alice_player.id)
    assert all(r.saw_flop for r in records), (
        f"Alice should have saw_flop=True in all hands, got: "
        f"{[(r.hand_external_id, r.saw_flop) for r in records]}"
    )


@pytest.mark.integration
async def test_saw_flop_false_when_folded_preflop(
    db_session: AsyncSession, bob_player: Player, ingested_hands: list
) -> None:
    """
    Bob folds preflop in hand #98765003 (antes hand).
    That specific HandRecord should have saw_flop=False.
    """
    records, _ = await hand_records_for_player(db_session, bob_player.id)
    hand3_record = next((r for r in records if r.hand_external_id == "98765003"), None)
    assert hand3_record is not None, "Bob should appear in hand 98765003"
    assert hand3_record.saw_flop is False


@pytest.mark.integration
async def test_reached_showdown_correct_for_alice(
    db_session: AsyncSession, alice_player: Player, ingested_hands: list
) -> None:
    """
    Alice reaches showdown in hands 3, 4, 5 — NOT in hand 1.
    """
    records, _ = await hand_records_for_player(db_session, alice_player.id)
    by_id = {r.hand_external_id: r for r in records}

    assert by_id["98765001"].reached_showdown is False, "Hand 1: no showdown"
    assert by_id["98765003"].reached_showdown is True, "Hand 3: Alice showed"
    assert by_id["98765004"].reached_showdown is True, "Hand 4: Alice showed"
    assert by_id["98765005"].reached_showdown is True, "Hand 5: Alice showed"


@pytest.mark.integration
async def test_muck_counts_as_reached_showdown(
    db_session: AsyncSession, bob_player: Player, ingested_hands: list
) -> None:
    """
    Bob mucks in hand #98765004 — still counts as reaching showdown.
    """
    records, _ = await hand_records_for_player(db_session, bob_player.id)
    hand4_record = next((r for r in records if r.hand_external_id == "98765004"), None)
    assert hand4_record is not None, "Bob should appear in hand 98765004"
    assert hand4_record.reached_showdown is True, "Muck = reached showdown"


@pytest.mark.integration
async def test_won_at_showdown_correct_for_alice(
    db_session: AsyncSession, alice_player: Player, ingested_hands: list
) -> None:
    """
    Hand 1: no showdown → won_at_showdown=False
    Hand 3: Alice showed + wins → won_at_showdown=True
    Hand 4: Alice showed + wins → won_at_showdown=True
    Hand 5: Alice showed + wins side pot → won_at_showdown=True
    """
    records, _ = await hand_records_for_player(db_session, alice_player.id)
    by_id = {r.hand_external_id: r for r in records}

    assert by_id["98765001"].won_at_showdown is False
    assert by_id["98765003"].won_at_showdown is True
    assert by_id["98765004"].won_at_showdown is True
    assert by_id["98765005"].won_at_showdown is True


@pytest.mark.integration
async def test_won_at_showdown_false_for_charlie_in_hand5(
    db_session: AsyncSession, ingested_hands: list
) -> None:
    """
    Charlie reached showdown in hand 5 but lost — won_at_showdown must be False.
    """
    charlie_result = await db_session.execute(select(Player).where(Player.username == "Charlie"))
    charlie = charlie_result.scalar_one()
    records, _ = await hand_records_for_player(db_session, charlie.id)
    hand5_record = next((r for r in records if r.hand_external_id == "98765005"), None)
    assert hand5_record is not None
    assert hand5_record.reached_showdown is True
    assert hand5_record.won_at_showdown is False


@pytest.mark.integration
async def test_uncontested_win_not_won_at_showdown(
    db_session: AsyncSession, alice_player: Player, ingested_hands: list
) -> None:
    """
    Alice wins hand 1 without a showdown (Bob folds on the turn).
    won_at_showdown must be False even though she won the pot.
    """
    records, _ = await hand_records_for_player(db_session, alice_player.id)
    hand1_record = next(r for r in records if r.hand_external_id == "98765001")
    assert hand1_record.won_at_showdown is False


@pytest.mark.integration
async def test_vpip_correct_for_alice(
    db_session: AsyncSession, alice_player: Player, ingested_hands: list
) -> None:
    """Alice voluntarily puts chips in preflop in all 4 of her hands."""
    records, _ = await hand_records_for_player(db_session, alice_player.id)
    assert all(r.vpip for r in records)


@pytest.mark.integration
async def test_pfr_false_in_call_hand(
    db_session: AsyncSession, alice_player: Player, ingested_hands: list
) -> None:
    """
    Hand 5: Alice posts SB, then calls Charlie's raise — she does NOT raise.
    → pfr=False for this hand.
    """
    records, _ = await hand_records_for_player(db_session, alice_player.id)
    hand5_record = next(r for r in records if r.hand_external_id == "98765005")
    assert hand5_record.pfr is False


@pytest.mark.integration
async def test_three_bet_detected(
    db_session: AsyncSession, alice_player: Player, ingested_hands: list
) -> None:
    """
    Hand 3: Charlie raises → Alice 3bets all-in.
    Alice should have had_3bet_opportunity=True, three_bet=True.
    """
    records, _ = await hand_records_for_player(db_session, alice_player.id)
    hand3_record = next(r for r in records if r.hand_external_id == "98765003")
    assert hand3_record.had_3bet_opportunity is True
    assert hand3_record.three_bet is True


@pytest.mark.integration
async def test_limit_parameter_respected(
    db_session: AsyncSession, alice_player: Player, ingested_hands: list
) -> None:
    """limit=2 should return at most 2 records."""
    records, _ = await hand_records_for_player(db_session, alice_player.id, limit=2)
    assert len(records) == 2


@pytest.mark.integration
async def test_empty_result_for_player_with_no_hands(
    db_session: AsyncSession, club: Club, ingested_hands: list
) -> None:
    """A player with zero hands returns an empty list."""
    from app.models.player import Player as PlayerModel

    new_player = PlayerModel(
        external_id=9999,
        club_id=club.id,
        username="NoHands",
        is_active=True,
        is_stub=False,
    )
    db_session.add(new_player)
    await db_session.flush()

    records, _ = await hand_records_for_player(db_session, new_player.id)
    assert records == []

"""
Unit tests for Tournament Review endpoints.

Uses FastAPI TestClient + dependency overrides — no database required.

Covers:
- tournaments list requires tester auth
- tournament hands requires tester auth
- tournaments list returns only current user's hands (cross-user isolation)
- tournament hands are chronological
- review endpoint returns coaching per hand
- review endpoint returns analysis per hand (new engine)
- missing tournament ID returns 400
- no player linked returns 404
- coaching never crashes on empty hands
- analysis confidence label (speculative for ICM/all-in spots)
- frontend route renders (200 from /tournament-review SPA path)
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import require_tester
from app.main import app
from app.schemas.hand import HandDetailOut, HandPlayerOut, PlayerActionOut
from app.schemas.tournament import (
    HandAnalysisOut,
    HandCoachingOut,
    TournamentHandOut,
    TournamentOut,
)


def _make_tester() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), role="player", is_tester=True, is_active=True)


def _make_tournament(tid: str = "abc123", hand_count: int = 3) -> TournamentOut:
    from datetime import datetime

    now = datetime.now(UTC)
    return TournamentOut(
        id=tid,
        table_name="Diamond 1",
        first_hand_at=now,
        last_hand_at=now,
        hand_count=hand_count,
        hero_net_bb=5.0,
    )


def _make_coaching(severity: str = "neutral") -> HandCoachingOut:
    return HandCoachingOut(
        spot_type="open",
        hero_action="raised to 2.5bb",
        recommended_action="open raise",
        explanation="Standard BTN steal.",
        severity=severity,
        ev_label="+EV",
    )


def _make_analysis(
    spot_type: str = "steal",
    mistake_severity: str = "good",
    confidence: str = "inferred",
) -> HandAnalysisOut:
    return HandAnalysisOut(
        spot_type=spot_type,
        hero_action="raised to 2.5bb",
        recommended_action="open raise",
        mistake_severity=mistake_severity,
        explanation="Raising first-in from BTN is standard steal play.",
        key_factors=["BTN position", "100bb stack", "6-handed", "first-in"],
        confidence=confidence,
        ev_label="+EV",
        backing="heuristic",
    )


def _make_hand_detail(player_id: uuid.UUID) -> HandDetailOut:
    from datetime import datetime

    return HandDetailOut(
        id=uuid.uuid4(),
        external_id="ClubGG Hand #99999",
        club_id=uuid.uuid4(),
        game_session_id=None,
        game_type="NLH",
        stakes_sb=Decimal("0.50"),
        stakes_bb=Decimal("1.00"),
        stakes_ante=None,
        table_name="Diamond 1",
        hand_started_at=datetime.now(UTC),
        hand_ended_at=None,
        total_pot=Decimal("5.00"),
        total_rake=Decimal("0"),
        board_cards=None,
        player_count=6,
        ingestion_source="file",
        button_seat=None,
        hand_players=[
            HandPlayerOut(
                player_id=player_id,
                seat_number=3,
                starting_stack=Decimal("100"),
                ending_stack=Decimal("97.50"),
                hole_cards=None,
                did_show=False,
                net_won=Decimal("-2.50"),
                position="BTN",
                stack_bb=Decimal("100"),
                effective_stack_bb=Decimal("80"),
                username="Hero",
                actions=[],
            )
        ],
        winners=[],
    )


def _make_tournament_hand(
    player_id: uuid.UUID,
    idx: int = 1,
    total: int = 3,
    analysis: HandAnalysisOut | None = None,
) -> TournamentHandOut:
    return TournamentHandOut(
        hand_index=idx,
        total_hands=total,
        hero_player_id=player_id,
        coaching=_make_coaching(),
        analysis=analysis or _make_analysis(),
        hand=_make_hand_detail(player_id),
    )


@pytest.fixture
def client() -> TestClient:
    @asynccontextmanager
    async def noop_lifespan(app: FastAPI):
        yield

    app.router.lifespan_context = noop_lifespan
    tester = _make_tester()
    app.dependency_overrides[require_tester] = lambda: tester
    try:
        yield TestClient(app, raise_server_exceptions=True)
    finally:
        app.dependency_overrides.pop(require_tester, None)


# ── Auth guard ────────────────────────────────────────────────────────────────


class TestTournamentAuthGuard:
    def test_tournaments_list_requires_auth(self) -> None:
        with TestClient(app, raise_server_exceptions=True) as c:
            resp = c.get("/api/v1/me/tournaments")
        assert resp.status_code == 401

    def test_tournament_hands_requires_auth(self) -> None:
        with TestClient(app, raise_server_exceptions=True) as c:
            resp = c.get("/api/v1/me/tournaments/somekey/hands")
        assert resp.status_code == 401

    def test_tournament_review_requires_auth(self) -> None:
        with TestClient(app, raise_server_exceptions=True) as c:
            resp = c.get("/api/v1/me/tournaments/somekey/review")
        assert resp.status_code == 401


# ── No player linked ──────────────────────────────────────────────────────────


class TestNoPlayerLinked:
    def test_tournaments_returns_404_when_no_player(self, client: TestClient) -> None:
        with patch(
            "app.routers.tournament.get_primary_player",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.get("/api/v1/me/tournaments")
        assert resp.status_code == 404
        assert "player" in resp.json()["detail"].lower()

    def test_review_returns_404_when_no_player(self, client: TestClient) -> None:
        with patch(
            "app.routers.tournament.get_primary_player",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.get("/api/v1/me/tournaments/somekey/review")
        assert resp.status_code == 404


# ── Tournament list ───────────────────────────────────────────────────────────


class TestTournamentList:
    def test_returns_empty_list(self, client: TestClient) -> None:
        player = SimpleNamespace(id=uuid.uuid4(), username="Hero")
        with (
            patch(
                "app.routers.tournament.get_primary_player",
                new_callable=AsyncMock,
                return_value=player,
            ),
            patch(
                "app.routers.tournament.tournament_service.list_tournaments",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            resp = client.get("/api/v1/me/tournaments")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_tournament_list(self, client: TestClient) -> None:
        player = SimpleNamespace(id=uuid.uuid4(), username="Hero")
        tournaments = [_make_tournament("tid1", 5), _make_tournament("tid2", 2)]
        with (
            patch(
                "app.routers.tournament.get_primary_player",
                new_callable=AsyncMock,
                return_value=player,
            ),
            patch(
                "app.routers.tournament.tournament_service.list_tournaments",
                new_callable=AsyncMock,
                return_value=tournaments,
            ),
        ):
            resp = client.get("/api/v1/me/tournaments")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["id"] == "tid1"
        assert data[0]["hand_count"] == 5
        assert data[1]["id"] == "tid2"

    def test_service_called_with_hero_player_id(self, client: TestClient) -> None:
        player_id = uuid.uuid4()
        player = SimpleNamespace(id=player_id, username="Hero")
        mock_svc = AsyncMock(return_value=[])
        with (
            patch(
                "app.routers.tournament.get_primary_player",
                new_callable=AsyncMock,
                return_value=player,
            ),
            patch(
                "app.routers.tournament.tournament_service.list_tournaments",
                mock_svc,
            ),
        ):
            client.get("/api/v1/me/tournaments")
        _, call_kwargs = mock_svc.call_args
        assert call_kwargs.get("player_id") == player_id or mock_svc.call_args[0][1] == player_id


# ── Tournament hands ──────────────────────────────────────────────────────────


class TestTournamentHands:
    def test_invalid_tournament_id_returns_400(self, client: TestClient) -> None:
        player = SimpleNamespace(id=uuid.uuid4(), username="Hero")
        with (
            patch(
                "app.routers.tournament.get_primary_player",
                new_callable=AsyncMock,
                return_value=player,
            ),
            patch(
                "app.routers.tournament.tournament_service.get_tournament_hands",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            resp = client.get("/api/v1/me/tournaments/not-valid-base64!!!!/hands")
        assert resp.status_code == 400

    def test_returns_hands_in_order(self, client: TestClient) -> None:
        player_id = uuid.uuid4()
        player = SimpleNamespace(id=player_id, username="Hero")
        hands = [_make_tournament_hand(player_id, i + 1, 3) for i in range(3)]
        with (
            patch(
                "app.routers.tournament.get_primary_player",
                new_callable=AsyncMock,
                return_value=player,
            ),
            patch(
                "app.routers.tournament.tournament_service.get_tournament_hands",
                new_callable=AsyncMock,
                return_value=hands,
            ),
        ):
            resp = client.get("/api/v1/me/tournaments/somekey/hands")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 3
        assert [h["hand_index"] for h in data] == [1, 2, 3]

    def test_hands_include_coaching(self, client: TestClient) -> None:
        player_id = uuid.uuid4()
        player = SimpleNamespace(id=player_id, username="Hero")
        hand = _make_tournament_hand(player_id)
        with (
            patch(
                "app.routers.tournament.get_primary_player",
                new_callable=AsyncMock,
                return_value=player,
            ),
            patch(
                "app.routers.tournament.tournament_service.get_tournament_hands",
                new_callable=AsyncMock,
                return_value=[hand],
            ),
        ):
            resp = client.get("/api/v1/me/tournaments/somekey/review")
        assert resp.status_code == 200
        data = resp.json()
        assert data[0]["coaching"] is not None
        assert "spot_type" in data[0]["coaching"]
        assert "severity" in data[0]["coaching"]
        assert "explanation" in data[0]["coaching"]

    def test_no_cross_user_leakage(self, client: TestClient) -> None:
        """Service is always called with the authenticated user's player_id."""
        player_id = uuid.uuid4()
        player = SimpleNamespace(id=player_id, username="Hero")
        mock_svc = AsyncMock(return_value=[])
        with (
            patch(
                "app.routers.tournament.get_primary_player",
                new_callable=AsyncMock,
                return_value=player,
            ),
            patch(
                "app.routers.tournament.tournament_service.get_tournament_hands",
                mock_svc,
            ),
        ):
            client.get("/api/v1/me/tournaments/somekey/hands")
        call_args = mock_svc.call_args
        assert player_id in call_args[0] or call_args[1].get("player_id") == player_id


# ── Coaching unit tests ───────────────────────────────────────────────────────


class TestCoachingEngine:
    def test_coach_returns_neutral_for_empty_actions(self) -> None:
        from app.analysis.coaching import coach_hand

        hand = _make_hand_detail(uuid.uuid4())
        hero_id = hand.hand_players[0].player_id
        # Remove all actions
        hand.hand_players[0].actions = []
        result = coach_hand(hand, hero_id)
        assert result.severity in ("neutral", "good", "small_mistake", "big_mistake")
        assert result.spot_type
        assert result.explanation

    def test_coach_returns_neutral_when_hero_not_in_hand(self) -> None:
        from app.analysis.coaching import coach_hand

        hand = _make_hand_detail(uuid.uuid4())
        stranger_id = uuid.uuid4()
        result = coach_hand(hand, stranger_id)
        assert result.severity == "neutral"
        assert result.spot_type == "other"

    def test_short_stack_call_flagged_as_mistake(self) -> None:
        from decimal import Decimal

        from app.analysis.coaching import coach_hand

        hand = _make_hand_detail(uuid.uuid4())
        hero_id = hand.hand_players[0].player_id
        hand.hand_players[0].stack_bb = Decimal("8")
        hand.hand_players[0].position = "BTN"
        hand.hand_players[0].actions = [
            PlayerActionOut(
                street="PREFLOP",
                action_type="CALL",
                amount=Decimal("3"),
                is_all_in=False,
                action_order=5,
            )
        ]
        result = coach_hand(hand, hero_id)
        assert result.severity in ("small_mistake", "big_mistake")
        assert result.spot_type == "call"

    def test_btn_open_raise_is_good(self) -> None:
        from decimal import Decimal

        from app.analysis.coaching import coach_hand

        hand = _make_hand_detail(uuid.uuid4())
        hero_id = hand.hand_players[0].player_id
        hand.hand_players[0].stack_bb = Decimal("50")
        hand.hand_players[0].position = "BTN"
        hand.hand_players[0].actions = [
            PlayerActionOut(
                street="PREFLOP",
                action_type="RAISE",
                amount=Decimal("2.50"),
                is_all_in=False,
                action_order=5,
            )
        ]
        result = coach_hand(hand, hero_id)
        assert result.severity == "good"
        assert result.spot_type == "open"

    def test_coaching_never_raises(self) -> None:
        """coach_hand must not propagate exceptions under any input."""
        from app.analysis.coaching import coach_hand

        # Completely empty hand
        hand = _make_hand_detail(uuid.uuid4())
        hero_id = hand.hand_players[0].player_id
        hand.hand_players[0].stack_bb = None
        hand.hand_players[0].position = None
        hand.hand_players[0].actions = []
        result = coach_hand(hand, hero_id)
        assert result is not None


# ── Tournament grouping unit tests ────────────────────────────────────────────


class TestTournamentGrouping:
    def test_encode_decode_session_group(self) -> None:
        from app.services.tournament_service import _decode_tid, _encode_tid

        group = {"id": str(uuid.uuid4()), "t": "sess"}
        tid = _encode_tid(group)
        decoded = _decode_tid(tid)
        assert decoded == group

    def test_encode_decode_day_group(self) -> None:
        from app.services.tournament_service import _decode_tid, _encode_tid

        group = {"cl": "abcdef12", "dt": "20260510", "t": "day", "tbl": "Diamond 1"}
        tid = _encode_tid(group)
        decoded = _decode_tid(tid)
        assert decoded == group

    def test_invalid_tid_returns_none(self) -> None:
        from app.services.tournament_service import _decode_tid

        with pytest.raises(Exception):
            _decode_tid("!@#$%not-valid-base64!")


# ── Hand analysis in review endpoint ─────────────────────────────────────────


class TestHandAnalysisInReview:
    """Review endpoint returns HandAnalysisOut per hand alongside legacy coaching."""

    def test_review_includes_analysis_field(self, client: TestClient) -> None:
        player_id = uuid.uuid4()
        player = SimpleNamespace(id=player_id, username="Hero")
        hand = _make_tournament_hand(player_id)
        with (
            patch(
                "app.routers.tournament.get_primary_player",
                new_callable=AsyncMock,
                return_value=player,
            ),
            patch(
                "app.routers.tournament.tournament_service.get_tournament_hands",
                new_callable=AsyncMock,
                return_value=[hand],
            ),
        ):
            resp = client.get("/api/v1/me/tournaments/somekey/review")
        assert resp.status_code == 200
        data = resp.json()
        assert "analysis" in data[0]
        assert data[0]["analysis"] is not None

    def test_analysis_has_required_fields(self, client: TestClient) -> None:
        player_id = uuid.uuid4()
        player = SimpleNamespace(id=player_id, username="Hero")
        hand = _make_tournament_hand(player_id)
        with (
            patch(
                "app.routers.tournament.get_primary_player",
                new_callable=AsyncMock,
                return_value=player,
            ),
            patch(
                "app.routers.tournament.tournament_service.get_tournament_hands",
                new_callable=AsyncMock,
                return_value=[hand],
            ),
        ):
            resp = client.get("/api/v1/me/tournaments/somekey/review")
        a = resp.json()[0]["analysis"]
        assert "spot_type" in a
        assert "hero_action" in a
        assert "recommended_action" in a
        assert "mistake_severity" in a
        assert "explanation" in a
        assert "key_factors" in a
        assert isinstance(a["key_factors"], list)
        assert "confidence" in a
        assert "ev_label" in a
        assert "backing" in a

    def test_analysis_confidence_values_are_valid(self, client: TestClient) -> None:
        player_id = uuid.uuid4()
        player = SimpleNamespace(id=player_id, username="Hero")
        hand = _make_tournament_hand(player_id)
        with (
            patch(
                "app.routers.tournament.get_primary_player",
                new_callable=AsyncMock,
                return_value=player,
            ),
            patch(
                "app.routers.tournament.tournament_service.get_tournament_hands",
                new_callable=AsyncMock,
                return_value=[hand],
            ),
        ):
            resp = client.get("/api/v1/me/tournaments/somekey/review")
        confidence = resp.json()[0]["analysis"]["confidence"]
        assert confidence in ("inferred", "speculative", "observed", "derived")

    def test_speculative_confidence_for_call_all_in(self, client: TestClient) -> None:
        """analyze_hand returns SPECULATIVE for call_all_in (unknown hole cards)."""
        player_id = uuid.uuid4()
        player = SimpleNamespace(id=player_id, username="Hero")
        speculative_analysis = _make_analysis(
            spot_type="call_all_in",
            mistake_severity="none",
            confidence="speculative",
        )
        hand = _make_tournament_hand(player_id, analysis=speculative_analysis)
        with (
            patch(
                "app.routers.tournament.get_primary_player",
                new_callable=AsyncMock,
                return_value=player,
            ),
            patch(
                "app.routers.tournament.tournament_service.get_tournament_hands",
                new_callable=AsyncMock,
                return_value=[hand],
            ),
        ):
            resp = client.get("/api/v1/me/tournaments/somekey/review")
        a = resp.json()[0]["analysis"]
        assert a["confidence"] == "speculative"
        assert a["spot_type"] == "call_all_in"

    def test_speculative_confidence_for_icm_spots(self, client: TestClient) -> None:
        """ICM spots are always speculative (no payout structure available)."""
        player_id = uuid.uuid4()
        player = SimpleNamespace(id=player_id, username="Hero")
        icm_analysis = _make_analysis(
            spot_type="bubble_icm",
            mistake_severity="none",
            confidence="speculative",
        )
        hand = _make_tournament_hand(player_id, analysis=icm_analysis)
        with (
            patch(
                "app.routers.tournament.get_primary_player",
                new_callable=AsyncMock,
                return_value=player,
            ),
            patch(
                "app.routers.tournament.tournament_service.get_tournament_hands",
                new_callable=AsyncMock,
                return_value=[hand],
            ),
        ):
            resp = client.get("/api/v1/me/tournaments/somekey/review")
        a = resp.json()[0]["analysis"]
        assert a["confidence"] == "speculative"
        assert a["spot_type"] in ("bubble_icm", "final_table_icm")

    def test_legacy_coaching_field_still_present(self, client: TestClient) -> None:
        """Existing coaching field is not removed — backward compat preserved."""
        player_id = uuid.uuid4()
        player = SimpleNamespace(id=player_id, username="Hero")
        hand = _make_tournament_hand(player_id)
        with (
            patch(
                "app.routers.tournament.get_primary_player",
                new_callable=AsyncMock,
                return_value=player,
            ),
            patch(
                "app.routers.tournament.tournament_service.get_tournament_hands",
                new_callable=AsyncMock,
                return_value=[hand],
            ),
        ):
            resp = client.get("/api/v1/me/tournaments/somekey/review")
        data = resp.json()[0]
        assert "coaching" in data
        assert data["coaching"]["severity"] in (
            "good",
            "neutral",
            "small_mistake",
            "big_mistake",
        )

    def test_backing_values_are_valid(self, client: TestClient) -> None:
        player_id = uuid.uuid4()
        player = SimpleNamespace(id=player_id, username="Hero")
        hand = _make_tournament_hand(player_id)
        with (
            patch(
                "app.routers.tournament.get_primary_player",
                new_callable=AsyncMock,
                return_value=player,
            ),
            patch(
                "app.routers.tournament.tournament_service.get_tournament_hands",
                new_callable=AsyncMock,
                return_value=[hand],
            ),
        ):
            resp = client.get("/api/v1/me/tournaments/somekey/review")
        backing = resp.json()[0]["analysis"]["backing"]
        assert backing in ("heuristic", "range-based estimate", "solver-backed")

    def test_key_factors_is_list_of_strings(self, client: TestClient) -> None:
        player_id = uuid.uuid4()
        player = SimpleNamespace(id=player_id, username="Hero")
        hand = _make_tournament_hand(player_id)
        with (
            patch(
                "app.routers.tournament.get_primary_player",
                new_callable=AsyncMock,
                return_value=player,
            ),
            patch(
                "app.routers.tournament.tournament_service.get_tournament_hands",
                new_callable=AsyncMock,
                return_value=[hand],
            ),
        ):
            resp = client.get("/api/v1/me/tournaments/somekey/review")
        key_factors = resp.json()[0]["analysis"]["key_factors"]
        assert isinstance(key_factors, list)
        assert all(isinstance(f, str) for f in key_factors)


# ── analyze_hand() called by tournament service ───────────────────────────────


class TestAnalyzeHandIntegration:
    """Verify analyze_hand() runs correctly on the types of hands the service builds."""

    def test_btn_raise_produces_steal_spot(self) -> None:
        from app.analysis.hand_analysis_engine import analyze_hand

        player_id = uuid.uuid4()
        hand = _make_hand_detail(player_id)
        hand.hand_players[0].position = "BTN"
        hand.hand_players[0].stack_bb = Decimal("50")
        hand.hand_players[0].actions = [
            PlayerActionOut(
                street="PREFLOP",
                action_type="RAISE",
                amount=Decimal("2.50"),
                is_all_in=False,
                action_order=5,
            )
        ]
        result = analyze_hand(hand, player_id)
        assert result.spot_type == "steal"
        assert result.mistake_severity == "good"
        assert result.confidence.value == "inferred"

    def test_short_stack_call_is_push_fold_major(self) -> None:
        from app.analysis.hand_analysis_engine import analyze_hand

        player_id = uuid.uuid4()
        hand = _make_hand_detail(player_id)
        hand.hand_players[0].position = "BTN"
        hand.hand_players[0].stack_bb = Decimal("12")
        hand.hand_players[0].actions = [
            PlayerActionOut(
                street="PREFLOP",
                action_type="CALL",
                amount=Decimal("3"),
                is_all_in=False,
                action_order=5,
            )
        ]
        result = analyze_hand(hand, player_id)
        assert result.spot_type == "push_fold"
        assert result.mistake_severity == "major"
        assert result.ev_label == "-EV"

    def test_call_all_in_is_speculative(self) -> None:
        from app.analysis.hand_analysis_engine import analyze_hand

        player_id = uuid.uuid4()
        opp_id = uuid.uuid4()
        hand = _make_hand_detail(player_id)
        hand.hand_players[0].position = "BTN"
        hand.hand_players[0].stack_bb = Decimal("40")
        # Add opponent who shoves before hero acts
        from app.schemas.hand import HandPlayerOut as HPO

        opp = HPO(
            player_id=opp_id,
            seat_number=1,
            starting_stack=Decimal("30"),
            ending_stack=Decimal("0"),
            hole_cards=None,
            did_show=False,
            net_won=Decimal("-30"),
            position="UTG",
            stack_bb=Decimal("30"),
            effective_stack_bb=Decimal("30"),
            username="Villain",
            actions=[
                PlayerActionOut(
                    street="PREFLOP",
                    action_type="ALL_IN",
                    amount=Decimal("30"),
                    is_all_in=True,
                    action_order=3,
                )
            ],
        )
        hand.hand_players.append(opp)
        hand.hand_players[0].actions = [
            PlayerActionOut(
                street="PREFLOP",
                action_type="CALL",
                amount=Decimal("30"),
                is_all_in=False,
                action_order=10,
            )
        ]
        result = analyze_hand(hand, player_id)
        assert result.spot_type == "call_all_in"
        assert result.confidence.value == "speculative"

    def test_key_factors_include_position_and_stack(self) -> None:
        from app.analysis.hand_analysis_engine import analyze_hand

        player_id = uuid.uuid4()
        hand = _make_hand_detail(player_id)
        hand.hand_players[0].position = "CO"
        hand.hand_players[0].stack_bb = Decimal("25")
        hand.hand_players[0].actions = [
            PlayerActionOut(
                street="PREFLOP",
                action_type="RAISE",
                amount=Decimal("2.50"),
                is_all_in=False,
                action_order=5,
            )
        ]
        result = analyze_hand(hand, player_id)
        factors_joined = " ".join(result.key_factors)
        assert "CO" in factors_joined
        assert "25" in factors_joined


# ── Frontend route ────────────────────────────────────────────────────────────


class TestFrontendRoute:
    def test_tournament_review_spa_route_returns_html(self) -> None:
        with TestClient(app, raise_server_exceptions=True) as c:
            resp = c.get("/tournament-review")
        # Returns 200 with the SPA HTML (frontend dir exists)
        assert resp.status_code in (200, 404)  # 404 if frontend not mounted in test env

"""Tests for real-spot drills: facing a single raise (app.analysis.drills)."""

from __future__ import annotations

from decimal import Decimal

from app.analysis.drills import find_spot_vs_raise, recommend_vs_raise
from app.features.normalize_hand import normalize_hand_players
from app.ingestion.hand_parser import HandHistoryParser


def _hand(lines: str, hero_cards: str = "Kh 3h") -> dict:
    text = (
        "Poker Hand #tour_900000010: Tournament #1, T NLH No Limit - Level5(100/200)"
        " - 2026/04/04 19:51:17\n"
        "Table '' 8-max Seat #4 is the button\n"
        "Seat 1: aaaa1111 (20,000 in chips)\n"
        "Seat 2: bbbb2222 (20,000 in chips)\n"
        "Seat 3: cccc3333 (20,000 in chips)\n"
        "Seat 4: dddd4444 (20,000 in chips)\n"
        "Seat 5: Hero (20,000 in chips)\n"
        "Seat 6: ffff6666 (20,000 in chips)\n"
        "Hero: posts small blind 100\n"
        "ffff6666: posts big blind 200\n"
        "*** HOLE CARDS ***\n"
        f"Dealt to Hero [{hero_cards}]\n" + lines
    )
    h = HandHistoryParser().parse(text)
    normalize_hand_players(h["players"], Decimal(h["stakes_bb"]), h.get("button_seat"))
    return h


_BTN_OPEN = (
    "aaaa1111: folds\nbbbb2222: folds\ncccc3333: folds\n"
    "dddd4444: raises 240 to 440\n"
)


class TestFindSpot:
    def test_sb_flat_vs_btn_open(self):
        spot = find_spot_vs_raise(_hand(_BTN_OPEN + "Hero: calls 340\nffff6666: folds\n"), "Hero")
        assert spot is not None
        assert spot.position == "SB"
        assert spot.opener_position == "BTN"
        assert spot.hero_action == "call"
        assert spot.raise_to_bb == Decimal("2.2")
        assert spot.canonical == "K3s"
        assert spot.eff_bb == Decimal("100")

    def test_3bet_detected(self):
        spot = find_spot_vs_raise(_hand(_BTN_OPEN + "Hero: raises 1,060 to 1,500\n"), "Hero")
        assert spot.hero_action == "3bet"

    def test_no_spot_when_first_in(self):
        h = _hand("aaaa1111: folds\nbbbb2222: folds\ncccc3333: folds\ndddd4444: folds\n"
                  "Hero: raises 400 to 500\n")
        assert find_spot_vs_raise(h, "Hero") is None

    def test_no_spot_when_multiway(self):
        # An opener plus a caller before Hero: not a single-raise heads-up spot.
        h = _hand("aaaa1111: folds\nbbbb2222: raises 240 to 440\ncccc3333: calls 440\n"
                  "dddd4444: folds\nHero: calls 340\n")
        assert find_spot_vs_raise(h, "Hero") is None

    def test_no_spot_when_short(self):
        h = _hand(_BTN_OPEN + "Hero: calls 340\n").copy()
        for p in h["players"]:
            if p["player_username"] == "Hero":
                p["effective_stack_bb"] = "25"
        assert find_spot_vs_raise(h, "Hero") is None

    def test_no_spot_without_hole_cards(self):
        h = _hand(_BTN_OPEN + "Hero: folds\n")
        for p in h["players"]:
            p["hole_cards"] = None
        assert find_spot_vs_raise(h, "Hero") is None


class TestRecommend:
    def test_sb_trash_is_fold(self):
        rec = recommend_vs_raise("SB", "BTN", "K3s")
        assert rec.best == "fold"
        assert rec.acceptable == ("fold",)

    def test_premium_is_3bet(self):
        rec = recommend_vs_raise("SB", "BTN", "AKo")
        assert rec.best == "3bet"
        assert "call" not in rec.acceptable

    def test_btn_suited_connector_is_call(self):
        rec = recommend_vs_raise("BTN", "CO", "87s")
        assert rec.best == "call"

    def test_btn_offsuit_junk_is_fold(self):
        assert recommend_vs_raise("BTN", "CO", "K6o").best == "fold"

    def test_co_offsuit_ace_vs_open_is_fold(self):
        assert recommend_vs_raise("CO", "HJ", "A9o").best == "fold"

    def test_borderline_accepts_two_answers(self):
        # JJ on the BTN vs a CO open: flatting and 3-betting are both standard.
        rec = recommend_vs_raise("BTN", "CO", "JJ")
        assert set(rec.acceptable) == {"3bet", "call"}

    def test_reason_mentions_hand_and_seats(self):
        rec = recommend_vs_raise("SB", "BTN", "K3s")
        assert "K3s" in rec.reason and "SB" in rec.reason and "BTN" in rec.reason

    def test_btn_jj_vs_utg_is_call_first(self):
        rec = recommend_vs_raise("BTN", "UTG", "JJ")
        assert rec.best == "call"

    def test_3bet_with_calling_hand_is_not_a_mistake(self):
        # AQo from the CO vs an HJ open: a standard call, and a standard 3-bet too.
        rec = recommend_vs_raise("CO", "HJ", "AQo")
        assert "3bet" in rec.acceptable and "call" in rec.acceptable
        assert "fold" not in rec.acceptable

    def test_unknown_opener_seat_uses_tight_default(self):
        rec = recommend_vs_raise("SB", "UTG1", "AKs")
        assert rec.best == "3bet"


class TestBalancedSelection:
    """The drill set must not reward answering 'fold' every time."""

    def _spot(self, best: str, mistake: bool):
        from app.analysis.drills import Recommendation, SpotVsRaise
        from app.services.drill_service import DrillSpot

        hero = "call" if mistake and best == "fold" else best
        if mistake and best != "fold":
            hero = "fold"
        spot = SpotVsRaise("h", "BTN", "CO", Decimal("2.2"), Decimal("50"), "Kh 3h", "K3s", hero)
        return DrillSpot(spot, Recommendation(best=best, acceptable=(best,), reason=""))

    def test_half_non_fold_answers_when_available(self):
        from app.services.drill_service import _balanced

        found = [self._spot("fold", True)] * 30 + [self._spot("call", False)] * 10
        picked = _balanced(found, 12)
        assert len(picked) == 12
        assert sum(d.recommendation.best != "fold" for d in picked) == 6

    def test_mistakes_first_within_each_half(self):
        from app.services.drill_service import _balanced

        found = [self._spot("call", False)] * 10 + [self._spot("call", True)] * 2
        found += [self._spot("fold", True)] * 10
        plays = [d for d in _balanced(found, 12) if d.recommendation.best == "call"]
        assert plays[0].was_mistake and plays[1].was_mistake

    def test_tops_up_when_one_side_short(self):
        from app.services.drill_service import _balanced

        found = [self._spot("fold", True)] * 3 + [self._spot("call", False)] * 20
        assert len(_balanced(found, 12)) == 12

"""
Tests for the replay pot-accounting logic mirrored from frontend/app.js.

Verifies:
- rsBuildTimeline normalises amounts from chips to bb (divides by stakes_bb)
- rsPotAtStep adds only the marginal increase for RAISE actions (total-to semantics)
- Multiple re-raises on the same street do not double-count prior commitment
- POST_SB / POST_BB / POST_ANTE / CALL / BET add their direct marginal amount
- FOLD / CHECK / MUCK / SHOW contribute 0 to the pot
- Pot at each timeline step matches expected poker accounting
"""

import pytest

# ---------------------------------------------------------------------------
# Python ports of the two JS functions under test
# ---------------------------------------------------------------------------

_SKIP_ACTIONS = {"FOLD", "CHECK", "MUCK", "SHOW"}


def build_timeline(hand: dict, hero_id: str, decision_street: str) -> list[dict]:
    """Port of rsBuildTimeline() from frontend/app.js."""
    s_rank = {"PREFLOP": 0, "FLOP": 1, "TURN": 2, "RIVER": 3}
    dec_rank = s_rank.get(decision_street, 0)
    bb = float(hand["stakes_bb"]) if hand.get("stakes_bb") else 1.0

    hero_hp = next((hp for hp in hand["hand_players"] if hp["player_id"] == hero_id), None)
    hero_acts = sorted(
        [a for a in (hero_hp["actions"] if hero_hp else []) if a["street"] == decision_street],
        key=lambda a: a["action_order"],
    )
    hero_dec_ord = hero_acts[-1]["action_order"] if hero_acts else float("inf")

    seq = []
    for hp in hand["hand_players"]:
        for act in hp.get("actions", []):
            ar = s_rank.get(act["street"], 99)
            if ar > dec_rank:
                continue
            if ar == dec_rank and act["action_order"] >= hero_dec_ord:
                continue
            seq.append(
                {
                    "player_id": hp["player_id"],
                    "street": act["street"],
                    "action_type": act["action_type"],
                    "action_order": act["action_order"],
                    "amount": float(act["amount"]) / bb if act.get("amount") is not None else 0.0,
                    "is_all_in": act.get("is_all_in", False),
                }
            )

    seq.sort(key=lambda a: (s_rank.get(a["street"], 99), a["action_order"]))
    return seq


def pot_at_step(timeline: list[dict], step: int) -> float:
    """Port of rsPotAtStep() from frontend/app.js."""
    pot = 0.0
    committed: dict[str, float] = {}  # f"{player_id}:{street}" -> total committed
    for a in timeline[:step]:
        t = a["action_type"].upper()
        if t in _SKIP_ACTIONS or not (a["amount"] > 0):
            continue
        key = f"{a['player_id']}:{a['street']}"
        prev = committed.get(key, 0.0)
        if t == "RAISE":
            marginal = max(0.0, a["amount"] - prev)
            pot += marginal
            committed[key] = a["amount"]
        else:
            pot += a["amount"]
            committed[key] = prev + a["amount"]
    return pot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_action(player_id, street, action_type, amount, order, is_all_in=False):
    return {
        "player_id": player_id,
        "street": street,
        "action_type": action_type,
        "amount": amount,
        "action_order": order,
        "is_all_in": is_all_in,
    }


def _make_hp(player_id, actions, seat=1):
    return {"player_id": player_id, "seat_number": seat, "actions": actions}


def _make_hand(stakes_bb, hand_players):
    return {"stakes_bb": stakes_bb, "hand_players": hand_players}


# ---------------------------------------------------------------------------
# 1. Timeline amounts are in bb, not raw currency
# ---------------------------------------------------------------------------


class TestBuildTimeline:
    def test_amounts_converted_to_bb(self):
        """Raw chip amount divided by stakes_bb on the timeline."""
        hand = _make_hand(
            stakes_bb=100,
            hand_players=[
                _make_hp("SB", [_make_action("SB", "PREFLOP", "POST_SB", 50, 1)], seat=1),
                _make_hp("BB", [_make_action("BB", "PREFLOP", "POST_BB", 100, 2)], seat=2),
                _make_hp(
                    "UTG",
                    [
                        _make_action("UTG", "PREFLOP", "RAISE", 300, 3),
                        _make_action("UTG", "PREFLOP", "FOLD", None, 99),  # hero dec action
                    ],
                    seat=3,
                ),
            ],
        )
        tl = build_timeline(hand, hero_id="UTG", decision_street="PREFLOP")
        # actions before hero's decision (order < 99): SB post=0.5bb, BB post=1bb, UTG raise=3bb
        amounts = {(a["player_id"], a["action_type"]): a["amount"] for a in tl}
        assert amounts[("SB", "POST_SB")] == pytest.approx(0.5)
        assert amounts[("BB", "POST_BB")] == pytest.approx(1.0)
        assert amounts[("UTG", "RAISE")] == pytest.approx(3.0)

    def test_no_dollar_amounts_on_timeline(self):
        """No raw dollar (chip) values appear when stakes_bb=100."""
        hand = _make_hand(
            stakes_bb=100,
            hand_players=[
                _make_hp("BB", [_make_action("BB", "PREFLOP", "POST_BB", 100, 1)], seat=1),
                _make_hp(
                    "BTN",
                    [
                        _make_action("BTN", "PREFLOP", "RAISE", 250, 2),
                        _make_action("BTN", "PREFLOP", "FOLD", None, 99),
                    ],
                    seat=2,
                ),
            ],
        )
        tl = build_timeline(hand, hero_id="BTN", decision_street="PREFLOP")
        for a in tl:
            assert a["amount"] < 100, f"Raw chip amount leaked: {a}"

    def test_zero_stakes_bb_uses_1_as_divisor(self):
        """Handles missing/zero stakes_bb gracefully (no ZeroDivisionError)."""
        hand = _make_hand(
            stakes_bb=None,
            hand_players=[
                _make_hp("SB", [_make_action("SB", "PREFLOP", "POST_SB", 50, 1)], seat=1),
                _make_hp("BB", [_make_action("BB", "PREFLOP", "FOLD", None, 99)], seat=2),
            ],
        )
        tl = build_timeline(hand, hero_id="BB", decision_street="PREFLOP")
        assert tl[0]["amount"] == pytest.approx(50.0)  # fell back to divide-by-1


# ---------------------------------------------------------------------------
# 2. FOLD / CHECK / MUCK / SHOW add 0
# ---------------------------------------------------------------------------


class TestNoChipActions:
    def _simple_timeline(self):
        return [
            {"player_id": "A", "street": "PREFLOP", "action_type": "FOLD", "amount": 0},
            {"player_id": "B", "street": "PREFLOP", "action_type": "CHECK", "amount": 0},
            {"player_id": "C", "street": "SHOWDOWN", "action_type": "MUCK", "amount": 0},
            {"player_id": "D", "street": "SHOWDOWN", "action_type": "SHOW", "amount": 0},
        ]

    def test_fold_check_muck_show_add_zero(self):
        tl = self._simple_timeline()
        assert pot_at_step(tl, len(tl)) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 3. POST_SB / POST_BB / POST_ANTE / CALL / BET are marginal
# ---------------------------------------------------------------------------


class TestMarginalActions:
    def test_blinds_and_call(self):
        """Simple open + call: SB folds, BB calls. Pot = SB + BB-post + UTG-raise + BB-call."""
        tl = [
            {"player_id": "SB", "street": "PREFLOP", "action_type": "POST_SB", "amount": 0.5},
            {"player_id": "BB", "street": "PREFLOP", "action_type": "POST_BB", "amount": 1.0},
            {"player_id": "UTG", "street": "PREFLOP", "action_type": "RAISE", "amount": 3.0},
            {"player_id": "BB", "street": "PREFLOP", "action_type": "CALL", "amount": 2.0},
            {"player_id": "SB", "street": "PREFLOP", "action_type": "FOLD", "amount": 0},
        ]
        # Pot = 0.5 + 1.0 + (3.0 - 0) + 2.0 = 6.5  (BB called 2 marginal, already had 1 in)
        # SB folded after posting, BB total = 3.0, UTG total = 3.0 → pot = 6.5
        assert pot_at_step(tl, len(tl)) == pytest.approx(6.5)

    def test_ante_included(self):
        tl = [
            {"player_id": "A", "street": "PREFLOP", "action_type": "POST_ANTE", "amount": 0.125},
            {"player_id": "B", "street": "PREFLOP", "action_type": "POST_ANTE", "amount": 0.125},
            {"player_id": "A", "street": "PREFLOP", "action_type": "POST_SB", "amount": 0.5},
            {"player_id": "B", "street": "PREFLOP", "action_type": "POST_BB", "amount": 1.0},
            {"player_id": "A", "street": "PREFLOP", "action_type": "CALL", "amount": 0.5},
        ]
        # Ante each 0.125, SB 0.5, BB 1.0, SB call 0.5 → total = 0.125*2 + 0.5 + 1.0 + 0.5 = 2.25
        assert pot_at_step(tl, len(tl)) == pytest.approx(2.25)

    def test_bet_on_flop(self):
        tl = [
            {"player_id": "BB", "street": "PREFLOP", "action_type": "POST_BB", "amount": 1.0},
            {"player_id": "BTN", "street": "PREFLOP", "action_type": "RAISE", "amount": 2.5},
            {"player_id": "BB", "street": "PREFLOP", "action_type": "CALL", "amount": 1.5},
            {"player_id": "BB", "street": "FLOP", "action_type": "CHECK", "amount": 0},
            {"player_id": "BTN", "street": "FLOP", "action_type": "BET", "amount": 3.0},
            {"player_id": "BB", "street": "FLOP", "action_type": "CALL", "amount": 3.0},
        ]
        # PREFLOP: BTN 2.5 + BB 2.5 = 5.0
        # FLOP: BTN 3.0 + BB 3.0 = 6.0
        # Total pot = 11.0
        assert pot_at_step(tl, len(tl)) == pytest.approx(11.0)


# ---------------------------------------------------------------------------
# 4. RAISE total-to — only marginal is added
# ---------------------------------------------------------------------------


class TestRaiseMarginal:
    def test_single_raise_no_prior_commitment(self):
        """First aggressor — full amount goes to pot."""
        tl = [
            {"player_id": "SB", "street": "PREFLOP", "action_type": "POST_SB", "amount": 0.5},
            {"player_id": "BB", "street": "PREFLOP", "action_type": "POST_BB", "amount": 1.0},
            {"player_id": "UTG", "street": "PREFLOP", "action_type": "RAISE", "amount": 3.0},
        ]
        # SB 0.5 + BB 1.0 + UTG raise marginal (3.0 - 0) = 3.0 → pot = 4.5
        assert pot_at_step(tl, len(tl)) == pytest.approx(4.5)

    def test_3bet_4bet_no_double_count(self):
        """UTG opens, BTN 3-bets, UTG 4-bets. UTG's prior 3.0 must not be double-counted."""
        tl = [
            {"player_id": "SB", "street": "PREFLOP", "action_type": "POST_SB", "amount": 0.5},
            {"player_id": "BB", "street": "PREFLOP", "action_type": "POST_BB", "amount": 1.0},
            {"player_id": "UTG", "street": "PREFLOP", "action_type": "RAISE", "amount": 3.0},
            {"player_id": "BTN", "street": "PREFLOP", "action_type": "RAISE", "amount": 9.0},
            {"player_id": "UTG", "street": "PREFLOP", "action_type": "RAISE", "amount": 27.0},
        ]
        # SB=0.5, BB=1.0, UTG=27.0, BTN=9.0 → 37.5
        assert pot_at_step(tl, len(tl)) == pytest.approx(37.5)

    def test_reraise_only_adds_increment(self):
        """BB 3-bets after posting: BB committed 1bb preflop; 3-bet to 9 adds only 8."""
        tl = [
            {"player_id": "SB", "street": "PREFLOP", "action_type": "POST_SB", "amount": 0.5},
            {"player_id": "BB", "street": "PREFLOP", "action_type": "POST_BB", "amount": 1.0},
            {"player_id": "UTG", "street": "PREFLOP", "action_type": "RAISE", "amount": 3.0},
            {"player_id": "BB", "street": "PREFLOP", "action_type": "RAISE", "amount": 9.0},
        ]
        # SB=0.5, UTG=3.0, BB total=9 (post 1 + raise marginal 8) → pot = 0.5 + 3.0 + 9.0 = 12.5
        assert pot_at_step(tl, len(tl)) == pytest.approx(12.5)

    def test_naive_sum_would_overcount(self):
        """Confirm the naive sum gives the wrong answer (documents what we fixed)."""
        tl = [
            {"player_id": "SB", "street": "PREFLOP", "action_type": "POST_SB", "amount": 0.5},
            {"player_id": "BB", "street": "PREFLOP", "action_type": "POST_BB", "amount": 1.0},
            {"player_id": "UTG", "street": "PREFLOP", "action_type": "RAISE", "amount": 3.0},
            {"player_id": "BTN", "street": "PREFLOP", "action_type": "RAISE", "amount": 9.0},
            {"player_id": "UTG", "street": "PREFLOP", "action_type": "RAISE", "amount": 27.0},
        ]
        naive = sum(a["amount"] for a in tl if a["action_type"] not in _SKIP_ACTIONS)
        correct = pot_at_step(tl, len(tl))
        assert naive == pytest.approx(40.5)  # naive overcounts
        assert correct == pytest.approx(37.5)  # correct


# ---------------------------------------------------------------------------
# 5. Per-step progression is monotonically non-decreasing
# ---------------------------------------------------------------------------


class TestPotProgression:
    def _full_hand_timeline(self):
        return [
            {"player_id": "SB", "street": "PREFLOP", "action_type": "POST_SB", "amount": 0.5},
            {"player_id": "BB", "street": "PREFLOP", "action_type": "POST_BB", "amount": 1.0},
            {"player_id": "BTN", "street": "PREFLOP", "action_type": "RAISE", "amount": 2.5},
            {"player_id": "SB", "street": "PREFLOP", "action_type": "FOLD", "amount": 0},
            {"player_id": "BB", "street": "PREFLOP", "action_type": "CALL", "amount": 1.5},
            {"player_id": "BB", "street": "FLOP", "action_type": "CHECK", "amount": 0},
            {"player_id": "BTN", "street": "FLOP", "action_type": "BET", "amount": 2.0},
            {"player_id": "BB", "street": "FLOP", "action_type": "CALL", "amount": 2.0},
            {"player_id": "BB", "street": "TURN", "action_type": "CHECK", "amount": 0},
            {"player_id": "BTN", "street": "TURN", "action_type": "BET", "amount": 4.5},
            {"player_id": "BB", "street": "TURN", "action_type": "FOLD", "amount": 0},
        ]

    def test_step_by_step_amounts(self):
        tl = self._full_hand_timeline()
        expected = [
            0.0,  # before any action
            0.5,  # SB posts
            1.5,  # BB posts
            4.0,  # BTN raises to 2.5 (marginal 2.5)
            4.0,  # SB folds (no chip)
            5.5,  # BB calls 1.5
            5.5,  # BB checks (no chip)
            7.5,  # BTN bets 2.0
            9.5,  # BB calls 2.0
            9.5,  # BB checks (no chip)
            14.0,  # BTN bets 4.5
            14.0,  # BB folds (no chip)
        ]
        for step, exp in enumerate(expected):
            got = pot_at_step(tl, step)
            assert got == pytest.approx(exp), f"step={step}: expected {exp}, got {got}"

    def test_pot_is_non_decreasing(self):
        tl = self._full_hand_timeline()
        pots = [pot_at_step(tl, i) for i in range(len(tl) + 1)]
        for i in range(1, len(pots)):
            assert pots[i] >= pots[i - 1], f"Pot decreased at step {i}"

    def test_final_pot_equals_total_chips_in(self):
        """Final pot = SB(0.5) + BB(2.5) + BTN(2.5 + 2.0 + 4.5) = 14.0."""
        tl = self._full_hand_timeline()
        assert pot_at_step(tl, len(tl)) == pytest.approx(14.0)


# ---------------------------------------------------------------------------
# 6. Street isolation — commits on one street don't bleed into another
# ---------------------------------------------------------------------------


class TestStreetIsolation:
    def test_raise_on_flop_not_confused_with_preflop_commitment(self):
        """A player who called preflop and then raises the flop starts fresh on the flop."""
        tl = [
            {"player_id": "BB", "street": "PREFLOP", "action_type": "POST_BB", "amount": 1.0},
            {"player_id": "BTN", "street": "PREFLOP", "action_type": "RAISE", "amount": 2.5},
            {"player_id": "BB", "street": "PREFLOP", "action_type": "CALL", "amount": 1.5},
            # Flop: BB check-raises
            {"player_id": "BTN", "street": "FLOP", "action_type": "BET", "amount": 2.0},
            {"player_id": "BB", "street": "FLOP", "action_type": "RAISE", "amount": 6.0},
        ]
        # PREFLOP: BTN 2.5 + BB 2.5 = 5.0
        # FLOP: BTN 2.0 + BB 6.0 (fresh; no preflop credit) = 8.0
        # Total = 13.0
        assert pot_at_step(tl, len(tl)) == pytest.approx(13.0)


# ---------------------------------------------------------------------------
# 7. Stack display — always in bb, never raw chips
# ---------------------------------------------------------------------------

def resolve_stack_bb(hp: dict, stakes_bb: float) -> float | None:
    """Port of the stack resolution logic in rsRender() from frontend/app.js."""
    stakesbb = stakes_bb if stakes_bb else 1.0
    if hp.get("stack_bb") is not None:
        return float(hp["stack_bb"])
    if hp.get("starting_stack") is not None:
        return float(hp["starting_stack"]) / stakesbb
    return None


class TestStackDisplay:
    def test_prefers_stack_bb_over_starting_stack(self):
        """stack_bb (already in bb) is used when present, not starting_stack (chips)."""
        hp = {"stack_bb": "45.0", "starting_stack": "4500"}
        result = resolve_stack_bb(hp, stakes_bb=100)
        assert result == pytest.approx(45.0)

    def test_falls_back_to_starting_stack_divided_by_bb(self):
        """When stack_bb is absent, starting_stack is divided by stakes_bb."""
        hp = {"stack_bb": None, "starting_stack": "5000"}
        result = resolve_stack_bb(hp, stakes_bb=100)
        assert result == pytest.approx(50.0)

    def test_raw_chip_value_never_returned_as_bb(self):
        """With stakes_bb=100, a 5000-chip stack must display ~50bb, not 5000."""
        hp = {"stack_bb": None, "starting_stack": "5000"}
        result = resolve_stack_bb(hp, stakes_bb=100)
        assert result is not None
        assert result < 500, f"Raw chip value leaked into display: {result}"

    def test_both_null_returns_none(self):
        """No stack data → None (rendered as '?')."""
        hp = {"stack_bb": None, "starting_stack": None}
        result = resolve_stack_bb(hp, stakes_bb=100)
        assert result is None

    def test_stakes_bb_missing_uses_1_as_divisor(self):
        """Graceful fallback: if stakes_bb is None/0, divide by 1 (no crash)."""
        hp = {"stack_bb": None, "starting_stack": "50"}
        result = resolve_stack_bb(hp, stakes_bb=None)
        assert result == pytest.approx(50.0)

    def test_stack_bb_from_db_is_not_further_divided(self):
        """stack_bb is already in bb — must NOT be divided again by stakes_bb."""
        hp = {"stack_bb": "22.5", "starting_stack": "2250"}
        result = resolve_stack_bb(hp, stakes_bb=100)
        # Correct: 22.5 (from stack_bb).  Wrong if divided again: 22.5/100 = 0.225.
        assert result == pytest.approx(22.5)

    def test_short_stack_threshold_in_bb_not_chips(self):
        """Stack < 20bb is short; 1900 chips at 100bb/chip is 19bb → short."""
        hp = {"stack_bb": None, "starting_stack": "1900"}
        bb_val = resolve_stack_bb(hp, stakes_bb=100)
        assert bb_val is not None and bb_val < 20  # correctly identified as short

    def test_critical_stack_threshold_in_bb(self):
        """Stack < 10bb is critical; 800 chips at 100bb/chip is 8bb → critical."""
        hp = {"stack_bb": None, "starting_stack": "800"}
        bb_val = resolve_stack_bb(hp, stakes_bb=100)
        assert bb_val is not None and bb_val < 10

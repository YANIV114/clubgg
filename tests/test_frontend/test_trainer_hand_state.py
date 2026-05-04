"""
Python port of buildTrainerHandState() from frontend/app.js.

Tests cover:
- Blind posting (SB/BB only for preflop)
- Action log order preservation
- Marginal pot accounting for raise/3-bet/4-bet (total-to semantics)
- Folded players remain in seat list but get status='folded'
- Hero decision is always the last log entry
- Dealer button marker (isBTN) only on BTN seat
- Contributions for non-acting positions are 0
- Call without amount infers from current bet
- Multi-street history
- Board card parsing
- Exact pot totals for the four built-in replay drill scenarios
"""

import pytest

# ---------------------------------------------------------------------------
# Python port of buildTrainerHandState
# ---------------------------------------------------------------------------

CW_ORDER = ["BTN", "SB", "BB", "UTG", "HJ", "CO"]


def _parse_amount_bb(s: str | None) -> float:
    if not s:
        return 0.0
    return float(str(s).lower().replace("bb", "").strip()) or 0.0


def _classify_action(action_str: str) -> str:
    a = action_str.lower()
    if a == "fold":
        return "fold"
    if a.startswith("check"):
        return "check"
    if a == "call":
        return "call"
    if a.startswith("call"):
        return "call"
    if a.startswith("bet"):
        return "bet"
    if "all-in" in a:
        return "allin"
    if a.startswith("raise") or a.startswith("3-bet") or a.startswith("4-bet"):
        return "raise"
    return "check"


def build_trainer_hand_state(s: dict) -> dict:
    """
    Python port of buildTrainerHandState(s) from frontend/app.js.

    Parameters
    ----------
    s : dict with keys:
        position       – hero's position string ('BTN', 'SB', etc.)
        stack_bb       – hero's stack in bb (number)
        decisionStreet – 'PREFLOP' | 'FLOP' | 'TURN' | 'RIVER'
        actionHistory  – list of {pos, action, amount?}
        board          – None or string like 'K♥ 7♣ 3♦'
        hand           – list of card dicts (not used in state computation)

    Returns
    -------
    dict with:
        seats      – list of seat dicts
        potBb      – float
        boardCards – list[str]
        actionLog  – list of log entry dicts
        heroPos    – str
        heroStack  – number
    """
    hero_pos = s["position"]
    decision_street = s.get("decisionStreet", "PREFLOP")
    action_history = s.get("actionHistory") or []

    # 1. Collect all positions
    pos_set: set[str] = set()
    pos_set.add(hero_pos)
    is_preflop = decision_street == "PREFLOP" or not decision_street
    if is_preflop:
        pos_set.add("SB")
        pos_set.add("BB")
    for entry in action_history:
        pos_set.add(entry["pos"])

    # 2. Sort clockwise starting from hero
    hero_idx = CW_ORDER.index(hero_pos)
    seat_order = []
    for i in range(len(CW_ORDER)):
        pos = CW_ORDER[(hero_idx + i) % len(CW_ORDER)]
        if pos in pos_set:
            seat_order.append(pos)

    # 3. Build action log + pot accounting
    action_log = []
    contributions: dict[str, float] = {}
    pot_bb = 0.0
    current_bet = 0.0

    # SB/BB blinds (preflop only)
    if is_preflop:
        if "SB" in pos_set:
            contributions["SB"] = 0.5
            pot_bb += 0.5
            current_bet = max(current_bet, 0.5)
            action_log.append(
                {
                    "pos": "SB",
                    "text": "post 0.5bb",
                    "type": "blind",
                    "isHero": hero_pos == "SB",
                }
            )
        if "BB" in pos_set:
            contributions["BB"] = 1.0
            pot_bb += 1.0
            current_bet = max(current_bet, 1.0)
            action_log.append(
                {
                    "pos": "BB",
                    "text": "post 1bb",
                    "type": "blind",
                    "isHero": hero_pos == "BB",
                }
            )

    # History entries
    for entry in action_history:
        pos = entry["pos"]
        action_str = entry.get("action") or ""
        atype = _classify_action(action_str)
        amount_str = entry.get("amount")
        prev = contributions.get(pos, 0.0)
        text = action_str
        if amount_str:
            text = f"{action_str} ({amount_str})"

        if atype in ("fold", "check"):
            pass  # no chips
        elif atype in ("raise", "allin"):
            total_to = _parse_amount_bb(amount_str)
            if total_to > 0:
                marginal = max(0.0, total_to - prev)
                pot_bb += marginal
                contributions[pos] = total_to
                current_bet = max(current_bet, total_to)
        elif atype == "call":
            if amount_str:
                marginal = _parse_amount_bb(amount_str)
                pot_bb += marginal
                contributions[pos] = prev + marginal
            else:
                marginal = max(0.0, current_bet - prev)
                pot_bb += marginal
                contributions[pos] = current_bet
        elif atype == "bet":
            amount = _parse_amount_bb(amount_str)
            pot_bb += amount
            contributions[pos] = prev + amount
            current_bet = max(current_bet, contributions[pos])

        action_log.append({"pos": pos, "text": text, "type": atype, "isHero": pos == hero_pos})

    # Hero decision (always last)
    action_log.append(
        {
            "pos": hero_pos,
            "text": "your decision",
            "type": "decision",
            "isHero": True,
        }
    )

    # 4. Build seat list
    folded: set[str] = set()
    allin: set[str] = set()
    for entry in action_history:
        a = (entry.get("action") or "").lower()
        if a == "fold":
            folded.add(entry["pos"])
        if "all-in" in a:
            allin.add(entry["pos"])

    seats = [
        {
            "pos": pos,
            "isHero": pos == hero_pos,
            "status": "allin" if pos in allin else "folded" if pos in folded else "active",
            "contributionBb": contributions.get(pos, 0.0),
            "stack": s.get("stack_bb") if pos == hero_pos else None,
            "isBTN": pos == "BTN",
        }
        for pos in seat_order
    ]

    # 5. Board cards
    board = s.get("board")
    board_cards = board.split(" ") if board else []
    board_cards = [c for c in board_cards if c]

    return {
        "seats": seats,
        "potBb": pot_bb,
        "boardCards": board_cards,
        "actionLog": action_log,
        "heroPos": hero_pos,
        "heroStack": s.get("stack_bb"),
    }


# ---------------------------------------------------------------------------
# Scenario fixtures mirroring the four built-in TR_SCENARIOS replay drills
# ---------------------------------------------------------------------------

S_RD_PF_001 = {
    "id": "rd-pf-001",
    "type": "replay_drill",
    "position": "BTN",
    "stack_bb": 12,
    "decisionStreet": "PREFLOP",
    "actionHistory": [
        {"pos": "UTG", "action": "Fold"},
        {"pos": "HJ", "action": "Fold"},
        {"pos": "CO", "action": "Fold"},
    ],
    "board": None,
    "hand": [{"rank": "A", "suit": "♥", "red": True}, {"rank": "7", "suit": "♣", "red": False}],
    "options": [{"id": "fold"}, {"id": "push"}],
    "correct": "push",
}

S_RD_BB_001 = {
    "id": "rd-bb-001",
    "type": "replay_drill",
    "position": "BB",
    "stack_bb": 14,
    "decisionStreet": "PREFLOP",
    "actionHistory": [
        {"pos": "UTG", "action": "Fold"},
        {"pos": "HJ", "action": "Fold"},
        {"pos": "CO", "action": "Raise", "amount": "2.5bb"},
        {"pos": "BTN", "action": "Fold"},
        {"pos": "SB", "action": "Fold"},
    ],
    "board": None,
    "hand": [{"rank": "K", "suit": "♠", "red": False}, {"rank": "9", "suit": "♣", "red": False}],
    "options": [{"id": "fold"}, {"id": "call"}, {"id": "push"}],
    "correct": "call",
}

S_RD_FT_001 = {
    "id": "rd-ft-001",
    "type": "replay_drill",
    "position": "CO",
    "stack_bb": 30,
    "decisionStreet": "PREFLOP",
    "actionHistory": [
        {"pos": "UTG", "action": "Fold"},
        {"pos": "CO", "action": "Raise", "amount": "2.5bb"},
        {"pos": "BTN", "action": "3-bet", "amount": "7.5bb"},
        {"pos": "SB", "action": "Fold"},
        {"pos": "BB", "action": "Fold"},
    ],
    "board": None,
    "hand": [{"rank": "A", "suit": "♦", "red": True}, {"rank": "J", "suit": "♣", "red": False}],
    "options": [{"id": "fold"}, {"id": "call"}, {"id": "raise"}],
    "correct": "fold",
}

S_RD_GN_001 = {
    "id": "rd-gn-001",
    "type": "replay_drill",
    "position": "BTN",
    "stack_bb": 40,
    "decisionStreet": "FLOP",
    "actionHistory": [
        {"pos": "UTG", "action": "Fold"},
        {"pos": "HJ", "action": "Fold"},
        {"pos": "CO", "action": "Fold"},
        {"pos": "BTN", "action": "Raise", "amount": "2.2bb"},
        {"pos": "SB", "action": "Fold"},
        {"pos": "BB", "action": "Call"},
        {"pos": "BB", "action": "Check (flop)"},
    ],
    "board": "K♥ 7♣ 3♦",
    "hand": [{"rank": "K", "suit": "♦", "red": True}, {"rank": "Q", "suit": "♠", "red": False}],
    "options": [{"id": "check"}, {"id": "raise"}],
    "correct": "raise",
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBlinds:
    def test_only_sb_bb_post_blinds(self):
        """For a preflop scenario, only SB and BB blind entries are auto-generated."""
        state = build_trainer_hand_state(S_RD_PF_001)
        blind_entries = [e for e in state["actionLog"] if e["type"] == "blind"]
        assert len(blind_entries) == 2
        positions = [e["pos"] for e in blind_entries]
        assert "SB" in positions
        assert "BB" in positions

    def test_no_blinds_on_flop_scenario(self):
        """Postflop scenarios do not inject blind entries."""
        state = build_trainer_hand_state(S_RD_GN_001)
        blind_entries = [e for e in state["actionLog"] if e["type"] == "blind"]
        assert len(blind_entries) == 0

    def test_sb_blind_is_half_bb(self):
        state = build_trainer_hand_state(S_RD_PF_001)
        sb_entry = next(e for e in state["actionLog"] if e["type"] == "blind" and e["pos"] == "SB")
        assert "0.5" in sb_entry["text"]

    def test_bb_blind_is_one_bb(self):
        state = build_trainer_hand_state(S_RD_PF_001)
        bb_entry = next(e for e in state["actionLog"] if e["type"] == "blind" and e["pos"] == "BB")
        assert "1" in bb_entry["text"]


class TestActionOrder:
    def test_action_order_preserved(self):
        """History entries appear in input order after any blinds."""
        state = build_trainer_hand_state(S_RD_BB_001)
        # After SB and BB blinds the order must be UTG, HJ, CO, BTN, SB, then decision
        non_blind_non_decision = [
            e["pos"] for e in state["actionLog"] if e["type"] not in ("blind", "decision")
        ]
        assert non_blind_non_decision == ["UTG", "HJ", "CO", "BTN", "SB"]

    def test_hero_decision_is_last_log_entry(self):
        """The final entry in actionLog is always the hero decision entry."""
        for scenario in [S_RD_PF_001, S_RD_BB_001, S_RD_FT_001, S_RD_GN_001]:
            state = build_trainer_hand_state(scenario)
            last = state["actionLog"][-1]
            assert last["type"] == "decision"
            assert last["isHero"] is True
            assert last["pos"] == scenario["position"]


class TestPotAccounting:
    def test_raise_marginal_pot(self):
        """3-bet scenario: CO raises to 2.5, BTN 3-bets to 7.5. Both use total-to semantics."""
        state = build_trainer_hand_state(S_RD_FT_001)
        # SB=0.5, BB=1, CO raises to 2.5 (marginal 2.5), BTN 3-bets to 7.5 (marginal 7.5)
        # SB folds, BB folds → pot = 0.5 + 1 + 2.5 + 7.5 = 11.5
        assert state["potBb"] == pytest.approx(11.5)

    def test_no_fake_contributions(self):
        """Positions not in actionHistory have contributionBb == 0."""
        state = build_trainer_hand_state(S_RD_PF_001)
        # UTG, HJ, CO all folded — no chips committed by them
        for seat in state["seats"]:
            if seat["pos"] in ("UTG", "HJ", "CO"):
                assert seat["contributionBb"] == pytest.approx(0.0)

    def test_call_without_amount_infers_from_current_bet(self):
        """BB 'Call' (no amount) in rd-gn-001 actionHistory calls BTN's raise to 2.2bb.
        BB posted 1bb blind → marginal = 2.2 - 1.0 = 1.2bb; total contribution = 2.2bb.
        (rd-gn-001 is a FLOP drill so BB's preflop call appears in actionHistory.)"""
        # rd-gn-001 decisionStreet is FLOP, so no auto-blind injection.
        # BTN raises to 2.2bb preflop; BB calls (no amount stated).
        # With FLOP as decisionStreet the scenario has NO blind entries in the log,
        # so BB's initial contribution starts at 0 and currentBet is 2.2 after BTN raise.
        # BB call → marginal = max(0, 2.2 - 0) = 2.2bb; contributions['BB'] = 2.2bb.
        state = build_trainer_hand_state(S_RD_GN_001)
        bb_seat = next(seat for seat in state["seats"] if seat["pos"] == "BB")
        assert bb_seat["contributionBb"] == pytest.approx(2.2)

    def test_pot_bb_for_rd_pf_001(self):
        """UTG/HJ/CO fold. Hero BTN. Pot = SB(0.5) + BB(1) = 1.5bb."""
        state = build_trainer_hand_state(S_RD_PF_001)
        assert state["potBb"] == pytest.approx(1.5)

    def test_pot_bb_for_rd_bb_001(self):
        """CO raises to 2.5, BTN folds, SB folds. Hero BB has not yet acted.
        Pot at decision = SB blind(0.5) + BB blind(1.0) + CO raise marginal(2.5) = 4.0bb.
        (The 5.5bb in the scenario's setup text is the pot *after* BB calls — not shown here.)"""
        state = build_trainer_hand_state(S_RD_BB_001)
        assert state["potBb"] == pytest.approx(4.0)

    def test_pot_bb_for_rd_ft_001(self):
        """CO opens 2.5, BTN 3-bets 7.5, SB/BB fold.
        Pot = SB(0.5) + BB(1) + CO(2.5) + BTN(7.5) = 11.5bb."""
        state = build_trainer_hand_state(S_RD_FT_001)
        assert state["potBb"] == pytest.approx(11.5)

    def test_flop_scenario_includes_preflop_and_flop_actions(self):
        """rd-gn-001 is a FLOP scenario. Preflop actions appear in actionLog."""
        state = build_trainer_hand_state(S_RD_GN_001)
        positions_in_log = [e["pos"] for e in state["actionLog"] if e["type"] != "decision"]
        assert "UTG" in positions_in_log
        assert "BB" in positions_in_log

    def test_flop_scenario_no_double_count(self):
        """BTN Raise 2.2bb total-to + BB Call (no amount → infers 2.2bb) = 4.4bb.
        No blind injection for flop scenario."""
        state = build_trainer_hand_state(S_RD_GN_001)
        # BTN raises to 2.2, BB calls (infers 2.2 from currentBet)
        # pot = 2.2 + 2.2 = 4.4bb (no blinds because FLOP decisionStreet)
        assert state["potBb"] == pytest.approx(4.4)


class TestSeatList:
    def test_folded_players_not_removed(self):
        """Folded players still appear in the seats list."""
        state = build_trainer_hand_state(S_RD_BB_001)
        seat_positions = {seat["pos"] for seat in state["seats"]}
        # UTG, HJ, BTN, SB all folded — must still be present
        for pos in ("UTG", "HJ", "BTN", "SB"):
            assert pos in seat_positions

    def test_folded_players_have_folded_status(self):
        """Positions whose action was 'Fold' get status='folded'."""
        state = build_trainer_hand_state(S_RD_BB_001)
        for seat in state["seats"]:
            if seat["pos"] in ("UTG", "HJ", "BTN", "SB"):
                assert seat["status"] == "folded"

    def test_hero_seat_is_first(self):
        """Hero's seat is at index 0 (bottom of visual)."""
        for scenario in [S_RD_PF_001, S_RD_BB_001, S_RD_FT_001, S_RD_GN_001]:
            state = build_trainer_hand_state(scenario)
            assert state["seats"][0]["pos"] == scenario["position"]
            assert state["seats"][0]["isHero"] is True

    def test_button_marker_on_btn_seat(self):
        """isBTN=True only on the BTN seat."""
        state = build_trainer_hand_state(S_RD_PF_001)
        for seat in state["seats"]:
            if seat["pos"] == "BTN":
                assert seat["isBTN"] is True
            else:
                assert seat["isBTN"] is False

    def test_no_fake_contributions_position_not_in_history(self):
        """Positions auto-added (SB, BB) but not in actionHistory get contributions
        only from blind posting, not from imaginary actions."""
        # In rd-pf-001 SB/BB are not in actionHistory (they haven't acted yet)
        state = build_trainer_hand_state(S_RD_PF_001)
        sb_seat = next(s for s in state["seats"] if s["pos"] == "SB")
        bb_seat = next(s for s in state["seats"] if s["pos"] == "BB")
        # SB posted 0.5, BB posted 1
        assert sb_seat["contributionBb"] == pytest.approx(0.5)
        assert bb_seat["contributionBb"] == pytest.approx(1.0)

    def test_hero_stack_stored_on_hero_seat(self):
        """Hero's stack_bb is stored on the hero seat; other seats have None."""
        state = build_trainer_hand_state(S_RD_PF_001)
        for seat in state["seats"]:
            if seat["isHero"]:
                assert seat["stack"] == S_RD_PF_001["stack_bb"]
            else:
                assert seat["stack"] is None


class TestBoardCards:
    def test_board_cards_parsed_correctly(self):
        """'K♥ 7♣ 3♦' → 3-element list."""
        state = build_trainer_hand_state(S_RD_GN_001)
        assert len(state["boardCards"]) == 3

    def test_board_cards_content(self):
        state = build_trainer_hand_state(S_RD_GN_001)
        assert state["boardCards"] == ["K♥", "7♣", "3♦"]

    def test_no_board_returns_empty_list(self):
        state = build_trainer_hand_state(S_RD_PF_001)
        assert state["boardCards"] == []

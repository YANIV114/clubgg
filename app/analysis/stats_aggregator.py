"""
Aggregate per-player statistics from a list of HandDetailOut records.

Definitions
-----------
VPIP  — Voluntarily Put money In pot Preflop: player CALL/RAISE/BET/ALL_IN preflop
        (posts excluded). Denominator: hands dealt to player.
PFR   — PreFlop Raise: player RAISED/BET/ALL_IN preflop (same denominator as VPIP).
3-bet — Player re-raised when facing exactly one preflop raise before their action.
        Denominator: hands where player faced one preflop raise.
Fold-to-steal — BB folded when BTN or SB raised preflop first-in.
        Denominator: hands where player was BB AND BTN/SB raised preflop.
AF    — Aggression Frequency postflop: (bets+raises+all-ins) / (bets+raises+all-ins+calls)
        Denominator: hands with at least one postflop action (bet, raise, call, all-in).

Reliability — requires hands_observed >= 10.
"""

from __future__ import annotations

from uuid import UUID

from app.analysis.opponent_profile import PlayerStats
from app.schemas.hand import HandDetailOut, HandPlayerOut

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MIN_HANDS = 10  # must match opponent_profile._MIN_HANDS
_SKIP_POSTING = frozenset({"POST_SB", "POST_BB", "POST_ANTE"})
_RAISE_TYPES = frozenset({"RAISE", "BET", "ALL_IN", "ALLIN"})
_STEAL_POSITIONS = frozenset({"BTN", "SB"})

# ---------------------------------------------------------------------------
# Per-hand stat helpers
# ---------------------------------------------------------------------------


def _was_dealt_in(hp: HandPlayerOut) -> bool:
    """Player had at least one preflop action."""
    return any(a.street == "PREFLOP" for a in hp.actions)


def _vpip(hp: HandPlayerOut) -> bool:
    """True if player made a voluntary preflop money action."""
    return any(
        a.street == "PREFLOP" and a.action_type in ("CALL", "RAISE", "BET", "ALL_IN", "ALLIN")
        for a in hp.actions
        if a.action_type not in _SKIP_POSTING
    )


def _pfr(hp: HandPlayerOut) -> bool:
    """True if player raised preflop."""
    return any(
        a.street == "PREFLOP" and a.action_type in _RAISE_TYPES
        for a in hp.actions
        if a.action_type not in _SKIP_POSTING
    )


def _count_raises_before_hero(hand: HandDetailOut, hero_id: UUID, street: str) -> int:
    """Count opponent RAISE/BET/ALL_IN on `street` before hero's first voluntary action."""
    hero_hp = next((hp for hp in hand.hand_players if hp.player_id == hero_id), None)
    if not hero_hp:
        return 0
    vol = [a for a in hero_hp.actions if a.street == street and a.action_type not in _SKIP_POSTING]
    if not vol:
        return 0
    first_hero_order = min(a.action_order for a in vol)
    count = 0
    for hp in hand.hand_players:
        if hp.player_id == hero_id:
            continue
        for a in hp.actions:
            if (
                a.street == street
                and a.action_order < first_hero_order
                and a.action_type in _RAISE_TYPES
            ):
                count += 1
    return count


def _three_bet(hand: HandDetailOut, hp: HandPlayerOut) -> tuple[bool, bool]:
    """
    Returns (faced_one_raise, did_three_bet).

    faced_one_raise: player had exactly 1 opponent raise before their preflop action.
    did_three_bet: player then raised/bet preflop.
    """
    n = _count_raises_before_hero(hand, hp.player_id, "PREFLOP")
    if n != 1:
        return (False, False)
    vol = [a for a in hp.actions if a.street == "PREFLOP" and a.action_type not in _SKIP_POSTING]
    if not vol:
        return (False, False)
    did = any(a.action_type in _RAISE_TYPES for a in vol)
    return (True, did)


def _fold_to_steal(hand: HandDetailOut, hp: HandPlayerOut) -> tuple[bool, bool]:
    """
    Returns (faced_steal, folded).

    Only counted when hero is BB and BTN/SB raised preflop (first-in, no earlier raises).
    """
    if hp.position != "BB":
        return (False, False)

    steal_raise_order: int | None = None
    for opp in hand.hand_players:
        if opp.player_id == hp.player_id:
            continue
        if (opp.position or "").upper() not in _STEAL_POSITIONS:
            continue
        for a in opp.actions:
            if a.street == "PREFLOP" and a.action_type in _RAISE_TYPES:
                # Verify it was first-in: no raises before this action
                earlier_raises = sum(
                    1
                    for hp2 in hand.hand_players
                    for a2 in hp2.actions
                    if a2.street == "PREFLOP"
                    and a2.action_type in _RAISE_TYPES
                    and a2.action_order < a.action_order
                )
                if earlier_raises == 0:
                    steal_raise_order = a.action_order

    if steal_raise_order is None:
        return (False, False)

    # BB's preflop action after the steal raise
    bb_acts = [
        a
        for a in hp.actions
        if a.street == "PREFLOP"
        and a.action_type not in _SKIP_POSTING
        and a.action_order > steal_raise_order
    ]
    if not bb_acts:
        return (False, False)

    last = max(bb_acts, key=lambda a: a.action_order)
    return (True, last.action_type == "FOLD")


def _postflop_aggression(hp: HandPlayerOut) -> tuple[int, int, int]:
    """Returns (agg_actions, call_actions, postflop_hand_contribution)."""
    postflop = [a for a in hp.actions if a.street in ("FLOP", "TURN", "RIVER")]
    agg = sum(1 for a in postflop if a.action_type in _RAISE_TYPES)
    calls = sum(1 for a in postflop if a.action_type == "CALL")
    return agg, calls, 1 if postflop else 0


# ---------------------------------------------------------------------------
# Main aggregator functions
# ---------------------------------------------------------------------------


def aggregate_player_stats(
    player_id: UUID,
    hands: list[HandDetailOut],
) -> PlayerStats:
    """
    Compute stats for one player from a list of HandDetailOut records.

    Only hands where the player was dealt in (had at least one preflop action)
    contribute to the denominator.  Returns PlayerStats with reliable=False
    and hands_observed=0 if the player never appears or was never dealt in.
    """
    vpip_count = 0
    pfr_count = 0
    hands_dealt = 0
    three_bet_opps = 0
    three_bet_count = 0
    steal_opps = 0
    steal_folds = 0
    postflop_agg = 0
    postflop_calls = 0

    for hand in hands:
        hp = next((p for p in hand.hand_players if p.player_id == player_id), None)
        if hp is None or not _was_dealt_in(hp):
            continue

        hands_dealt += 1
        if _vpip(hp):
            vpip_count += 1
        if _pfr(hp):
            pfr_count += 1

        faced, did = _three_bet(hand, hp)
        if faced:
            three_bet_opps += 1
            if did:
                three_bet_count += 1

        fts_faced, fts_folded = _fold_to_steal(hand, hp)
        if fts_faced:
            steal_opps += 1
            if fts_folded:
                steal_folds += 1

        agg, calls, _ph = _postflop_aggression(hp)
        postflop_agg += agg
        postflop_calls += calls

    if hands_dealt == 0:
        return PlayerStats(hands_observed=0, reliable=False)

    vpip = vpip_count / hands_dealt
    pfr_val = pfr_count / hands_dealt
    three_bet = three_bet_count / three_bet_opps if three_bet_opps >= 5 else None
    fold_steal = steal_folds / steal_opps if steal_opps >= 5 else None
    agg_freq_denom = postflop_agg + postflop_calls
    agg_freq = postflop_agg / agg_freq_denom if agg_freq_denom > 0 else None

    return PlayerStats(
        vpip=round(vpip, 4),
        pfr=round(pfr_val, 4),
        aggression_freq=round(agg_freq, 4) if agg_freq is not None else None,
        fold_to_steal=round(fold_steal, 4) if fold_steal is not None else None,
        three_bet_pct=round(three_bet, 4) if three_bet is not None else None,
        hands_observed=hands_dealt,
        reliable=hands_dealt >= _MIN_HANDS,
    )


def aggregate_all_players(
    hands: list[HandDetailOut],
) -> dict[UUID, PlayerStats]:
    """
    Compute stats for every player appearing in the hand list.

    Returns a dict keyed by player_id.  Every player who appears in at least
    one hand is included; players with zero dealt-in hands will have
    hands_observed=0 and reliable=False.
    """
    player_ids: set[UUID] = {hp.player_id for hand in hands for hp in hand.hand_players}
    return {pid: aggregate_player_stats(pid, hands) for pid in player_ids}


__all__ = ["aggregate_player_stats", "aggregate_all_players"]

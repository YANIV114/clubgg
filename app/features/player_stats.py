"""
Per-player aggregate statistics.

Pure functions — no DB, no IO. Takes HandRecord inputs, returns PlayerStats.

All output statistics are INFERRED. Even when derived from counted frequencies,
the counts represent patterns over a sample that does not necessarily generalize.
Opponent tendencies, ICM pressure, and table dynamics are unknown.

Stat definitions
----------------
VPIP (voluntarily put chips in preflop):
    Hands where player CALL/RAISE/BET/ALL_IN preflop / total hands dealt.
    Excludes forced posts (SB, BB, ante). BB "check" when facing no raise = 0.

PFR (preflop raise %):
    Hands where player RAISE/BET/ALL_IN preflop / total hands dealt.

3bet% (three-bet frequency):
    Hands where player re-raised preflop / hands where player faced an open raise.
    Denominator = ``had_3bet_opportunity`` count, not total hands.

fold-to-3bet:
    Hands where player folded to a 3bet / hands where player opened and faced a 3bet.
    Denominator = ``faced_3bet`` count (opened preflop, then faced a re-raise).

WTSD (went to showdown):
    Hands player reached showdown / hands player saw the flop.

WSD (won at showdown):
    Hands player won at showdown / hands player reached showdown.

Postflop stats
--------------
cbet_pct:
    Hands where hero bet the flop as PF aggressor / hands where hero was PF aggressor
    and saw the flop.  Excludes spots where another player bet first on the flop.

fold_to_flop_bet:
    Hands where hero folded on the flop facing a bet / hands where hero saw the flop
    and another player bet before hero's last flop action.

turn_barrel_pct:
    Hands where hero bet the turn / hands where hero c-bet the flop and saw the turn.
    Measures double-barrel frequency.

fold_to_turn_bet:
    Hands where hero folded facing a turn bet / hands where hero saw the turn and
    another player bet before hero's last turn action.

delayed_cbet_pct:
    Hands where hero bet the turn as the first bettor / hands where hero was the
    PF aggressor, checked the flop (and opponent also checked), and saw the turn.
    Measures how often hero "bombs" the turn after a passive flop.

check_raise_pct:
    Hands where hero raised after checking on any postflop street / hands where hero
    checked then faced a bet on the same street.

aggression_factor:
    (Total postflop bets + raises) / (Total postflop calls) across all hands.
    n = total postflop calls.  Standard measure of postflop aggression.
    Returns None when total postflop calls = 0 (player never called postflop).

Usage
-----
    records: list[HandRecord] = service.fetch_hand_records(player_id, session)
    stats = compute_player_stats(player_id=player_id, hands=records)

    if stats.vpip.is_reliable():
        print(f"VPIP: {stats.vpip.value:.1%}  [{stats.vpip.label} n={stats.vpip.n}]")
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from app.features.labels import LabeledMetric, inferred

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_FOUR_PLACES = Decimal("0.0001")

# Action type strings — duplicated from ActionType StrEnum to keep this module
# free of SQLAlchemy imports (features/ must be pure Python, no ORM deps).
_VOLUNTARY_PREFLOP: frozenset[str] = frozenset({"CALL", "RAISE", "BET", "ALL_IN"})
_RAISE_TYPES: frozenset[str] = frozenset({"RAISE", "BET", "ALL_IN"})
_POST_TYPES: frozenset[str] = frozenset({"POST_SB", "POST_BB", "POST_ANTE"})
# Positions from which a raise counts as a "steal attempt"
_STEAL_POSITIONS: frozenset[str] = frozenset({"BTN", "CO", "SB"})
# Positions that can defend (receive a steal)
_BLIND_POSITIONS: frozenset[str] = frozenset({"BB", "SB"})

# Postflop streets (excludes SHOWDOWN — SHOW/MUCK don't affect postflop stats)
_POSTFLOP_STREETS: frozenset[str] = frozenset({"FLOP", "TURN", "RIVER"})


# ---------------------------------------------------------------------------
# Input type
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HandRecord:
    """
    A single player's participation in one hand.

    This is the boundary between raw DB data and pure analytics. Never pass
    SQLAlchemy model instances into stat-computation functions; convert them
    to HandRecord first (see ``hand_record_from_actions``).

    All boolean flags are precomputed from the raw action sequence at
    data-preparation time.

    Fields
    ------
    hand_external_id:
        The hand's ClubGG external_id. Used in evidence strings for leak output.
    position:
        Position string ("BTN", "CO", etc.) or None when button seat was absent.
        None positions are excluded from positional breakdowns — never faked.
    stack_bb:
        Hero's starting stack in big blinds. None if bb_size was zero or absent.
    effective_stack_bb:
        min(hero_stack_bb, deepest_opponent_stack_bb). None if unavailable.
    vpip:
        Player voluntarily put chips in preflop (CALL/RAISE/BET/ALL_IN).
        Forced posts do NOT count. BB check with no raise = False.
    pfr:
        Player raised preflop (RAISE/BET/ALL_IN). Includes opens and 3bets.
    had_3bet_opportunity:
        Another player had already raised before this player's first non-forced
        preflop action, giving them the opportunity to re-raise (3bet).
    three_bet:
        Player had a 3bet opportunity AND re-raised.
    faced_3bet:
        Player opened preflop AND subsequently faced a re-raise from another player.
    folded_to_3bet:
        Player faced a 3bet (opened, then was 3bet) AND folded to it.
    saw_flop:
        Player did not fold preflop AND the hand reached the flop.
        Must be provided externally — cannot be computed from actions alone
        (requires knowing whether the flop was dealt).
    reached_showdown:
        Player showed or mucked cards at showdown.
    won_at_showdown:
        Player reached showdown AND won (appears in hand_winners for this hand).
        Must be provided externally — requires HandWinner or net_won data.

    Postflop fields (all default False/0; set correctly when saw_flop=True and
    postflop action data is supplied to hand_record_from_actions)
    -----------------------------------------------------------------------
    cbet_opportunity:
        Hero was the preflop raiser AND saw the flop.
    cbet:
        cbet_opportunity AND hero placed the first bet on the flop (no prior bet
        by another player before hero's first flop action).
    faced_flop_bet:
        Hero saw the flop AND another player bet/raised before hero's last flop action.
    folded_to_flop_bet:
        faced_flop_bet AND hero's last flop action was FOLD.
    turn_barrel_opportunity:
        Hero c-bet the flop AND had turn actions (saw the turn).
    turn_barreled:
        turn_barrel_opportunity AND hero placed the first bet on the turn.
    faced_turn_bet:
        Hero had turn actions AND another player bet/raised before hero's last turn action.
    folded_to_turn_bet:
        faced_turn_bet AND hero's last turn action was FOLD.
    delayed_cbet_opportunity:
        Hero was PF aggressor, checked the flop, no one bet the flop (check-check),
        and hero had turn actions.
    delayed_cbet:
        delayed_cbet_opportunity AND hero placed the first bet on the turn.
    check_raise_opportunity:
        On any postflop street, hero checked, then another player bet after
        hero's check, and hero had at least one more action on that street.
    check_raised:
        check_raise_opportunity AND hero raised (BET/RAISE/ALL_IN) after checking.
    postflop_bets_raises:
        Count of BET/RAISE/ALL_IN actions by hero on FLOP+TURN+RIVER.
        Used as the numerator for aggression_factor.
    postflop_calls:
        Count of CALL actions by hero on FLOP+TURN+RIVER.
        Used as the denominator for aggression_factor.
    """

    hand_external_id: str
    position: str | None
    stack_bb: Decimal | None
    effective_stack_bb: Decimal | None
    vpip: bool
    pfr: bool
    had_3bet_opportunity: bool
    three_bet: bool
    faced_3bet: bool
    folded_to_3bet: bool
    saw_flop: bool
    reached_showdown: bool
    won_at_showdown: bool

    # ── Steal / defend fields ─────────────────────────────────────────────────
    # All default False when position data is unavailable (no "position" key in
    # action dicts).  This keeps old callers that don't supply positions safe.

    had_steal_opportunity: bool  # in BTN/CO/SB, pot unopened before hero acts
    stole: bool  # had_steal_opportunity AND raised
    faced_steal: bool  # in BB/SB, first raiser was from BTN/CO/SB
    folded_to_steal: bool  # faced_steal AND folded
    re_steal_opportunity: bool  # == faced_steal (kept per API contract)
    attempted_resteal: bool  # faced_steal AND raised (3-bet the stealer)
    folded_bb_to_btn_open: bool  # BB specifically folded to BTN open
    folded_sb_to_btn_open: bool  # SB specifically folded to BTN open
    faced_btn_open_as_bb: bool  # BB, BTN raised (denominator for bb_fold_to_btn)
    faced_co_open_as_bb: bool  # BB, CO raised (denominator for bb_fold_to_co)
    open_position: str | None  # hero's position if stole, else None
    defender_position: str | None  # hero's position if faced_steal, else None

    # ── Postflop fields (defaults=False/0 for backward compatibility) ─────────
    cbet_opportunity: bool = field(default=False)
    cbet: bool = field(default=False)
    faced_flop_bet: bool = field(default=False)
    folded_to_flop_bet: bool = field(default=False)
    turn_barrel_opportunity: bool = field(default=False)
    turn_barreled: bool = field(default=False)
    faced_turn_bet: bool = field(default=False)
    folded_to_turn_bet: bool = field(default=False)
    delayed_cbet_opportunity: bool = field(default=False)
    delayed_cbet: bool = field(default=False)
    check_raise_opportunity: bool = field(default=False)
    check_raised: bool = field(default=False)
    postflop_bets_raises: int = field(default=0)
    postflop_calls: int = field(default=0)

    # ── Hand context ──────────────────────────────────────────────────────────
    # True when the hand had antes (tournament levels). Selects leak baselines.
    has_ante: bool = field(default=False)
    # Net chips won in the hand / big blind.  None when the result is unknown.
    net_bb: Decimal | None = field(default=None)


# ---------------------------------------------------------------------------
# Output types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PositionalStats:
    """
    Aggregate stats for a specific position within a player's sample.

    All rate fields are INFERRED. ``n_hands`` is the denominator for VPIP/PFR.
    3bet%/fold-to-3bet use eligible-situation counts as denominators (encoded
    in the ``n`` field of each LabeledMetric).
    """

    position: str
    n_hands: int
    vpip: LabeledMetric[Decimal | None]
    pfr: LabeledMetric[Decimal | None]
    three_bet_pct: LabeledMetric[Decimal | None]
    fold_to_3bet: LabeledMetric[Decimal | None]
    # Positional steal/defend rates (None denominator → INFERRED(None, n=0))
    steal_pct: LabeledMetric[Decimal | None]  # BTN/CO/SB: stole/opportunities
    fold_to_steal: LabeledMetric[Decimal | None]  # BB/SB: folded/faced-steal


@dataclass(frozen=True)
class PlayerStats:
    """
    Aggregate statistics for a player across a sample of hands.

    All rate fields are INFERRED. Sample sizes (n) are the denominators for
    each stat:
      - vpip, pfr, wtsd, wsd: n = hand_count (or saw_flop count for wtsd)
      - three_bet_pct: n = had_3bet_opportunity count
      - fold_to_3bet:  n = faced_3bet count
      - cbet_pct:      n = cbet_opportunity count
      - fold_to_flop_bet: n = faced_flop_bet count
      - turn_barrel_pct:  n = turn_barrel_opportunity count
      - fold_to_turn_bet: n = faced_turn_bet count
      - delayed_cbet_pct: n = delayed_cbet_opportunity count
      - check_raise_pct:  n = check_raise_opportunity count
      - aggression_factor: n = total postflop calls (denominator of AF formula)

    ``is_reliable(min_n=20)`` returns True when the sample size for that stat
    meets the threshold. Use this before displaying a stat in reports.

    Positional breakdown excludes hands where position is None.
    """

    player_id: uuid.UUID
    hand_count: int
    vpip: LabeledMetric[Decimal | None]
    pfr: LabeledMetric[Decimal | None]
    three_bet_pct: LabeledMetric[Decimal | None]
    fold_to_3bet: LabeledMetric[Decimal | None]
    wtsd: LabeledMetric[Decimal | None]
    wsd: LabeledMetric[Decimal | None]
    # ── Steal stats (from BTN/CO/SB) ─────────────────────────────────────────
    steal_pct: LabeledMetric[Decimal | None]  # overall steal%
    btn_steal_pct: LabeledMetric[Decimal | None]  # BTN steal%
    co_steal_pct: LabeledMetric[Decimal | None]  # CO steal%
    sb_steal_pct: LabeledMetric[Decimal | None]  # SB steal%
    # ── Defend stats (BB/SB vs steals) ───────────────────────────────────────
    fold_to_steal: LabeledMetric[Decimal | None]  # overall blind fold to steal
    bb_fold_to_steal: LabeledMetric[Decimal | None]  # BB fold to any steal
    sb_fold_to_steal: LabeledMetric[Decimal | None]  # SB fold to any steal
    bb_fold_to_btn_open: LabeledMetric[Decimal | None]  # BB fold specifically to BTN
    bb_fold_to_co_open: LabeledMetric[Decimal | None]  # BB fold specifically to CO
    # ── Re-steal ─────────────────────────────────────────────────────────────
    resteal_pct: LabeledMetric[Decimal | None]  # 3-bet when facing a steal
    positional: dict[str, PositionalStats]
    # ── Postflop stats ────────────────────────────────────────────────────────
    cbet_pct: LabeledMetric[Decimal | None]  # flop c-bet%
    fold_to_flop_bet: LabeledMetric[Decimal | None]  # fold when facing flop bet
    turn_barrel_pct: LabeledMetric[Decimal | None]  # double-barrel%
    fold_to_turn_bet: LabeledMetric[Decimal | None]  # fold when facing turn bet
    delayed_cbet_pct: LabeledMetric[Decimal | None]  # bet turn after check-check flop
    check_raise_pct: LabeledMetric[Decimal | None]  # check-raise any postflop street
    aggression_factor: LabeledMetric[Decimal | None]  # (bets+raises) / calls postflop


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_player_stats(
    player_id: uuid.UUID,
    hands: Sequence[HandRecord],
) -> PlayerStats:
    """
    Compute aggregate statistics from a sequence of HandRecord inputs.

    Parameters
    ----------
    player_id:
        The player's UUID — stored in the result for traceability.
    hands:
        Per-hand records for this player. All records are assumed to belong to
        the same player. Empty sequence returns PlayerStats with all rates
        as INFERRED(None, n=0).

    Returns
    -------
    PlayerStats with all rate fields labeled INFERRED.
    """
    n = len(hands)

    vpip_n = sum(1 for h in hands if h.vpip)
    pfr_n = sum(1 for h in hands if h.pfr)

    opp_3bet = sum(1 for h in hands if h.had_3bet_opportunity)
    did_3bet = sum(1 for h in hands if h.three_bet)

    faced_3bet = sum(1 for h in hands if h.faced_3bet)
    folded_3bet = sum(1 for h in hands if h.folded_to_3bet)

    saw_flop_n = sum(1 for h in hands if h.saw_flop)
    reached_sd = sum(1 for h in hands if h.reached_showdown)
    won_sd = sum(1 for h in hands if h.won_at_showdown)

    # ── Steal counts ─────────────────────────────────────────────────────────
    steal_opp = sum(1 for h in hands if h.had_steal_opportunity)
    steals = sum(1 for h in hands if h.stole)
    btn_opp = sum(1 for h in hands if h.position == "BTN" and h.had_steal_opportunity)
    btn_steals = sum(1 for h in hands if h.position == "BTN" and h.stole)
    co_opp = sum(1 for h in hands if h.position == "CO" and h.had_steal_opportunity)
    co_steals = sum(1 for h in hands if h.position == "CO" and h.stole)
    sb_opp = sum(1 for h in hands if h.position == "SB" and h.had_steal_opportunity)
    sb_steals = sum(1 for h in hands if h.position == "SB" and h.stole)

    # ── Defend counts ─────────────────────────────────────────────────────────
    all_faced_steal = sum(1 for h in hands if h.faced_steal)
    all_folded_steal = sum(1 for h in hands if h.folded_to_steal)
    bb_faced_steal = sum(1 for h in hands if h.position == "BB" and h.faced_steal)
    bb_folded_steal = sum(1 for h in hands if h.position == "BB" and h.folded_to_steal)
    sb_faced_steal = sum(1 for h in hands if h.position == "SB" and h.faced_steal)
    sb_folded_steal = sum(1 for h in hands if h.position == "SB" and h.folded_to_steal)
    bb_faced_btn = sum(1 for h in hands if h.faced_btn_open_as_bb)
    bb_folded_btn = sum(1 for h in hands if h.folded_bb_to_btn_open)
    bb_faced_co = sum(1 for h in hands if h.faced_co_open_as_bb)
    # BB folded to CO: faced CO open AND folded (folded_to_steal=True because faced_steal=True)
    bb_folded_co = sum(1 for h in hands if h.faced_co_open_as_bb and h.folded_to_steal)
    resteal_opp = all_faced_steal
    resteals = sum(1 for h in hands if h.attempted_resteal)

    # ── Postflop counts ───────────────────────────────────────────────────────
    cbet_opp = sum(1 for h in hands if h.cbet_opportunity)
    cbet_n = sum(1 for h in hands if h.cbet)

    faced_flop_bet_n = sum(1 for h in hands if h.faced_flop_bet)
    folded_flop_bet_n = sum(1 for h in hands if h.folded_to_flop_bet)

    turn_barrel_opp = sum(1 for h in hands if h.turn_barrel_opportunity)
    turn_barrel_n = sum(1 for h in hands if h.turn_barreled)

    faced_turn_bet_n = sum(1 for h in hands if h.faced_turn_bet)
    folded_turn_bet_n = sum(1 for h in hands if h.folded_to_turn_bet)

    delayed_cbet_opp = sum(1 for h in hands if h.delayed_cbet_opportunity)
    delayed_cbet_n = sum(1 for h in hands if h.delayed_cbet)

    check_raise_opp = sum(1 for h in hands if h.check_raise_opportunity)
    check_raise_n = sum(1 for h in hands if h.check_raised)

    total_bets_raises = sum(h.postflop_bets_raises for h in hands)
    total_calls = sum(h.postflop_calls for h in hands)

    return PlayerStats(
        player_id=player_id,
        hand_count=n,
        vpip=_rate(vpip_n, n, f"vpip_count={vpip_n} / hands={n}"),
        pfr=_rate(pfr_n, n, f"pfr_count={pfr_n} / hands={n}"),
        three_bet_pct=_rate(
            did_3bet,
            opp_3bet,
            f"3bets={did_3bet} / 3bet-opportunities={opp_3bet}",
        ),
        fold_to_3bet=_rate(
            folded_3bet,
            faced_3bet,
            f"folds-to-3bet={folded_3bet} / faced-3bet={faced_3bet}",
        ),
        wtsd=_rate(
            reached_sd,
            saw_flop_n,
            f"reached-showdown={reached_sd} / saw-flop={saw_flop_n}",
        ),
        wsd=_rate(
            won_sd,
            reached_sd,
            f"won-at-sd={won_sd} / reached-showdown={reached_sd}",
        ),
        steal_pct=_rate(steals, steal_opp, f"steals={steals} / steal-opp={steal_opp}"),
        btn_steal_pct=_rate(btn_steals, btn_opp, f"btn-steals={btn_steals} / btn-opp={btn_opp}"),
        co_steal_pct=_rate(co_steals, co_opp, f"co-steals={co_steals} / co-opp={co_opp}"),
        sb_steal_pct=_rate(sb_steals, sb_opp, f"sb-steals={sb_steals} / sb-opp={sb_opp}"),
        fold_to_steal=_rate(
            all_folded_steal,
            all_faced_steal,
            f"folded-steal={all_folded_steal} / faced-steal={all_faced_steal}",
        ),
        bb_fold_to_steal=_rate(
            bb_folded_steal,
            bb_faced_steal,
            f"bb-folded-steal={bb_folded_steal} / bb-faced-steal={bb_faced_steal}",
        ),
        sb_fold_to_steal=_rate(
            sb_folded_steal,
            sb_faced_steal,
            f"sb-folded-steal={sb_folded_steal} / sb-faced-steal={sb_faced_steal}",
        ),
        bb_fold_to_btn_open=_rate(
            bb_folded_btn,
            bb_faced_btn,
            f"bb-folded-btn={bb_folded_btn} / bb-faced-btn={bb_faced_btn}",
        ),
        bb_fold_to_co_open=_rate(
            bb_folded_co,
            bb_faced_co,
            f"bb-folded-co={bb_folded_co} / bb-faced-co={bb_faced_co}",
        ),
        resteal_pct=_rate(
            resteals,
            resteal_opp,
            f"resteals={resteals} / resteal-opp={resteal_opp}",
        ),
        positional=_compute_positional(hands),
        # Postflop
        cbet_pct=_rate(cbet_n, cbet_opp, f"cbets={cbet_n} / cbet-opp={cbet_opp}"),
        fold_to_flop_bet=_rate(
            folded_flop_bet_n,
            faced_flop_bet_n,
            f"folded-flop-bet={folded_flop_bet_n} / faced-flop-bet={faced_flop_bet_n}",
        ),
        turn_barrel_pct=_rate(
            turn_barrel_n,
            turn_barrel_opp,
            f"turn-barrels={turn_barrel_n} / turn-barrel-opp={turn_barrel_opp}",
        ),
        fold_to_turn_bet=_rate(
            folded_turn_bet_n,
            faced_turn_bet_n,
            f"folded-turn-bet={folded_turn_bet_n} / faced-turn-bet={faced_turn_bet_n}",
        ),
        delayed_cbet_pct=_rate(
            delayed_cbet_n,
            delayed_cbet_opp,
            f"delayed-cbets={delayed_cbet_n} / delayed-cbet-opp={delayed_cbet_opp}",
        ),
        check_raise_pct=_rate(
            check_raise_n,
            check_raise_opp,
            f"check-raises={check_raise_n} / check-raise-opp={check_raise_opp}",
        ),
        aggression_factor=_rate(
            total_bets_raises,
            total_calls,
            f"postflop-bets-raises={total_bets_raises} / postflop-calls={total_calls}",
        ),
    )


def hand_record_from_actions(
    hand_external_id: str,
    player_position: str | None,
    player_stack_bb: Decimal | None,
    player_effective_stack_bb: Decimal | None,
    this_hand_player_id: str,
    all_preflop_actions: list[dict[str, Any]],
    saw_flop: bool,
    reached_showdown: bool,
    won_at_showdown: bool,
    all_postflop_actions: list[dict[str, Any]] | None = None,
) -> HandRecord:
    """
    Build a HandRecord from raw action data.

    This is the conversion layer between DB-sourced action dicts and the pure
    analytics input type. Called by service code, not by stat-computation code.

    Parameters
    ----------
    this_hand_player_id:
        The ``hand_player_id`` (as string) for the player being analysed.
        Used to partition actions into "mine" and "other".
    all_preflop_actions:
        All PREFLOP actions across all players at this hand, each a dict with:
          - ``hand_player_id``: str
          - ``action_type``:    str (ActionType value)
          - ``action_order``:   int (global ordering within the hand)
        Must include actions for all players, not just the hero.
    all_postflop_actions:
        All FLOP/TURN/RIVER actions across all players, each a dict with:
          - ``hand_player_id``: str
          - ``action_type``:    str (ActionType value)
          - ``action_order``:   int (global ordering within the hand)
          - ``street``:         str ("FLOP", "TURN", or "RIVER")
        Optional — omit or pass None to skip postflop flag computation.
        SHOWDOWN-street actions should not be included.
    saw_flop:
        Whether the player saw the flop. Must be supplied externally — requires
        knowing whether the board was dealt to the flop.
    reached_showdown:
        Whether the player reached showdown. Requires action/showdown data.
    won_at_showdown:
        Whether the player won at showdown. Requires HandWinner or net_won data.

    Notes
    -----
    ``three_bet`` definition: player had a 3bet opportunity (someone raised
    before their turn) AND re-raised. This is true for the re-raise regardless
    of whether it was strictly the 3rd aggression (e.g. in a cold-4bet spot it
    would over-count slightly). For standard 6-max tournament hands this is
    acceptable — the error rate is very low.

    ``faced_3bet`` definition: player raised preflop, then another player
    raised after their first raise. This correctly captures open-raiser vs 3bet,
    but will also fire in squeeze spots where multiple players raise. The
    limitation is documented in ``limitations`` fields of any leak using this.
    """
    sorted_pf = sorted(all_preflop_actions, key=lambda a: a["action_order"])
    my_pf = [a for a in sorted_pf if a["hand_player_id"] == this_hand_player_id]
    other_pf = [a for a in sorted_pf if a["hand_player_id"] != this_hand_player_id]

    # VPIP: voluntary chip commitment preflop
    vpip = any(a["action_type"] in _VOLUNTARY_PREFLOP for a in my_pf)

    # PFR: any preflop raise (open, 3bet, 4bet — all count)
    pfr = any(a["action_type"] in _RAISE_TYPES for a in my_pf)

    # Find this player's first non-forced preflop action order
    first_voluntary_order: int | None = None
    for a in my_pf:
        if a["action_type"] not in _POST_TYPES:
            first_voluntary_order = a["action_order"]
            break

    # had_3bet_opportunity: another player raised *before* my first voluntary action
    had_3bet_opportunity = False
    if first_voluntary_order is not None:
        had_3bet_opportunity = any(
            a["action_type"] in _RAISE_TYPES and a["action_order"] < first_voluntary_order
            for a in other_pf
        )

    three_bet = had_3bet_opportunity and pfr

    # faced_3bet / folded_to_3bet: I raised, then someone re-raised after me
    faced_3bet = False
    folded_to_3bet = False
    if pfr:
        first_raise_order: int | None = next(
            (a["action_order"] for a in my_pf if a["action_type"] in _RAISE_TYPES),
            None,
        )
        if first_raise_order is not None:
            # Did another player raise after my first raise?
            faced_3bet = any(
                a["action_type"] in _RAISE_TYPES and a["action_order"] > first_raise_order
                for a in other_pf
            )
            if faced_3bet:
                my_actions_after = [a for a in my_pf if a["action_order"] > first_raise_order]
                folded_to_3bet = any(a["action_type"] == "FOLD" for a in my_actions_after)

    # ── Steal / defend detection ──────────────────────────────────────────────
    # Uses "position" key in action dicts (optional — absent ⇒ None).
    # When positions are missing, all steal flags stay False (safe fallback).

    hero_pos: str | None = player_position

    # Hero's first non-post action (their actual decision)
    hero_first_decision: dict[str, Any] | None = next(
        (a for a in my_pf if a["action_type"] not in _POST_TYPES), None
    )
    hero_first_decision_order: int = (
        hero_first_decision["action_order"] if hero_first_decision is not None else 999_999
    )

    # Other players' actions before hero decides
    others_before_hero = [a for a in other_pf if a["action_order"] < hero_first_decision_order]

    # Steal opportunity: hero in steal position, pot not yet opened
    others_voluntary_before = [
        a for a in others_before_hero if a["action_type"] in _VOLUNTARY_PREFLOP
    ]
    had_steal_opportunity = hero_pos in _STEAL_POSITIONS and len(others_voluntary_before) == 0
    stole = had_steal_opportunity and pfr

    # First raiser among other players before hero acts
    first_raise_before: dict[str, Any] | None = next(
        (a for a in others_before_hero if a["action_type"] in _RAISE_TYPES), None
    )
    first_raiser_pos: str | None = (
        first_raise_before.get("position") if first_raise_before is not None else None
    )

    # Faced steal: in blind position, first raiser was from steal position
    faced_steal = hero_pos in _BLIND_POSITIONS and first_raiser_pos in _STEAL_POSITIONS

    # Hero folded at any point preflop
    hero_folded_pf = any(a["action_type"] == "FOLD" for a in my_pf)

    folded_to_steal = faced_steal and hero_folded_pf
    re_steal_opportunity = faced_steal
    attempted_resteal = faced_steal and pfr

    # Position-specific flags
    folded_bb_to_btn_open = hero_pos == "BB" and first_raiser_pos == "BTN" and hero_folded_pf
    folded_sb_to_btn_open = hero_pos == "SB" and first_raiser_pos == "BTN" and hero_folded_pf
    faced_btn_open_as_bb = hero_pos == "BB" and first_raiser_pos == "BTN"
    faced_co_open_as_bb = hero_pos == "BB" and first_raiser_pos == "CO"

    open_position: str | None = hero_pos if stole else None
    defender_position: str | None = hero_pos if (faced_steal and not folded_to_steal) else None

    # ── Postflop flags ────────────────────────────────────────────────────────
    pf_flags = _compute_postflop_flags(
        pfr=pfr,
        saw_flop=saw_flop,
        hero_id=this_hand_player_id,
        all_postflop_actions=all_postflop_actions or [],
    )

    return HandRecord(
        hand_external_id=hand_external_id,
        position=player_position,
        stack_bb=player_stack_bb,
        effective_stack_bb=player_effective_stack_bb,
        vpip=vpip,
        pfr=pfr,
        had_3bet_opportunity=had_3bet_opportunity,
        three_bet=three_bet,
        faced_3bet=faced_3bet,
        folded_to_3bet=folded_to_3bet,
        saw_flop=saw_flop,
        reached_showdown=reached_showdown,
        won_at_showdown=won_at_showdown,
        had_steal_opportunity=had_steal_opportunity,
        stole=stole,
        faced_steal=faced_steal,
        folded_to_steal=folded_to_steal,
        re_steal_opportunity=re_steal_opportunity,
        attempted_resteal=attempted_resteal,
        folded_bb_to_btn_open=folded_bb_to_btn_open,
        folded_sb_to_btn_open=folded_sb_to_btn_open,
        faced_btn_open_as_bb=faced_btn_open_as_bb,
        faced_co_open_as_bb=faced_co_open_as_bb,
        open_position=open_position,
        defender_position=defender_position,
        **pf_flags,
    )


# ---------------------------------------------------------------------------
# Postflop flag computation
# ---------------------------------------------------------------------------


def _compute_postflop_flags(
    pfr: bool,
    saw_flop: bool,
    hero_id: str,
    all_postflop_actions: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Derive postflop HandRecord boolean flags from the full action sequence.

    Returns a dict keyed by the postflop HandRecord field names.  All values
    default to False/0 when saw_flop=False or no postflop actions are supplied.

    Design notes
    ------------
    - "First bet on a street" means: hero's first action on that street was
      BET/RAISE/ALL_IN AND no other player bet/raised before hero's first action.
    - "Faced a bet" means: another player bet/raised before hero's last action on
      the street (i.e., hero had an opportunity to respond).
    - check-raise detection checks all postflop streets; if the player had the
      opportunity on multiple streets, the result reflects OR across streets.
    - Aggression factor components (postflop_bets_raises, postflop_calls) count
      raw actions across all postflop streets and are aggregated across many hands
      in compute_player_stats to produce the AF ratio.
    """
    result: dict[str, Any] = {
        "cbet_opportunity": False,
        "cbet": False,
        "faced_flop_bet": False,
        "folded_to_flop_bet": False,
        "turn_barrel_opportunity": False,
        "turn_barreled": False,
        "faced_turn_bet": False,
        "folded_to_turn_bet": False,
        "delayed_cbet_opportunity": False,
        "delayed_cbet": False,
        "check_raise_opportunity": False,
        "check_raised": False,
        "postflop_bets_raises": 0,
        "postflop_calls": 0,
    }

    if not saw_flop or not all_postflop_actions:
        return result

    # Group and sort by street
    flop = sorted(
        (a for a in all_postflop_actions if a.get("street") == "FLOP"),
        key=lambda a: a["action_order"],
    )
    turn = sorted(
        (a for a in all_postflop_actions if a.get("street") == "TURN"),
        key=lambda a: a["action_order"],
    )
    river = sorted(
        (a for a in all_postflop_actions if a.get("street") == "RIVER"),
        key=lambda a: a["action_order"],
    )

    hero_flop = [a for a in flop if a["hand_player_id"] == hero_id]
    hero_turn = [a for a in turn if a["hand_player_id"] == hero_id]
    hero_river = [a for a in river if a["hand_player_id"] == hero_id]
    others_flop = [a for a in flop if a["hand_player_id"] != hero_id]
    others_turn = [a for a in turn if a["hand_player_id"] != hero_id]
    others_river = [a for a in river if a["hand_player_id"] != hero_id]

    all_hero_postflop = hero_flop + hero_turn + hero_river

    # ── Aggression factor components ──────────────────────────────────────────
    result["postflop_bets_raises"] = sum(
        1 for a in all_hero_postflop if a["action_type"] in _RAISE_TYPES
    )
    result["postflop_calls"] = sum(1 for a in all_hero_postflop if a["action_type"] == "CALL")

    # ── C-bet ─────────────────────────────────────────────────────────────────
    # Opportunity: hero was PF raiser AND saw flop
    result["cbet_opportunity"] = pfr

    if pfr and hero_flop:
        hero_first_flop_order = hero_flop[0]["action_order"]
        # No other player bet/raised before hero's first flop action
        others_bet_before = any(
            a["action_type"] in _RAISE_TYPES and a["action_order"] < hero_first_flop_order
            for a in others_flop
        )
        if not others_bet_before:
            result["cbet"] = hero_flop[0]["action_type"] in _RAISE_TYPES

    # ── Faced flop bet ────────────────────────────────────────────────────────
    if hero_flop:
        hero_last_flop_order = hero_flop[-1]["action_order"]
        result["faced_flop_bet"] = any(
            a["action_type"] in _RAISE_TYPES and a["action_order"] < hero_last_flop_order
            for a in others_flop
        )
        if result["faced_flop_bet"]:
            result["folded_to_flop_bet"] = hero_flop[-1]["action_type"] == "FOLD"

    # ── Delayed c-bet ─────────────────────────────────────────────────────────
    # Conditions: hero was PF aggressor + did NOT c-bet + flop was check-check + saw turn
    if pfr and not result["cbet"] and hero_flop and hero_turn:
        flop_any_bet = any(a["action_type"] in _RAISE_TYPES for a in flop)
        hero_checked_flop = hero_flop[0]["action_type"] == "CHECK"
        if hero_checked_flop and not flop_any_bet:
            result["delayed_cbet_opportunity"] = True
            hero_first_turn_order = hero_turn[0]["action_order"]
            others_bet_before_turn = any(
                a["action_type"] in _RAISE_TYPES and a["action_order"] < hero_first_turn_order
                for a in others_turn
            )
            if not others_bet_before_turn:
                result["delayed_cbet"] = hero_turn[0]["action_type"] in _RAISE_TYPES

    # ── Turn barrel (double barrel) ────────────────────────────────────────────
    if result["cbet"] and hero_turn:
        result["turn_barrel_opportunity"] = True
        hero_first_turn_order = hero_turn[0]["action_order"]
        others_bet_before_turn = any(
            a["action_type"] in _RAISE_TYPES and a["action_order"] < hero_first_turn_order
            for a in others_turn
        )
        if not others_bet_before_turn:
            result["turn_barreled"] = hero_turn[0]["action_type"] in _RAISE_TYPES

    # ── Faced turn bet ────────────────────────────────────────────────────────
    if hero_turn:
        hero_last_turn_order = hero_turn[-1]["action_order"]
        result["faced_turn_bet"] = any(
            a["action_type"] in _RAISE_TYPES and a["action_order"] < hero_last_turn_order
            for a in others_turn
        )
        if result["faced_turn_bet"]:
            result["folded_to_turn_bet"] = hero_turn[-1]["action_type"] == "FOLD"

    # ── Check-raise (any postflop street) ────────────────────────────────────
    # True if on any street: hero checked → opponent bet → hero raised.
    # OR (opportunity only): hero checked → opponent bet → hero called/folded.
    for hero_street, all_street, others_street in [
        (hero_flop, flop, others_flop),
        (hero_turn, turn, others_turn),
        (hero_river, river, others_river),
    ]:
        if len(hero_street) < 2:
            continue
        first_hero = hero_street[0]
        if first_hero["action_type"] != "CHECK":
            continue
        # Did an opponent bet after hero's check?
        someone_bet_after = any(
            a["action_type"] in _RAISE_TYPES and a["action_order"] > first_hero["action_order"]
            for a in others_street
        )
        if not someone_bet_after:
            continue
        # Hero had at least one more action after the check
        hero_after = [a for a in hero_street if a["action_order"] > first_hero["action_order"]]
        if not hero_after:
            continue
        result["check_raise_opportunity"] = True
        if any(a["action_type"] in _RAISE_TYPES for a in hero_after):
            result["check_raised"] = True
        # Count at most one check-raise opportunity per hand
        break

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _rate(
    numerator: int,
    denominator: int,
    source: str,
) -> LabeledMetric[Decimal | None]:
    """
    Compute a frequency rate as a labeled INFERRED metric.

    Returns INFERRED(None, n=0) when denominator is zero.
    Sets a confidence note when n < 20 (below ``is_reliable()`` threshold).
    """
    if denominator == 0:
        return inferred(
            None,
            source=source,
            n=0,
            confidence_note="no eligible hands in sample",
        )
    value = (Decimal(numerator) / Decimal(denominator)).quantize(
        _FOUR_PLACES, rounding=ROUND_HALF_UP
    )
    if denominator < 5:
        note = f"very low — only {denominator} eligible hand(s)"
    elif denominator < 20:
        note = f"low — only {denominator} eligible hands (< 20)"
    else:
        note = ""
    return inferred(value, source=source, n=denominator, confidence_note=note)


def _compute_positional(hands: Sequence[HandRecord]) -> dict[str, PositionalStats]:
    """
    Group hands by position and compute per-position stats.

    Hands with position=None are excluded — their absence is correct, not zero.
    """
    groups: dict[str, list[HandRecord]] = defaultdict(list)
    for h in hands:
        if h.position is not None:
            groups[h.position].append(h)

    result: dict[str, PositionalStats] = {}
    for position, pos_hands in groups.items():
        n = len(pos_hands)
        steal_opp_pos = sum(1 for h in pos_hands if h.had_steal_opportunity)
        steals_pos = sum(1 for h in pos_hands if h.stole)
        faced_steal_pos = sum(1 for h in pos_hands if h.faced_steal)
        folded_steal_pos = sum(1 for h in pos_hands if h.folded_to_steal)
        result[position] = PositionalStats(
            position=position,
            n_hands=n,
            vpip=_rate(
                sum(1 for h in pos_hands if h.vpip),
                n,
                f"vpip from {position} (n={n})",
            ),
            pfr=_rate(
                sum(1 for h in pos_hands if h.pfr),
                n,
                f"pfr from {position} (n={n})",
            ),
            three_bet_pct=_rate(
                sum(1 for h in pos_hands if h.three_bet),
                sum(1 for h in pos_hands if h.had_3bet_opportunity),
                f"3bet% from {position}",
            ),
            fold_to_3bet=_rate(
                sum(1 for h in pos_hands if h.folded_to_3bet),
                sum(1 for h in pos_hands if h.faced_3bet),
                f"fold-to-3bet from {position}",
            ),
            steal_pct=_rate(
                steals_pos,
                steal_opp_pos,
                f"steal% from {position}",
            ),
            fold_to_steal=_rate(
                folded_steal_pos,
                faced_steal_pos,
                f"fold-to-steal from {position}",
            ),
        )

    return result

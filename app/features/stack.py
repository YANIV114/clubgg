"""
Stack normalization features.

All outputs are DERIVED — computed from OBSERVED chip counts and OBSERVED
blind sizes with no inferential step.

Definitions
-----------
stack_bb:
    A player's chip stack expressed in big blinds.
    stack_bb = chips / bb_size

effective_stack_bb:
    The relevant stack depth for a given confrontation.
    In a heads-up pot: min(hero_stack_bb, villain_stack_bb).
    Multi-way: min(hero_stack_bb, second_deepest_active_stack_bb).
    This is the maximum amount that can change hands.

spr (stack-to-pot ratio):
    effective_stack_bb / pot_bb at the start of a given street.
    Useful for postflop commitment decisions.
    SPR < 1: trivially committed.
    SPR 1–4: strong draws / sets often commit.
    SPR > 10: speculative; implied-odds territory.

pot_bb:
    Pot size expressed in big blinds.

m_ratio:
    Total chips / (SB + BB + antes_per_hand).
    Useful for tournament push-fold pressure.
    M < 5: push-fold zone; M 5–10: danger zone; M > 20: healthy.
    Note: Only meaningful in tournament context. Returns None in cash.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from app.features.labels import LabeledMetric, derived, speculative

_ZERO = Decimal("0")
_ONE = Decimal("1")
_QUANTIZE_2 = Decimal("0.01")
_QUANTIZE_1 = Decimal("0.1")


def _q(value: Decimal, places: str = "0.01") -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def stack_bb(
    chips: Decimal,
    bb_size: Decimal,
) -> LabeledMetric[Decimal]:
    """
    Express a chip stack in big blinds.

    Parameters
    ----------
    chips:    Chip count (must be >= 0).
    bb_size:  The big blind size in chips (must be > 0).
    """
    if bb_size <= _ZERO:
        raise ValueError(f"bb_size must be > 0, got {bb_size}")
    if chips < _ZERO:
        raise ValueError(f"chips must be >= 0, got {chips}")
    value = _q(chips / bb_size)
    return derived(
        value,
        source=f"chips ({chips}) / bb_size ({bb_size})",
    )


def effective_stack_bb(
    hero_stack_bb: Decimal,
    other_stacks_bb: list[Decimal],
) -> LabeledMetric[Decimal]:
    """
    Compute the effective stack in BB for a confrontation.

    In a heads-up pot (one opponent), this is min(hero, villain).
    Multi-way: min(hero, deepest_opponent).

    The 'deepest opponent' model is used rather than the shallowest because
    effective depth is constrained by the shortest stack only in the specific
    all-in sub-pot; for decision-making we care about how much can change hands
    if everyone is in, which is bound by the second-deepest stack.

    If other_stacks_bb is empty, returns hero_stack_bb (no opponents).
    """
    if not other_stacks_bb:
        return derived(
            _q(hero_stack_bb),
            source="no opponents — effective stack = hero stack",
        )
    deepest_opponent = max(other_stacks_bb)
    value = _q(min(hero_stack_bb, deepest_opponent))
    return derived(
        value,
        source=f"min(hero {hero_stack_bb:.2f}bb, deepest_opp {deepest_opponent:.2f}bb)",
    )


def spr(
    effective_stack_bb_value: Decimal,
    pot_bb_value: Decimal,
) -> LabeledMetric[Decimal]:
    """
    Stack-to-pot ratio at a given decision point.

    effective_stack_bb_value: remaining effective stack in BB at this decision.
    pot_bb_value: total pot in BB before this decision.

    Returns None-valued metric if pot is zero (pre-action street start).
    """
    if pot_bb_value <= _ZERO:
        return derived(
            Decimal("0"),
            source="pot_bb is zero — SPR undefined",
        )
    value = _q(effective_stack_bb_value / pot_bb_value)
    return derived(
        value,
        source=f"eff_stack ({effective_stack_bb_value:.2f}bb) / pot ({pot_bb_value:.2f}bb)",
    )


def pot_bb(
    pot_chips: Decimal,
    bb_size: Decimal,
) -> LabeledMetric[Decimal]:
    """Pot size expressed in big blinds."""
    if bb_size <= _ZERO:
        raise ValueError(f"bb_size must be > 0, got {bb_size}")
    value = _q(pot_chips / bb_size)
    return derived(value, source=f"pot_chips ({pot_chips}) / bb_size ({bb_size})")


def m_ratio(
    total_chips: Decimal,
    sb_size: Decimal,
    bb_size: Decimal,
    ante_per_hand: Decimal = _ZERO,
    players_at_table: int = 1,
) -> LabeledMetric[Decimal]:
    """
    Harrington M-ratio for tournament stack pressure.

    total_chips:     Player's current chip count.
    sb_size:         Small blind size.
    bb_size:         Big blind size.
    ante_per_hand:   Total antes posted per hand (all players combined).
    players_at_table: Number of players currently at the table
                      (used to estimate ante contribution per orbit).

    Returned label:
      DERIVED when all inputs are OBSERVED data.

    Note: M is only meaningful in tournament context.
    In a cash game, a large M just means the player has a healthy stack.
    """
    orbit_cost = sb_size + bb_size + ante_per_hand
    if orbit_cost <= _ZERO:
        raise ValueError("orbit cost (SB + BB + antes) must be > 0")
    value = _q(total_chips / orbit_cost, "0.1")
    return derived(
        value,
        source=(
            f"chips ({total_chips}) / orbit_cost "
            f"(sb={sb_size} + bb={bb_size} + ante={ante_per_hand} = {orbit_cost})"
        ),
    )


def bet_size_bb(
    bet_amount: Decimal,
    bb_size: Decimal,
) -> LabeledMetric[Decimal]:
    """Bet/raise/call size in big blinds."""
    if bb_size <= _ZERO:
        raise ValueError(f"bb_size must be > 0, got {bb_size}")
    value = _q(bet_amount / bb_size)
    return derived(value, source=f"bet ({bet_amount}) / bb ({bb_size})")


def bet_size_pct(
    bet_amount: Decimal,
    pot_before_bet: Decimal,
) -> LabeledMetric[Decimal]:
    """
    Bet size as a fraction of pot (0.0 – 1.0+).
    Useful for sizing pattern analysis.
    Returns 0 if pot is zero.
    """
    if pot_before_bet <= _ZERO:
        return derived(Decimal("0"), source="pot is zero — sizing pct undefined")
    value = _q(bet_amount / pot_before_bet)
    return derived(
        value,
        source=f"bet ({bet_amount}) / pot ({pot_before_bet})",
    )

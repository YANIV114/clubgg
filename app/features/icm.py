"""
ICM (Independent Chip Model) interface and implementations.

ICM converts chip counts into equity share of the prize pool. It is
critical for tournament decisions near the bubble, at final tables, and
in satellites.

Architecture
------------
``ICMCalculator`` is a Protocol — any conforming class can be injected.
``NullICMCalculator`` is the default fallback when payout structure or
chip counts are unavailable (common with ClubGG data that does not include
tournament registration/payout data).

All outputs from this module are labeled SPECULATIVE unless:
  - The payout structure is confirmed from a reliable source (not inferred).
  - All remaining chip stacks are known.
Even then, ICM assumes chip-EV linearity within stacks, which is only an
approximation of real tournament equity.

Limitations (always included in output):
  - ICM ignores skill edge between players.
  - ICM ignores blind pressure asymmetry.
  - ICM is inaccurate in very short-handed situations (2–3 players left).
  - ChipEV and ICMEV diverge most dramatically near the bubble.

Usage
-----
    calc = NullICMCalculator()  # safe no-op default
    equity = calc.equity(my_chips=50000, all_stacks=[50000, 30000, 20000], payouts=[...])
    # equity.label == SPECULATIVE; equity.value == None

    # Or with a real implementation:
    calc = IndyChipModelCalculator()
    equity = calc.equity(...)
    # equity.label == SPECULATIVE unless payouts are confirmed
"""
from __future__ import annotations

from decimal import Decimal
from typing import Protocol, runtime_checkable

from app.features.labels import LabeledMetric, speculative


_NULL_CONFIDENCE = (
    "NullICMCalculator — payout structure not available from ClubGG data. "
    "Inject a real ICMCalculator with confirmed payouts to get meaningful output."
)

_GENERAL_LIMITATIONS = (
    "ICM ignores skill edge, blind asymmetry, and short-handed inaccuracy. "
    "Treat as approximation only."
)


@runtime_checkable
class ICMCalculator(Protocol):
    """
    Protocol for ICM equity calculators.

    Implementations must return labeled outputs; the label must reflect
    whether the payout structure was confirmed (speculative if inferred
    or absent).
    """

    def equity(
        self,
        my_chips: Decimal,
        all_stacks: list[Decimal],
        payouts: list[Decimal],
    ) -> LabeledMetric[Decimal | None]:
        """
        Compute this player's ICM equity as a fraction of total prize pool.

        Parameters
        ----------
        my_chips:
            This player's current chip count.
        all_stacks:
            Chip counts of ALL remaining players including this player.
            Sum must be consistent (ClubGG chip counts may not sum perfectly
            due to rounding; implementations should be tolerant).
        payouts:
            Prize amounts for each finishing position (1st, 2nd, ...).
            Must be in descending order. Length determines the payout spots.

        Returns
        -------
        LabeledMetric[Decimal | None]
            equity.value: fraction of total prize pool (0.0–1.0), or None
            if calculation was not possible.
            equity.label: always SPECULATIVE unless a subclass overrides
            this with confirmed-data logic.
        """
        ...

    def pressure_factor(
        self,
        my_chips: Decimal,
        all_stacks: list[Decimal],
        payouts: list[Decimal],
        pot_size: Decimal,
    ) -> LabeledMetric[Decimal | None]:
        """
        ICM pressure: ratio of calling_ev_icm / calling_ev_chips.
        Values < 1 indicate ICM penalty for calling; < 0.7 means heavy pressure.

        Returns None if ICM calculation is not available.
        """
        ...


class NullICMCalculator:
    """
    Safe fallback when payout structure is unavailable.

    Always returns None-valued SPECULATIVE metrics with an explicit note
    explaining why. This is the correct behavior — returning a fake number
    would violate the "do not fake precision" principle.
    """

    def equity(
        self,
        my_chips: Decimal,
        all_stacks: list[Decimal],
        payouts: list[Decimal],
    ) -> LabeledMetric[Decimal | None]:
        return speculative(
            value=None,
            source="NullICMCalculator",
            confidence_note=_NULL_CONFIDENCE,
        )

    def pressure_factor(
        self,
        my_chips: Decimal,
        all_stacks: list[Decimal],
        payouts: list[Decimal],
        pot_size: Decimal,
    ) -> LabeledMetric[Decimal | None]:
        return speculative(
            value=None,
            source="NullICMCalculator",
            confidence_note=_NULL_CONFIDENCE,
        )


class SimpleICMCalculator:
    """
    Basic recursive ICM calculator (Malmuth-Harville model).

    Produces SPECULATIVE output because:
      1. ClubGG hand histories do not include confirmed payout structures.
         Callers must supply payouts from an external confirmed source.
      2. The Malmuth-Harville model is an approximation; accuracy degrades
         in short-handed spots and with large chip-count disparities.

    For satellite calculations (where ICM equity is binary: make-it or bust),
    use SatelliteICMCalculator instead (not yet implemented — interface defined).

    Computational complexity: O(n! / (n-k)!) where n = players, k = payout spots.
    Not suitable for n > 9 without memoization. Use for final table analysis only.
    """

    def equity(
        self,
        my_chips: Decimal,
        all_stacks: list[Decimal],
        payouts: list[Decimal],
    ) -> LabeledMetric[Decimal | None]:
        if not payouts or not all_stacks:
            return speculative(
                value=None,
                source="SimpleICMCalculator",
                confidence_note="empty payouts or stacks",
            )
        if my_chips not in all_stacks:
            # Guard: require caller to include my_chips in all_stacks
            return speculative(
                value=None,
                source="SimpleICMCalculator",
                confidence_note="my_chips not found in all_stacks",
            )

        total = sum(all_stacks)
        if total <= Decimal("0"):
            return speculative(value=None, source="SimpleICMCalculator", confidence_note="zero total chips")

        equities = _icm_recursive(all_stacks, payouts)
        my_index = all_stacks.index(my_chips)
        my_equity = equities[my_index]
        total_prize = sum(payouts)
        equity_fraction = my_equity / total_prize if total_prize > 0 else Decimal("0")

        return speculative(
            value=equity_fraction.quantize(Decimal("0.0001")),
            source="Malmuth-Harville ICM model",
            confidence_note=_GENERAL_LIMITATIONS,
        )

    def pressure_factor(
        self,
        my_chips: Decimal,
        all_stacks: list[Decimal],
        payouts: list[Decimal],
        pot_size: Decimal,
    ) -> LabeledMetric[Decimal | None]:
        """
        Simplified ICM pressure factor.
        Compares chip-EV call vs ICM-EV call on a binary all-in.
        This is an approximation; a full calculation requires win probability.
        Returns None — a full implementation requires equity vs hand range.
        """
        return speculative(
            value=None,
            source="SimpleICMCalculator.pressure_factor",
            confidence_note=(
                "Pressure factor requires win probability vs opponent range. "
                "Not computable without range model. " + _GENERAL_LIMITATIONS
            ),
        )


def _icm_recursive(
    stacks: list[Decimal],
    payouts: list[Decimal],
    _cache: dict | None = None,
) -> list[Decimal]:
    """
    Recursive Malmuth-Harville ICM.
    Returns a list of expected prize amounts for each player (same order as stacks).
    """
    if _cache is None:
        _cache = {}

    key = (tuple(stacks), tuple(payouts))
    if key in _cache:
        return _cache[key]

    n = len(stacks)
    total = sum(stacks)
    result = [Decimal("0")] * n

    if not payouts or total == Decimal("0"):
        _cache[key] = result
        return result

    payout = payouts[0]
    remaining_payouts = payouts[1:]

    for i in range(n):
        if stacks[i] == Decimal("0"):
            continue
        # Probability this player finishes 1st
        p_first = stacks[i] / total
        # Recurse: remove player i, recalculate for remaining spots
        sub_stacks = stacks[:i] + [Decimal("0")] + stacks[i + 1:]
        # Filter zeros for the recursive call but maintain index alignment
        non_zero_indices = [j for j, s in enumerate(sub_stacks) if s > Decimal("0")]
        if remaining_payouts and non_zero_indices:
            sub_result_filtered = _icm_recursive(
                [sub_stacks[j] for j in non_zero_indices],
                remaining_payouts,
                _cache,
            )
            sub_result = [Decimal("0")] * n
            for idx, orig_idx in enumerate(non_zero_indices):
                sub_result[orig_idx] = sub_result_filtered[idx]
        else:
            sub_result = [Decimal("0")] * n

        result[i] += p_first * payout
        for j in range(n):
            if j != i:
                result[j] += p_first * sub_result[j]

    _cache[key] = result
    return result

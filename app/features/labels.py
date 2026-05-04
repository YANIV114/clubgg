"""
Metric labeling system.

Every piece of output from the analytics pipeline must carry a MetricLabel.
This is enforced by wrapping values in LabeledMetric rather than passing
raw numbers through analysis functions.

Labels:
  OBSERVED   — directly present in raw source data (hand history, API)
  DERIVED    — computed from observed data with no inferential step
               (e.g. stack_bb = chips / bb_size)
  INFERRED   — estimated from observed patterns with meaningful uncertainty
               (e.g. opponent fold-to-3bet% from a small sample)
  SPECULATIVE — output that depends on unverified assumptions or very thin data
               (e.g. ICM equity without a confirmed payout structure)

Usage:
    stack_bb: LabeledMetric[Decimal] = LabeledMetric(
        value=Decimal("22.5"),
        label=MetricLabel.DERIVED,
        source="stack / bb_size",
    )
"""
from __future__ import annotations

import dataclasses
from enum import StrEnum
from typing import Generic, TypeVar

T = TypeVar("T")


class MetricLabel(StrEnum):
    OBSERVED = "observed"
    DERIVED = "derived"
    INFERRED = "inferred"
    SPECULATIVE = "speculative"


@dataclasses.dataclass(frozen=True)
class LabeledMetric(Generic[T]):
    """
    A value with its epistemic label and an optional human-readable source note.

    ``source`` should describe how the value was produced in plain language,
    not a code reference. Example: "starting_stack / bb_size" or
    "3-bet count / total facing-3bet situations (n=12)".
    """

    value: T
    label: MetricLabel
    source: str = ""
    # Optional: attach a sample size when relevant (for INFERRED/SPECULATIVE)
    n: int | None = None
    # Optional: attach a confidence note (e.g. "low — fewer than 20 samples")
    confidence_note: str = ""

    def is_reliable(self, min_n: int = 20) -> bool:
        """
        Returns True if this metric is OBSERVED or DERIVED, or if it is
        INFERRED/SPECULATIVE with a sample size >= min_n.
        """
        if self.label in (MetricLabel.OBSERVED, MetricLabel.DERIVED):
            return True
        if self.n is not None:
            return self.n >= min_n
        return False

    def __repr__(self) -> str:
        n_str = f" n={self.n}" if self.n is not None else ""
        note_str = f" ({self.confidence_note})" if self.confidence_note else ""
        return f"LabeledMetric({self.value!r} [{self.label}{n_str}]{note_str})"


def observed(value: T, source: str = "") -> LabeledMetric[T]:
    return LabeledMetric(value=value, label=MetricLabel.OBSERVED, source=source)


def derived(value: T, source: str = "") -> LabeledMetric[T]:
    return LabeledMetric(value=value, label=MetricLabel.DERIVED, source=source)


def inferred(value: T, source: str = "", n: int | None = None, confidence_note: str = "") -> LabeledMetric[T]:
    return LabeledMetric(
        value=value,
        label=MetricLabel.INFERRED,
        source=source,
        n=n,
        confidence_note=confidence_note,
    )


def speculative(value: T, source: str = "", confidence_note: str = "") -> LabeledMetric[T]:
    return LabeledMetric(
        value=value,
        label=MetricLabel.SPECULATIVE,
        source=source,
        confidence_note=confidence_note,
    )

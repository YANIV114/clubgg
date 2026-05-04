"""Tests for the metric labeling system."""
from decimal import Decimal

import pytest

from app.features.labels import (
    LabeledMetric,
    MetricLabel,
    derived,
    inferred,
    observed,
    speculative,
)


class TestMetricLabel:
    def test_enum_values(self) -> None:
        assert MetricLabel.OBSERVED == "observed"
        assert MetricLabel.DERIVED == "derived"
        assert MetricLabel.INFERRED == "inferred"
        assert MetricLabel.SPECULATIVE == "speculative"


class TestLabeledMetric:
    def test_observed_factory(self) -> None:
        m = observed(42, source="raw hand data")
        assert m.value == 42
        assert m.label == MetricLabel.OBSERVED
        assert m.source == "raw hand data"

    def test_derived_factory(self) -> None:
        m = derived(Decimal("22.5"), source="chips / bb_size")
        assert m.value == Decimal("22.5")
        assert m.label == MetricLabel.DERIVED

    def test_inferred_factory(self) -> None:
        m = inferred(Decimal("0.65"), source="fold-to-3bet", n=15, confidence_note="low n")
        assert m.label == MetricLabel.INFERRED
        assert m.n == 15
        assert m.confidence_note == "low n"

    def test_speculative_factory(self) -> None:
        m = speculative(None, source="NullICM", confidence_note="no payout data")
        assert m.label == MetricLabel.SPECULATIVE
        assert m.value is None

    def test_is_reliable_observed(self) -> None:
        assert observed(1).is_reliable() is True

    def test_is_reliable_derived(self) -> None:
        assert derived(1).is_reliable() is True

    def test_is_reliable_inferred_high_n(self) -> None:
        m = inferred(0.5, n=50)
        assert m.is_reliable(min_n=20) is True

    def test_is_reliable_inferred_low_n(self) -> None:
        m = inferred(0.5, n=10)
        assert m.is_reliable(min_n=20) is False

    def test_is_reliable_speculative_no_n(self) -> None:
        m = speculative(0.5)
        assert m.is_reliable() is False

    def test_frozen(self) -> None:
        m = observed(1)
        with pytest.raises(AttributeError):
            m.value = 2  # type: ignore[misc]

    def test_repr_includes_label(self) -> None:
        m = derived(Decimal("10"), source="test")
        assert "derived" in repr(m)
        assert "10" in repr(m)

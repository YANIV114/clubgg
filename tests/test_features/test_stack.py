"""Tests for stack normalization features."""
from decimal import Decimal

import pytest

from app.features.labels import MetricLabel
from app.features.stack import (
    bet_size_bb,
    bet_size_pct,
    effective_stack_bb,
    m_ratio,
    pot_bb,
    spr,
    stack_bb,
)


class TestStackBb:
    def test_basic(self) -> None:
        result = stack_bb(Decimal("100"), Decimal("2"))
        assert result.value == Decimal("50.00")
        assert result.label == MetricLabel.DERIVED

    def test_fractional(self) -> None:
        result = stack_bb(Decimal("150"), Decimal("4"))
        assert result.value == Decimal("37.50")

    def test_zero_chips(self) -> None:
        result = stack_bb(Decimal("0"), Decimal("2"))
        assert result.value == Decimal("0.00")

    def test_zero_bb_raises(self) -> None:
        with pytest.raises(ValueError):
            stack_bb(Decimal("100"), Decimal("0"))

    def test_negative_chips_raises(self) -> None:
        with pytest.raises(ValueError):
            stack_bb(Decimal("-10"), Decimal("2"))

    def test_rounding(self) -> None:
        # 100 / 3 = 33.333... → rounds to 33.33
        result = stack_bb(Decimal("100"), Decimal("3"))
        assert result.value == Decimal("33.33")

    def test_source_present(self) -> None:
        result = stack_bb(Decimal("200"), Decimal("2"))
        assert "200" in result.source
        assert "2" in result.source


class TestEffectiveStackBb:
    def test_hero_is_short(self) -> None:
        result = effective_stack_bb(Decimal("20"), [Decimal("50"), Decimal("30")])
        assert result.value == Decimal("20.00")

    def test_hero_is_deep(self) -> None:
        result = effective_stack_bb(Decimal("100"), [Decimal("40"), Decimal("30")])
        assert result.value == Decimal("40.00")

    def test_equal_stacks(self) -> None:
        result = effective_stack_bb(Decimal("50"), [Decimal("50")])
        assert result.value == Decimal("50.00")

    def test_no_opponents(self) -> None:
        result = effective_stack_bb(Decimal("75"), [])
        assert result.value == Decimal("75.00")

    def test_label_is_derived(self) -> None:
        result = effective_stack_bb(Decimal("20"), [Decimal("30")])
        assert result.label == MetricLabel.DERIVED


class TestSpr:
    def test_basic(self) -> None:
        result = spr(Decimal("100"), Decimal("10"))
        assert result.value == Decimal("10.00")

    def test_committed_spr(self) -> None:
        result = spr(Decimal("8"), Decimal("20"))
        assert result.value == Decimal("0.40")

    def test_zero_pot(self) -> None:
        result = spr(Decimal("50"), Decimal("0"))
        assert result.value == Decimal("0")


class TestPotBb:
    def test_basic(self) -> None:
        result = pot_bb(Decimal("50"), Decimal("2"))
        assert result.value == Decimal("25.00")

    def test_label(self) -> None:
        assert pot_bb(Decimal("10"), Decimal("1")).label == MetricLabel.DERIVED


class TestMRatio:
    def test_healthy_stack(self) -> None:
        result = m_ratio(
            total_chips=Decimal("50000"),
            sb_size=Decimal("500"),
            bb_size=Decimal("1000"),
            ante_per_hand=Decimal("0"),
        )
        # orbit = 1500, M = 50000/1500 ≈ 33.3
        assert result.value > Decimal("30")
        assert result.label == MetricLabel.DERIVED

    def test_push_fold_zone(self) -> None:
        result = m_ratio(
            total_chips=Decimal("7000"),
            sb_size=Decimal("500"),
            bb_size=Decimal("1000"),
            ante_per_hand=Decimal("1000"),
        )
        # orbit = 2500, M = 7000/2500 = 2.8 → push-fold
        assert result.value < Decimal("5")

    def test_zero_orbit_cost_raises(self) -> None:
        with pytest.raises(ValueError):
            m_ratio(Decimal("5000"), Decimal("0"), Decimal("0"))


class TestBetSizeBb:
    def test_basic(self) -> None:
        result = bet_size_bb(Decimal("6"), Decimal("2"))
        assert result.value == Decimal("3.00")

    def test_label(self) -> None:
        assert bet_size_bb(Decimal("4"), Decimal("1")).label == MetricLabel.DERIVED


class TestBetSizePct:
    def test_half_pot(self) -> None:
        result = bet_size_pct(Decimal("5"), Decimal("10"))
        assert result.value == Decimal("0.50")

    def test_overbet(self) -> None:
        result = bet_size_pct(Decimal("15"), Decimal("10"))
        assert result.value == Decimal("1.50")

    def test_zero_pot(self) -> None:
        result = bet_size_pct(Decimal("5"), Decimal("0"))
        assert result.value == Decimal("0")

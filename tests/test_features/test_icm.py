"""Tests for ICM interface and implementations."""
from decimal import Decimal

import pytest

from app.features.icm import NullICMCalculator, SimpleICMCalculator, ICMCalculator
from app.features.labels import MetricLabel


class TestNullICMCalculator:
    def test_equity_returns_none(self) -> None:
        calc = NullICMCalculator()
        result = calc.equity(
            my_chips=Decimal("1000"),
            all_stacks=[Decimal("1000"), Decimal("1000"), Decimal("1000")],
            payouts=[Decimal("500"), Decimal("300"), Decimal("200")],
        )
        assert result.value is None
        assert result.label == MetricLabel.SPECULATIVE

    def test_pressure_returns_none(self) -> None:
        calc = NullICMCalculator()
        result = calc.pressure_factor(
            my_chips=Decimal("1000"),
            all_stacks=[Decimal("1000"), Decimal("2000")],
            payouts=[Decimal("500"), Decimal("300")],
            pot_size=Decimal("200"),
        )
        assert result.value is None
        assert result.label == MetricLabel.SPECULATIVE

    def test_confidence_note_present(self) -> None:
        calc = NullICMCalculator()
        result = calc.equity(Decimal("1000"), [Decimal("1000")], [Decimal("1000")])
        assert result.confidence_note  # not empty

    def test_conforms_to_protocol(self) -> None:
        calc = NullICMCalculator()
        assert isinstance(calc, ICMCalculator)


class TestSimpleICMCalculator:
    def test_equal_stacks_equal_equity(self) -> None:
        """With equal stacks and a single payout spot, all players have equal equity."""
        calc = SimpleICMCalculator()
        stacks = [Decimal("1000"), Decimal("1000"), Decimal("1000")]
        payouts = [Decimal("900")]  # winner take all, one prize
        result = calc.equity(
            my_chips=Decimal("1000"),
            all_stacks=stacks,
            payouts=payouts,
        )
        # Each player has 1/3 chance of winning
        assert result.value is not None
        assert abs(result.value - Decimal("0.3333")) < Decimal("0.001")

    def test_chip_leader_has_more_equity(self) -> None:
        calc = SimpleICMCalculator()
        stacks = [Decimal("5000"), Decimal("3000"), Decimal("2000")]
        payouts = [Decimal("600"), Decimal("300"), Decimal("100")]
        big_stack = calc.equity(Decimal("5000"), stacks, payouts)
        small_stack = calc.equity(Decimal("2000"), stacks, payouts)
        assert big_stack.value is not None
        assert small_stack.value is not None
        assert big_stack.value > small_stack.value

    def test_equity_sums_to_one_approximately(self) -> None:
        calc = SimpleICMCalculator()
        stacks = [Decimal("4000"), Decimal("3000"), Decimal("2000"), Decimal("1000")]
        payouts = [Decimal("500"), Decimal("300"), Decimal("200")]
        total_prize = sum(payouts)
        total_equity = Decimal("0")
        for s in stacks:
            result = calc.equity(s, stacks, payouts)
            assert result.value is not None
            total_equity += result.value * total_prize
        assert abs(total_equity - total_prize) < Decimal("0.01")

    def test_label_is_speculative(self) -> None:
        calc = SimpleICMCalculator()
        result = calc.equity(
            Decimal("1000"),
            [Decimal("1000"), Decimal("2000")],
            [Decimal("300"), Decimal("200")],
        )
        assert result.label == MetricLabel.SPECULATIVE

    def test_empty_payouts_returns_none(self) -> None:
        calc = SimpleICMCalculator()
        result = calc.equity(Decimal("1000"), [Decimal("1000")], [])
        assert result.value is None

    def test_my_chips_not_in_stacks(self) -> None:
        calc = SimpleICMCalculator()
        result = calc.equity(
            Decimal("9999"),
            [Decimal("1000"), Decimal("2000")],
            [Decimal("300")],
        )
        assert result.value is None

    def test_conforms_to_protocol(self) -> None:
        calc = SimpleICMCalculator()
        assert isinstance(calc, ICMCalculator)

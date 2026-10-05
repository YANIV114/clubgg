"""Tests for leak_finder — per-hand analysis results → behavioral leaks."""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.analysis.hand_analysis_engine import HandAnalysisResult
from app.analysis.leak_finder import AnalyzedHandRecord, find_leaks
from app.features.labels import MetricLabel


def _rec(spot: str, action: str, severity: str) -> AnalyzedHandRecord:
    return AnalyzedHandRecord(
        hand_external_id=f"h{uuid.uuid4().hex[:8]}",
        result=HandAnalysisResult(
            spot_type=spot,
            hero_action=action,
            recommended_action="shove all-in or fold",
            mistake_severity=severity,
            explanation="",
            key_factors=[],
            confidence=MetricLabel.INFERRED,
            ev_label="-EV",
            backing="range-based estimate",
        ),
        position="SB",
        stack_bb=Decimal("11"),
    )


def _flat_call_leak(n_mistakes: int, n_total: int):
    records = [_rec("push_fold", "called 1.5bb", "major")] * n_mistakes + [
        _rec("push_fold", "folded", "none")
    ] * (n_total - n_mistakes)
    report = find_leaks(records, uuid.uuid4())
    return next((lk for lk in report.leaks if lk.leak_id == "flat-calling-short-stack"), None)


class TestFlatCallingShortStack:
    def test_rare_flat_calls_are_not_critical(self):
        # 6 of 176 spots (3%) is a real but infrequent mistake.
        leak = _flat_call_leak(6, 176)
        assert leak is not None
        assert leak.severity != "critical"

    def test_frequent_flat_calls_are_critical(self):
        leak = _flat_call_leak(10, 50)
        assert leak is not None
        assert leak.severity == "critical"

    def test_single_flat_call_not_reported(self):
        assert _flat_call_leak(1, 50) is None

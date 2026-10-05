"""Tests for per-tournament summaries and phase breakdown (app.features.tournaments)."""

from __future__ import annotations

import dataclasses
import uuid
from decimal import Decimal

from app.features.tournaments import compute_tournaments, format_hint
from tests.test_features.test_tournament_leaks import _record


def _r(tid="T1", level=3, net=0.0, busted=False, vpip=False, pfr=False, name="Daily NLH"):
    return dataclasses.replace(
        _record(50, vpip=vpip, pfr=pfr),
        tournament_id=tid,
        tournament_name=name,
        blind_level=level,
        net_bb=Decimal(str(net)),
        busted=busted,
    )


def _t(res, tid):
    return next(t for t in res.tournaments if t.tournament_id == tid)


class TestTournamentSummary:
    def test_hands_levels_and_result(self):
        res = compute_tournaments(uuid.uuid4(), [_r(level=2, net=5), _r(level=9, net=-2)])
        t = _t(res, "T1")
        assert t.hands == 2
        assert (t.first_level, t.last_level) == (2, 9)
        assert t.total_bb == Decimal("3.0")

    def test_single_entry_no_bust(self):
        t = _t(compute_tournaments(uuid.uuid4(), [_r(), _r()]), "T1")
        assert (t.entries, t.busts, t.ended_busted) == (1, 0, False)

    def test_bust_then_reentry(self):
        recs = [_r(), _r(busted=True), _r(), _r(busted=True)]
        t = _t(compute_tournaments(uuid.uuid4(), recs), "T1")
        assert t.entries == 2
        assert t.busts == 2
        assert t.ended_busted is True

    def test_newest_tournament_first(self):
        res = compute_tournaments(uuid.uuid4(), [_r(tid="OLD"), _r(tid="NEW")])
        assert [t.tournament_id for t in res.tournaments] == ["NEW", "OLD"]

    def test_hands_without_tournament_counted_not_listed(self):
        res = compute_tournaments(uuid.uuid4(), [_r(), _r(tid=None)])
        assert res.hands_without_tournament == 1
        assert [t.tournament_id for t in res.tournaments] == ["T1"]


class TestFormatHint:
    def test_reentry(self):
        assert format_hint("200K GTD ♠ FROZEN THRONE HR ♠ RE") == "re-entry"

    def test_bounty(self):
        assert format_hint("Wednesday KO Main Event") == "bounty"
        assert format_hint("Sunday PKO") == "bounty"

    def test_satellite(self):
        assert format_hint("Main Event SAT") == "satellite"

    def test_unknown(self):
        assert format_hint("880 DAILY OVERLAY") is None

    def test_no_false_match_inside_words(self):
        # "RE" inside "FREEZE" or "KO" inside "KOBE" must not match.
        assert format_hint("FREEZEOUT KOBE CUP") is None


class TestPhases:
    def test_phase_buckets_by_level(self):
        recs = [_r(level=1), _r(level=6), _r(level=7), _r(level=13), _r(level=25)]
        res = compute_tournaments(uuid.uuid4(), recs)
        assert [(p.label, p.hands) for p in res.phases] == [
            ("Early (levels 1–6)", 2),
            ("Middle (levels 7–12)", 1),
            ("Late (level 13+)", 2),
        ]

    def test_phase_has_play_stats_and_result(self):
        recs = [_r(level=2, vpip=True, pfr=True, net=1)] + [_r(level=2, net=-1)] * 3
        early = compute_tournaments(uuid.uuid4(), recs).phases[0]
        assert early.vpip.value == Decimal("0.2500")
        assert early.pfr.value == Decimal("0.2500")
        assert early.bb_per_100.n == 4

    def test_unknown_level_excluded_from_phases(self):
        res = compute_tournaments(uuid.uuid4(), [_r(level=None), _r(level=3)])
        assert sum(p.hands for p in res.phases) == 1

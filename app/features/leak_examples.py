"""
Example hand picker for detected leaks.

For each leak_id, filters HandRecord instances that demonstrate the pattern
and builds a short coaching narrative:
  - situation:     what happened in that hand
  - why_weak:      why that line may be losing, position/stack-aware
  - stronger_line: a concrete alternative (no fake EV, no solver claims)

Design rules
------------
- Only fields on HandRecord + HandContext (board_cards) are used — no raw_text parsing.
- Teaching value ranks examples: position-known > stack-known > board-known.
- Up to MAX_EXAMPLES per leak; extras discarded.
- Handles None position/stack gracefully.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from app.features.player_stats import HandRecord


@dataclass(frozen=True)
class HandContext:
    """Minimal hand metadata needed for coaching examples."""

    board_cards: str | None
    stakes_bb: Decimal


@dataclass(frozen=True)
class HandExample:
    hand_external_id: str
    position: str | None
    stack_bb: str | None
    effective_stack_bb: str | None
    board_cards: str | None
    situation: str
    why_weak: str
    stronger_line: str


# ── Helpers ───────────────────────────────────────────────────────────────────


def _pd(r: HandRecord) -> str:
    """Short position + depth string for narrative."""
    parts = []
    if r.position:
        parts.append(r.position)
    if r.stack_bb is not None:
        parts.append(f"{float(r.stack_bb):.0f}bb")
        if r.effective_stack_bb is not None:
            parts.append(f"({float(r.effective_stack_bb):.0f}bb eff)")
    return " ".join(parts) if parts else "unknown position/depth"


def _board(ctx: HandContext | None) -> str:
    if ctx and ctx.board_cards:
        return f" [{ctx.board_cards}]"
    return ""


def _board_texture(ctx: HandContext | None) -> str:
    """Return a brief board-texture qualifier for coaching text, or empty string."""
    if not ctx or not ctx.board_cards:
        return ""
    cards = ctx.board_cards.split()
    if len(cards) < 3:
        return ""
    suits = [c[-1].lower() for c in cards[:3]]
    ranks = [c[:-1] for c in cards[:3]]
    rank_map = {
        "2": 2,
        "3": 3,
        "4": 4,
        "5": 5,
        "6": 6,
        "7": 7,
        "8": 8,
        "9": 9,
        "t": 10,
        "j": 11,
        "q": 12,
        "k": 13,
        "a": 14,
    }
    rank_vals = sorted([rank_map.get(r.lower(), 0) for r in ranks], reverse=True)
    flush_draw = len(set(suits)) <= 2
    connectedness = (rank_vals[0] - rank_vals[2]) <= 4 if len(rank_vals) >= 3 else False
    high_card = rank_vals[0] >= 11  # J or higher

    if flush_draw and connectedness:
        return " (wet, connected board)"
    if flush_draw:
        return " (flush-draw board)"
    if connectedness:
        return " (connected board)"
    if high_card:
        return " (high-card dry board)"
    return " (dry board)"


def _teaching_value(r: HandRecord, ctx: HandContext | None) -> int:
    score = 0
    if r.position is not None:
        score += 3
    if r.stack_bb is not None:
        score += 2
    if r.effective_stack_bb is not None:
        score += 2
    if ctx is not None and ctx.board_cards:
        score += 1
    return score


# ── Per-leak builder functions ────────────────────────────────────────────────
# Each returns (situation, why_weak, stronger_line).

_Builder = Callable[[HandRecord, "HandContext | None"], tuple[str, str, str]]


def _b_vpip_too_loose(r: HandRecord, ctx: HandContext | None) -> tuple[str, str, str]:
    action = "raised" if r.pfr else "called"
    situation = f"Voluntarily {action} into pot from {_pd(r)}."
    pos = r.position or "this position"
    why_weak = (
        f"From {pos}, entering with marginal hands inflates average cost-per-hand "
        "and creates dominated-hand situations. Early/middle position entries are "
        "most expensive — ranges should be narrowest there."
    )
    stronger = (
        f"From {pos}, restrict opens to hands with clear equity: pairs, suited "
        "broadways, suited connectors. Fold marginal off-suit holdings (K7o, Q5o, J4o)."
    )
    return situation, why_weak, stronger


def _b_pfr_too_passive(r: HandRecord, ctx: HandContext | None) -> tuple[str, str, str]:
    situation = f"Called preflop without raising from {_pd(r)}."
    pos = r.position or "this position"
    why_weak = (
        "Flat-calling gives up fold equity, lets players behind enter cheaply, "
        f"and leaves your range undefined. From {pos}, most hands that are worth "
        "playing are worth raising."
    )
    stronger = (
        "Convert the flat-call to an open-raise (or fold). "
        "If the hand is not strong enough to raise, it is usually not strong enough to call."
    )
    return situation, why_weak, stronger


def _b_fold_to_3bet(r: HandRecord, ctx: HandContext | None) -> tuple[str, str, str]:
    eff = f" at {float(r.effective_stack_bb):.0f}bb eff" if r.effective_stack_bb else ""
    situation = f"Opened from {_pd(r)}, faced a 3-bet, and folded{eff}."
    pos = r.position or "this position"
    eff_bb = float(r.effective_stack_bb) if r.effective_stack_bb else None

    if eff_bb is not None and eff_bb < 15:
        why_weak = (
            f"At {eff_bb:.0f}bb eff the hand is in push-fold territory. Folding to a 3-bet "
            "after opening is a chip leak: either shove pre or fold before entering. "
            "Flat-calling then folding to a 3-bet loses chips without a plan."
        )
        stronger = (
            f"From {pos} at {eff_bb:.0f}bb: open-jam any hand worth opening, or fold pre. "
            "Never open-then-fold — that is the worst of both worlds."
        )
    elif eff_bb is not None and eff_bb < 30:
        why_weak = (
            f"At {eff_bb:.0f}bb eff, a 3-bet re-opens the action to a very committed pot. "
            "Folding leaves opponents free to 3-bet any two cards from position for "
            "instant profit — your open range must include a 4-bet shove range."
        )
        stronger = (
            f"From {pos} at {eff_bb:.0f}bb: 4-bet jam with top ~20% of your open range "
            "(pairs TT+, AQs+, AKo). Tighten your opening range so every hand in it "
            "is willing to get it in against a 3-bet."
        )
    else:
        why_weak = (
            f"Folding to every 3-bet from {pos} is exploitable: at 40bb+ the pot odds "
            "after an open rarely justify folding a reasonable hand. Opponents will identify "
            "and exploit a high fold-to-3bet by 3-betting you nearly every orbit."
        )
        stronger = (
            f"From {pos}: build a mixed defence — 4-bet jam premium hands (QQ+, AKs), "
            "call with suited connectors, mid-pairs, and suited broadways. "
            "Target fold-to-3bet below 65% at this depth."
        )
    return situation, why_weak, stronger


def _b_three_bet_opportunity(r: HandRecord, ctx: HandContext | None) -> tuple[str, str, str]:
    action = "3-bet" if r.three_bet else "did not 3-bet (called or folded)"
    situation = f"Had 3-bet opportunity from {_pd(r)} — {action}."
    pos = r.position or "this position"
    if r.three_bet:
        why_weak = (
            f"3-betting {_pd(r)} is part of a pattern where your 3-bet frequency "
            "may be above baseline (4–12%). Attentive opponents adjust with tighter "
            "calling ranges and higher 4-bet frequency."
        )
        stronger = "Ensure 3-bet bluffs have strong blockers (Axs, KQs) and equity when called. Reduce light 3-bets from OOP."
    else:
        why_weak = (
            f"Not 3-betting from {pos} too often lets opponents open wide without resistance. "
            "A polarised 3-bet range is essential to protect your calling range and "
            "prevent opponents from auto-profiting with steals."
        )
        stronger = (
            "Add light 3-bets from BTN/CO: strong value (QQ+, AKs) + bluffs with "
            "blockers (A2s–A5s, K4s). Target 5–9% overall."
        )
    return situation, why_weak, stronger


def _b_btn_steal_missed(r: HandRecord, ctx: HandContext | None) -> tuple[str, str, str]:
    stack_bb = float(r.stack_bb) if r.stack_bb else None
    stack = f"{stack_bb:.0f}bb" if stack_bb else "unknown stack"
    situation = f"BTN with action folded to — did not open-raise ({stack})."

    if stack_bb is not None and stack_bb < 15:
        why_weak = (
            f"At {stack_bb:.0f}bb, BTN is the single best spot to shove. "
            "Passing a fold-or-jam opportunity from BTN costs about 0.5bb per orbit "
            "in EV — it accumulates quickly."
        )
        stronger = (
            f"From BTN at {stack_bb:.0f}bb: shove any hand that passes a push-fold chart "
            "(most Ax, Kx, pairs, suited connectors). With two opponents to act, "
            "your fold equity is highest here."
        )
    else:
        why_weak = (
            "BTN is the most profitable steal spot: in position postflop against only "
            "two players, with the entire table having already folded. Passing this "
            "costs roughly 0.5–1bb EV per missed orbit."
        )
        stronger = (
            f"From BTN at {stack}{'bb' if stack_bb and not stack.endswith('bb') else ''}: "
            "open 2.2–2.5bb with any pair, suited connector, broadway, or Ax hand. "
            "Only fold the very bottom of your range (22, offsuit trash below a 7-high)."
        )
    return situation, why_weak, stronger


def _b_co_steal_missed(r: HandRecord, ctx: HandContext | None) -> tuple[str, str, str]:
    stack_bb = float(r.stack_bb) if r.stack_bb else None
    stack = f"{stack_bb:.0f}bb" if stack_bb else "unknown stack"
    situation = f"CO with action folded to — did not open-raise ({stack})."

    if stack_bb is not None and stack_bb < 15:
        why_weak = (
            f"At {stack_bb:.0f}bb from CO, this is a shove spot — not a fold. "
            "Passing when short-stacked prevents you from accumulating chips "
            "when your fold equity is still meaningful."
        )
        stronger = f"CO at {stack_bb:.0f}bb: shove any Ax, Kx, pair, or suited hand. If BTN/blinds fold often enough, this is +EV."
    else:
        why_weak = (
            "CO is the second-best steal position. Not opening surrenders the pot to "
            "BTN and the blinds, who will collect dead money while your stack bleeds."
        )
        stronger = (
            f"From CO at {stack}: open 2.2–2.5bb with any pair, suited ace, suited "
            "connector, broadway, and most Kx/Qx suited. Target 28–38% open frequency."
        )
    return situation, why_weak, stronger


def _b_sb_steal_missed(r: HandRecord, ctx: HandContext | None) -> tuple[str, str, str]:
    stack_bb = float(r.stack_bb) if r.stack_bb else None
    stack = f"{stack_bb:.0f}bb" if stack_bb else "unknown stack"
    situation = f"SB with action folded to — did not raise ({stack})."

    if stack_bb is not None and stack_bb < 15:
        why_weak = (
            f"At {stack_bb:.0f}bb in the SB heads-up vs BB, you have fold equity and "
            "position advantage on a short stack. Completing the SB here is a passive "
            "leak — it lets BB realise equity for free."
        )
        stronger = f"SB at {stack_bb:.0f}bb: shove or fold. Never complete. Shove range: Ax, Kx, pairs, suited connectors."
    else:
        why_weak = (
            "SB vs BB is heads-up with the widest mutual ranges. "
            "Completing gives BB a free flop, undefined range, "
            "and out-of-position misery for you on every street."
        )
        stronger = (
            f"SB at {stack}: raise-or-fold. Open 2.5–3bb with any pair, suited hand, "
            "broadway, or connected cards. Complete only with a deliberate limping strategy "
            "— otherwise fold weak hands, raise the rest."
        )
    return situation, why_weak, stronger


def _b_bb_fold_steal(r: HandRecord, ctx: HandContext | None) -> tuple[str, str, str]:
    situation = f"Folded in the BB facing a steal attempt ({_pd(r)})."
    eff_bb = float(r.effective_stack_bb) if r.effective_stack_bb else None
    eff_note = f" at {eff_bb:.0f}bb eff" if eff_bb else ""
    why_weak = (
        f"BB already has 1bb invested and faces the best pot odds at the table{eff_note}. "
        "Folding too often is mechanically exploitable: any steal position can open "
        "any two cards and print money once they know you fold too wide."
    )
    if eff_bb and eff_bb < 15:
        stronger = (
            f"BB at {eff_bb:.0f}bb eff: defend by shoving your top ~30–40% vs wide steals "
            "(Ax, Kx, pairs, suited broadways). Avoid calling — 3-bet or fold."
        )
    else:
        stronger = (
            "Defend BB vs steal: call with all pairs, suited hands, broadways, and "
            "any connector 54+. Mix in 3-bets with TT+, AQs+, and A2s–A5s as bluffs. "
            "Target defence frequency of 45–55%."
        )
    return situation, why_weak, stronger


def _b_bb_fold_btn(r: HandRecord, ctx: HandContext | None) -> tuple[str, str, str]:
    situation = f"Folded in the BB specifically to a BTN open ({_pd(r)})."
    eff_bb = float(r.effective_stack_bb) if r.effective_stack_bb else None
    why_weak = (
        "BTN vs BB is heads-up with the widest BTN opening range in the game. "
        "BTN can open 60–70% of hands profitably if BB folds too often. "
        "BB must continue roughly 45–55% to prevent exploitation."
    )
    if eff_bb and eff_bb < 20:
        stronger = (
            f"BB at {eff_bb:.0f}bb vs BTN: 3-bet shove with strong hands (pairs 88+, AQ+) "
            "and fold the bottom of your range. Narrow calling range — prioritise re-shoving."
        )
    else:
        stronger = (
            "Defend BB vs BTN with all suited hands, all pairs, all broadways, and "
            "offsuit connectors 76o+. Add a 3-bet range: TT+/AQs+ for value, "
            "A2s–A5s/K4s–K5s as bluffs."
        )
    return situation, why_weak, stronger


def _b_resteal_missed(r: HandRecord, ctx: HandContext | None) -> tuple[str, str, str]:
    situation = f"Faced a steal attempt from {_pd(r)} — did not 3-bet (no resteal)."
    why_weak = (
        "Rarely restealing lets opponents steal cheaply from all positions. "
        "Without a non-trivial 3-bet frequency, your blind defence is purely passive "
        "and easily exploited with thin open ranges."
    )
    stronger = (
        "Build a polar BB/SB 3-bet range: strong value (TT+, AQs+) and re-steal "
        "bluffs (A2s–A5s, K4s). Target 8–15% resteal frequency."
    )
    return situation, why_weak, stronger


def _b_wtsd_high(r: HandRecord, ctx: HandContext | None) -> tuple[str, str, str]:
    brd = _board(ctx)
    situation = f"Saw flop{brd} and went to showdown ({_pd(r)})."
    why_weak = (
        f"Reaching showdown on{brd if brd else ' this board'} with a calling-dominant line "
        "suggests over-calling on turns and rivers. Opponents can triple-barrel with "
        "air on scare streets for an immediate profit."
    )
    stronger = (
        "Introduce disciplined turn/river folds: middle pair with weak kicker "
        "facing two streets of aggression is usually a fold on wet or paired boards."
    )
    return situation, why_weak, stronger


def _b_wtsd_low(r: HandRecord, ctx: HandContext | None) -> tuple[str, str, str]:
    brd = _board(ctx)
    situation = f"Saw flop{brd} but folded before showdown ({_pd(r)})."
    why_weak = (
        "Over-folding after the flop allows opponents to barrel profitably with air. "
        "If you hold a one-pair hand or better on a blank turn, a fold is often too "
        "tight and gives opponents free licence to bluff."
    )
    stronger = (
        "Build a bluff-catching range: top pair-weak kicker and second pair are "
        "usually worth calling one or two streets. Look for blank turns where "
        "you should be calling, not folding."
    )
    return situation, why_weak, stronger


def _b_wsd_low(r: HandRecord, ctx: HandContext | None) -> tuple[str, str, str]:
    brd = _board(ctx)
    situation = f"Reached showdown{brd} but lost ({_pd(r)})."
    why_weak = (
        "Losing showdowns frequently suggests calling the river with hands that "
        "rarely beat a bet. This inflates losses at and around showdown."
    )
    stronger = (
        "Before calling a river bet, ask: what hands in their betting range do I beat? "
        "If the answer is few (mostly bluffs), use blocker logic — does your hand block "
        "their likely bluffs? If not, a fold is often correct."
    )
    return situation, why_weak, stronger


def _b_cbet_high(r: HandRecord, ctx: HandContext | None) -> tuple[str, str, str]:
    brd = _board(ctx)
    board_texture = _board_texture(ctx)
    situation = f"C-bet as preflop aggressor{brd} ({_pd(r)})."
    why_weak = (
        f"C-betting almost every flop{brd} is exploitable{board_texture}: opponents float "
        "cheaply and win the pot when you give up on the turn. "
        "A 100% c-bet range is also unprotected — any check becomes a transparent give-up."
    )
    stronger = (
        "Mix in checks on connected and wet boards: protect by checking strong hands "
        "occasionally, and use give-up checks strategically. "
        "Target 50–65% on connected boards, 65–75% heads-up on dry ace-high flops."
    )
    return situation, why_weak, stronger


def _b_cbet_low(r: HandRecord, ctx: HandContext | None) -> tuple[str, str, str]:
    brd = _board(ctx)
    board_texture = _board_texture(ctx)
    situation = f"Checked back as preflop aggressor{brd} — did not c-bet ({_pd(r)})."
    why_weak = (
        f"Checking back{brd}{board_texture} gives up initiative and lets opponents "
        "realise equity for free. As PF aggressor, your range has an equity advantage "
        "on most boards — failing to leverage it concedes the pot."
    )
    stronger = (
        "C-bet 50–65% on connected boards, 65–75% on dry ace-high flops. "
        "Use a small size (33–40% pot) to bet wide. "
        "Check back hands that benefit from a free turn (sets, top two) occasionally to protect your check range."
    )
    return situation, why_weak, stronger


def _b_fold_flop_bet(r: HandRecord, ctx: HandContext | None) -> tuple[str, str, str]:
    brd = _board(ctx)
    board_texture = _board_texture(ctx)
    situation = f"Folded to a flop bet{brd} ({_pd(r)})."
    eff_bb = float(r.effective_stack_bb) if r.effective_stack_bb else None
    why_weak = (
        f"Folding too often to flop bets{brd}{board_texture} is directly exploitable: "
        "once opponents detect a high fold-to-flop-bet frequency, they profitably "
        "c-bet any two cards and collect without needing to improve."
    )
    if eff_bb and eff_bb < 20:
        stronger = (
            f"At {eff_bb:.0f}bb eff: flop calls commit a large fraction of your stack — "
            "evaluate whether calling sets up a profitable turn shove. "
            "If yes, call or shove the flop; if no, fold is correct."
        )
    else:
        stronger = (
            f"Build a flop calling range{brd}: second pair, gut-shots, backdoor flush "
            "draws, and any overcards with equity. Against a 50–66% pot c-bet, "
            "you need ~27–40% equity to continue — most one-pair hands qualify."
        )
    return situation, why_weak, stronger


def _b_fold_turn_bet(r: HandRecord, ctx: HandContext | None) -> tuple[str, str, str]:
    brd = _board(ctx)
    board_texture = _board_texture(ctx)
    situation = f"Folded to a turn bet{brd} ({_pd(r)})."
    eff_bb = float(r.effective_stack_bb) if r.effective_stack_bb else None
    why_weak = (
        f"Over-folding to turn bets{brd}{board_texture} enables a profitable double-barrel "
        "line: opponents can barrel the turn with air on any board where you fold too wide. "
        "Turn folds should be reserved for boards where your hand genuinely deteriorated."
    )
    if eff_bb and eff_bb < 20:
        stronger = (
            f"At {eff_bb:.0f}bb eff: a turn call often commits you — consider whether "
            "your hand supports a raise-shove on the turn. If you're calling, "
            "plan to call or bluff-catch the river as well."
        )
    else:
        stronger = (
            f"On blank turns{brd if brd else ''}: call with one pair or better if "
            "the pot odds are above 25%. Raise two-pair+ to deny equity. "
            "Only fold when the turn card significantly improved villain's range "
            "(flush or straight completes, paired board that hits their range)."
        )
    return situation, why_weak, stronger


def _b_too_passive(r: HandRecord, ctx: HandContext | None) -> tuple[str, str, str]:
    brd = _board(ctx)
    situation = f"Called postflop without betting or raising{brd} ({_pd(r)})."
    why_weak = (
        "A calling-only postflop style lets opponents control pot size, realise "
        "equity cheaply, and take free cards on scare streets. Strong made hands "
        "should build pots with bets and raises."
    )
    stronger = (
        "Identify spots where you hold sets, two-pair, or an overpair: raise for "
        "value rather than calling. Replace one call in three with a raise when "
        "you want the pot bigger."
    )
    return situation, why_weak, stronger


# ── Registry ──────────────────────────────────────────────────────────────────

_Filter = Callable[[HandRecord], bool]

_REGISTRY: dict[str, tuple[_Filter, _Builder]] = {
    "vpip_too_loose": (
        lambda r: r.vpip,
        _b_vpip_too_loose,
    ),
    "pfr_too_passive": (
        lambda r: r.vpip and not r.pfr,
        _b_pfr_too_passive,
    ),
    "fold_to_3bet_too_high": (
        lambda r: r.folded_to_3bet,
        _b_fold_to_3bet,
    ),
    "three_bet_too_low": (
        lambda r: r.had_3bet_opportunity and not r.three_bet,
        _b_three_bet_opportunity,
    ),
    "three_bet_too_high": (
        lambda r: r.three_bet,
        _b_three_bet_opportunity,
    ),
    "btn_steal_too_low": (
        lambda r: r.position == "BTN" and r.had_steal_opportunity and not r.stole,
        _b_btn_steal_missed,
    ),
    "co_steal_too_low": (
        lambda r: r.position == "CO" and r.had_steal_opportunity and not r.stole,
        _b_co_steal_missed,
    ),
    "sb_steal_too_low": (
        lambda r: r.position == "SB" and r.had_steal_opportunity and not r.stole,
        _b_sb_steal_missed,
    ),
    "bb_overfolding_vs_steals": (
        lambda r: r.faced_steal and r.folded_to_steal,
        _b_bb_fold_steal,
    ),
    "bb_overfolding_vs_btn": (
        lambda r: r.faced_btn_open_as_bb and r.folded_bb_to_btn_open,
        _b_bb_fold_btn,
    ),
    "sb_overfolding_vs_steals": (
        lambda r: r.defender_position == "SB" and r.folded_to_steal,
        _b_bb_fold_steal,
    ),
    "resteal_too_low": (
        lambda r: r.re_steal_opportunity and not r.attempted_resteal,
        _b_resteal_missed,
    ),
    "wtsd_too_high": (
        lambda r: r.saw_flop and r.reached_showdown,
        _b_wtsd_high,
    ),
    "wtsd_too_low": (
        lambda r: r.saw_flop and not r.reached_showdown,
        _b_wtsd_low,
    ),
    "wsd_suspiciously_low": (
        lambda r: r.reached_showdown and not r.won_at_showdown,
        _b_wsd_low,
    ),
    "cbet_too_high": (
        lambda r: r.cbet,
        _b_cbet_high,
    ),
    "cbet_too_low": (
        lambda r: r.cbet_opportunity and not r.cbet,
        _b_cbet_low,
    ),
    "fold_to_flop_bet_too_high": (
        lambda r: r.folded_to_flop_bet,
        _b_fold_flop_bet,
    ),
    "fold_to_turn_bet_too_high": (
        lambda r: r.folded_to_turn_bet,
        _b_fold_turn_bet,
    ),
    "too_passive_postflop": (
        lambda r: r.postflop_calls > 0 and r.postflop_bets_raises == 0,
        _b_too_passive,
    ),
}

MAX_EXAMPLES = 3


def build_leak_examples(
    leak_id: str,
    records: list[HandRecord],
    contexts: dict[str, HandContext],
) -> list[HandExample]:
    """
    Return up to MAX_EXAMPLES HandExample objects for the given leak_id.

    Filters ``records`` by the leak's trigger condition, ranks by teaching value
    (position-known > stack-known > board-known), and returns the top results.
    """
    entry = _REGISTRY.get(leak_id)
    if entry is None:
        return []

    filt, builder = entry
    matched = [r for r in records if filt(r)]
    if not matched:
        return []

    ranked = sorted(
        matched,
        key=lambda r: _teaching_value(r, contexts.get(r.hand_external_id)),
        reverse=True,
    )

    examples: list[HandExample] = []
    for r in ranked[:MAX_EXAMPLES]:
        ctx = contexts.get(r.hand_external_id)
        situation, why_weak, stronger_line = builder(r, ctx)
        examples.append(
            HandExample(
                hand_external_id=r.hand_external_id,
                position=r.position,
                stack_bb=str(r.stack_bb) if r.stack_bb is not None else None,
                effective_stack_bb=(
                    str(r.effective_stack_bb) if r.effective_stack_bb is not None else None
                ),
                board_cards=ctx.board_cards if ctx else None,
                situation=situation,
                why_weak=why_weak,
                stronger_line=stronger_line,
            )
        )
    return examples

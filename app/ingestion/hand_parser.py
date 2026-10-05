"""
HandHistoryParser  — parses a single ClubGG hand history text block.
HandHistoryFileIngestor — watches a directory and ingests .txt files.

ClubGG hand history format (PokerStars-like with ClubGG header extensions):

    ClubGG Hand #12345678: Hold'em No Limit ($0.50/$1.00) - 2024-01-15 22:31:07 UTC
    Club: MyClub (ID: 42)  Agent: AgentJohn (ID: 7)
    Table 'Diamond 1' 6-max Seat #3 is the button
    Seat 1: Alice ($100.00 in chips)
    Seat 2: Bob ($75.50 in chips)
    Alice: posts small blind $0.50
    Bob: posts big blind $1.00
    *** HOLE CARDS ***
    Alice: raises $3.00 to $4.00
    Bob: calls $3.00
    *** FLOP *** [Ah Kd 2c]
    Bob: checks
    Alice: bets $5.00
    Bob: folds
    *** SUMMARY ***
    Total pot $9.00 | Rake $0.45
    Board [Ah Kd 2c]
    Seat 1: Alice collected $8.55 from main pot

Design notes
------------
- ``_parse_streets`` handles the preamble (blinds/antes), each betting round, and
  the SHOW DOWN section in a single left-to-right scan.
- ``_enrich`` runs after all parse steps to merge showdown data into player dicts
  and compute ``saw_flop`` per player.
- SHOW and MUCK actions in the SHOWDOWN section are stored as ``player_actions``
  so ``reached_showdown`` can be derived at query time without a separate column.
- ``ending_stack`` is NOT computed from file hands.  The format provides no
  reliable per-seat ending stack (only winner collection amounts), so it stays
  None.  ``net_won`` on HandPlayer will therefore also be None for file hands.
"""

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.ingestion.base import AbstractIngestor, IngestDomain, IngestResult

logger = logging.getLogger(__name__)

# ── Regex patterns ────────────────────────────────────────────────────────────

_HAND_BLOCK_RE = re.compile(r"(?=^(?:ClubGG|Poker) Hand #)", re.MULTILINE)

# Old PokerStars-like ClubGG format
_HEADER_RE = re.compile(
    r"ClubGG Hand #(?P<hand_id>\w+):\s+(?P<game_desc>[^(]+?)\s+"
    r"\(\$(?P<sb>[\d.]+)/\$(?P<bb>[\d.]+)(?:/\$(?P<ante>[\d.]+))?\)"
    r"\s+-\s+(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) UTC"
)

# GGPoker/ClubGG export format — two sub-variants:
#   Tournament: Poker Hand #tour_434136888: ... NLH No Limit - Level12(750/1,500) - 2026/04/04 20:08:15
#   Cash game:  Poker Hand #RC123456: Hold'em No Limit ($1/$2) - 2026/04/18 20:28:07
_HEADER_GG_RE = re.compile(
    r"Poker Hand #(?P<hand_id>\S+):\s+(?P<game_desc>.+?)\s+No Limit"
    r"(?:"
    r"\s+-\s+Level(?P<level>\d+)\((?P<sb>[\d,]+)/(?P<bb>[\d,]+)(?:/[\d,]+)?\)"  # tournament: " - Level12(750/1,500)"
    r"|"
    r"\s+\(\$(?P<sb2>[\d,]+(?:\.\d+)?)/\$(?P<bb2>[\d,]+(?:\.\d+)?)\)"  # cash: " ($1/$2)"
    r")\s+-\s+"
    r"(?P<ts>\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2})"
)
# Tournament game description: "Tournament #3317780, 200K GTD ♠ FROZEN THRONE HR ♠ RE NLH"
_TOURNAMENT_RE = re.compile(r"Tournament #(?P<tid>\d+),\s*(?P<name>.+)")
_GAME_SUFFIX_RE = re.compile(r"\s+(?:NLH|PLO\d?|Hold'em|Short Deck)$", re.IGNORECASE)
_CLUB_RE = re.compile(
    r"Club:\s+(?P<club_name>.+?)\s+\(ID:\s*(?P<club_id>\d+)\)"
    r"(?:\s+Agent:\s+(?P<agent_name>.+?)\s+\(ID:\s*(?P<agent_id>\d+)\))?"
)
_TABLE_RE = re.compile(r"Table '(?P<table_name>[^']*)'\s+(?P<max_players>\d+)-max")
_BUTTON_RE = re.compile(r"Seat #(?P<btn>\d+) is the button")
_SEAT_RE = re.compile(
    r"^Seat (?P<seat>\d+):\s+(?P<username>.+?)\s+\(\$?(?P<stack>[\d,]+(?:\.\d+)?) in chips\)",
    re.MULTILINE,
)

# Matches voluntary betting-round actions: folds, checks, calls, bets, raises, all-in.
# Handles both old format ($-prefixed, no commas) and GGPoker format (no $, comma thousands).
# For raises: captures both X and Y from "raises X to Y" — Y (amount2) is the total.
# For "is all-in" (standalone): raw_action == "is", mapped to ALL_IN.
# Separators are [ \t], never \s: \s matches newlines, so "X: folds\n2d57...: folds"
# would read "2" as fold's amount and swallow the next player's line.
_ACTION_RE = re.compile(
    r"^(?P<username>.+?):[ \t]+"
    r"(?P<action>folds|checks|calls|bets|raises|is all-in)"
    r"(?:[ \t]+\$?(?P<amount>[\d,]+(?:\.\d+)?))?"
    # "to Y" may follow the increment ("raises 450 to 570") or stand alone
    # ("raises to 21 and is all-in").
    r"(?:[ \t]+to[ \t]+\$?(?P<amount2>[\d,]+(?:\.\d+)?))?"
    r"(?P<allin> and is all-in)?",
    re.MULTILINE,
)

# Blind/ante posts — appear in the preamble before *** HOLE CARDS ***
# Handles both "posts small blind $X" and "posts the ante Y" (GGPoker format).
_BLIND_RE = re.compile(
    r"^(?P<username>.+?):\s+posts (?:the )?(?P<blind_type>small blind|big blind|ante)"
    r"\s+\$?(?P<amount>[\d,]+(?:\.\d+)?)",
    re.MULTILINE,
)

# Winner "collected" lines — appear in SHOWDOWN or SUMMARY section.
# Old: "Seat N: Alice collected $8.55 from main pot"
# GGPoker: "Alice collected 18,573 from pot"
# pot_desc normalised: "pot"/"main pot" → "main", "side pot" → "side", "side pot-1" → "side-1"
_WINNER_RE = re.compile(
    r"^(?:Seat \d+:\s+)?(?P<username>.+?)\s+collected\s+\$?(?P<amount>[\d,]+(?:\.\d+)?)\s+from\s+(?P<pot_desc>.+)$",
    re.MULTILINE,
)

# SHOW DOWN / run-out shows (GGPoker shows these before *** SHOWDOWN ***)
_SHOW_RE = re.compile(
    r"^(?P<username>.+?):\s+shows \[(?P<cards>[^\]]+)\](?:\s+\((?P<description>[^)]+)\))?",
    re.MULTILINE,
)
# Hole cards dealt to each player — GGPoker format: "Dealt to Hero [Qs 6s]"
_DEALT_RE = re.compile(
    r"^Dealt to (?P<username>.+?) \[(?P<cards>[^\]]+)\]",
    re.MULTILINE,
)
_MUCK_RE = re.compile(
    r"^(?P<username>.+?):\s+mucks hand",
    re.MULTILINE,
)

_BOARD_RE = re.compile(r"Board \[(?P<cards>[^\]]+)\]")
# "Uncalled bet (9,600) returned to 589f9da2" / "Uncalled bet ($4.00) returned to Alice"
_UNCALLED_RE = re.compile(
    r"^Uncalled bet \(\$?(?P<amount>[\d,]+(?:\.\d+)?)\) returned to (?P<username>.+?)\s*$",
    re.MULTILINE,
)
_POT_RE = re.compile(
    r"Total pot \$?(?P<total>[\d,]+(?:\.\d+)?)(?:\s*\|\s*Rake \$?(?P<rake>[\d,]+(?:\.\d+)?))?"
)

_STREET_HEADERS: dict[str, str] = {
    "HOLE CARDS": "PREFLOP",
    "FLOP": "FLOP",
    "TURN": "TURN",
    "RIVER": "RIVER",
    "SHOW DOWN": "SHOWDOWN",
    "SHOWDOWN": "SHOWDOWN",  # GGPoker format (no space)
}
_STREET_HEADER_RE = re.compile(
    r"^\*{3}\s+(?P<street>HOLE CARDS|FLOP|TURN|RIVER|SHOW DOWN|SHOWDOWN)\s+\*{3}",
    re.MULTILINE,
)

_ACTION_TYPE_MAP: dict[str, str] = {
    "folds": "FOLD",
    "checks": "CHECK",
    "calls": "CALL",
    "bets": "BET",
    "raises": "RAISE",
    "is": "ALL_IN",  # "is all-in" standalone
}


# ── Internal data structure ───────────────────────────────────────────────────


@dataclass
class _ParsedHand:
    hand_id: str = ""
    club_id: int = 0
    club_name: str = ""
    game_type: str = "NLH"
    stakes_sb: Decimal = Decimal("0")
    stakes_bb: Decimal = Decimal("0")
    stakes_ante: Decimal | None = None
    tournament_external_id: str | None = None
    tournament_name: str | None = None
    blind_level_index: int | None = None
    table_name: str | None = None
    button_seat: int | None = None
    hand_started_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    total_pot: Decimal = Decimal("0")
    total_rake: Decimal = Decimal("0")
    board_cards: str | None = None
    players: list[dict[str, Any]] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    winners: list[dict[str, Any]] = field(default_factory=list)
    raw_text: str = ""
    # Tracked during _parse_streets
    streets_dealt: set[str] = field(default_factory=set)
    # username → {did_show, hole_cards, hand_description}
    showdowns: dict[str, dict[str, Any]] = field(default_factory=dict)
    # username → uncalled bet returned to that player
    returned: dict[str, Decimal] = field(default_factory=dict)


# ── Parser ────────────────────────────────────────────────────────────────────


class HandHistoryParser:
    """Parses a single ClubGG hand block into a raw dict for the ingestion pipeline."""

    def parse(self, block: str) -> dict[str, Any]:
        """
        Parse one hand history block.

        Returns a dict matching the shape expected by ``normalize_file_hand()``.
        Raises ``ValueError`` if the header line cannot be parsed.
        """
        h = _ParsedHand(raw_text=block)

        self._parse_header(block, h)
        self._parse_seats(block, h)
        self._parse_streets(block, h)  # also fills streets_dealt + showdowns
        self._parse_summary(block, h)  # winners, pot, board
        self._enrich(h)  # saw_flop, did_show, hole_cards per player;
        # winning_hand_description on winners
        self._compute_results(h)  # ending_stack per player, when the hand reconciles

        return {
            "external_id": h.hand_id,
            "club_external_id": h.club_id,
            "club_name": h.club_name,
            "game_type": h.game_type,
            "stakes_sb": str(h.stakes_sb),
            "stakes_bb": str(h.stakes_bb),
            "stakes_ante": str(h.stakes_ante) if h.stakes_ante else None,
            "tournament_external_id": h.tournament_external_id,
            "tournament_name": h.tournament_name,
            "blind_level_index": h.blind_level_index,
            "table_name": h.table_name,
            "button_seat": h.button_seat,
            "hand_started_at": h.hand_started_at.isoformat(),
            "total_pot": str(h.total_pot),
            "total_rake": str(h.total_rake),
            "board_cards": h.board_cards,
            "raw_text": h.raw_text,
            "ingestion_source": "file",
            "players": h.players,
            "actions": h.actions,
            "winners": h.winners,
        }

    # ── Private parse steps ───────────────────────────────────────────────────

    def _parse_header(self, block: str, h: _ParsedHand) -> None:
        m = _HEADER_RE.search(block)
        if m:
            h.hand_id = m.group("hand_id")
            h.stakes_sb = Decimal(m.group("sb"))
            h.stakes_bb = Decimal(m.group("bb"))
            if m.group("ante"):
                h.stakes_ante = Decimal(m.group("ante"))
            h.hand_started_at = datetime.strptime(m.group("ts"), "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=UTC
            )
            desc = m.group("game_desc").lower()
            cm = _CLUB_RE.search(block)
            if cm:
                h.club_id = int(cm.group("club_id"))
                h.club_name = cm.group("club_name").strip()
        else:
            m = _HEADER_GG_RE.search(block)
            if not m:
                raise ValueError("Could not parse hand header")
            h.hand_id = m.group("hand_id")
            # Tournament uses sb/bb groups; cash game uses sb2/bb2 groups
            sb_raw = m.group("sb") or m.group("sb2") or "0"
            bb_raw = m.group("bb") or m.group("bb2") or "0"
            h.stakes_sb = Decimal(sb_raw.replace(",", ""))
            h.stakes_bb = Decimal(bb_raw.replace(",", ""))
            h.hand_started_at = datetime.strptime(m.group("ts"), "%Y/%m/%d %H:%M:%S").replace(
                tzinfo=UTC
            )
            desc = m.group("game_desc").lower()
            if m.group("level"):
                h.blind_level_index = int(m.group("level"))
            tm = _TOURNAMENT_RE.match(m.group("game_desc"))
            if tm:
                h.tournament_external_id = tm.group("tid")
                h.tournament_name = _GAME_SUFFIX_RE.sub("", tm.group("name")).strip() or None
            # No club line in GGPoker exports — use sentinel 0 (auto-created by upload endpoint)
            h.club_id = 0
            h.club_name = "ClubGG"

        if "omaha" in desc and "5" in desc:
            h.game_type = "PLO5"
        elif "omaha" in desc:
            h.game_type = "PLO"
        elif "short" in desc:
            h.game_type = "SHORT_DECK"
        else:
            h.game_type = "NLH"

        tm = _TABLE_RE.search(block)
        if tm:
            h.table_name = tm.group("table_name") or None

        bm = _BUTTON_RE.search(block)
        if bm:
            h.button_seat = int(bm.group("btn"))

    def _parse_seats(self, block: str, h: _ParsedHand) -> None:
        for m in _SEAT_RE.finditer(block):
            h.players.append(
                {
                    "player_username": m.group("username"),
                    "seat_number": int(m.group("seat")),
                    "starting_stack": str(Decimal(m.group("stack").replace(",", ""))),
                    # Enriched by _enrich() after full parse
                    "did_show": False,
                    "hole_cards": None,
                    "saw_flop": False,
                }
            )

    def _parse_streets(self, block: str, h: _ParsedHand) -> None:
        """
        Scan the block segment by segment, separated by *** STREET *** headers.

        Segments alternate: [text, street_name, text, street_name, ...]
        ``re.split`` with a capturing group inserts the captured token between
        text segments.

        action_order is a monotonically increasing counter shared across all
        streets so that overall hand ordering is preserved.
        """
        segments = _STREET_HEADER_RE.split(block)
        current_street = "PREFLOP"
        action_order = 0

        i = 0
        while i < len(segments):
            seg = segments[i]

            # Street header token — advance current_street and record it
            if seg in _STREET_HEADERS:
                current_street = _STREET_HEADERS[seg]
                h.streets_dealt.add(current_street)
                i += 1
                continue

            if current_street == "PREFLOP":
                # Hole cards dealt — GGPoker: "Dealt to Hero [Qs 6s]"
                for m in _DEALT_RE.finditer(seg):
                    username = m.group("username")
                    if username not in h.showdowns:
                        h.showdowns[username] = {
                            "did_show": False,
                            "hole_cards": m.group("cards"),
                            "hand_description": None,
                        }
                    elif h.showdowns[username].get("hole_cards") is None:
                        h.showdowns[username]["hole_cards"] = m.group("cards")

                # Preamble (i==0) and post-HOLE-CARDS segment both land here.
                # Blinds and antes only appear in the preamble.
                for m in _BLIND_RE.finditer(seg):
                    blind_type = m.group("blind_type")
                    action_map = {
                        "small blind": "POST_SB",
                        "big blind": "POST_BB",
                        "ante": "POST_ANTE",
                    }
                    amount = Decimal(m.group("amount").replace(",", ""))
                    # GGPoker tournament headers omit the ante, so take it from
                    # the posts. Use the largest post: a short stack may post
                    # a partial ante.
                    if blind_type == "ante" and (
                        h.stakes_ante is None or amount > h.stakes_ante
                    ):
                        h.stakes_ante = amount
                    h.actions.append(
                        {
                            "player_username": m.group("username"),
                            "street": "PREFLOP",
                            "action_type": action_map[blind_type],
                            "amount": str(amount),
                            "is_all_in": False,
                            "action_order": action_order,
                        }
                    )
                    action_order += 1

            if current_street in ("PREFLOP", "FLOP", "TURN", "RIVER"):
                for m in _ACTION_RE.finditer(seg):
                    raw_action = m.group("action").lower().split()[0]
                    action_type = _ACTION_TYPE_MAP.get(raw_action, "FOLD")
                    is_all_in = bool(m.group("allin")) or raw_action == "is"
                    # For raises: amount2 is the total-to (use it); for others: amount
                    amount_str = m.group("amount2") or m.group("amount")
                    h.actions.append(
                        {
                            "player_username": m.group("username"),
                            "street": current_street,
                            "action_type": action_type,
                            "amount": str(Decimal(amount_str.replace(",", "")))
                            if amount_str
                            else None,
                            "is_all_in": is_all_in,
                            "action_order": action_order,
                        }
                    )
                    action_order += 1

                # GGPoker all-in run-out shows appear before *** SHOWDOWN ***
                for m in _SHOW_RE.finditer(seg):
                    username = m.group("username")
                    if username not in h.showdowns:
                        h.showdowns[username] = {
                            "did_show": True,
                            "hole_cards": m.group("cards"),
                            "hand_description": m.group("description") or None,
                        }
                    else:
                        h.showdowns[username]["did_show"] = True
                        if h.showdowns[username].get("hole_cards") is None:
                            h.showdowns[username]["hole_cards"] = m.group("cards")
                    h.actions.append(
                        {
                            "player_username": username,
                            "street": "SHOWDOWN",
                            "action_type": "SHOW",
                            "amount": None,
                            "is_all_in": False,
                            "action_order": action_order,
                        }
                    )
                    action_order += 1

            elif current_street == "SHOWDOWN":
                # Record SHOW and MUCK as actions (enables reached_showdown
                # derivation at query time via action_type IN ('SHOW','MUCK')).
                for m in _SHOW_RE.finditer(seg):
                    username = m.group("username")
                    cards = m.group("cards")
                    description = m.group("description") or None
                    h.showdowns[username] = {
                        "did_show": True,
                        "hole_cards": cards,
                        "hand_description": description,
                    }
                    h.actions.append(
                        {
                            "player_username": username,
                            "street": "SHOWDOWN",
                            "action_type": "SHOW",
                            "amount": None,
                            "is_all_in": False,
                            "action_order": action_order,
                        }
                    )
                    action_order += 1

                for m in _MUCK_RE.finditer(seg):
                    username = m.group("username")
                    # Don't overwrite if already recorded as a show
                    if username not in h.showdowns:
                        h.showdowns[username] = {
                            "did_show": False,
                            "hole_cards": None,
                            "hand_description": None,
                        }
                    h.actions.append(
                        {
                            "player_username": username,
                            "street": "SHOWDOWN",
                            "action_type": "MUCK",
                            "amount": None,
                            "is_all_in": False,
                            "action_order": action_order,
                        }
                    )
                    action_order += 1

            i += 1

    def _parse_summary(self, block: str, h: _ParsedHand) -> None:
        pot_m = _POT_RE.search(block)
        if pot_m:
            h.total_pot = Decimal(pot_m.group("total").replace(",", ""))
            rake = pot_m.group("rake")
            h.total_rake = Decimal(rake.replace(",", "")) if rake else Decimal("0")

        board_m = _BOARD_RE.search(block)
        if board_m:
            h.board_cards = board_m.group("cards")

        for m in _UNCALLED_RE.finditer(block):
            username = m.group("username")
            amount = Decimal(m.group("amount").replace(",", ""))
            h.returned[username] = h.returned.get(username, Decimal("0")) + amount

        for m in _WINNER_RE.finditer(block):
            pot_desc = m.group("pot_desc").strip().lower()
            # Normalise: "pot"/"main pot" → "main", "side pot" → "side", "side pot-1" → "side-1"
            if pot_desc in ("pot", "main pot"):
                pot_type = "main"
            else:
                pot_type = pot_desc.replace(" pot", "").strip() or "main"
            h.winners.append(
                {
                    "player_username": m.group("username"),
                    "pot_type": pot_type,
                    "amount_won": str(Decimal(m.group("amount").replace(",", ""))),
                    "winning_hand_description": None,  # filled in _enrich
                }
            )

    def _enrich(self, h: _ParsedHand) -> None:
        """
        Post-parse enrichment:
        - Merge showdown show/muck data (did_show, hole_cards) into player dicts.
        - Compute saw_flop per player from streets_dealt + preflop fold flags.
        - Fill winning_hand_description on winners from showdown show data.
        """
        # Enrich player dicts with showdown outcomes
        for p in h.players:
            sd = h.showdowns.get(p["player_username"])
            if sd:
                p["did_show"] = sd["did_show"]
                p["hole_cards"] = sd["hole_cards"]

        # Compute saw_flop:
        # A player saw the flop iff:
        #   (a) the flop was dealt (FLOP appears in streets_dealt), AND
        #   (b) the player did not fold preflop.
        # Note: a player who checked the flop without acting still "saw" it
        # because they stayed in the hand to the flop.
        had_flop = "FLOP" in h.streets_dealt
        preflop_folds: set[str] = {
            a["player_username"]
            for a in h.actions
            if a["street"] == "PREFLOP" and a["action_type"] == "FOLD"
        }
        for p in h.players:
            p["saw_flop"] = had_flop and p["player_username"] not in preflop_folds

        # Enrich winner records with hand description from show lines
        for w in h.winners:
            sd = h.showdowns.get(w["player_username"])
            if sd and sd.get("hand_description"):
                w["winning_hand_description"] = sd["hand_description"]

    def _compute_results(self, h: _ParsedHand) -> None:
        """
        Set ``ending_stack`` per player = starting − chips put in + chips collected.

        Chips put in: antes, plus each street's final commitment (blinds, calls
        and bets add; "raises X to Y" sets the street total to Y), minus any
        uncalled bet returned.  The hand must reconcile — chips in equal chips
        collected plus rake — otherwise ending_stack stays None: a result is
        never guessed.
        """
        put_in: dict[str, Decimal] = {p["player_username"]: Decimal("0") for p in h.players}
        street_total: dict[tuple[str, str], Decimal] = {}

        for a in h.actions:
            t = a["action_type"]
            if t in ("SHOW", "MUCK", "FOLD", "CHECK"):
                continue
            user = a["player_username"]
            if user not in put_in or a["amount"] is None:
                return  # unknown seat or an all-in with no amount: can't account
            amount = Decimal(a["amount"])
            if t == "POST_ANTE":
                put_in[user] += amount
                continue
            key = (user, a["street"])
            prev = street_total.get(key, Decimal("0"))
            street_total[key] = amount if t == "RAISE" else prev + amount

        for (user, _street), amount in street_total.items():
            put_in[user] += amount
        for user, amount in h.returned.items():
            if user not in put_in:
                return
            put_in[user] -= amount

        collected: dict[str, Decimal] = {}
        for w in h.winners:
            user = w["player_username"]
            if user not in put_in:
                return
            collected[user] = collected.get(user, Decimal("0")) + Decimal(w["amount_won"])

        if sum(put_in.values()) != sum(collected.values()) + h.total_rake:
            logger.debug("Hand %s does not reconcile; results left unknown", h.hand_id)
            return

        for p in h.players:
            user = p["player_username"]
            start = Decimal(p["starting_stack"])
            p["ending_stack"] = str(start - put_in[user] + collected.get(user, Decimal("0")))


# ── File ingestor ─────────────────────────────────────────────────────────────


class HandHistoryFileIngestor(AbstractIngestor):
    """
    Watches HAND_HISTORY_WATCH_DIR for .txt files and parses + ingests them.
    Processed files are moved to HAND_HISTORY_PROCESSED_DIR.
    Failed files are moved to <watch_dir>/failed/ with a .error sidecar.
    """

    def __init__(self, club_id: str, session_factory: object) -> None:
        from app.config import settings

        super().__init__(club_id, session_factory)
        self._parser = HandHistoryParser()
        self._watch_dir = Path(settings.HAND_HISTORY_WATCH_DIR)
        self._processed_dir = Path(settings.HAND_HISTORY_PROCESSED_DIR)
        self._failed_dir = self._watch_dir / "failed"

    # ── AbstractIngestor interface ────────────────────────────────────────────

    async def fetch_hands(self, since: datetime | None = None) -> list[dict[str, Any]]:
        """Scan watch directory and parse all .txt files."""
        results: list[dict[str, Any]] = []
        self._processed_dir.mkdir(parents=True, exist_ok=True)
        self._failed_dir.mkdir(parents=True, exist_ok=True)

        for path in self._watch_dir.glob("*.txt"):
            try:
                text = path.read_text(encoding="utf-8")
                parsed = self._parse_text(text)
                for hand in parsed:
                    hand["_source_file"] = str(path)
                results.extend(parsed)
                self._move_to_processed(path)
            except Exception as exc:
                logger.warning("Failed to parse %s: %s", path, exc)
                self._move_to_failed(path, str(exc))

        return results

    async def fetch_players(self) -> list[dict[str, Any]]:
        raise NotImplementedError("File ingestor only supports hand histories")

    async def fetch_transactions(self, since: datetime | None = None) -> list[dict[str, Any]]:
        raise NotImplementedError("File ingestor only supports hand histories")

    async def fetch_tables(self) -> list[dict[str, Any]]:
        raise NotImplementedError("File ingestor only supports hand histories")

    # ── Persistence (file-specific routing) ──────────────────────────────────

    async def persist(
        self, domain: IngestDomain, records: list[dict[str, Any]], errors: list[str]
    ) -> tuple[int, int]:
        """
        Normalize file hand records with normalize_file_hand() and upsert.

        Overrides AbstractIngestor.persist() to route through the file normalizer
        instead of the API normalizer.  normalize_hand_players() is called first
        to enrich player dicts with position and BB-normalized stack fields.
        """
        from decimal import Decimal

        from app.features.normalize_hand import normalize_hand_players
        from app.ingestion.normalizer import normalize_file_hand
        from app.services.hand_service import upsert_hand

        upserted = 0
        skipped = 0

        async with self.session_factory() as session:  # type: ignore[operator]
            for raw in records:
                try:
                    normalize_hand_players(
                        raw["players"],
                        Decimal(str(raw["stakes_bb"])),
                        raw.get("button_seat"),
                    )
                    payload = normalize_file_hand(raw, self.club_id)
                    await upsert_hand(session, payload)
                    upserted += 1
                except Exception as exc:
                    errors.append(f"hands/{raw.get('external_id', '?')}: {exc}")
                    skipped += 1
            await session.commit()

        return upserted, skipped

    # ── Batch upload entrypoint (multi-file, auto-club, duplicate detection) ──

    async def run_from_uploads(self, file_texts: list[str]) -> "BatchIngestResult":
        """
        Parse and ingest multiple hand-history texts with duplicate detection.

        Clubs are auto-upserted from data embedded in the files — no club_id
        query parameter required.  Hands that already exist in the DB are
        counted as duplicates and skipped rather than re-upserted.
        """
        from decimal import Decimal

        from app.features.normalize_hand import normalize_hand_players
        from app.ingestion.base import BatchIngestResult
        from app.ingestion.normalizer import normalize_file_hand
        from app.services.hand_service import get_existing_external_ids, upsert_hand
        from app.services.player_service import upsert_club

        start = time.monotonic()
        errors: list[str] = []
        all_raw: list[dict[str, Any]] = []
        parse_failures = 0

        # ── Phase 1: parse all files (pure Python, no DB) ────────────────────
        for i, text in enumerate(file_texts, 1):
            blocks = [b.strip() for b in _HAND_BLOCK_RE.split(text) if b.strip()]
            for block in blocks:
                try:
                    all_raw.append(self._parser.parse(block))
                except ValueError as exc:
                    parse_failures += 1
                    errors.append(f"file_{i}: parse error — {exc}")

        hands_parsed = len(all_raw)

        # ── Phase 2: persist (single session) ────────────────────────────────
        imported = 0
        duplicates = 0

        async with self.session_factory() as session:  # type: ignore[operator]
            # Auto-upsert every club referenced in the files
            clubs_seen: dict[int, str] = {}
            for raw in all_raw:
                ext_id = raw.get("club_external_id")
                name = raw.get("club_name") or f"Club {ext_id}"
                if ext_id is not None and ext_id not in clubs_seen:
                    clubs_seen[int(ext_id)] = name
            for ext_id, name in clubs_seen.items():
                await upsert_club(session, ext_id, name)
            await session.flush()

            # Deduplicate within the batch (same hand in multiple files)
            seen_in_batch: set[str] = set()
            deduped: list[dict[str, Any]] = []
            for raw in all_raw:
                eid = str(raw.get("external_id", ""))
                if eid in seen_in_batch:
                    duplicates += 1
                else:
                    seen_in_batch.add(eid)
                    deduped.append(raw)

            # Batch-check which hand IDs already exist in DB
            existing = await get_existing_external_ids(session, list(seen_in_batch))

            for raw in deduped:
                ext_id = str(raw.get("external_id", ""))
                if ext_id in existing:
                    duplicates += 1
                    continue
                try:
                    normalize_hand_players(
                        raw["players"],
                        Decimal(str(raw["stakes_bb"])),
                        raw.get("button_seat"),
                    )
                    payload = normalize_file_hand(raw, str(raw.get("club_external_id", "")))
                    await upsert_hand(session, payload)
                    imported += 1
                except Exception as exc:
                    errors.append(f"hands/{ext_id}: {exc}")
                    parse_failures += 1

            await session.commit()

        return BatchIngestResult(
            files_processed=len(file_texts),
            hands_parsed=hands_parsed,
            hands_imported=imported,
            duplicates_skipped=duplicates,
            parse_failures=parse_failures,
            errors=errors,
            duration_seconds=time.monotonic() - start,
        )

    # ── Direct text upload entrypoint ─────────────────────────────────────────

    async def run_from_text(self, text: str) -> IngestResult:
        """Parse and ingest a hand history from raw text (used by the upload endpoint)."""
        start = time.monotonic()
        errors: list[str] = []
        raw_records: list[dict[str, Any]] = []

        try:
            raw_records = self._parse_text(text)
        except Exception as exc:
            errors.append(str(exc))
            return IngestResult(
                domain=IngestDomain.HANDS,
                club_id=self.club_id,
                errors=errors,
                duration_seconds=time.monotonic() - start,
            )

        upserted, skipped = await self.persist(IngestDomain.HANDS, raw_records, errors)
        return IngestResult(
            domain=IngestDomain.HANDS,
            club_id=self.club_id,
            records_fetched=len(raw_records),
            records_upserted=upserted,
            records_skipped=skipped,
            errors=errors,
            duration_seconds=time.monotonic() - start,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _parse_text(self, text: str) -> list[dict[str, Any]]:
        blocks = [b.strip() for b in _HAND_BLOCK_RE.split(text) if b.strip()]
        results = []
        for block in blocks:
            try:
                results.append(self._parser.parse(block))
            except ValueError as exc:
                logger.warning("Skipping unparseable block: %s", exc)
        return results

    def _move_to_processed(self, path: Path) -> None:
        dest = self._processed_dir / path.name
        path.rename(dest)

    def _move_to_failed(self, path: Path, error: str) -> None:
        dest = self._failed_dir / path.name
        path.rename(dest)
        (self._failed_dir / f"{path.name}.error").write_text(error, encoding="utf-8")

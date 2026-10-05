from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.leaks import PlayerLeaksOut
from app.schemas.stats import PlayerStatsOut


class LinkPlayerRequest(BaseModel):
    player_id: uuid.UUID
    is_primary: bool = True


class LinkedPlayerOut(BaseModel):
    model_config = {"from_attributes": True}

    player_id: uuid.UUID
    player_username: str
    is_primary: bool
    is_stub: bool
    linked_at: datetime


class MeSummaryOut(BaseModel):
    hands_analyzed: int
    biggest_leak: str | None
    leaks_count: int
    analysis_note: str


class MeAnalysisOut(BaseModel):
    player_id: uuid.UUID
    player_username: str
    summary: MeSummaryOut
    stats: PlayerStatsOut
    leaks: PlayerLeaksOut


class HandPlayerSummaryOut(BaseModel):
    player_id: uuid.UUID
    username: str | None
    position: str | None
    stack_bb: str | None


class MeHandOut(BaseModel):
    hand_external_id: str
    table_name: str | None
    position: str | None
    stack_bb: str | None
    net_won: str | None  # chips
    net_won_bb: str | None = None  # net_won / big blind (derived)
    board_cards: str | None
    hand_started_at: datetime
    player_count: int
    hero_player_id: uuid.UUID
    hero_username: str | None = None
    all_players: list[HandPlayerSummaryOut] = []


class MeHandsOut(BaseModel):
    player_id: uuid.UUID
    hands: list[MeHandOut]
    total: int


class MeImportSummary(BaseModel):
    files_processed: int
    hands_parsed: int
    hands_imported: int
    duplicates_skipped: int
    parse_failures: int
    errors: list[str]
    duration_seconds: float
    detected_player_username: str | None = None
    detected_player_id: str | None = None
    player_linked: bool = False
    player_is_primary: bool = False
    link_message: str = ""

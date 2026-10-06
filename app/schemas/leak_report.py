from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class LeakFindingOut(BaseModel):
    leak_id: str
    category: str
    title: str
    description: str
    evidence: list[str]
    confidence: str
    severity: str
    frequency: float | None = None
    sample_size: int
    limitations: str
    suggested_fix: str


class LeakReportOut(BaseModel):
    player_id: uuid.UUID
    leaks: list[LeakFindingOut]
    summary: str
    total_hands_analyzed: int
    sample_size: int
    generated_at: datetime

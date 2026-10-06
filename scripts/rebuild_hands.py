"""Re-derive actions, winners and results for every stored hand from raw_text.

Run after any parser change that alters actions or results. Re-importing the
files won't do it: duplicates are skipped and actions/winners are inserted
with ON CONFLICT DO NOTHING.
Per hand: delete its actions + winners, then re-run the normal file pipeline
(parse → normalize_hand_players → normalize_file_hand → upsert_hand).
All in one transaction.

Back up first:   pg_dump clubgg > clubgg_backup.sql
Run:             uv run python scripts/rebuild_hands.py
"""

import asyncio
from decimal import Decimal

from sqlalchemy import delete, select

from app.db.session import AsyncSessionFactory
from app.features.normalize_hand import normalize_hand_players
from app.ingestion.hand_parser import HandHistoryParser
from app.ingestion.normalizer import normalize_file_hand
from app.models.hand import Hand, HandWinner, PlayerAction
from app.models.player import Club
from app.services.hand_service import upsert_hand


async def main() -> None:
    parser = HandHistoryParser()
    async with AsyncSessionFactory() as s:
        rows = (
            await s.execute(
                select(Hand.id, Hand.external_id, Hand.raw_text, Club.external_id).join(
                    Club, Club.id == Hand.club_id
                )
            )
        ).all()
        done = 0
        for hand_id, ext_id, raw_text, club_ext in rows:
            raw = parser.parse(raw_text)
            assert raw["external_id"] == ext_id, ext_id
            await s.execute(delete(PlayerAction).where(PlayerAction.hand_id == hand_id))
            await s.execute(delete(HandWinner).where(HandWinner.hand_id == hand_id))
            normalize_hand_players(
                raw["players"], Decimal(str(raw["stakes_bb"])), raw.get("button_seat")
            )
            await upsert_hand(s, normalize_file_hand(raw, str(club_ext)))
            done += 1
        await s.commit()
    print(f"rebuilt {done} hands")


asyncio.run(main())

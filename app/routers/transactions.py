import uuid
from datetime import datetime

from fastapi import APIRouter, Query

from app.dependencies import DBSession
from app.models.transaction import TransactionType
from app.schemas.common import PaginatedResponse
from app.schemas.transaction import ChipTransactionOut
from app.services.transaction_service import list_transactions

router = APIRouter()


@router.get("/", response_model=PaginatedResponse[ChipTransactionOut])
async def list_transactions_route(
    db: DBSession,
    club_id: uuid.UUID | None = None,
    player_id: uuid.UUID | None = None,
    agent_id: uuid.UUID | None = None,
    transaction_type: TransactionType | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> PaginatedResponse[ChipTransactionOut]:
    return await list_transactions(
        db,
        club_id=club_id,
        player_id=player_id,
        agent_id=agent_id,
        transaction_type=transaction_type,
        from_date=from_date,
        to_date=to_date,
        page=page,
        page_size=page_size,
    )

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class IngestDomain(StrEnum):
    HANDS = "hands"
    PLAYERS = "players"
    TRANSACTIONS = "transactions"
    TABLES = "tables"


@dataclass
class IngestResult:
    domain: IngestDomain
    club_id: str
    records_fetched: int = 0
    records_upserted: int = 0
    records_skipped: int = 0
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0


@dataclass
class BatchIngestResult:
    files_processed: int = 0
    hands_parsed: int = 0
    hands_imported: int = 0
    duplicates_skipped: int = 0
    parse_failures: int = 0
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0


class AbstractIngestor(ABC):
    """
    Base class for all ingestors.

    Subclasses implement domain-specific fetch + upsert logic.
    The `run()` method handles timing and error aggregation; call it
    from scheduler jobs or manual trigger endpoints.
    """

    def __init__(self, club_id: str, session_factory: object) -> None:
        self.club_id = club_id
        self.session_factory = session_factory

    # ── Abstract fetch methods ────────────────────────────────────────────────

    @abstractmethod
    async def fetch_hands(self, since: datetime | None) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def fetch_players(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def fetch_transactions(self, since: datetime | None) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def fetch_tables(self) -> list[dict[str, Any]]: ...

    # ── Persistence (implemented by subclasses or mixed-in) ──────────────────

    async def persist(
        self, domain: IngestDomain, records: list[dict[str, Any]], errors: list[str]
    ) -> tuple[int, int]:
        """
        Normalize raw records and upsert via the service layer.
        Returns (upserted_count, skipped_count).
        Override in subclasses that handle persistence differently.
        """
        from app.ingestion import normalizer
        from app.services import hand_service, player_service, session_service, transaction_service

        upserted = 0
        skipped = 0

        async with self.session_factory() as session:  # type: ignore[operator]
            for raw in records:
                try:
                    if domain == IngestDomain.HANDS:
                        await hand_service.upsert_hand(
                            session, normalizer.normalize_api_hand(raw, self.club_id)
                        )
                    elif domain == IngestDomain.PLAYERS:
                        await player_service.upsert_player(
                            session, normalizer.normalize_api_player(raw, self.club_id)
                        )
                    elif domain == IngestDomain.TRANSACTIONS:
                        await transaction_service.upsert_transaction(
                            session, normalizer.normalize_api_transaction(raw, self.club_id)
                        )
                    elif domain == IngestDomain.TABLES:
                        await session_service.upsert_session(
                            session, normalizer.normalize_api_table(raw, self.club_id)
                        )
                    upserted += 1
                except Exception as exc:
                    errors.append(f"{domain}/{raw.get('id', '?')}: {exc}")
                    skipped += 1
            await session.commit()

        return upserted, skipped

    # ── Entrypoint ────────────────────────────────────────────────────────────

    async def run(self, domain: IngestDomain, since: datetime | None = None) -> IngestResult:
        """Fetch, normalize, and upsert one domain. Returns an IngestResult."""
        start = time.monotonic()
        errors: list[str] = []
        raw_records: list[dict[str, Any]] = []

        try:
            raw_records = await self._dispatch_fetch(domain, since)
        except Exception as exc:
            errors.append(str(exc))
            return IngestResult(
                domain=domain,
                club_id=self.club_id,
                errors=errors,
                duration_seconds=time.monotonic() - start,
            )

        upserted, skipped = await self.persist(domain, raw_records, errors)
        return IngestResult(
            domain=domain,
            club_id=self.club_id,
            records_fetched=len(raw_records),
            records_upserted=upserted,
            records_skipped=skipped,
            errors=errors,
            duration_seconds=time.monotonic() - start,
        )

    async def _dispatch_fetch(
        self, domain: IngestDomain, since: datetime | None
    ) -> list[dict[str, Any]]:
        if domain == IngestDomain.HANDS:
            return await self.fetch_hands(since)
        if domain == IngestDomain.PLAYERS:
            return await self.fetch_players()
        if domain == IngestDomain.TRANSACTIONS:
            return await self.fetch_transactions(since)
        if domain == IngestDomain.TABLES:
            return await self.fetch_tables()
        raise ValueError(f"Unknown domain: {domain}")

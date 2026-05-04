"""
ClubGGApiIngestor — polls ClubGG's internal REST API to ingest all four
data domains (hands, players, transactions, tables).

Auth: every request carries X-Club-ID and X-API-Key headers.
Pagination: ClubGG endpoints return {"data": [...], "next_cursor": str|null}.
"""
import logging
from datetime import datetime

import httpx

from app.config import settings
from app.ingestion.base import AbstractIngestor, IngestDomain

logger = logging.getLogger(__name__)


class ClubGGApiIngestor(AbstractIngestor):
    def __init__(
        self,
        club_id: str,
        session_factory: object,
        api_key: str | None = None,
    ) -> None:
        super().__init__(club_id, session_factory)
        self._api_key = (
            # Per-club key takes precedence: CLUBGG_API_KEY_<CLUB_ID>
            getattr(settings, f"CLUBGG_API_KEY_{club_id}", None)
            or api_key
            or settings.CLUBGG_API_KEY
        )
        self._client: httpx.AsyncClient | None = None

    # ── HTTP client ───────────────────────────────────────────────────────────

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=settings.CLUBGG_BASE_URL,
                headers={
                    "X-Club-ID": self.club_id,
                    "X-API-Key": self._api_key,
                },
                timeout=settings.CLUBGG_REQUEST_TIMEOUT,
            )
        return self._client

    async def _paginate(self, path: str, params: dict) -> list[dict]:
        """Fetch all pages from a cursor-paginated ClubGG endpoint."""
        client = await self._client_()
        results: list[dict] = []
        cursor: str | None = None

        while True:
            if cursor:
                params = {**params, "cursor": cursor}
            resp = await client.get(path, params=params)
            resp.raise_for_status()
            body: dict = resp.json()
            results.extend(body.get("data", []))
            cursor = body.get("next_cursor")
            if not cursor:
                break

        logger.debug("Fetched %d records from %s (club %s)", len(results), path, self.club_id)
        return results

    # ── Fetch methods ─────────────────────────────────────────────────────────

    async def fetch_hands(self, since: datetime | None = None) -> list[dict]:
        params: dict = {"club_id": self.club_id, "page_size": 200}
        if since:
            params["since"] = since.isoformat()
        return await self._paginate("/api/hands", params)

    async def fetch_players(self) -> list[dict]:
        return await self._paginate(
            "/api/players", {"club_id": self.club_id, "page_size": 500}
        )

    async def fetch_transactions(self, since: datetime | None = None) -> list[dict]:
        params: dict = {"club_id": self.club_id, "page_size": 200}
        if since:
            params["since"] = since.isoformat()
        return await self._paginate("/api/transactions", params)

    async def fetch_tables(self) -> list[dict]:
        return await self._paginate(
            "/api/tables", {"club_id": self.club_id, "status": "active", "page_size": 100}
        )

    # ── Checkpoint helpers ────────────────────────────────────────────────────

    async def _get_since(self, domain: IngestDomain) -> datetime | None:
        """Return last_fetched_at from ingest_checkpoints for (club_id, domain)."""
        from sqlalchemy import text

        async with self.session_factory() as session:  # type: ignore[operator]
            row = await session.execute(
                text(
                    "SELECT last_fetched_at FROM ingest_checkpoints "
                    "WHERE club_id = :club_id AND domain = :domain"
                ),
                {"club_id": self.club_id, "domain": domain.value},
            )
            result = row.fetchone()
            return result[0] if result else None

    async def _update_checkpoint(self, domain: IngestDomain, ts: datetime) -> None:
        from sqlalchemy import text

        async with self.session_factory() as session:  # type: ignore[operator]
            await session.execute(
                text(
                    "INSERT INTO ingest_checkpoints (club_id, domain, last_fetched_at) "
                    "VALUES (:club_id, :domain, :ts) "
                    "ON CONFLICT (club_id, domain) DO UPDATE SET last_fetched_at = EXCLUDED.last_fetched_at"
                ),
                {"club_id": self.club_id, "domain": domain.value, "ts": ts},
            )
            await session.commit()

    async def run(self, domain: IngestDomain, since: datetime | None = None) -> "IngestResult":  # type: ignore[override]
        from datetime import timezone

        from app.ingestion.base import IngestResult

        # Auto-load the since cursor from checkpoints unless caller provided one
        effective_since = since if since is not None else await self._get_since(domain)
        result = await super().run(domain, since=effective_since)

        if not result.errors:
            await self._update_checkpoint(domain, datetime.now(tz=timezone.utc))

        return result

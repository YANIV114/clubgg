"""
APScheduler setup for background ingestion jobs.

One set of jobs is registered per club_id in CLUBGG_CLUB_IDS:
  - api_hands_{club_id}        — every INGEST_HANDS_INTERVAL_SECONDS
  - api_transactions_{club_id} — every INGEST_TRANSACTIONS_INTERVAL_SECONDS
  - api_players_{club_id}      — every INGEST_PLAYERS_INTERVAL_SECONDS
  - api_tables_{club_id}       — every INGEST_TABLES_INTERVAL_SECONDS

One global file-watcher job:
  - file_hand_histories        — every INGEST_FILE_POLL_INTERVAL_SECONDS

Jobs are persisted in PostgreSQL (sync psycopg2 DSN) so they survive restarts.
"""
import logging

from app.config import settings

logger = logging.getLogger(__name__)

_scheduler = None


async def _run_api_job(club_id: str, domain_str: str) -> None:
    from app.db.session import AsyncSessionFactory
    from app.ingestion.base import IngestDomain
    from app.ingestion.clubgg_api import ClubGGApiIngestor

    ingestor = ClubGGApiIngestor(club_id, AsyncSessionFactory)
    result = await ingestor.run(IngestDomain(domain_str))
    if result.errors:
        logger.warning(
            "Ingest %s/%s finished with errors: %s", club_id, domain_str, result.errors
        )
    else:
        logger.info(
            "Ingest %s/%s: fetched=%d upserted=%d (%.2fs)",
            club_id,
            domain_str,
            result.records_fetched,
            result.records_upserted,
            result.duration_seconds,
        )


async def _run_file_job() -> None:
    from app.db.session import AsyncSessionFactory
    from app.ingestion.base import IngestDomain
    from app.ingestion.hand_parser import HandHistoryFileIngestor

    for club_id in settings.club_ids:
        ingestor = HandHistoryFileIngestor(club_id, AsyncSessionFactory)
        result = await ingestor.run(IngestDomain.HANDS)
        logger.info(
            "File ingest %s: fetched=%d upserted=%d",
            club_id,
            result.records_fetched,
            result.records_upserted,
        )


async def start_scheduler() -> None:
    global _scheduler

    if not settings.club_ids:
        logger.info("No CLUBGG_CLUB_IDS configured — scheduler will not register API jobs")

    try:
        from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
        from apscheduler.schedulers.asyncio import AsyncIOScheduler

        # APScheduler's SQLAlchemy job store is synchronous; strip asyncpg driver
        sync_dsn = settings.DATABASE_URL.replace("+asyncpg", "")

        jobstores = {"default": SQLAlchemyJobStore(url=sync_dsn)}
        _scheduler = AsyncIOScheduler(jobstores=jobstores, timezone="UTC")

        for club_id in settings.club_ids:
            _scheduler.add_job(
                _run_api_job,
                "interval",
                seconds=settings.INGEST_HANDS_INTERVAL_SECONDS,
                args=[club_id, "hands"],
                id=f"api_hands_{club_id}",
                replace_existing=True,
                misfire_grace_time=60,
            )
            _scheduler.add_job(
                _run_api_job,
                "interval",
                seconds=settings.INGEST_TRANSACTIONS_INTERVAL_SECONDS,
                args=[club_id, "transactions"],
                id=f"api_transactions_{club_id}",
                replace_existing=True,
                misfire_grace_time=60,
            )
            _scheduler.add_job(
                _run_api_job,
                "interval",
                seconds=settings.INGEST_PLAYERS_INTERVAL_SECONDS,
                args=[club_id, "players"],
                id=f"api_players_{club_id}",
                replace_existing=True,
            )
            _scheduler.add_job(
                _run_api_job,
                "interval",
                seconds=settings.INGEST_TABLES_INTERVAL_SECONDS,
                args=[club_id, "tables"],
                id=f"api_tables_{club_id}",
                replace_existing=True,
            )

        _scheduler.add_job(
            _run_file_job,
            "interval",
            seconds=settings.INGEST_FILE_POLL_INTERVAL_SECONDS,
            id="file_hand_histories",
            replace_existing=True,
        )

        _scheduler.start()
        logger.info("APScheduler started with %d jobs", len(_scheduler.get_jobs()))

    except Exception as exc:
        logger.error("Failed to start scheduler: %s", exc)
        _scheduler = None


async def shutdown_scheduler() -> None:
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped")

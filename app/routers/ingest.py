import logging
from typing import Literal

from fastapi import APIRouter, Body, File, HTTPException, UploadFile

from app.config import settings
from app.db.session import AsyncSessionFactory
from app.ingestion.base import IngestDomain
from app.ingestion.clubgg_api import ClubGGApiIngestor
from app.ingestion.hand_parser import HandHistoryFileIngestor
from app.schemas.common import ImportSummary, UpsertResult

logger = logging.getLogger(__name__)
router = APIRouter()

IngestDomainLiteral = Literal["hands", "players", "transactions", "tables"]


@router.post("/api/trigger", status_code=202, response_model=list[UpsertResult])
async def trigger_api_ingest(
    club_id: str = Body(...),
    domains: list[IngestDomainLiteral] = Body(...),
) -> list[UpsertResult]:
    """Manually trigger an API ingestion run for a specific club and set of domains."""
    if club_id not in settings.club_ids:
        raise HTTPException(status_code=400, detail=f"Unknown club_id: {club_id}")

    ingestor = ClubGGApiIngestor(club_id, AsyncSessionFactory)
    results: list[UpsertResult] = []
    for domain_str in domains:
        result = await ingestor.run(IngestDomain(domain_str))
        results.append(
            UpsertResult(
                records_fetched=result.records_fetched,
                records_upserted=result.records_upserted,
                records_skipped=result.records_skipped,
                errors=result.errors,
                duration_seconds=result.duration_seconds,
            )
        )
    return results


@router.post("/file", status_code=202, response_model=UpsertResult)
async def upload_hand_history_file(
    club_id: str,
    file: UploadFile,
) -> UpsertResult:
    """Upload a ClubGG hand history .txt file for immediate parsing and ingestion."""
    if not file.filename or not file.filename.endswith(".txt"):
        raise HTTPException(status_code=400, detail="Only .txt hand history files accepted")

    content = await file.read()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded")

    ingestor = HandHistoryFileIngestor(club_id, AsyncSessionFactory)
    result = await ingestor.run_from_text(text)
    return UpsertResult(
        records_fetched=result.records_fetched,
        records_upserted=result.records_upserted,
        records_skipped=result.records_skipped,
        errors=result.errors,
        duration_seconds=result.duration_seconds,
    )


@router.post("/upload", response_model=ImportSummary)
async def upload_hand_history_files(
    files: list[UploadFile] = File(...),
) -> ImportSummary:
    """
    Upload one or more ClubGG hand history .txt files.

    - Club is auto-created from data embedded in the file headers.
    - Hands already in the database are counted as duplicates and skipped.
    - Returns a per-file breakdown: parsed, imported, duplicates, failures.
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")

    texts: list[str] = []
    for f in files:
        if not f.filename or not f.filename.endswith(".txt"):
            raise HTTPException(
                status_code=400,
                detail=f"{f.filename!r}: only .txt hand history files accepted",
            )
        content = await f.read()
        try:
            texts.append(content.decode("utf-8"))
        except UnicodeDecodeError:
            raise HTTPException(
                status_code=400,
                detail=f"{f.filename!r}: file must be UTF-8 encoded",
            )

    ingestor = HandHistoryFileIngestor("", AsyncSessionFactory)
    result = await ingestor.run_from_uploads(texts)
    return ImportSummary(
        files_processed=result.files_processed,
        hands_parsed=result.hands_parsed,
        hands_imported=result.hands_imported,
        duplicates_skipped=result.duplicates_skipped,
        parse_failures=result.parse_failures,
        errors=result.errors,
        duration_seconds=result.duration_seconds,
    )

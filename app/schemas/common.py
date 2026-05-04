from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    has_next: bool

    model_config = ConfigDict(arbitrary_types_allowed=True)


class UpsertResult(BaseModel):
    records_fetched: int
    records_upserted: int
    records_skipped: int
    errors: list[str]
    duration_seconds: float


class ImportSummary(BaseModel):
    files_processed: int
    hands_parsed: int
    hands_imported: int
    duplicates_skipped: int
    parse_failures: int
    errors: list[str]
    duration_seconds: float

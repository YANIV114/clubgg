"""
test_services-scoped fixtures.

The me_import tests use AsyncSessionFactory (committed sessions), so any hands
they insert persist in the real DB and pollute count-based hand_records tests.
This conftest truncates the hands tables once per pytest session before the
hand_records integration tests run.
"""

import os

import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

_TEST_DB_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://yaniv@localhost:5432/clubgg_test")

_TABLES = [
    "player_actions",
    "hand_winners",
    "hand_players",
    "hands",
]


@pytest_asyncio.fixture(scope="session", autouse=True)
async def clean_committed_hands():
    """Truncate committed hand data before this test module's session starts."""
    if not os.getenv("DATABASE_URL"):
        yield
        return
    engine = create_async_engine(_TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        for table in _TABLES:
            await conn.execute(sa.text(f"TRUNCATE {table} CASCADE"))
    await engine.dispose()
    yield

"""
Shared pytest fixtures for the ClubGG test suite.

Tests that require a live database are marked with @pytest.mark.integration
and are skipped unless DATABASE_URL is set in the environment.
Unit tests (parser, normalizer) run without any DB.

Integration fixture design
--------------------------
Each integration test function gets its own rolled-back transaction so tests
are fully isolated:

    test_engine   (session-scoped) — created once per pytest session
    db_session    (function-scoped) — wrapped in BEGIN/ROLLBACK per test
    async_client  (function-scoped) — FastAPI TestClient overriding get_db

The rollback pattern means the DB starts clean for every test without
paying the cost of table truncation or schema recreation.
"""
import os
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# ── Paths ─────────────────────────────────────────────────────────────────────

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# ── Markers ───────────────────────────────────────────────────────────────────


@pytest.fixture
def sample_hand_history_text() -> str:
    return (FIXTURES_DIR / "sample_hand_history.txt").read_text(encoding="utf-8")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "integration: mark test as requiring a live PostgreSQL database"
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if not os.getenv("DATABASE_URL"):
        skip_db = pytest.mark.skip(reason="DATABASE_URL not set")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip_db)


# ── Beta gate ─────────────────────────────────────────────────────────────────

TEST_INVITE_CODE = "test-invite-code"


@pytest.fixture
def beta_gate(monkeypatch: pytest.MonkeyPatch) -> str:
    """Enable the beta gate with TEST_INVITE_CODE, as in production.

    Users registered with this invite code get is_tester=True and can reach
    routes protected by require_tester.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "BETA_INVITE_CODE", TEST_INVITE_CODE)
    return TEST_INVITE_CODE


# ── DB integration fixtures ───────────────────────────────────────────────────
# Only instantiated when DATABASE_URL is set.


_TEST_DB_URL = os.getenv(
    "DATABASE_URL", "postgresql+asyncpg://yaniv@localhost:5432/clubgg_test"
)


@pytest_asyncio.fixture
async def test_engine():
    """One async engine per test function, disposed on exit."""
    engine = create_async_engine(_TEST_DB_URL, echo=False)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine: Any) -> AsyncGenerator[AsyncSession, None]:
    """
    One async session per test, fully isolated via transaction rollback.

    BEGIN → [test runs] → ROLLBACK.  Nothing is committed to the DB.
    Uses a savepoint so that code under test can use session.begin_nested()
    without conflicting with the outer transaction.
    """
    async with test_engine.connect() as conn:
        await conn.begin()
        # Expose the connection as a session factory
        factory = async_sessionmaker(conn, expire_on_commit=False, autoflush=False)
        async with factory() as session:
            yield session
        await conn.rollback()


@pytest_asyncio.fixture
async def async_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """
    HTTPX AsyncClient wired to the FastAPI app with get_db overridden to use
    the test session.  Because the session is shared, all DB writes made via
    the endpoint are visible in the test's db_session and are rolled back
    after the test.
    """
    from app.db.session import get_db
    from app.lifespan import lifespan
    from app.main import app

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    # Disable lifespan so the scheduler doesn't start during tests
    app.router.lifespan_context = lifespan  # kept but scheduler needs DB
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)

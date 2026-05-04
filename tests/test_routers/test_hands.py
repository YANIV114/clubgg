"""
Smoke tests for the /api/v1/hands router.
These use FastAPI's TestClient and mock the service layer — no DB needed.
"""

import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import require_tester
from app.main import app
from app.schemas.common import PaginatedResponse
from app.schemas.hand import HandOut


def _make_tester() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), role="player", is_tester=True, is_active=True)


@pytest.fixture
def client() -> TestClient:
    @asynccontextmanager
    async def noop_lifespan(app: FastAPI):
        yield

    app.router.lifespan_context = noop_lifespan
    tester = _make_tester()
    app.dependency_overrides[require_tester] = lambda: tester
    try:
        yield TestClient(app, raise_server_exceptions=True)
    finally:
        app.dependency_overrides.pop(require_tester, None)


class TestHandsRouter:
    def test_list_hands_returns_200(self, client: TestClient) -> None:
        empty_page: PaginatedResponse[HandOut] = PaginatedResponse(
            items=[], total=0, page=1, page_size=50, has_next=False
        )
        with patch("app.routers.hands.list_hands", new_callable=AsyncMock, return_value=empty_page):
            resp = client.get("/api/v1/hands/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_get_hand_not_found(self, client: TestClient) -> None:
        with patch("app.routers.hands.get_hand", new_callable=AsyncMock, return_value=None):
            resp = client.get("/api/v1/hands/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    def test_health_endpoint(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

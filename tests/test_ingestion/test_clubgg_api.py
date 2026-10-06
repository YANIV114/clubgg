"""
Tests for ClubGGApiIngestor (no live DB or real API required).
Uses httpx mock transport to simulate ClubGG API responses.
"""
import pytest
import httpx

from app.ingestion.clubgg_api import ClubGGApiIngestor


class MockTransport(httpx.MockTransport if hasattr(httpx, "MockTransport") else object):
    """Minimal mock transport that returns a fixed response."""

    def __init__(self, responses: dict[str, dict]) -> None:
        self._responses = responses

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        for pattern, resp in self._responses.items():
            if pattern in path:
                return httpx.Response(200, json=resp)
        return httpx.Response(404, json={"error": "not found"})


class TestClubGGApiIngestor:
    def test_instantiation(self) -> None:
        ingestor = ClubGGApiIngestor(club_id="42", session_factory=None, api_key="test-key")
        assert ingestor.club_id == "42"

    def test_api_key_from_settings_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CLUBGG_API_KEY", "env-key")
        # Build a fresh Settings rather than reloading app.config: a reload
        # replaces the module-level `settings` and leaves other modules
        # holding the stale instance, which breaks later monkeypatching.
        from app.config import Settings

        assert Settings().CLUBGG_API_KEY == "env-key"

    @pytest.mark.asyncio
    async def test_fetch_hands_empty(self) -> None:
        """fetch_hands should return an empty list when API returns no data."""
        ingestor = ClubGGApiIngestor(club_id="42", session_factory=None, api_key="k")
        # Override the client with one backed by a mock transport
        ingestor._client = httpx.AsyncClient(
            base_url="https://mock.clubgg.test",
            transport=httpx.MockTransport(  # type: ignore[attr-defined]
                lambda req: httpx.Response(200, json={"data": [], "next_cursor": None})
            ),
        )
        result = await ingestor.fetch_hands(since=None)
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_hands_pagination(self) -> None:
        """fetch_hands should follow next_cursor until exhausted."""
        pages = [
            {"data": [{"id": "h1"}], "next_cursor": "page2"},
            {"data": [{"id": "h2"}], "next_cursor": None},
        ]
        call_count = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal call_count
            resp = pages[min(call_count, len(pages) - 1)]
            call_count += 1
            return httpx.Response(200, json=resp)

        ingestor = ClubGGApiIngestor(club_id="42", session_factory=None, api_key="k")
        ingestor._client = httpx.AsyncClient(
            base_url="https://mock.clubgg.test",
            transport=httpx.MockTransport(handler),  # type: ignore[attr-defined]
        )
        result = await ingestor.fetch_hands(since=None)
        assert len(result) == 2
        assert call_count == 2

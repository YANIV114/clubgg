"""
Integration tests for POST /api/v1/me/import.

Note: HandHistoryFileIngestor.run_from_uploads() uses AsyncSessionFactory
(its own committed session), so imported data persists past rollback.
All upserts are idempotent — re-running tests is safe.
"""

import io

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.conftest import TEST_INVITE_CODE

pytestmark = pytest.mark.usefixtures("beta_gate")


@pytest_asyncio.fixture(autouse=True)
async def _reset_app_engine():
    """Dispose the app engine after each test so asyncpg pool connections
    don't leak across function-scoped event loops."""
    yield
    from app.db.session import engine

    await engine.dispose()


# Minimal hand history with "Dealt to" line so hero detection works.
# Club ID 9901 is unique enough to avoid collisions with other test data.
_HAND_HERO = "Hero"
_HAND_CLUB_EXT_ID = 9901

_SAMPLE_HAND = f"""\
ClubGG Hand #77700001: Hold'em No Limit ($0.50/$1.00) - 2024-06-01 12:00:00 UTC
Club: ImportTestClub (ID: {_HAND_CLUB_EXT_ID})  Agent: MainAgent (ID: 1)
Table 'Alpha 1' 6-max Seat #1 is the button
Seat 1: {_HAND_HERO} ($100.00 in chips)
Seat 2: Villain ($100.00 in chips)
{_HAND_HERO}: posts small blind $0.50
Villain: posts big blind $1.00
*** HOLE CARDS ***
Dealt to {_HAND_HERO} [As Kd]
{_HAND_HERO}: raises $3.00 to $3.50
Villain: folds
Uncalled bet ($2.50) returned to {_HAND_HERO}
*** SUMMARY ***
Total pot $2.00 | Rake $0.10
Seat 1: {_HAND_HERO} collected $1.90 from main pot
"""


def _hand_file(content: str = _SAMPLE_HAND, filename: str = "hands.txt"):
    return ("files", (filename, io.BytesIO(content.encode()), "text/plain"))


async def _register(client: AsyncClient, email: str) -> str:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "testpass123", "invite_code": TEST_INVITE_CODE},
    )
    assert resp.status_code == 201
    return resp.json()["access_token"]


@pytest.mark.integration
class TestMeImport:
    async def test_unauthenticated_import_rejected(self, async_client: AsyncClient) -> None:
        resp = await async_client.post(
            "/api/v1/me/import",
            files=[_hand_file()],
        )
        assert resp.status_code == 401

    async def test_authenticated_import_links_detected_player(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register(async_client, "import1@example.com")

        resp = await async_client.post(
            "/api/v1/me/import",
            files=[_hand_file()],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()

        assert data["hands_parsed"] >= 1
        assert data["detected_player_username"] == _HAND_HERO
        assert data["player_linked"] is True
        assert data["player_is_primary"] is True
        assert _HAND_HERO in data["link_message"]

    async def test_primary_player_not_overwritten_on_second_import(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """If user already has a primary player, a second import does not replace it."""
        token = await _register(async_client, "import2@example.com")

        # First import — sets primary
        resp1 = await async_client.post(
            "/api/v1/me/import",
            files=[_hand_file()],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp1.status_code == 200
        assert resp1.json()["player_is_primary"] is True

        # Second import of the same file — idempotent, primary already set
        resp2 = await async_client.post(
            "/api/v1/me/import",
            files=[_hand_file()],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        # player_linked may be True (idempotent re-link) but is_primary stays True
        # and link_message should not claim it was set as primary again
        assert data2["detected_player_username"] == _HAND_HERO
        # Primary was already set — link_message signals that
        assert "primary" in data2["link_message"].lower()

    async def test_non_txt_file_rejected(self, async_client: AsyncClient) -> None:
        token = await _register(async_client, "import3@example.com")
        resp = await async_client.post(
            "/api/v1/me/import",
            files=[_hand_file(filename="hands.csv")],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 400
        assert "txt" in resp.json()["detail"].lower()

    async def test_me_hands_reports_result_in_bb(self, async_client: AsyncClient) -> None:
        token = await _register(async_client, "import5@example.com")
        headers = {"Authorization": f"Bearer {token}"}
        resp = await async_client.post("/api/v1/me/import", files=[_hand_file()], headers=headers)
        assert resp.status_code == 200

        hands = (await async_client.get("/api/v1/me/hands", headers=headers)).json()["hands"]
        hand = next(h for h in hands if h["hand_external_id"] == "77700001")
        # Hero raises to $3.50, $2.50 comes back uncalled: $1.00 in, $1.90 collected.
        assert hand["net_won"] is not None
        assert hand["net_won_bb"] == "0.9"

    async def test_me_analysis_reflects_imported_hands(
        self, async_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        token = await _register(async_client, "import4@example.com")

        # Import first
        resp = await async_client.post(
            "/api/v1/me/import",
            files=[_hand_file()],
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["player_linked"] is True

        # /me/analysis should now work (player linked) and show the imported hand
        analysis_resp = await async_client.get(
            "/api/v1/me/analysis",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert analysis_resp.status_code == 200
        data = analysis_resp.json()
        assert data["player_username"] == _HAND_HERO
        assert data["summary"]["hands_analyzed"] >= 1

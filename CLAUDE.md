# ClubGG Backend

FastAPI backend for ingesting and analyzing data from ClubGG, a private online poker club platform.

## Quick Start

```bash
# Install uv if not present
curl -LsSf https://astral.sh/uv/install.sh | sh

# Create virtualenv and install dependencies
uv sync --extra dev

# Copy and fill environment variables
cp .env.example .env
# Edit .env — at minimum set DATABASE_URL and CLUBGG_API_KEY

# Run database migrations
uv run alembic upgrade head

# Start dev server
uv run uvicorn app.main:app --reload --port 8000
# API docs: http://localhost:8000/docs
```

## Dev Commands

| Command | Purpose |
|---|---|
| `uv sync --extra dev` | Install all dependencies incl. dev |
| `uv run alembic upgrade head` | Apply all pending migrations |
| `uv run alembic revision --autogenerate -m "description"` | Generate new migration from model changes |
| `uv run alembic downgrade -1` | Roll back one migration |
| `uv run pytest` | Run all tests |
| `uv run pytest -x -v` | Stop on first failure, verbose |
| `uv run pytest --cov=app` | Run with coverage report |
| `uv run ruff check .` | Lint |
| `uv run ruff format .` | Format |
| `uv run mypy app/` | Type check |

## Architecture

```
HTTP Clients / File System
        │
        ▼
  Ingestion Layer (app/ingestion/)
    ├── ClubGGApiIngestor   — polls ClubGG REST API via httpx
    └── HandHistoryFileIngestor — parses .txt export files
        │
        ▼ upserts via services
  Service Layer (app/services/)
    ├── hand_service
    ├── player_service
    ├── transaction_service
    └── session_service
        │
        ▼ async ORM calls
  Database Models (app/models/)   →   PostgreSQL (asyncpg)
        ▲
        │
  FastAPI Routers (app/routers/)
        ▲
        │
  Pydantic Schemas (app/schemas/)
```

## Ingestion Modes

### 1. ClubGG REST API (`app/ingestion/clubgg_api.py`)
Polls ClubGG endpoints on a schedule via APScheduler. Auth via `X-Club-ID` and `X-API-Key` headers. Each club in `CLUBGG_CLUB_IDS` gets its own set of scheduler jobs:
- Hands + Transactions: every `INGEST_HANDS_INTERVAL_SECONDS` (default 5 min)
- Players: every `INGEST_PLAYERS_INTERVAL_SECONDS` (default 30 min)
- Tables: every `INGEST_TABLES_INTERVAL_SECONDS` (default 15 min)

Endpoints assumed:
```
GET /api/hands?club_id=&since=&cursor=&page_size=
GET /api/players?club_id=&cursor=&page_size=
GET /api/transactions?club_id=&since=&cursor=&page_size=
GET /api/tables?club_id=&status=active&cursor=&page_size=
```
Response envelope: `{"data": [...], "next_cursor": str | null, "total": int}`

### 2. Hand History File Parser (`app/ingestion/hand_parser.py`)
Watches `HAND_HISTORY_WATCH_DIR` for `.txt` files every `INGEST_FILE_POLL_INTERVAL_SECONDS` (default 60 s). After successful processing, moves files to `HAND_HISTORY_PROCESSED_DIR`. Failed files go to `HAND_HISTORY_WATCH_DIR/failed/` with a `.error` sidecar.

Hand history format is PokerStars-like with ClubGG-specific header lines:
```
ClubGG Hand #12345678: Hold'em No Limit ($0.50/$1.00) - 2024-01-15 22:31:07 UTC
Club: MyClub (ID: 42)  Agent: AgentJohn (ID: 7)
Table 'Diamond 1' 6-max Seat #3 is the button
...
```

### Manual Triggers
```
POST /api/v1/ingest/api/trigger   — trigger API ingest for a club + domain list
POST /api/v1/ingest/file          — upload a hand history file directly
```

## Key Design Decisions

- **UUIDs as primary keys** everywhere. ClubGG's own IDs are stored in `external_id` columns (bigint/varchar) and are the upsert key.
- **Idempotent upserts** via PostgreSQL `INSERT ... ON CONFLICT (external_id) DO UPDATE SET ...`. Re-running any ingestion job is always safe.
- **`ingest_checkpoints` table** tracks `last_fetched_at` per `(club_id, domain)` so the API ingestor only pulls records newer than the last successful run.
- **All chip amounts** are `NUMERIC(20,4)` in the DB and Python `Decimal` in application code — no floating-point.
- **All timestamps** stored as `TIMESTAMP WITH TIME ZONE` in UTC.
- **Alembic** uses the synchronous `psycopg2` driver (DSN has `+psycopg2`). The app uses `asyncpg` at runtime.
- **APScheduler** uses `SQLAlchemyJobStore` backed by the same PostgreSQL instance (sync psycopg2 DSN) so jobs survive restarts.
- **Agent tree** is a self-referential adjacency list on `agents` (`parent_agent_id → agents.id`). Tree traversal uses a recursive CTE when needed.
- **`raw_text`** on `hands` stores the verbatim hand history block so re-parsing is always possible.
- **Stub player creation**: during hand upsert, if a username resolves to no known player, a stub `Player` record is created and marked `is_stub=True` to be enriched by the next player sync.

## Environment Variables

See `.env.example` for all variables with descriptions. Key ones:

| Variable | Description |
|---|---|
| `DATABASE_URL` | asyncpg DSN: `postgresql+asyncpg://user:pass@host:5432/clubgg` |
| `CLUBGG_BASE_URL` | ClubGG API base URL |
| `CLUBGG_CLUB_IDS` | Comma-separated club IDs to ingest |
| `CLUBGG_API_KEY` | Shared API key (or use `CLUBGG_API_KEY_<CLUB_ID>` per club) |
| `HAND_HISTORY_WATCH_DIR` | Directory polled for `.txt` hand history files |
| `ENVIRONMENT` | `development` / `staging` / `production` |

## Adding a New Club
Add the club ID to `CLUBGG_CLUB_IDS` and restart. The scheduler auto-registers all jobs for every club at startup. If the club needs a different API key, set `CLUBGG_API_KEY_<CLUB_ID>=...`.

## Extending the Hand Parser
Add new regex patterns to `HandHistoryParser._patterns` in `app/ingestion/hand_parser.py`. The `parse()` method calls `_parse_header`, `_parse_seats`, `_parse_streets`, and `_parse_summary` — add a new private method and call it from `parse()` if a new section type is needed.

## Data Model Summary

```
clubs ──< agents (self-ref tree) ──< players
                                         │
hands ──< hand_players <───────────────┘
      │       └──< player_actions
      └──< hand_winners
      │
game_sessions ──< seat_assignments ──< players
      │
      └── hands.game_session_id (FK)

chip_transactions → players / agents / hands

ingest_checkpoints  (club_id, domain) → last_fetched_at
```

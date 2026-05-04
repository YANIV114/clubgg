import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.lifespan import lifespan
from app.middleware.logging import RequestLoggingMiddleware, configure_logging
from app.middleware.rate_limit import RateLimitMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.routers import (
    admin,
    auth,
    billing,
    courses,
    hands,
    ingest,
    me,
    onboarding,
    players,
    preferences,
    sessions,
    transactions,
)

configure_logging(
    settings.LOG_LEVEL,
    json_logs=(settings.ENVIRONMENT != "development"),
)

app = FastAPI(
    title="ClubGG Analytics API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(
    RateLimitMiddleware,
    enforce=(settings.ENVIRONMENT != "development"),
)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

app.include_router(
    admin.router,
    prefix=f"{settings.API_PREFIX}",
    tags=["admin"],
)
app.include_router(
    hands.router,
    prefix=f"{settings.API_PREFIX}/hands",
    tags=["hands"],
)
app.include_router(
    players.router,
    prefix=f"{settings.API_PREFIX}/players",
    tags=["players"],
)
app.include_router(
    transactions.router,
    prefix=f"{settings.API_PREFIX}/transactions",
    tags=["transactions"],
)
app.include_router(
    sessions.router,
    prefix=f"{settings.API_PREFIX}/sessions",
    tags=["sessions"],
)
app.include_router(
    ingest.router,
    prefix=f"{settings.API_PREFIX}/ingest",
    tags=["ingest"],
)
app.include_router(
    preferences.router,
    prefix=f"{settings.API_PREFIX}/preferences",
    tags=["preferences"],
)
app.include_router(
    auth.router,
    prefix=f"{settings.API_PREFIX}/auth",
    tags=["auth"],
)
app.include_router(
    billing.router,
    prefix=f"{settings.API_PREFIX}",
    tags=["billing"],
)
app.include_router(
    courses.router,
    prefix=f"{settings.API_PREFIX}",
    tags=["courses"],
)
app.include_router(
    me.router,
    prefix=f"{settings.API_PREFIX}",
    tags=["me"],
)
app.include_router(
    onboarding.router,
    prefix=f"{settings.API_PREFIX}",
    tags=["onboarding"],
)

# Mount frontend static files
_frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(_frontend_dir):
    app.mount("/static", StaticFiles(directory=_frontend_dir), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_dashboard() -> FileResponse:
        return FileResponse(os.path.join(_frontend_dir, "index.html"))

    # Register known SPA routes so history.pushState paths survive page refresh.
    _spa_html = os.path.join(_frontend_dir, "index.html")

    async def _serve_spa(_req: Request) -> FileResponse:
        return FileResponse(_spa_html)

    for _sp_path in (
        "/analysis",
        "/learn",
        "/learn/{course_id}",
        "/learn/{course_id}/{lesson_id}",
        "/trainer",
        "/progress",
        "/account",
        "/pricing",
        "/login",
        "/signup",
        "/onboarding",
        "/courses",
        "/courses/{slug}",
        "/admin",
    ):
        app.add_api_route(_sp_path, _serve_spa, include_in_schema=False)


@app.get("/health", tags=["health"])
async def health() -> dict[str, str]:
    return {"status": "ok"}

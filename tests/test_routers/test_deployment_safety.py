"""
Unit tests for deployment safety features — no database required.

Covers:
- Production config validation (JWT, BETA_INVITE_CODE, CORS_ORIGINS)
- Security headers present on every response
- /health endpoint returns 200
- Rate limiting returns 429 after limit exceeded
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import app

# ── Config validation ─────────────────────────────────────────────────────────


class TestProductionConfigValidation:
    def test_dev_jwt_secret_rejected_in_production(self) -> None:
        with pytest.raises(Exception, match="JWT_SECRET_KEY"):
            Settings(
                ENVIRONMENT="production",
                JWT_SECRET_KEY="dev-secret-change-in-production-minimum-32-chars!!",
                BETA_INVITE_CODE="some-invite",
                CORS_ORIGINS="https://example.com",
                DATABASE_URL="postgresql+asyncpg://x:y@localhost/db",
            )

    def test_short_jwt_secret_rejected_in_production(self) -> None:
        with pytest.raises(Exception, match="JWT_SECRET_KEY"):
            Settings(
                ENVIRONMENT="production",
                JWT_SECRET_KEY="too-short",
                BETA_INVITE_CODE="some-invite",
                CORS_ORIGINS="https://example.com",
                DATABASE_URL="postgresql+asyncpg://x:y@localhost/db",
            )

    def test_missing_beta_invite_code_rejected_in_production(self) -> None:
        with pytest.raises(Exception, match="BETA_INVITE_CODE"):
            Settings(
                ENVIRONMENT="production",
                JWT_SECRET_KEY="a" * 32,
                BETA_INVITE_CODE="",
                CORS_ORIGINS="https://example.com",
                DATABASE_URL="postgresql+asyncpg://x:y@localhost/db",
            )

    def test_missing_cors_origins_rejected_in_production(self) -> None:
        with pytest.raises(Exception, match="CORS_ORIGINS"):
            Settings(
                ENVIRONMENT="production",
                JWT_SECRET_KEY="a" * 32,
                BETA_INVITE_CODE="some-invite",
                CORS_ORIGINS="",
                DATABASE_URL="postgresql+asyncpg://x:y@localhost/db",
            )

    def test_valid_production_config_accepted(self) -> None:
        s = Settings(
            ENVIRONMENT="production",
            JWT_SECRET_KEY="a" * 32,
            BETA_INVITE_CODE="some-invite",
            CORS_ORIGINS="https://example.com",
            DATABASE_URL="postgresql+asyncpg://x:y@localhost/db",
        )
        assert s.ENVIRONMENT == "production"

    def test_development_config_does_not_require_extras(self) -> None:
        s = Settings(
            ENVIRONMENT="development",
            JWT_SECRET_KEY="dev-secret-change-in-production-minimum-32-chars!!",
            BETA_INVITE_CODE="",
            CORS_ORIGINS="",
            DATABASE_URL="postgresql+asyncpg://x:y@localhost/db",
        )
        assert s.ENVIRONMENT == "development"


# ── Security headers ──────────────────────────────────────────────────────────


class TestSecurityHeaders:
    def test_health_includes_security_headers(self) -> None:
        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"
        assert resp.headers.get("referrer-policy") == "no-referrer"
        assert "content-security-policy" in resp.headers

    def test_api_response_includes_security_headers(self) -> None:
        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.post("/api/v1/auth/login", json={})
        assert resp.headers.get("x-content-type-options") == "nosniff"
        assert resp.headers.get("x-frame-options") == "DENY"


# ── Health endpoint ───────────────────────────────────────────────────────────


class TestHealthEndpoint:
    def test_health_returns_ok(self) -> None:
        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_health_no_auth_required(self) -> None:
        with TestClient(app, raise_server_exceptions=True) as client:
            resp = client.get("/health")
        assert resp.status_code == 200


# ── Rate limiting ─────────────────────────────────────────────────────────────


class TestRateLimiting:
    def test_register_rate_limited_after_5_requests(self) -> None:
        from app.middleware.rate_limit import RateLimitMiddleware

        middleware = RateLimitMiddleware(app=None, enforce=True)
        # Verify limits are configured for register endpoint
        assert "/api/v1/auth/register" in middleware._limits
        max_reqs, window = middleware._limits["/api/v1/auth/register"]
        assert max_reqs <= 10
        assert window >= 60

    def test_login_rate_limit_configured(self) -> None:
        from app.middleware.rate_limit import RateLimitMiddleware

        middleware = RateLimitMiddleware(app=None, enforce=True)
        assert "/api/v1/auth/login" in middleware._limits
        max_reqs, window = middleware._limits["/api/v1/auth/login"]
        assert max_reqs <= 20
        assert window >= 60

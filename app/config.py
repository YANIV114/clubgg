from pydantic import computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_SECRET = "dev-secret-change-in-production-minimum-32-chars!!"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://yaniv@localhost:5432/clubgg"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    # ClubGG API
    CLUBGG_BASE_URL: str = "https://api.clubgg.net"
    CLUBGG_CLUB_IDS: str = ""
    CLUBGG_API_KEY: str = ""
    CLUBGG_REQUEST_TIMEOUT: int = 30

    # Hand history file ingestion
    HAND_HISTORY_WATCH_DIR: str = "/tmp/hand_histories"
    HAND_HISTORY_PROCESSED_DIR: str = "/tmp/hand_histories/processed"

    # Scheduler intervals (seconds)
    INGEST_HANDS_INTERVAL_SECONDS: int = 300
    INGEST_PLAYERS_INTERVAL_SECONDS: int = 1800
    INGEST_TABLES_INTERVAL_SECONDS: int = 900
    INGEST_TRANSACTIONS_INTERVAL_SECONDS: int = 300
    INGEST_FILE_POLL_INTERVAL_SECONDS: int = 60

    # JWT
    JWT_SECRET_KEY: str = _DEV_SECRET
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 1440  # 24 hours

    # CORS — comma-separated list of allowed origins (empty = deny all in prod)
    CORS_ORIGINS: str = ""

    # Stripe
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRICE_STARTER: str = ""
    STRIPE_PRICE_PRO: str = ""
    STRIPE_PRICE_ELITE: str = ""
    BILLING_SUCCESS_URL: str = "http://localhost:8000/account?billing=success"
    BILLING_CANCEL_URL: str = "http://localhost:8000/pricing"

    # Beta access gate — when set, signup requires a matching invite_code
    BETA_INVITE_CODE: str = ""

    # App
    LOG_LEVEL: str = "INFO"
    API_PREFIX: str = "/api/v1"
    ENVIRONMENT: str = "development"

    @model_validator(mode="after")
    def _validate_production_secrets(self) -> "Settings":
        if self.ENVIRONMENT == "production":
            if self.JWT_SECRET_KEY == _DEV_SECRET or len(self.JWT_SECRET_KEY) < 32:
                raise ValueError(
                    "JWT_SECRET_KEY must be at least 32 characters and not the default dev value in production. "
                    "Generate one with: openssl rand -hex 32"
                )
            if not self.BETA_INVITE_CODE:
                raise ValueError(
                    "BETA_INVITE_CODE must be set in production to prevent unauthorized signups."
                )
            if not self.CORS_ORIGINS:
                raise ValueError(
                    "CORS_ORIGINS must be set in production. "
                    "Example: https://app.clubgg.com,https://admin.clubgg.com"
                )
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def club_ids(self) -> list[str]:
        return [c.strip() for c in self.CLUBGG_CLUB_IDS.split(",") if c.strip()]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def stripe_price_map(self) -> dict[str, str]:
        m = {
            "starter": self.STRIPE_PRICE_STARTER,
            "pro": self.STRIPE_PRICE_PRO,
            "elite": self.STRIPE_PRICE_ELITE,
        }
        return {slug: pid for slug, pid in m.items() if pid}

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origins_list(self) -> list[str]:
        if self.ENVIRONMENT == "development":
            return ["*"]
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]


settings = Settings()

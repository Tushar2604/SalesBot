"""Application settings, loaded once from the environment."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    # core
    environment: Literal["development", "test", "staging", "production"] = "development"
    log_level: str = "INFO"
    api_base_url: str = "http://localhost:8000"
    web_base_url: str = "http://localhost:3000"

    # database
    database_url: str = (
        "postgresql+asyncpg://salesrobo:salesrobo_dev_password@postgres:5432/salesrobo"
    )
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_echo: bool = False

    # redis / celery
    redis_url: str = "redis://redis:6379/0"
    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"

    # auth
    jwt_secret: SecretStr = SecretStr("dev-only-insecure-secret")
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 30

    # secret encryption for LinkedIn sessions / proxy creds / mailbox creds
    encryption_key: SecretStr = SecretStr("")

    # object storage
    s3_endpoint_url: str | None = "http://minio:9000"
    # Address browsers use for signed media links, when it differs from the
    # internal one (e.g. https://files.example.com in front of MinIO). Unset:
    # links are signed for `s3_endpoint_url`, right for real S3/R2.
    s3_public_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_bucket: str = "salesrobo"
    s3_access_key: SecretStr = SecretStr("minioadmin")
    s3_secret_key: SecretStr = SecretStr("minioadmin")

    # ── LinkedIn publishing (official API, 3-legged OAuth) ────────────────────
    # Distinct from the automation session: publishing a post on a member's
    # behalf is only permitted through an authorized developer app holding the
    # `w_member_social` scope. Absent credentials are not an error — the feature
    # reports itself unavailable rather than pretending to publish.
    linkedin_client_id: str = ""
    linkedin_client_secret: SecretStr = SecretStr("")
    # Must match a redirect URL registered on the LinkedIn app exactly.
    linkedin_redirect_uri: str = "http://localhost:8010/api/v1/linkedin/oauth/callback"
    linkedin_api_base_url: str = "https://api.linkedin.com"
    # Versioned REST header required by the Posts API.
    linkedin_api_version: str = "202409"
    linkedin_publishing_scopes: str = "openid profile w_member_social"

    # ai
    anthropic_api_key: SecretStr = SecretStr("")
    ai_generation_model: str = "claude-opus-5"
    ai_classification_model: str = "claude-haiku-4-5-20251001"
    # Inbox assistant providers, tried in this order until one answers.
    # Any of: openai, gemini, anthropic. A provider without a key is skipped.
    ai_assistant_providers: str = "openai,gemini"
    openai_api_key: SecretStr = SecretStr("")
    openai_model: str = "gpt-5-mini"
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-2.5-flash"

    # AI lead finder: people-data providers, tried in this order until one
    # returns people. Any of: exa, pdl, apollo, brave. A provider without a
    # key is skipped. None of them touch a LinkedIn account — searching
    # LinkedIn with a member's session is what gets accounts restricted.
    lead_search_providers: str = "exa,pdl,apollo,brave"
    exa_api_key: SecretStr = SecretStr("")
    pdl_api_key: SecretStr = SecretStr("")
    apollo_api_key: SecretStr = SecretStr("")
    brave_search_api_key: SecretStr = SecretStr("")
    # Each search spends provider credits; this caps one workspace's day.
    lead_search_daily_limit: int = 50

    # Integration layer. API keys: requests per minute per key.
    api_key_rate_limit_per_minute: int = Field(default=300, ge=10, le=10_000)
    # Serve the interactive API reference (/docs) in production too, for
    # customers building integrations. Endpoints stay protected either way.
    api_docs_public: bool = False
    # Webhook URLs on private/loopback networks let a user make the server call
    # its own internal services (SSRF). Off in production; None = allowed only
    # in development and test, so a local receiver can be used while building.
    webhooks_allow_private_urls: bool | None = None

    @property
    def allow_private_webhook_urls(self) -> bool:
        if self.webhooks_allow_private_urls is not None:
            return self.webhooks_allow_private_urls
        return self.environment in ("development", "test")

    # billing
    stripe_secret_key: SecretStr = SecretStr("")
    stripe_webhook_secret: SecretStr = SecretStr("")

    # proxies
    proxy_provider: str = "none"
    proxy_provider_username: SecretStr = SecretStr("")
    proxy_provider_password: SecretStr = SecretStr("")
    proxy_provider_host: str = ""
    proxy_provider_port: int = 0

    # ── safety engine defaults ────────────────────────────────────────────────
    # These are floors/ceilings the dispatcher enforces. Per-account overrides
    # may only ever be *more* conservative than the max values.
    # "browser" runs every action inside a real Chromium (the working path);
    # "voyager" is the legacy httpx driver, which LinkedIn rejects after login.
    linkedin_driver: Literal["browser", "voyager"] = "browser"
    # How old an invite must be before we spend a page load checking for acceptance.
    linkedin_acceptance_min_age_minutes: int = Field(default=30, ge=1)
    # How long an unanswered invite keeps being checked before it is marked
    # expired ("no response"). Matches the 21-day hygiene rule in the safety docs.
    linkedin_invite_tracking_days: int = Field(default=21, ge=1, le=90)
    # How many unread/changed threads the browser driver opens per inbox poll.
    # Was 3: fine for a quiet inbox, but with more unread threads waiting than
    # this every poll, whichever conversations sit further down the list never
    # get opened at all — so they never reach the AI assistant for a draft.
    # Raised, but still a real cap: opening dozens of threads in one pass would
    # itself look like scraping rather than someone checking their messages.
    linkedin_inbox_max_threads_per_poll: int = Field(default=10, ge=1, le=30)
    safety_default_test_mode: bool = True
    # Warm-up (test mode): invites/day falls in [daily_invites, daily_invites_max],
    # varied per account per day so the volume is not a constant. Messages are flat.
    safety_test_mode_daily_invites: int = Field(default=3, ge=1, le=20)
    safety_test_mode_daily_invites_max: int = Field(default=5, ge=1, le=20)
    safety_test_mode_daily_messages: int = Field(default=2, ge=1, le=20)
    safety_max_daily_invites: int = Field(default=75, ge=1, le=100)
    safety_max_weekly_invites: int = Field(default=100, ge=1, le=200)
    # Gap between any two actions of one account (campaign steps and bot
    # replies alike): a random 2-10 minutes, median 5 — a person working
    # through a list, not a script firing on a timer.
    safety_min_action_gap_seconds: int = Field(default=120, ge=15)
    safety_median_action_gap_seconds: int = Field(default=300, ge=30)
    safety_max_action_gap_seconds: int = Field(default=600, ge=60)

    # ── remote-browser login (Phase 1) ───────────────────────────────────────
    # A real, human-driven Chromium session used only to establish a LinkedIn
    # login; see api/app/linkedin/remote_browser/. Kept separate from the
    # safety-engine settings above since these bound a UI session, not outreach.
    # One saved Chromium profile per LinkedIn account (cookies, storage, cache),
    # so every sign-in and action runs on the same "computer". Holds live
    # sessions: keep it on private storage, never in the repository.
    browser_profiles_dir: str = "/data/browser-profiles"
    # Every LinkedIn account must go out through its own proxy. On a server,
    # "no proxy" means the data-centre IP every account shares — the pattern
    # LinkedIn bans. Unset: required in production, optional elsewhere.
    require_proxy: bool | None = None
    remote_browser_max_concurrent: int = Field(default=3, ge=1, le=20)
    remote_browser_ttl_seconds: int = Field(default=900, ge=60)
    remote_browser_idle_timeout_seconds: int = Field(default=300, ge=30)

    sentry_dsn: str = ""

    @property
    def sync_database_url(self) -> str:
        """psycopg URL for Alembic and sync Celery task sessions."""
        return self.database_url.replace("+asyncpg", "+psycopg")

    @property
    def linkedin_publishing_configured(self) -> bool:
        """Whether this deployment has a LinkedIn app able to publish at all."""
        return bool(self.linkedin_client_id and self.linkedin_client_secret.get_secret_value())

    @property
    def linkedin_scope_list(self) -> list[str]:
        return [s for s in self.linkedin_publishing_scopes.split() if s]

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def proxy_required(self) -> bool:
        """Required in every real environment, including development.

        Gating this on `is_production` is how most of this project's own
        accounts ended up logging into LinkedIn over the bare server IP and
        getting `auth_lost` almost immediately: "development" is not a reason
        to skip the guard that keeps LinkedIn from clustering accounts by IP.
        Only the automated test suite (`environment == "test"`) is exempt by
        default, since it never touches a real LinkedIn session.
        """
        return self.require_proxy if self.require_proxy is not None else self.environment != "test"

    @property
    def cors_origins(self) -> list[str]:
        """localhost and 127.0.0.1 are different origins to the browser."""
        base = self.web_base_url.rstrip("/")
        origins = {base}
        if "://localhost" in base:
            origins.add(base.replace("://localhost", "://127.0.0.1"))
        if "://127.0.0.1" in base:
            origins.add(base.replace("://127.0.0.1", "://localhost"))
        return sorted(origins)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

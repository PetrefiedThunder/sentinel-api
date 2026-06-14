from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://user:pass@localhost:5432/sentinel"
    # Optional Postgres read replica. When empty (default), read-only endpoints
    # fall back to the primary engine — behaviour is identical to having no
    # replica. When set, read sessions target this URL. See
    # docs/runbooks/postgres-read-replica.md for provisioning.
    READ_REPLICA_URL: str = ""
    REDIS_URL: str = "redis://localhost:6379/0"
    JWT_SECRET: str = "change-me"
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_FROM_NUMBER: str = ""
    TWILIO_MESSAGING_SERVICE_SID: str = ""
    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = ""
    EMAIL_REPLY_TO: str = ""
    PUBLIC_APP_URL: str = "https://app.pauseapi.app"
    PUBLIC_API_URL: str = "https://api.pauseapi.app"
    # Comma-separated list of approver strings (email or sms:+1...). Used when the
    # caller's `approvers` list is empty — so the system always has a fallback recipient.
    DEFAULT_APPROVERS: str = ""

    ADMIN_TOKEN: str = ""

    # Staleness threshold for an in-progress idempotency claim. The claim-first
    # flow reserves an IdempotencyKey row with response_status=0 (_IN_PROGRESS)
    # before running the handler. If the process crashes between claiming and
    # storing the real response, that row would otherwise stay in-progress
    # forever, bricking the key (every retry polls, times out, gets a 409). When
    # `now - created_at` exceeds this threshold the claim is treated as abandoned
    # and a retry takes it over and re-runs the handler. Must comfortably exceed
    # the longest expected in-request handler time and the brief poll window
    # (~0.25s); 30s leaves a wide margin while keeping recovery prompt.
    IDEMPOTENCY_INPROGRESS_TTL_SECONDS: int = 30

    # Stripe billing — keys come from Stripe dashboard. If empty, billing
    # endpoints return 503 (feature disabled).
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRICE_PRO: str = ""  # price_... id of the Pro monthly plan
    STRIPE_SUCCESS_URL: str = "https://app.pauseapi.app/billing?status=success"
    STRIPE_CANCEL_URL: str = "https://app.pauseapi.app/billing?status=cancelled"

    # RFC 3161 Time Stamping Authority endpoint (e.g. https://freetsa.org/tsr).
    # Empty (default) disables audit-event timestamping entirely.
    TSA_URL: str = ""

    SENTRY_DSN: str = ""
    SENTRY_ENVIRONMENT: str = "production"
    SENTRY_TRACES_SAMPLE_RATE: float = 0.05

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def default_approvers_list(self) -> list[str]:
        return [a.strip() for a in self.DEFAULT_APPROVERS.split(",") if a.strip()]


settings = Settings()

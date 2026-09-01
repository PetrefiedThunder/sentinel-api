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

    # Staleness threshold for an in-progress idempotency claim. New writes
    # atomically commit the claim, handler effects, and stored response, so a
    # crash rolls them all back. A committed _IN_PROGRESS row can only have an
    # indeterminate/legacy outcome; once older than this threshold it fails
    # closed with 409 instead of re-running a potentially completed write. Keep
    # this comfortably above the longest expected handler and brief poll window.
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

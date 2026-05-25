from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://user:pass@localhost:5432/sentinel"
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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

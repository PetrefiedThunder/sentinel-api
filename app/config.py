from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://user:pass@localhost:5432/sentinel"
    REDIS_URL: str = "redis://localhost:6379/0"
    JWT_SECRET: str = "change-me"
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_FROM_NUMBER: str = ""
    RESEND_API_KEY: str = ""
    PUBLIC_APP_URL: str = "https://app.pauseapi.app"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

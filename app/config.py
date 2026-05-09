from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Telegram
    telegram_bot_token: str = ""
    webhook_url: str = ""

    # LLM
    gemini_api_key: str = ""
    groq_api_key: str = ""

    # Maps
    google_maps_api_key: str = ""

    # Weather
    weatherapi_key: str = ""
    openweather_api_key: str = ""

    # Flights
    travelpayouts_token: str = ""

    # OpenSky
    opensky_user: str = ""
    opensky_pass: str = ""

    # Database
    database_url: str = "postgresql+asyncpg://travel:travel@db:5432/travel_agent"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # App
    secret_key: str = "change-me-in-production"
    environment: str = "development"
    port: int = 8001

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def webhook_path(self) -> str:
        return f"/webhook/{self.secret_key}"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

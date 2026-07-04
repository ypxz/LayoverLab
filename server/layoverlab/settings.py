from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://layover:layover@localhost:5433/layoverlab"

    crawl_enabled: bool = True
    crawl_min_interval_s: float = 2.0
    crawl_breaker_cooldown_s: float = 300.0
    http_cache_dir: str = ".cache/http"

    travelpayouts_token: str = ""
    gf_enabled: bool = False
    tequila_api_key: str = ""
    amadeus_client_id: str = ""
    amadeus_client_secret: str = ""
    wizz_enabled: bool = True
    easyjet_enabled: bool = True

    api_cors_origins: str = "http://localhost:3000"

    # engine defaults
    fare_ttl_hours: int = 48


@lru_cache
def get_settings() -> Settings:
    return Settings()

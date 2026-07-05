from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+psycopg://layover:layover@localhost:5433/layoverlab"

    crawl_enabled: bool = True
    crawl_min_interval_s: float = 2.0
    crawl_breaker_cooldown_s: float = 300.0
    http_cache_dir: str = ".cache/http"
    crawl_daily_budget: int = 500
    sched_tick_s: int = 60
    crawler_concurrency: int = 2

    travelpayouts_token: str = ""
    gf_enabled: bool = False
    tequila_api_key: str = ""
    amadeus_client_id: str = ""
    amadeus_client_secret: str = ""
    wizz_enabled: bool = True
    easyjet_enabled: bool = True
    fixture_connector: bool = False

    api_cors_origins: str = "http://localhost:3000"

    # engine defaults
    fare_ttl_hours: int = 48

    # streaming search
    search_stream_max_s: int = 60
    search_stream_poll_s: float = 5.0

    # rate limiting
    rate_limit_enabled: bool = True
    rate_search_per_min: int = 10
    rate_default_per_min: int = 60

    # admin + metrics
    admin_token: str = ""
    metrics_enabled: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()

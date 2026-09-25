from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gemini_api_key: str
    gemini_model: str = "gemini-3.5-transcribe-live"
    redis_url: str = "redis://localhost:6379"
    gateway_host: str = "0.0.0.0"
    gateway_port: int = 8000
    log_level: str = "INFO"

    # ── Production dashboard ──────────────────────────────────────────────
    # Set to a non-empty secret to enable the dashboard; empty = disabled.
    dashboard_token: str = ""

    # Latency thresholds (milliseconds)
    latency_warn_ms: int = 1500   # yellow alert
    latency_crit_ms: int = 4000   # red alert

    # Staleness thresholds: seconds without a transcript event
    stale_warn_sec: int = 30      # yellow — possible silence or slow audio
    stale_crit_sec: int = 120     # red — stream likely dead

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()

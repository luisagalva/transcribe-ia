from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    gemini_api_key: str
    gemini_model: str = "gemini-3.5-transcribe-live"
    # Flash model for fast, cheap translation of short subtitle segments
    gemini_translation_model: str = "gemini-3.8-flash"
    redis_url: str = "redis://localhost:6379"
    gateway_host: str = "0.0.0.0"
    gateway_port: int = 8000
    log_level: str = "INFO"
    # Comma-separated list of languages to translate to by default, e.g. "en,es,pt"
    default_target_langs: str = "en"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()

from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Anthropic
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    # Apify fallback
    apify_api_key: str = ""

    # Whisper
    whisper_model: str = "base"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"

    # Paths
    plans_dir: Path = Path("plans")
    temp_dir: Path = Path("tmp")

    # Telegram
    telegram_bot_token: str = ""

    # Server
    host: str = "127.0.0.1"
    port: int = 8000

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()

# Ensure directories exist
settings.plans_dir.mkdir(exist_ok=True)
settings.temp_dir.mkdir(exist_ok=True)

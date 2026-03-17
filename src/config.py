from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Anthropic (direct — currently out of credits)
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    # OpenRouter (LLM provider)
    openrouter_api_key: str = ""
    openrouter_model: str = "moonshotai/kimi-k2.5"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # Per-step model overrides (leave blank to use openrouter_model)
    openrouter_model_analysis: str = ""
    openrouter_model_plan: str = ""
    openrouter_model_similarity: str = "google/gemini-2.5-flash"

    # Apify fallback
    apify_api_key: str = ""

    # Whisper
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"

    # Paths
    plans_dir: Path = Path("plans")
    temp_dir: Path = Path("tmp")
    sister_projects_dir: Path = Path(__file__).resolve().parent.parent.parent

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""  # Chat ID for similarity notifications from API route
    enable_telegram_bot: bool = True  # Set False in local dev to avoid polling conflict

    # Auth
    reelbot_api_key: str = ""  # Required for write operations on plans

    # Server
    host: str = "127.0.0.1"
    port: int = 8000
    public_url: str = ""  # e.g. https://reelbot.leadneedleai.com
    cors_origins: str = "https://reelbot.leadneedleai.com"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


settings = Settings()

# Ensure directories exist
settings.plans_dir.mkdir(exist_ok=True)
settings.temp_dir.mkdir(exist_ok=True)

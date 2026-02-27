import shutil
from pathlib import Path
from loguru import logger

from src.config import settings


def create_temp_dir(reel_id: str) -> Path:
    """Create a temporary directory for processing a reel."""
    temp_dir = settings.temp_dir / reel_id
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir


def cleanup_temp_dir(reel_id: str) -> None:
    """Remove temporary files after processing."""
    temp_dir = settings.temp_dir / reel_id
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
        logger.debug(f"Cleaned up temp dir: {temp_dir}")

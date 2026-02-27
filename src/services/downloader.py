import re
import subprocess
import json
from pathlib import Path
from loguru import logger

from src.models import ReelMetadata


def extract_shortcode(url: str) -> str:
    """Extract the reel shortcode from an Instagram URL."""
    patterns = [
        r"instagram\.com/reel/([A-Za-z0-9_-]+)",
        r"instagram\.com/reels/([A-Za-z0-9_-]+)",
        r"instagram\.com/p/([A-Za-z0-9_-]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    raise ValueError(f"Could not extract shortcode from URL: {url}")


def download_reel(url: str, output_dir: Path) -> tuple[Path, ReelMetadata]:
    """Download an Instagram reel using yt-dlp. Returns (video_path, metadata)."""
    shortcode = extract_shortcode(url)
    output_path = output_dir / f"{shortcode}.mp4"

    logger.info(f"Downloading reel {shortcode} to {output_path}")

    # Download with yt-dlp, write metadata to JSON
    info_path = output_dir / f"{shortcode}.info.json"
    cmd = [
        "yt-dlp",
        "--no-warnings",
        "--write-info-json",
        "-o", str(output_path),
        url,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {result.stderr}")

    if not output_path.exists():
        # yt-dlp may add an extension
        candidates = list(output_dir.glob(f"{shortcode}.*"))
        video_files = [f for f in candidates if f.suffix in (".mp4", ".webm") and ".info" not in f.name]
        if video_files:
            output_path = video_files[0]
        else:
            raise FileNotFoundError(f"Downloaded file not found for {shortcode}")

    # Parse metadata
    creator = ""
    caption = ""
    duration = 0.0
    if info_path.exists():
        with open(info_path) as f:
            info = json.load(f)
        creator = info.get("uploader", "") or info.get("channel", "")
        caption = info.get("description", "") or info.get("title", "")
        duration = info.get("duration", 0.0) or 0.0

    metadata = ReelMetadata(
        url=url,
        shortcode=shortcode,
        creator=creator,
        caption=caption,
        duration=duration,
    )

    logger.info(f"Downloaded: {output_path} ({duration:.1f}s, by {creator})")
    return output_path, metadata

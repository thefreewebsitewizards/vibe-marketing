import re
import subprocess
import json
import time
from pathlib import Path
import httpx
from loguru import logger

from src.config import settings
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
    """Download reel with yt-dlp, falling back to Apify if it fails."""
    shortcode = extract_shortcode(url)

    # Try yt-dlp first
    try:
        return _download_ytdlp(url, shortcode, output_dir)
    except Exception as e:
        logger.warning(f"yt-dlp failed: {e}")

    # Fallback to Apify
    if settings.apify_api_key:
        logger.info("Falling back to Apify instagram-reel-scraper...")
        try:
            return _download_apify(url, shortcode, output_dir)
        except Exception as e2:
            logger.error(f"Apify fallback also failed: {e2}")
            raise RuntimeError(f"All download methods failed. yt-dlp: {e} | Apify: {e2}")
    else:
        raise RuntimeError(f"yt-dlp failed and no APIFY_API_KEY configured: {e}")


def _download_ytdlp(url: str, shortcode: str, output_dir: Path) -> tuple[Path, ReelMetadata]:
    """Download using yt-dlp."""
    output_path = output_dir / f"{shortcode}.mp4"
    info_path = output_dir / f"{shortcode}.info.json"

    logger.info(f"Downloading reel {shortcode} via yt-dlp")

    cmd = [
        "yt-dlp",
        "--no-warnings",
        "--write-info-json",
        "-o", str(output_path),
        url,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(result.stderr[:500])

    if not output_path.exists():
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
        url=url, shortcode=shortcode, creator=creator,
        caption=caption, duration=duration,
    )
    logger.info(f"Downloaded via yt-dlp: {output_path} ({duration:.1f}s, by {creator})")
    return output_path, metadata


def _download_apify(url: str, shortcode: str, output_dir: Path) -> tuple[Path, ReelMetadata]:
    """Download using Apify instagram-reel-scraper as fallback."""
    output_path = output_dir / f"{shortcode}.mp4"

    # Start the Apify actor run
    run_url = "https://api.apify.com/v2/acts/apify~instagram-reel-scraper/runs"
    headers = {"Authorization": f"Bearer {settings.apify_api_key}"}
    payload = {
        "directUrls": [url],
        "resultsLimit": 1,
    }

    with httpx.Client(timeout=120) as client:
        # Start run
        resp = client.post(run_url, json=payload, headers=headers)
        resp.raise_for_status()
        run_data = resp.json()["data"]
        run_id = run_data["id"]
        dataset_id = run_data["defaultDatasetId"]

        logger.info(f"Apify run started: {run_id}")

        # Poll until finished (max ~90s)
        status_url = f"https://api.apify.com/v2/actor-runs/{run_id}"
        for _ in range(30):
            time.sleep(3)
            status_resp = client.get(status_url, headers=headers)
            status = status_resp.json()["data"]["status"]
            if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                break

        if status != "SUCCEEDED":
            raise RuntimeError(f"Apify run {status}: {run_id}")

        # Get results
        dataset_url = f"https://api.apify.com/v2/datasets/{dataset_id}/items"
        items_resp = client.get(dataset_url, headers=headers)
        items = items_resp.json()

        if not items:
            raise RuntimeError("Apify returned no results")

        item = items[0]
        video_url = item.get("videoUrl") or item.get("video_url") or item.get("videoPlaybackUrl")
        if not video_url:
            raise RuntimeError(f"No video URL in Apify response: {list(item.keys())}")

        # Download the video file
        video_resp = client.get(video_url)
        video_resp.raise_for_status()
        output_path.write_bytes(video_resp.content)

    creator = item.get("ownerUsername", "") or item.get("author", "")
    caption = item.get("caption", "") or item.get("text", "")
    duration = float(item.get("videoDuration", 0) or item.get("duration", 0) or 0)

    metadata = ReelMetadata(
        url=url, shortcode=shortcode, creator=creator,
        caption=caption, duration=duration,
    )
    logger.info(f"Downloaded via Apify: {output_path} ({duration:.1f}s, by {creator})")
    return output_path, metadata

import re
import subprocess
import json
import time
from pathlib import Path

import httpx
from loguru import logger

from src.config import settings
from src.constants import DOWNLOAD_TIMEOUT
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
    raise ValueError(f"Could not extract shortcode from URL: {url[:120]}")


def is_post_url(url: str) -> bool:
    """Check if URL is a /p/ post (vs /reel/)."""
    return bool(re.search(r"instagram\.com/p/", url))


def download_reel(url: str, output_dir: Path) -> tuple[Path | list[Path], ReelMetadata]:
    """Download reel/carousel with yt-dlp, falling back to Apify if it fails.

    Returns (video_path, metadata) for reels or (image_paths, metadata) for carousels.
    """
    shortcode = extract_shortcode(url)

    # Try yt-dlp first
    ytdlp_err = None
    try:
        return _download_ytdlp(url, shortcode, output_dir)
    except Exception as e:
        ytdlp_err = str(e)
        logger.warning(f"yt-dlp failed: {ytdlp_err}")

    # Fallback to Apify
    if settings.apify_api_key:
        is_post = is_post_url(url)
        actor = "apify~instagram-post-scraper" if is_post else "apify~instagram-reel-scraper"
        logger.info(f"Falling back to Apify {actor}...")
        try:
            return _download_apify(url, shortcode, output_dir, actor=actor)
        except Exception as e2:
            logger.error(f"Apify fallback also failed: {e2}")
            raise RuntimeError(f"All download methods failed. yt-dlp: {ytdlp_err} | Apify: {e2}")
    else:
        raise RuntimeError(f"yt-dlp failed and no APIFY_API_KEY configured: {ytdlp_err}")


def _download_ytdlp(url: str, shortcode: str, output_dir: Path) -> tuple[Path | list[Path], ReelMetadata]:
    """Download using yt-dlp. Detects carousel posts (images) vs reels (video)."""
    output_path = output_dir / f"{shortcode}.mp4"
    info_path = output_dir / f"{shortcode}.info.json"

    logger.info(f"Downloading {shortcode} via yt-dlp")

    cmd = [
        "yt-dlp",
        "--no-warnings",
        "--write-info-json",
        "--write-comments",
        "--write-thumbnail",
        "-o", str(output_path),
        url,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=DOWNLOAD_TIMEOUT)

    # For /p/ posts, yt-dlp may fail because there's no video.
    # Check if we at least got metadata or a thumbnail before giving up.
    if result.returncode != 0:
        # Check if we got an info.json (metadata) even though video download failed
        if not info_path.exists():
            raise RuntimeError(result.stderr[:500])

    # Parse metadata first (need it for content_type detection)
    creator = ""
    caption = ""
    duration = 0.0
    like_count = 0
    comment_count = 0
    comments = []
    if info_path.exists():
        with open(info_path) as f:
            info = json.load(f)
        creator = info.get("uploader", "") or info.get("channel", "")
        caption = info.get("description", "") or info.get("title", "")
        duration = info.get("duration", 0.0) or 0.0
        raw_date = info.get("upload_date", "") or ""
        upload_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}" if len(raw_date) == 8 else ""
        like_count = info.get("like_count", 0) or 0
        comment_count = info.get("comment_count", 0) or 0
        for c in (info.get("comments") or [])[:10]:
            author = c.get("author", "") or ""
            text = c.get("text", "") or ""
            if text.strip():
                comments.append({"author": author, "text": text[:500]})

    # Check for images (carousel or single image post)
    image_files = sorted(output_dir.glob(f"{shortcode}*.jpg")) + sorted(output_dir.glob(f"{shortcode}*.png"))
    # Exclude thumbnail files (yt-dlp names them .jpg alongside .info.json)
    image_files = [f for f in image_files if ".info" not in f.name]

    if image_files and not output_path.exists():
        content_type = "carousel" if len(image_files) > 1 else "post"
        metadata = ReelMetadata(
            url=url, shortcode=shortcode, creator=creator,
            caption=caption, duration=0.0, content_type=content_type,
            upload_date=upload_date, like_count=like_count,
            comment_count=comment_count, comments=comments,
        )
        logger.info(f"Downloaded {content_type} via yt-dlp: {len(image_files)} image(s) by {creator}")
        return image_files, metadata

    # Also check for webp thumbnails (common for image posts where yt-dlp only gets the thumb)
    if not output_path.exists():
        webp_files = sorted(output_dir.glob(f"{shortcode}*.webp"))
        if webp_files:
            metadata = ReelMetadata(
                url=url, shortcode=shortcode, creator=creator,
                caption=caption, duration=0.0, content_type="post",
                upload_date=upload_date, like_count=like_count,
                comment_count=comment_count, comments=comments,
            )
            logger.info(f"Downloaded post thumbnail via yt-dlp: {len(webp_files)} image(s) by {creator}")
            return webp_files, metadata

    # Standard video path
    if not output_path.exists():
        candidates = list(output_dir.glob(f"{shortcode}.*"))
        video_files = [f for f in candidates if f.suffix in (".mp4", ".webm") and ".info" not in f.name]
        if video_files:
            output_path = video_files[0]
        else:
            raise FileNotFoundError(f"Downloaded file not found for {shortcode}")

    metadata = ReelMetadata(
        url=url, shortcode=shortcode, creator=creator,
        caption=caption, duration=duration, upload_date=upload_date,
        like_count=like_count, comment_count=comment_count, comments=comments,
    )
    logger.info(f"Downloaded via yt-dlp: {output_path} ({duration:.1f}s, by {creator}, {len(comments)} comments)")
    return output_path, metadata


def _download_apify(
    url: str,
    shortcode: str,
    output_dir: Path,
    actor: str = "apify~instagram-reel-scraper",
) -> tuple[Path | list[Path], ReelMetadata]:
    """Download using Apify as fallback. Supports both reel and post scrapers."""
    output_path = output_dir / f"{shortcode}.mp4"

    # Start the Apify actor run
    run_url = f"https://api.apify.com/v2/acts/{actor}/runs"
    headers = {"Authorization": f"Bearer {settings.apify_api_key}"}
    payload = {
        "directUrls": [url],
        "resultsLimit": 1,
    }

    with httpx.Client(timeout=DOWNLOAD_TIMEOUT) as client:
        # Start run
        resp = client.post(run_url, json=payload, headers=headers)
        resp.raise_for_status()
        run_data = resp.json()["data"]
        run_id = run_data["id"]
        dataset_id = run_data["defaultDatasetId"]

        logger.info(f"Apify run started: {run_id} (actor: {actor})")

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
        creator = item.get("ownerUsername", "") or item.get("author", "")
        caption = item.get("caption", "") or item.get("text", "")

        # Try video first
        video_url = item.get("videoUrl") or item.get("video_url") or item.get("videoPlaybackUrl")
        if video_url:
            video_resp = client.get(video_url)
            video_resp.raise_for_status()
            output_path.write_bytes(video_resp.content)
            duration = float(item.get("videoDuration", 0) or item.get("duration", 0) or 0)
            metadata = ReelMetadata(
                url=url, shortcode=shortcode, creator=creator,
                caption=caption, duration=duration,
            )
            logger.info(f"Downloaded video via Apify: {output_path} ({duration:.1f}s, by {creator})")
            return output_path, metadata

        # No video — try images (post or carousel)
        image_urls = item.get("images") or item.get("displayUrl") or item.get("imageUrls") or []
        if isinstance(image_urls, str):
            image_urls = [image_urls]

        if not image_urls:
            # Last resort: try the display_url field
            display = item.get("display_url") or item.get("displayUrl") or ""
            if display:
                image_urls = [display]

        if not image_urls:
            raise RuntimeError(f"No video or image URLs in Apify response: {list(item.keys())}")

        # Download images
        downloaded = []
        for i, img_url in enumerate(image_urls):
            ext = ".jpg"
            img_path = output_dir / f"{shortcode}_{i}{ext}"
            img_resp = client.get(img_url)
            img_resp.raise_for_status()
            img_path.write_bytes(img_resp.content)
            downloaded.append(img_path)

        content_type = "carousel" if len(downloaded) > 1 else "post"
        metadata = ReelMetadata(
            url=url, shortcode=shortcode, creator=creator,
            caption=caption, duration=0.0, content_type=content_type,
        )
        logger.info(f"Downloaded {content_type} via Apify: {len(downloaded)} image(s) by {creator}")
        return downloaded, metadata

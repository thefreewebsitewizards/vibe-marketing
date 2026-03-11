import subprocess
import base64
from pathlib import Path
from loguru import logger


def extract_keyframes(video_path: Path, output_dir: Path, max_frames: int = 8) -> list[Path]:
    """Extract keyframes from video at regular intervals using ffmpeg.

    Captures frames spread evenly across the video so we catch on-screen text,
    URLs, repo names, screenshots, etc. that the speaker references visually.
    """
    frames_dir = output_dir / "frames"
    frames_dir.mkdir(exist_ok=True)

    # Get video duration
    probe_cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path),
    ]
    probe = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=10)
    duration = float(probe.stdout.strip()) if probe.returncode == 0 else 60.0

    # Calculate interval to spread frames evenly
    interval = max(duration / (max_frames + 1), 1.0)

    # Extract frames at intervals using scene-independent method
    cmd = [
        "ffmpeg",
        "-i", str(video_path),
        "-vf", f"fps=1/{interval:.1f},scale=512:-2",
        "-frames:v", str(max_frames),
        "-q:v", "3",
        "-y",
        str(frames_dir / "frame_%03d.jpg"),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        logger.warning(f"Frame extraction failed: {result.stderr[:200]}")
        return []

    frames = sorted(frames_dir.glob("frame_*.jpg"))
    logger.info(f"Extracted {len(frames)} keyframes from {duration:.0f}s video")
    return frames


def frames_to_base64(frame_paths: list[Path]) -> list[dict]:
    """Convert frame images to base64-encoded content blocks for Claude vision API."""
    image_blocks = []
    for path in frame_paths:
        data = base64.b64encode(path.read_bytes()).decode("utf-8")
        image_blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": data,
            },
        })
    return image_blocks

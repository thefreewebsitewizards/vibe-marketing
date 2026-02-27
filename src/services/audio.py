import subprocess
from pathlib import Path
from loguru import logger


def extract_audio(video_path: Path, output_dir: Path) -> Path:
    """Extract audio from video as 16kHz mono WAV for Whisper."""
    audio_path = output_dir / f"{video_path.stem}.wav"

    logger.info(f"Extracting audio from {video_path}")

    cmd = [
        "ffmpeg",
        "-i", str(video_path),
        "-vn",                  # No video
        "-acodec", "pcm_s16le", # 16-bit PCM
        "-ar", "16000",         # 16kHz sample rate
        "-ac", "1",             # Mono
        "-y",                   # Overwrite
        str(audio_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr}")

    logger.info(f"Audio extracted: {audio_path}")
    return audio_path

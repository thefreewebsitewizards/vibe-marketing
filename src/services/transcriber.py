import asyncio
import threading
from pathlib import Path
from loguru import logger

from src.config import settings
from src.models import TranscriptResult

# Lazy-load the model to avoid slow startup
_model = None
_model_lock = threading.Lock()

# Async semaphore — acquired BEFORE entering to_thread so we never block the thread pool.
# 2 slots matches the VPS core count (2 CPUs).
whisper_semaphore = asyncio.Semaphore(2)


def _get_model():
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                from faster_whisper import WhisperModel
                logger.info(f"Loading Whisper model: {settings.whisper_model} ({settings.whisper_compute_type})")
                _model = WhisperModel(
                    settings.whisper_model,
                    device=settings.whisper_device,
                    compute_type=settings.whisper_compute_type,
                )
    return _model


def transcribe(audio_path: Path) -> TranscriptResult:
    """Transcribe audio file using faster-whisper.

    Callers should acquire whisper_semaphore before calling this via to_thread
    to avoid thread pool starvation. See telegram_handlers._run_telegram_pipeline.
    """
    logger.info(f"Transcribing {audio_path}")

    model = _get_model()
    segments, info = model.transcribe(str(audio_path), beam_size=5)

    text_parts = []
    for segment in segments:
        text_parts.append(segment.text.strip())

    full_text = " ".join(text_parts)
    logger.info(f"Transcribed {info.duration:.1f}s of {info.language} audio ({len(full_text)} chars)")

    return TranscriptResult(
        text=full_text,
        language=info.language,
        duration=info.duration,
    )

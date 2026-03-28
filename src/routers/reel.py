import json
import threading
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from src.config import settings
from src.utils.auth import require_api_key
from src.models import (
    ReelRequest, PipelineResult, PlanStatus, TranscriptResult,
    CostBreakdown,
)
from src.services.downloader import download_reel, extract_shortcode
from src.services.audio import extract_audio
from src.services.frames import extract_keyframes
from src.services.transcriber import transcribe
from src.services.analyzer import analyze_reel, analyze_carousel
from src.services.ocr import extract_text_from_images
from src.services.planner import generate_plan, check_plan_similarity
from src.utils.file_ops import create_temp_dir, cleanup_temp_dir
from src.utils.plan_writer import write_plan
from src.utils.plan_manager import is_duplicate, get_index, save_index
from src.utils.insight_distributor import distribute_insights

router = APIRouter()


def _add_processing_entry(reel_id: str, reel_url: str) -> None:
    """Add a placeholder entry to the plan index so duplicate checks work."""
    index = get_index()
    date_str = datetime.now().strftime("%Y-%m-%d")
    entry = {
        "reel_id": reel_id,
        "title": f"Processing: {reel_id}",
        "status": PlanStatus.PROCESSING.value,
        "plan_dir": f"{date_str}_{reel_id}",
        "created_at": datetime.now().isoformat(),
        "source_url": reel_url,
        "theme": "",
        "category": "",
        "relevance_score": 0.0,
        "estimated_cost": 0.0,
        "routed_to": "",
        "task_count": 0,
        "total_hours": 0.0,
    }
    index["plans"].append(entry)
    save_index(index)


def _friendly_error(error: str) -> str:
    """Convert raw error strings to user-friendly labels."""
    lower = error.lower()
    if "download" in lower or "yt-dlp" in lower or "extractor" in lower:
        return "Download failed"
    if "transcri" in lower or "whisper" in lower or "audio" in lower:
        return "Transcription failed"
    if "timeout" in lower or "timed out" in lower:
        return "Request timed out"
    if "rate limit" in lower or "429" in lower:
        return "Rate limited — try again later"
    if "api" in lower or "openrouter" in lower or "claude" in lower:
        return "Analysis failed"
    return "Processing failed"


def _update_processing_entry(reel_id: str, status: PlanStatus, error: str = "") -> None:
    """Update the processing entry status (used for marking failures)."""
    index = get_index()
    for entry in reversed(index["plans"]):
        if entry["reel_id"] == reel_id:
            entry["status"] = status.value
            if error:
                entry["title"] = _friendly_error(error)
                entry["error_detail"] = error[:300]
            break
    save_index(index)



def _run_pipeline(reel_id: str, reel_url: str, user_context: str = "") -> None:
    """Run the full pipeline in a background thread."""
    try:
        logger.info(f"Background pipeline started for {reel_id}")

        temp_dir = create_temp_dir(reel_id)

        download_result, metadata = download_reel(reel_url, temp_dir)

        costs = CostBreakdown()

        if metadata.content_type in ("carousel", "post"):
            image_paths = download_result if isinstance(download_result, list) else [download_result]
            ocr_text = extract_text_from_images(image_paths)
            transcript = TranscriptResult(text=ocr_text or metadata.caption or "", language="en")
            analysis, analysis_cr = analyze_carousel(ocr_text, metadata, image_paths, user_context=user_context)
        else:
            video_path = download_result
            frame_paths = extract_keyframes(video_path, temp_dir)
            try:
                audio_path = extract_audio(video_path, temp_dir)
                transcript = transcribe(audio_path)
            except RuntimeError:
                logger.warning(f"No audio stream in {reel_id}, using caption + visual analysis only")
                transcript = TranscriptResult(text=metadata.caption or "", language="en")
            analysis, analysis_cr = analyze_reel(transcript, metadata, frame_paths, user_context=user_context)
        costs.add("analysis", analysis_cr.model, analysis_cr.prompt_tokens, analysis_cr.completion_tokens, analysis_cr.cost_usd, analysis_cr.generation_id)

        similarity, sim_cr = check_plan_similarity(analysis)
        if sim_cr:
            costs.add("similarity", sim_cr.model, sim_cr.prompt_tokens, sim_cr.completion_tokens, sim_cr.cost_usd, sim_cr.generation_id)

        plan, plan_cr = generate_plan(analysis, metadata, user_context=user_context, similarity=similarity)
        costs.add("plan", plan_cr.model, plan_cr.prompt_tokens, plan_cr.completion_tokens, plan_cr.cost_usd, plan_cr.generation_id)

        costs.resolve_actual_costs()

        result = PipelineResult(
            reel_id=reel_id,
            status=PlanStatus.REVIEW,
            metadata=metadata,
            transcript=transcript,
            analysis=analysis,
            plan=plan,
            similarity=similarity,
            cost_breakdown=costs,
        )

        # Remove ALL old entries for this reel_id before write_plan adds the new one
        # (handles retries of failed/skipped plans creating duplicates)
        index = get_index()
        index["plans"] = [e for e in index["plans"] if e["reel_id"] != reel_id]
        save_index(index)

        write_plan(result)

        # Distribute insights to all relevant project folders
        distributions = distribute_insights(
            category=analysis.category,
            key_insights=analysis.key_insights,
            web_design_insights=analysis.web_design_insights,
            reel_id=reel_id,
            theme=analysis.theme,
            creator=metadata.creator,
            source_url=metadata.url,
        )
        if distributions:
            # Log distribution in the plan metadata
            dist_path = settings.plans_dir / result.plan_dir / "distributions.json"
            if dist_path.parent.exists():
                import json as _json
                dist_path.write_text(_json.dumps(distributions, indent=2))

        cleanup_temp_dir(reel_id)

        logger.info(f"Background pipeline complete for {reel_id}")

    except Exception as e:
        logger.error(f"Background pipeline failed for {reel_id}: {e}")
        _update_processing_entry(reel_id, PlanStatus.FAILED, str(e))


@router.post("/process-reel", status_code=202)
def process_reel(request: ReelRequest, _: str = Depends(require_api_key)) -> dict:
    """Accept a reel for processing. Returns 202 immediately; pipeline runs in the background."""
    try:
        reel_id = extract_shortcode(request.reel_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if is_duplicate(reel_id):
        raise HTTPException(
            status_code=409,
            detail=f"Reel {reel_id} has already been processed. Check /plans/{reel_id} for its status.",
        )

    _add_processing_entry(reel_id, request.reel_url)

    thread = threading.Thread(
        target=_run_pipeline,
        args=(reel_id, request.reel_url, request.context),
        daemon=True,
        name=f"pipeline-{reel_id}",
    )
    thread.start()

    logger.info(f"Pipeline dispatched to background for {reel_id}")

    return {
        "status": "processing",
        "reel_id": reel_id,
        "poll_url": f"/plans/{reel_id}",
    }


class BatchRequest(BaseModel):
    reel_urls: list[str] = Field(max_length=20)
    context: str = Field(default="", max_length=2000)


@router.post("/process-batch", status_code=202)
def process_batch(request: BatchRequest, _: str = Depends(require_api_key)) -> dict:
    """Accept multiple reels for parallel processing. Sends Telegram notification for each."""
    results = []
    for url in request.reel_urls:
        try:
            reel_id = extract_shortcode(url)
        except ValueError:
            results.append({"url": url, "status": "invalid_url"})
            continue

        if is_duplicate(reel_id):
            results.append({"reel_id": reel_id, "status": "duplicate"})
            continue

        _add_processing_entry(reel_id, url)
        thread = threading.Thread(
            target=_run_pipeline,
            args=(reel_id, url, request.context),
            daemon=True,
            name=f"pipeline-{reel_id}",
        )
        thread.start()
        results.append({"reel_id": reel_id, "status": "processing"})

    processing = [r for r in results if r.get("status") == "processing"]
    logger.info(f"Batch: {len(processing)} reels dispatched, {len(results) - len(processing)} skipped")
    return {"results": results, "processing_count": len(processing)}


class SendMessageRequest(BaseModel):
    text: str = Field(max_length=4000)
    chat_id: int | None = None  # Falls back to TELEGRAM_CHAT_ID env var


@router.post("/send-telegram")
def send_telegram(request: SendMessageRequest, _: str = Depends(require_api_key)) -> dict:
    """Send a message to the Telegram chat via the bot."""
    from src.services.telegram_bot import get_bot_app, get_bot_loop
    import asyncio

    chat_id = request.chat_id or settings.telegram_chat_id
    if not chat_id:
        raise HTTPException(status_code=503, detail="No chat_id provided and TELEGRAM_CHAT_ID not configured")

    bot_app = get_bot_app()
    loop = get_bot_loop()
    if not bot_app or not loop:
        raise HTTPException(status_code=503, detail="Telegram bot not running")

    future = asyncio.run_coroutine_threadsafe(
        bot_app.bot.send_message(
            chat_id=int(chat_id),
            text=request.text,
            disable_web_page_preview=True,
        ),
        loop,
    )
    future.result(timeout=10)
    return {"status": "sent"}

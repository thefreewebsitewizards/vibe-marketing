import json
import threading
from datetime import datetime

from fastapi import APIRouter, HTTPException
from loguru import logger

from src.config import settings
from src.models import ReelRequest, PipelineResult, PlanStatus, TranscriptResult, CostBreakdown
from src.services.downloader import download_reel, extract_shortcode
from src.services.audio import extract_audio
from src.services.frames import extract_keyframes
from src.services.transcriber import transcribe
from src.services.analyzer import analyze_reel, analyze_carousel
from src.services.ocr import extract_text_from_images
from src.services.planner import generate_plan, check_plan_similarity
from src.services.repurposer import generate_repurposing_plan
from src.services.personal_brand import generate_personal_brand_plan
from src.utils.file_ops import create_temp_dir, cleanup_temp_dir
from src.utils.plan_writer import write_plan
from src.utils.plan_manager import is_duplicate, get_index, save_index

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


def _update_processing_entry(reel_id: str, status: PlanStatus, error: str = "") -> None:
    """Update the processing entry status (used for marking failures)."""
    index = get_index()
    for entry in reversed(index["plans"]):
        if entry["reel_id"] == reel_id:
            entry["status"] = status.value
            if error:
                entry["title"] = f"Failed: {error[:100]}"
            break
    save_index(index)


def _run_pipeline(reel_id: str, reel_url: str) -> None:
    """Run the full pipeline in a background thread."""
    try:
        logger.info(f"Background pipeline started for {reel_id}")

        temp_dir = create_temp_dir(reel_id)

        download_result, metadata = download_reel(reel_url, temp_dir)

        costs = CostBreakdown()

        if metadata.content_type == "carousel":
            image_paths = download_result
            ocr_text = extract_text_from_images(image_paths)
            transcript = TranscriptResult(text=ocr_text, language="en")
            analysis, analysis_cr = analyze_carousel(ocr_text, metadata, image_paths)
        else:
            video_path = download_result
            audio_path = extract_audio(video_path, temp_dir)
            frame_paths = extract_keyframes(video_path, temp_dir)
            transcript = transcribe(audio_path)
            analysis, analysis_cr = analyze_reel(transcript, metadata, frame_paths)
        costs.add("analysis", analysis_cr.model, analysis_cr.prompt_tokens, analysis_cr.completion_tokens, analysis_cr.cost_usd)

        similarity, sim_cr = check_plan_similarity(analysis)
        if sim_cr:
            costs.add("similarity", sim_cr.model, sim_cr.prompt_tokens, sim_cr.completion_tokens, sim_cr.cost_usd)

        if similarity.recommendation == "skip":
            logger.info(f"Skipping {reel_id}: too similar to existing plans (max_score={similarity.max_score})")
            _update_processing_entry(reel_id, PlanStatus.SKIPPED,
                f"Too similar to existing plans (score {similarity.max_score})")
            cleanup_temp_dir(reel_id)
            return

        plan, plan_cr = generate_plan(analysis, metadata)
        costs.add("plan", plan_cr.model, plan_cr.prompt_tokens, plan_cr.completion_tokens, plan_cr.cost_usd)

        repurposing_plan, rep_cr = generate_repurposing_plan(analysis, metadata, transcript.text)
        costs.add("repurposing", rep_cr.model, rep_cr.prompt_tokens, rep_cr.completion_tokens, rep_cr.cost_usd)

        personal_brand_plan, pb_cr = generate_personal_brand_plan(analysis, metadata, transcript.text)
        costs.add("personal_brand", pb_cr.model, pb_cr.prompt_tokens, pb_cr.completion_tokens, pb_cr.cost_usd)

        result = PipelineResult(
            reel_id=reel_id,
            status=PlanStatus.REVIEW,
            metadata=metadata,
            transcript=transcript,
            analysis=analysis,
            plan=plan,
            repurposing_plan=repurposing_plan,
            personal_brand_plan=personal_brand_plan,
            similarity=similarity,
            cost_breakdown=costs,
        )

        # Remove the placeholder processing entry before write_plan adds the real one
        index = get_index()
        index["plans"] = [
            e for e in index["plans"]
            if not (e["reel_id"] == reel_id and e["status"] == PlanStatus.PROCESSING.value)
        ]
        save_index(index)

        write_plan(result)

        cleanup_temp_dir(reel_id)

        logger.info(f"Background pipeline complete for {reel_id}")

    except Exception as e:
        logger.error(f"Background pipeline failed for {reel_id}: {e}")
        _update_processing_entry(reel_id, PlanStatus.FAILED, str(e))


@router.post("/process-reel", status_code=202)
def process_reel(request: ReelRequest) -> dict:
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
        args=(reel_id, request.reel_url),
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

from fastapi import APIRouter, HTTPException
from loguru import logger

from src.models import ReelRequest, PipelineResult, PlanStatus
from src.services.downloader import download_reel, extract_shortcode
from src.services.audio import extract_audio
from src.services.frames import extract_keyframes
from src.services.transcriber import transcribe
from src.services.analyzer import analyze_reel
from src.services.planner import generate_plan
from src.utils.file_ops import create_temp_dir, cleanup_temp_dir
from src.utils.plan_writer import write_plan
from src.utils.plan_manager import is_duplicate

router = APIRouter()


@router.post("/process-reel")
def process_reel(request: ReelRequest) -> dict:
    """Full pipeline: download → extract audio/frames → transcribe → analyze → plan → store."""
    reel_id = ""
    try:
        reel_id = extract_shortcode(request.reel_url)

        if is_duplicate(reel_id):
            raise HTTPException(
                status_code=409,
                detail=f"Reel {reel_id} has already been processed. Check /plans/{reel_id} for its status.",
            )

        logger.info(f"Processing reel: {reel_id}")

        # Setup
        temp_dir = create_temp_dir(reel_id)

        # Pipeline
        video_path, metadata = download_reel(request.reel_url, temp_dir)
        audio_path = extract_audio(video_path, temp_dir)
        frame_paths = extract_keyframes(video_path, temp_dir)
        transcript = transcribe(audio_path)
        analysis = analyze_reel(transcript, metadata, frame_paths)
        plan = generate_plan(analysis, metadata)

        # Store results
        result = PipelineResult(
            reel_id=reel_id,
            status=PlanStatus.REVIEW,
            metadata=metadata,
            transcript=transcript,
            analysis=analysis,
            plan=plan,
        )
        plan_dir = write_plan(result)

        # Read back the full plan markdown for review
        plan_md = (plan_dir / "plan.md").read_text()

        # Cleanup temp files
        cleanup_temp_dir(reel_id)

        logger.info(f"Pipeline complete for {reel_id}")
        return {
            "status": "success",
            "reel_id": reel_id,
            "plan_title": plan.title,
            "plan_summary": plan.summary,
            "tasks_count": len(plan.tasks),
            "total_hours": plan.total_estimated_hours,
            "plan_dir": str(plan_dir),
            "relevance_score": analysis.relevance_score,
            "plan_markdown": plan_md,
        }

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Pipeline failed for {reel_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Pipeline failed: {e}")

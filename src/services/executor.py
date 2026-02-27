"""Plan execution engine — reads approved plans and executes tasks Claude Code can handle."""
import json
from pathlib import Path
from loguru import logger

from src.config import settings
from src.models import PlanStatus
from src.utils.plan_manager import get_plans_by_status, update_plan_status


def get_approved_plans() -> list[dict]:
    """Get all plans that are approved and ready for execution."""
    return get_plans_by_status(PlanStatus.APPROVED)


def load_plan(plan_dir_name: str) -> dict:
    """Load a plan's full data from its directory."""
    plan_dir = settings.plans_dir / plan_dir_name

    data = {"plan_dir": str(plan_dir), "plan_dir_name": plan_dir_name}

    plan_md = plan_dir / "plan.md"
    if plan_md.exists():
        data["plan_markdown"] = plan_md.read_text()

    meta_path = plan_dir / "metadata.json"
    if meta_path.exists():
        with open(meta_path) as f:
            data["metadata"] = json.load(f)

    analysis_path = plan_dir / "analysis.json"
    if analysis_path.exists():
        with open(analysis_path) as f:
            data["analysis"] = json.load(f)

    transcript_path = plan_dir / "transcript.txt"
    if transcript_path.exists():
        data["transcript"] = transcript_path.read_text()

    return data


def mark_in_progress(reel_id: str) -> None:
    update_plan_status(reel_id, PlanStatus.IN_PROGRESS)


def mark_completed(reel_id: str) -> None:
    update_plan_status(reel_id, PlanStatus.COMPLETED)


def mark_failed(reel_id: str) -> None:
    update_plan_status(reel_id, PlanStatus.FAILED)


def get_execution_summary() -> str:
    """Get a summary of all plans by status for display."""
    lines = []
    for status in PlanStatus:
        plans = get_plans_by_status(status)
        if plans:
            lines.append(f"\n{status.value.upper()} ({len(plans)}):")
            for p in plans:
                lines.append(f"  - {p['reel_id']}: {p['title']}")
    return "\n".join(lines) if lines else "No plans found."

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from loguru import logger as audit_logger
from pydantic import BaseModel, Field

from src.config import settings
from src.models import PlanStatus
from src.utils.auth import require_api_key


def _audit_log(action: str, reel_id: str, details: dict) -> None:
    """Append to plans/_audit.jsonl for action history."""
    entry = {"ts": datetime.now().isoformat(), "action": action, "reel_id": reel_id, **details}
    audit_path = settings.plans_dir / "_audit.jsonl"
    try:
        with open(audit_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass
    audit_logger.info(f"AUDIT: {action} {reel_id} {details}")
from src.services.executor import (
    get_approved_plans,
    load_plan,
    load_plan_tasks,
    get_execution_summary,
)
from src.utils.plan_manager import update_plan_status, get_plans_by_status, find_plan_by_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/plans")


class StatusUpdate(BaseModel):
    status: PlanStatus


class ApproveRequest(BaseModel):
    selected_tasks: list[int] = Field(max_length=50)
    notes: str = Field(default="", max_length=2000)


class FeedbackRequest(BaseModel):
    rating: Literal["good", "bad", "partial"]
    comment: str = Field(default="", max_length=2000)


_REEL_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _validate_reel_id(reel_id: str) -> str:
    """Validate reel_id to prevent path traversal or injection."""
    if not _REEL_ID_PATTERN.match(reel_id):
        raise HTTPException(status_code=400, detail="Invalid reel ID format")
    return reel_id


@router.get("/")
def list_plans():
    """List all plans grouped by status."""
    result = {}
    for status in PlanStatus:
        plans = get_plans_by_status(status)
        if plans:
            result[status.value] = plans
    return result


@router.get("/approved")
def list_approved():
    """Get all approved plans ready for execution."""
    return get_approved_plans()


@router.get("/{reel_id}/view", response_class=HTMLResponse)
def view_plan(reel_id: str):
    """Serve the pre-rendered HTML view of a plan with live status."""
    _validate_reel_id(reel_id)
    entry = find_plan_by_id(reel_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Plan not found: {reel_id}")
    html_path = settings.plans_dir / entry["plan_dir"] / "view.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="HTML view not generated for this plan")
    html = html_path.read_text()
    # Inject live status from index (pre-rendered HTML bakes in the
    # status at creation time, which goes stale after approve/skip/complete)
    live_status = entry.get("status", "review")
    html = re.sub(
        r"var PLAN_STATUS = '[^']*';",
        f"var PLAN_STATUS = '{live_status}';",
        html,
    )
    return HTMLResponse(html)


@router.get("/{reel_id}")
def get_plan(reel_id: str):
    """Get full plan data for a specific reel."""
    _validate_reel_id(reel_id)
    entry = find_plan_by_id(reel_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Plan not found: {reel_id}")
    return load_plan(entry["plan_dir"])


@router.patch("/{reel_id}/status")
def update_status(reel_id: str, body: StatusUpdate, _: str = Depends(require_api_key)):
    """Update a plan's status."""
    _validate_reel_id(reel_id)
    updated = update_plan_status(reel_id, body.status)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Plan not found: {reel_id}")
    return {"reel_id": reel_id, "status": body.status.value}


@router.post("/{reel_id}/approve")
def approve_plan(reel_id: str, body: ApproveRequest):
    """Approve a plan with selected tasks. No API key required (web UI use)."""
    _validate_reel_id(reel_id)
    entry = find_plan_by_id(reel_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Plan not found: {reel_id}")

    if entry["status"] not in (PlanStatus.REVIEW.value, "review"):
        raise HTTPException(status_code=400, detail=f"Plan is {entry['status']}, must be in review")

    # Validate task indices against plan
    plan_data = load_plan_tasks(entry["plan_dir"])
    if not plan_data:
        raise HTTPException(status_code=404, detail="No plan.json found")

    task_count = len(plan_data.get("tasks", []))
    invalid = [i for i in body.selected_tasks if i < 0 or i >= task_count]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Invalid task indices: {invalid}")

    if not body.selected_tasks:
        raise HTTPException(status_code=400, detail="No tasks selected")

    # Save selected tasks and notes to metadata
    meta_path = settings.plans_dir / entry["plan_dir"] / "metadata.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
    else:
        meta = {}

    meta["selected_tasks"] = body.selected_tasks
    if body.notes:
        meta["approval_notes"] = body.notes
    meta_path.write_text(json.dumps(meta, indent=2))

    # Approve — update_plan_status triggers execution via _trigger_execution
    update_plan_status(reel_id, PlanStatus.APPROVED)

    _audit_log("approve", reel_id, {"selected_tasks": body.selected_tasks, "notes": body.notes})

    # Send Telegram notification (non-blocking)
    _notify_plan_approved(reel_id, plan_data, body.selected_tasks)

    return {
        "reel_id": reel_id,
        "status": "approved",
        "selected_tasks": body.selected_tasks,
        "notes": body.notes,
    }


def _notify_plan_approved(reel_id: str, plan_data: dict, selected_tasks: list[int]) -> None:
    """Send Telegram notification when a plan is approved. Replaces n8n workflow."""
    try:
        from src.services.telegram_bot import get_bot_app, get_bot_loop

        chat_id = settings.telegram_chat_id
        if not chat_id:
            return

        bot_app = get_bot_app()
        if not bot_app:
            logger.warning("Telegram bot not running, skipping approval notification")
            return

        title = plan_data.get("title", f"Plan: {reel_id}")
        tasks = plan_data.get("tasks", [])
        selected = [tasks[i] for i in selected_tasks if i < len(tasks)]
        auto_tasks = [t for t in selected if t.get("automatable")]
        manual_tasks = [t for t in selected if not t.get("automatable")]

        lines = [f"*Plan Approved*: {title}"]
        if auto_tasks:
            lines.append(f"\n*Auto-executing ({len(auto_tasks)}):*")
            for t in auto_tasks[:5]:
                lines.append(f"  - {t.get('title', t.get('description', '?'))}")
        if manual_tasks:
            lines.append(f"\n*Manual ({len(manual_tasks)}):*")
            for t in manual_tasks[:5]:
                lines.append(f"  - {t.get('title', t.get('description', '?'))}")

        web_url = f"https://reelbot.leadneedleai.com/plans/{reel_id}/view"
        lines.append(f"\n[View Plan]({web_url})")

        message = "\n".join(lines)

        loop = get_bot_loop()
        if loop:
            import asyncio
            asyncio.run_coroutine_threadsafe(
                bot_app.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode="Markdown",
                    disable_web_page_preview=True,
                ),
                loop,
            )
        else:
            logger.warning("Telegram bot loop not available, skipping notification")
    except Exception as e:
        logger.error(f"Plan approval notification failed: {e}")


@router.post("/{reel_id}/skip")
def skip_plan(reel_id: str):
    """Skip/reject a plan. No API key required (web UI use)."""
    _validate_reel_id(reel_id)
    entry = find_plan_by_id(reel_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Plan not found: {reel_id}")

    update_plan_status(reel_id, PlanStatus.SKIPPED)
    _audit_log("skip", reel_id, {})
    return {"reel_id": reel_id, "status": "skipped"}


@router.post("/{reel_id}/feedback")
def submit_feedback(reel_id: str, body: FeedbackRequest):
    """Save feedback for a plan."""
    _validate_reel_id(reel_id)
    from src.utils.feedback import save_feedback, update_feedback_comment

    save_feedback(reel_id, body.rating)
    if body.comment:
        update_feedback_comment(reel_id, body.comment)
    _audit_log("feedback", reel_id, {"rating": body.rating, "comment": body.comment[:100] if body.comment else ""})

    return {"reel_id": reel_id, "rating": body.rating}


@router.get("/summary/all")
def summary():
    """Get a text summary of all plans."""
    return {"summary": get_execution_summary()}


@router.post("/{reel_id}/execute")
def execute_plan_endpoint(reel_id: str, _: str = Depends(require_api_key)):
    """Manually trigger execution of an approved plan."""
    _validate_reel_id(reel_id)
    entry = find_plan_by_id(reel_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Plan {reel_id} not found")
    if entry["status"] != PlanStatus.APPROVED.value:
        raise HTTPException(status_code=400, detail=f"Plan is {entry['status']}, must be approved")

    from src.services.executor import execute_plan
    import threading

    thread = threading.Thread(
        target=execute_plan,
        args=(reel_id, entry["plan_dir"]),
        daemon=True,
    )
    thread.start()

    return {"status": "executing", "reel_id": reel_id}


@router.get("/{reel_id}/tasks")
def list_tasks(reel_id: str):
    """List all tasks for a plan with their execution status.

    This is the primary endpoint for external agents (Claude Code, OpenClaw)
    to discover what work needs doing.
    """
    _validate_reel_id(reel_id)
    entry = find_plan_by_id(reel_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Plan not found: {reel_id}")

    plan_data = load_plan_tasks(entry["plan_dir"])
    if not plan_data:
        raise HTTPException(status_code=404, detail="No plan.json found")

    # Check approved level from metadata
    meta_path = settings.plans_dir / entry["plan_dir"] / "metadata.json"
    approved_level = None
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        approved_level = meta.get("approved_level")

    # Load execution log if it exists
    log_path = settings.plans_dir / entry["plan_dir"] / "execution_log.json"
    executed = {}
    if log_path.exists():
        log = json.loads(log_path.read_text())
        for r in log.get("auto_results", []):
            executed[r["task_index"]] = r

    _VALID_TASK_STATUSES = {"pending", "completed", "failed", "needs_human"}

    tasks = []
    for i, task in enumerate(plan_data.get("tasks", [])):
        # Filter by approved level (cumulative: L2 includes L1 tasks)
        task_level = task.get("level", 1)
        if approved_level and task_level > approved_level:
            continue

        exec_result = executed.get(i)
        task_status = "pending"
        if exec_result:
            raw_status = exec_result.get("status", "completed")
            task_status = raw_status if raw_status in _VALID_TASK_STATUSES else "pending"
        elif task.get("requires_human"):
            task_status = "needs_human"

        tasks.append({
            "index": i,
            "title": task.get("title", ""),
            "description": task.get("description", ""),
            "tools": task.get("tools", []),
            "tool_data": task.get("tool_data", {}),
            "requires_human": task.get("requires_human", False),
            "priority": task.get("priority", "medium"),
            "deliverables": task.get("deliverables", []),
            "level": task_level,
            "status": task_status,
            "execution_notes": exec_result.get("notes", "") if exec_result else "",
        })

    return {
        "reel_id": reel_id,
        "plan_status": entry["status"],
        "title": plan_data.get("title", ""),
        "tasks": tasks,
    }


class TaskCompletion(BaseModel):
    status: Literal["completed", "failed"] = "completed"
    notes: str = Field(default="", max_length=2000)


@router.patch("/{reel_id}/tasks/{task_index}")
def update_task(reel_id: str, task_index: int, body: TaskCompletion, _: str = Depends(require_api_key)):
    """Mark a specific task as completed/failed. For external agent use.

    Updates the execution_log.json in the plan directory.
    """
    _validate_reel_id(reel_id)
    entry = find_plan_by_id(reel_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Plan not found: {reel_id}")

    plan_data = load_plan_tasks(entry["plan_dir"])
    if not plan_data:
        raise HTTPException(status_code=404, detail="No plan.json found")

    tasks = plan_data.get("tasks", [])
    if task_index < 0 or task_index >= len(tasks):
        raise HTTPException(status_code=404, detail=f"Task index {task_index} out of range")

    # Load or create execution log
    log_path = settings.plans_dir / entry["plan_dir"] / "execution_log.json"
    if log_path.exists():
        log = json.loads(log_path.read_text())
    else:
        log = {"reel_id": reel_id, "auto_results": [], "human_tasks_pending": []}

    # Update or append result
    existing = None
    for r in log["auto_results"]:
        if r["task_index"] == task_index:
            existing = r
            break

    from datetime import datetime
    result_entry = {
        "task_index": task_index,
        "title": tasks[task_index].get("title", ""),
        "status": body.status,
        "notes": body.notes,
        "executed_at": datetime.now().isoformat(),
    }

    if existing:
        existing.update(result_entry)
    else:
        log["auto_results"].append(result_entry)

    log_path.write_text(json.dumps(log, indent=2))

    # Check if all tasks are now done
    completed_indices = {r["task_index"] for r in log["auto_results"] if r["status"] == "completed"}
    all_auto = {i for i, t in enumerate(tasks) if not t.get("requires_human")}
    if all_auto and all_auto <= completed_indices:
        has_human = any(t.get("requires_human") for t in tasks)
        if not has_human:
            update_plan_status(reel_id, PlanStatus.COMPLETED)

    return {"reel_id": reel_id, "task_index": task_index, "status": body.status}

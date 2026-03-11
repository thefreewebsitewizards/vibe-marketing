import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from src.config import settings
from src.models import PlanStatus
from src.utils.auth import require_api_key
from src.services.executor import (
    get_approved_plans,
    load_plan,
    load_plan_tasks,
    get_execution_summary,
)
from src.utils.plan_manager import update_plan_status, get_plans_by_status, find_plan_by_id

router = APIRouter(prefix="/plans")


class StatusUpdate(BaseModel):
    status: PlanStatus


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
    """Serve the pre-rendered HTML view of a plan."""
    entry = find_plan_by_id(reel_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Plan not found: {reel_id}")
    html_path = settings.plans_dir / entry["plan_dir"] / "view.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="HTML view not generated for this plan")
    return HTMLResponse(html_path.read_text())


@router.get("/{reel_id}")
def get_plan(reel_id: str):
    """Get full plan data for a specific reel."""
    entry = find_plan_by_id(reel_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Plan not found: {reel_id}")
    return load_plan(entry["plan_dir"])


@router.patch("/{reel_id}/status")
def update_status(reel_id: str, body: StatusUpdate, _: str = Depends(require_api_key)):
    """Update a plan's status."""
    updated = update_plan_status(reel_id, body.status)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Plan not found: {reel_id}")
    return {"reel_id": reel_id, "status": body.status.value}


@router.get("/summary/all")
def summary():
    """Get a text summary of all plans."""
    return {"summary": get_execution_summary()}


@router.post("/{reel_id}/execute")
def execute_plan_endpoint(reel_id: str, _: str = Depends(require_api_key)):
    """Manually trigger execution of an approved plan."""
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

    tasks = []
    for i, task in enumerate(plan_data.get("tasks", [])):
        # Filter by approved level (cumulative: L2 includes L1 tasks)
        task_level = task.get("level", 1)
        if approved_level and task_level > approved_level:
            continue

        exec_result = executed.get(i)
        task_status = "pending"
        if exec_result:
            task_status = exec_result.get("status", "completed")
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
    status: str = "completed"  # completed or failed
    notes: str = ""


@router.patch("/{reel_id}/tasks/{task_index}")
def update_task(reel_id: str, task_index: int, body: TaskCompletion, _: str = Depends(require_api_key)):
    """Mark a specific task as completed/failed. For external agent use.

    Updates the execution_log.json in the plan directory.
    """
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

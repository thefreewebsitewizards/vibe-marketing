"""Plan execution engine -- reads approved plans and executes tasks by tier.

Tier 1 (auto): Claude Code can handle -- code, configs, scripts, API calls
Tier 2 (human): Requires Dylan -- money, judgment, external commitments
"""
import json
from pathlib import Path
from datetime import datetime

import httpx
from loguru import logger

from src.config import settings
from src.models import PlanStatus
from src.utils.plan_manager import get_plans_by_status, update_plan_status
from src.services.tool_handlers import (
    TOOL_HANDLERS as _TOOL_HANDLERS,
    handle_sales_script as _handle_sales_script,
    handle_content as _handle_content,
    handle_knowledge_base as _handle_knowledge_base,
)

# Tools that are deferred to the VPS agent loop (not executed server-side)
_DEFERRED_TOOLS = {"claude_code"}


def classify_task(task: dict) -> str:
    """Classify a task as 'auto', 'human', or 'deferred'."""
    if task.get("requires_human", False):
        return "human"
    tools = task.get("tools", [])
    if any(t in _DEFERRED_TOOLS for t in tools):
        return "deferred"
    return "auto"


def get_approved_plans() -> list[dict]:
    """Get all plans that are approved and ready for execution."""
    return get_plans_by_status(PlanStatus.APPROVED)


def load_plan_tasks(plan_dir_name: str) -> dict | None:
    """Load structured plan data from plan.json."""
    plan_json = settings.plans_dir / plan_dir_name / "plan.json"
    if not plan_json.exists():
        logger.warning(f"No plan.json found in {plan_dir_name}")
        return None
    with open(plan_json) as f:
        return json.load(f)


def load_plan(plan_dir_name: str) -> dict:
    """Load a plan's full data from its directory."""
    plan_dir = settings.plans_dir / plan_dir_name
    data = {"plan_dir": str(plan_dir), "plan_dir_name": plan_dir_name}

    for name, key in [("plan.md", "plan_markdown"), ("plan.json", "plan_data"),
                      ("metadata.json", "metadata"), ("analysis.json", "analysis"),
                      ("transcript.txt", "transcript")]:
        path = plan_dir / name
        if path.exists():
            content = path.read_text()
            data[key] = json.loads(content) if name.endswith(".json") else content

    return data


def _execute_auto_task(task: dict, plan_dir: str, task_index: int) -> dict:
    """Execute a single auto task using tool-specific handlers."""
    title = task.get("title", "Untitled")
    tools = task.get("tools", [])
    tool_data = task.get("tool_data", {})

    logger.info(f"Executing task {task_index}: {title} (tools: {tools})")

    result = {
        "task_index": task_index,
        "title": title,
        "status": "completed",
        "tools": tools,
        "notes": "",
        "executed_at": datetime.now().isoformat(),
    }

    handler_results = []
    for tool in tools:
        handler = _TOOL_HANDLERS.get(tool)
        if handler:
            handler_results.append(handler(task, tool_data, plan_dir))
        else:
            handler_results.append(f"[{tool}] No handler -- logged only")

    result["notes"] = "; ".join(handler_results) if handler_results else "No tools to execute"
    return result


def _notify_human_tasks(reel_id: str, plan_title: str, human_tasks: list[dict]) -> None:
    """Send Telegram notification about tasks that need human action."""
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        logger.warning("Telegram not configured, cannot notify about human tasks")
        return

    task_lines = []
    for i, task in enumerate(human_tasks, 1):
        reason = task.get("human_reason", "Requires human judgment")
        task_lines.append(f"{i}. *{task['title']}*\n   _{reason}_")

    message = (
        f"*Plan needs your input*\n\n"
        f"*{plan_title}*\n\n"
        f"These tasks need you:\n"
        + "\n".join(task_lines)
        + f"\n\nReply /done {reel_id} when complete"
    )

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        httpx.post(url, json={
            "chat_id": int(settings.telegram_chat_id),
            "text": message,
            "parse_mode": "Markdown",
        }, timeout=10.0)
    except Exception as e:
        logger.error(f"Failed to notify about human tasks: {e}")


def _notify_execution_complete(reel_id: str, plan_title: str, results: list[dict], human_count: int) -> None:
    """Send Telegram summary of execution results."""
    if not settings.telegram_bot_token or not settings.telegram_chat_id:
        return

    completed = sum(1 for r in results if r["status"] == "completed")
    failed = sum(1 for r in results if r["status"] == "failed")

    status_line = f"{completed} auto-tasks done"
    if failed:
        status_line += f", {failed} failed"
    if human_count:
        status_line += f", {human_count} waiting on you"

    message = f"*Execution complete*\n\n*{plan_title}*\n{status_line}"

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    try:
        httpx.post(url, json={
            "chat_id": int(settings.telegram_chat_id),
            "text": message,
            "parse_mode": "Markdown",
        }, timeout=10.0)
    except Exception as e:
        logger.error(f"Failed to send execution summary: {e}")


def execute_plan(reel_id: str, plan_dir_name: str) -> dict:
    """Execute an approved plan: auto tasks run, human tasks get notified.

    Reads approved_level from metadata.json and only executes tasks
    at or below that level (levels are cumulative: L2 includes L1).

    Returns summary dict with counts and results.
    """
    plan_data = load_plan_tasks(plan_dir_name)
    if not plan_data:
        logger.error(f"Cannot execute {reel_id}: no plan.json")
        update_plan_status(reel_id, PlanStatus.FAILED)
        return {"error": "no plan.json", "auto_count": 0, "human_count": 0}

    tasks = plan_data.get("tasks", [])
    plan_title = plan_data.get("title", "Untitled Plan")

    # Read selected tasks from metadata (set during web approval)
    selected_tasks = None
    meta_path = settings.plans_dir / plan_dir_name / "metadata.json"
    if meta_path.exists():
        try:
            with open(meta_path) as f:
                meta = json.load(f)
            selected_tasks = meta.get("selected_tasks")
            if selected_tasks is None:
                approved_level = meta.get("approved_level")
                if approved_level:
                    selected_tasks = [
                        i for i, t in enumerate(tasks)
                        if t.get("level", 1) <= approved_level
                    ]
        except Exception as e:
            logger.warning(f"Failed to read task selection: {e}")

    # Filter to only selected tasks
    if selected_tasks is not None:
        selected_set = set(selected_tasks)
        tasks_with_indices = [(i, t) for i, t in enumerate(tasks) if i in selected_set]
        logger.info(f"Executing {len(tasks_with_indices)} selected tasks out of {len(tasks)}")
    else:
        tasks_with_indices = list(enumerate(tasks))

    auto_tasks = [(i, t) for i, t in tasks_with_indices if classify_task(t) == "auto"]
    human_tasks = [t for _, t in tasks_with_indices if classify_task(t) == "human"]
    deferred_tasks = [t for _, t in tasks_with_indices if classify_task(t) == "deferred"]

    if deferred_tasks:
        logger.info(f"{len(deferred_tasks)} task(s) deferred to VPS agent loop (claude_code)")

    update_plan_status(reel_id, PlanStatus.IN_PROGRESS)

    results = []
    for task_index, task in auto_tasks:
        try:
            result = _execute_auto_task(task, str(settings.plans_dir / plan_dir_name), task_index)
            results.append(result)
        except Exception as e:
            logger.error(f"Task {task_index} failed: {e}")
            results.append({
                "task_index": task_index,
                "title": task.get("title", ""),
                "status": "failed",
                "error": str(e),
            })

    log_path = settings.plans_dir / plan_dir_name / "execution_log.json"
    log_path.write_text(json.dumps({
        "reel_id": reel_id,
        "executed_at": datetime.now().isoformat(),
        "auto_results": results,
        "human_tasks_pending": [t.get("title") for t in human_tasks],
        "deferred_tasks_pending": [t.get("title") for t in deferred_tasks],
    }, indent=2))

    if human_tasks:
        _notify_human_tasks(reel_id, plan_title, human_tasks)

    _notify_execution_complete(reel_id, plan_title, results, len(human_tasks))

    all_auto_passed = all(r["status"] == "completed" for r in results)
    if human_tasks or deferred_tasks:
        pass  # Keep in_progress -- waiting on human or agent loop
    elif all_auto_passed:
        update_plan_status(reel_id, PlanStatus.COMPLETED)
    else:
        update_plan_status(reel_id, PlanStatus.FAILED)

    return {
        "auto_count": len(auto_tasks),
        "human_count": len(human_tasks),
        "results": results,
    }


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

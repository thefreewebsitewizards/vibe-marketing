"""Manage plan status transitions and lookups."""

import json
import threading
from pathlib import Path

from loguru import logger

from src.config import settings
from src.models import PlanStatus

# Lock for read-modify-write on _index.json
_index_lock = threading.Lock()


def get_index() -> dict:
    """Read the plan index."""
    index_path = settings.plans_dir / "_index.json"
    if index_path.exists():
        with open(index_path) as f:
            return json.load(f)
    return {"plans": []}


def save_index(index: dict) -> None:
    """Write the plan index atomically (write to temp, then rename)."""
    index_path = settings.plans_dir / "_index.json"
    tmp_path = index_path.with_suffix(".tmp")
    with open(tmp_path, "w") as f:
        json.dump(index, f, indent=2)
    tmp_path.replace(index_path)


def update_plan_status(reel_id: str, new_status: PlanStatus) -> bool:
    """Update a plan's status in both _index.json and its metadata.json.
    Returns True if found and updated."""
    with _index_lock:
        index = get_index()

        found = False
        plan_dir_name = None
        for entry in index["plans"]:
            if entry["reel_id"] == reel_id:
                entry["status"] = new_status.value
                plan_dir_name = entry["plan_dir"]
                found = True
                break  # Only update first match

        if not found:
            return False

        save_index(index)

    # Also update metadata.json in the plan directory
    if plan_dir_name:
        meta_path = settings.plans_dir / plan_dir_name / "metadata.json"
        if meta_path.exists():
            with open(meta_path) as f:
                meta = json.load(f)
            meta["status"] = new_status.value
            with open(meta_path, "w") as f:
                json.dump(meta, f, indent=2)

    logger.info(f"Plan {reel_id} status → {new_status.value}")

    # Auto-execution trigger: notify when a plan is approved
    if new_status == PlanStatus.APPROVED:
        _trigger_execution(reel_id, plan_dir_name)

    return True


def _trigger_execution(reel_id: str, plan_dir_name: str | None) -> None:
    """Fire execution when a plan is approved.
    Writes to queue file AND tries immediate execution."""
    # Write to queue (for watcher fallback)
    trigger_path = settings.plans_dir / "_approved_queue.json"
    queue = []
    if trigger_path.exists():
        with open(trigger_path) as f:
            queue = json.load(f)

    if not any(item["reel_id"] == reel_id for item in queue):
        queue.append({
            "reel_id": reel_id,
            "plan_dir": plan_dir_name,
            "approved_at": __import__("datetime").datetime.now().isoformat(),
        })
        with open(trigger_path, "w") as f:
            json.dump(queue, f, indent=2)
        logger.info(f"Execution trigger: {reel_id} added to approved queue")

    # Try immediate execution (in background thread)
    if plan_dir_name:
        import threading
        from src.services.executor import execute_plan

        thread = threading.Thread(
            target=execute_plan,
            args=(reel_id, plan_dir_name),
            daemon=True,
            name=f"executor-{reel_id}",
        )
        thread.start()
        logger.info(f"Executor thread started for {reel_id}")


def get_plans_by_status(status: PlanStatus) -> list[dict]:
    """Get all plans with a given status."""
    index = get_index()
    return [p for p in index["plans"] if p["status"] == status.value]


def get_latest_plan() -> dict | None:
    """Get the most recently created plan."""
    index = get_index()
    if index["plans"]:
        return index["plans"][-1]
    return None


def find_plan_by_id(reel_id: str) -> dict | None:
    """Find the most recent plan entry for a reel_id."""
    index = get_index()
    for entry in reversed(index["plans"]):
        if entry["reel_id"] == reel_id:
            return entry
    return None


def is_duplicate(reel_id: str) -> bool:
    """Check if this reel has already been processed."""
    return find_plan_by_id(reel_id) is not None


def load_plan_content(reel_id: str) -> str:
    """Load the plan.md content for a given reel_id. Returns empty string if not found."""
    index = get_index()
    for entry in reversed(index["plans"]):
        if entry["reel_id"] == reel_id:
            plan_md = settings.plans_dir / entry["plan_dir"] / "plan.md"
            if plan_md.exists():
                content = plan_md.read_text()
                # Truncate to ~2000 chars to keep token cost reasonable
                return content[:2000]
    return ""


def get_past_plan_summaries(limit: int = 10) -> str:
    """Get summaries of recent plans for knowledge base cross-referencing.
    Returns a text block the planner can use to avoid duplicate recommendations."""
    index = get_index()
    plans = index.get("plans", [])
    if not plans:
        return ""

    recent = plans[-limit:]
    lines = []
    for p in recent:
        plan_dir = settings.plans_dir / p["plan_dir"]
        plan_md = plan_dir / "plan.md"
        if plan_md.exists():
            # Extract just the title and task titles from the plan
            content = plan_md.read_text()
            task_titles = []
            for line in content.split("\n"):
                if line.startswith("### "):
                    # Strip "### 1. " prefix
                    title = line.lstrip("#").strip()
                    if title and title[0].isdigit():
                        title = title.split(". ", 1)[-1]
                    task_titles.append(title)
            lines.append(f"- [{p['reel_id']}] {p['title']}: {', '.join(task_titles)}")
        else:
            lines.append(f"- [{p['reel_id']}] {p['title']}")

    return "\n".join(lines)

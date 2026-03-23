"""Central changes log — tracks every modification made by plan execution.

Each entry records what was changed, where, and why. Persisted as JSONL
in the plans volume so it survives deploys.
"""
import json
import threading
from datetime import datetime
from pathlib import Path

from loguru import logger

from src.config import settings

_LOG_PATH = settings.plans_dir / "_changes.jsonl"
_lock = threading.Lock()


def log_change(
    reel_id: str,
    change_type: str,
    target: str,
    summary: str,
    detail: str = "",
    source_url: str = "",
    plan_title: str = "",
) -> dict:
    """Append a change entry to the log.

    Args:
        reel_id: Source reel shortcode
        change_type: Category (sales_script, knowledge_base, content_draft, claude_code, etc.)
        target: What was changed (section ID, KB entry title, file path, etc.)
        summary: One-line description of the change
        detail: Full content or diff (optional, can be long)
        source_url: Instagram URL of the source reel
        plan_title: Title of the plan that triggered this change
    """
    entry = {
        "timestamp": datetime.now().isoformat(),
        "reel_id": reel_id,
        "source_url": source_url,
        "plan_title": plan_title,
        "change_type": change_type,
        "target": target,
        "summary": summary,
        "detail": detail,
    }

    with _lock:
        with open(_LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")

    logger.debug(f"Change logged: [{change_type}] {target} — {summary}")
    return entry


def get_changes(limit: int = 100, change_type: str = "") -> list[dict]:
    """Read recent changes, optionally filtered by type."""
    if not _LOG_PATH.exists():
        return []

    entries = []
    with open(_LOG_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if change_type and entry.get("change_type") != change_type:
                    continue
                entries.append(entry)
            except json.JSONDecodeError:
                continue

    # Most recent first
    entries.reverse()
    return entries[:limit]


def get_changes_summary() -> dict:
    """Get a count of changes by type."""
    if not _LOG_PATH.exists():
        return {}

    counts: dict[str, int] = {}
    with open(_LOG_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                ct = entry.get("change_type", "unknown")
                counts[ct] = counts.get(ct, 0) + 1
            except json.JSONDecodeError:
                continue

    return counts

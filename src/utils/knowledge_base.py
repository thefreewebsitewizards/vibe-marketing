"""Persistent knowledge base for L1 "note it" tasks.

Stores insights from reels as searchable entries in a JSON file.
"""
import json
from datetime import datetime
from pathlib import Path
from loguru import logger

from src.config import settings


def _kb_path() -> Path:
    return settings.plans_dir / "_knowledge_base.json"


def _load() -> list[dict]:
    path = _kb_path()
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return []


def _save(entries: list[dict]) -> None:
    path = _kb_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(entries, f, indent=2)


def add_entry(
    reel_id: str,
    title: str,
    content: str,
    category: str = "",
    tags: list[str] | None = None,
    source_url: str = "",
) -> dict:
    """Add a knowledge base entry. Returns the new entry."""
    entries = _load()

    entry = {
        "id": f"{reel_id}_{int(datetime.now().timestamp())}",
        "reel_id": reel_id,
        "title": title,
        "content": content,
        "category": category,
        "tags": tags or [],
        "source_url": source_url,
        "created_at": datetime.now().isoformat(),
    }

    entries.append(entry)
    _save(entries)
    logger.info(f"KB entry added: {title} (reel: {reel_id})")
    return entry


def get_entries(
    category: str = "",
    tag: str = "",
    limit: int = 50,
) -> list[dict]:
    """Get knowledge base entries, optionally filtered."""
    entries = _load()

    if category:
        entries = [e for e in entries if e.get("category") == category]
    if tag:
        entries = [e for e in entries if tag in e.get("tags", [])]

    return entries[-limit:]


def search_entries(query: str, limit: int = 20) -> list[dict]:
    """Simple text search across title and content."""
    entries = _load()
    query_lower = query.lower()
    matches = [
        e for e in entries
        if query_lower in e.get("title", "").lower()
        or query_lower in e.get("content", "").lower()
        or any(query_lower in t.lower() for t in e.get("tags", []))
    ]
    return matches[-limit:]


def get_recent_context(limit: int = 10) -> str:
    """Get recent KB entries as context string for LLM prompts."""
    entries = _load()[-limit:]
    if not entries:
        return ""

    lines = []
    for e in entries:
        tags_str = f" [{', '.join(e['tags'])}]" if e.get("tags") else ""
        lines.append(f"- {e['title']}{tags_str}: {e['content'][:100]}")

    return "\n".join(lines)

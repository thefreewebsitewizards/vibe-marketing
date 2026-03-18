"""Individual tool handler functions for plan task execution.

Each handler processes a specific tool type (sales_script, content, etc.)
and returns a status string describing what was done.
"""
import json
import re
from pathlib import Path

from loguru import logger


def handle_sales_script(task: dict, tool_data: dict, plan_dir: str) -> str:
    """Execute a sales_script update using tool_data or regex fallback."""
    from src.utils.script_manager import update_section, get_section

    section_id = tool_data.get("section_id", "")
    new_content = tool_data.get("new_content", "")

    # Fallback: try to extract section_id from description/deliverables
    if not section_id:
        text = task.get("description", "") + " ".join(task.get("deliverables", []))
        match = re.search(r'/api/script/sections/(\w+)', text)
        if match:
            section_id = match.group(1)

    if not section_id:
        return "[sales_script] No section_id in tool_data or description -- skipped"

    existing = get_section(section_id)
    if existing is None:
        return f"[sales_script] Section '{section_id}' not found -- skipped"

    note = tool_data.get("note", "")

    if note and not new_content:
        current = existing.get("content", "") if isinstance(existing, dict) else str(existing)
        appended = f"{current}\n\nNote: {note}"
        update_section(section_id, appended)
        logger.info(f"Added note to sales script section '{section_id}'")
        return f"[sales_script] Added note to section '{section_id}': {note[:80]}"

    if not new_content:
        return f"[sales_script] Section '{section_id}' found but no new_content provided -- logged for manual update"

    update_section(section_id, new_content)
    logger.info(f"Updated sales script section '{section_id}'")
    return f"[sales_script] Updated section '{section_id}'"


def handle_content(task: dict, tool_data: dict, plan_dir: str) -> str:
    """Save content drafts (ad copy, emails, social posts) to files."""
    drafts = tool_data.get("drafts", [])
    content_type = tool_data.get("content_type", "content")

    if not drafts:
        drafts = task.get("deliverables", [])

    if not drafts:
        return f"[content] No drafts in tool_data or deliverables -- skipped"

    output_dir = Path(plan_dir) / "drafts"
    output_dir.mkdir(exist_ok=True)

    filename = f"{content_type}_{task.get('title', 'untitled')[:40]}.md".replace(" ", "_").lower()
    filepath = output_dir / filename

    lines = [f"# {task.get('title', 'Untitled')}", ""]
    for i, draft in enumerate(drafts, 1):
        if len(drafts) > 1:
            lines.append(f"## Draft {i}")
        lines.append(draft)
        lines.append("")

    filepath.write_text("\n".join(lines))
    logger.info(f"Saved {len(drafts)} draft(s) to {filepath}")
    return f"[content] Saved {len(drafts)} draft(s) to drafts/{filename}"



def handle_knowledge_base(task: dict, tool_data: dict, plan_dir: str) -> str:
    """Save an insight to the persistent knowledge base."""
    from src.utils.knowledge_base import add_entry

    source_url = ""
    meta_path = Path(plan_dir) / "metadata.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            source_url = meta.get("source_url", "")
        except Exception:
            pass

    reel_id = Path(plan_dir).name.split("_", 1)[-1] if "_" in Path(plan_dir).name else ""

    content = tool_data.get("content", "") or task.get("description", "")
    title = tool_data.get("title", "") or task.get("title", "")
    category = tool_data.get("category", "")
    tags = tool_data.get("tags", [])

    if not content:
        return "[knowledge_base] No content to save -- skipped"

    entry = add_entry(
        reel_id=reel_id,
        title=title,
        content=content,
        category=category,
        tags=tags,
        source_url=source_url,
    )

    return f"[knowledge_base] Saved: {title} (id: {entry['id']})"


# Tool handler dispatch table
TOOL_HANDLERS = {
    "sales_script": handle_sales_script,
    "meta_ads": handle_content,
    "email": handle_content,
    "social_media": handle_content,
    "content": handle_content,
    "knowledge_base": handle_knowledge_base,
    # NOTE: claude_code is NOT here — it's deferred to the VPS agent loop
}

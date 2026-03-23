"""Script flowchart editor — serves page + JSON API."""
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from src.config import settings
from src.utils.auth import require_api_key
from src.utils.script_manager import get_script_json, get_section, update_section

router = APIRouter()

STATIC_DIR = Path(__file__).resolve().parent.parent.parent / "static"


class SectionUpdate(BaseModel):
    content: str
    label: str | None = None


@router.get("/script", response_class=HTMLResponse)
def script_page():
    """Serve the flowchart editor HTML page."""
    html_path = STATIC_DIR / "script.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="script.html not found")
    return HTMLResponse(html_path.read_text())


@router.get("/api/script")
def api_get_script():
    """Return full script JSON (nodes + edges)."""
    return get_script_json()


@router.get("/api/script/sections/{section_id}")
def api_get_section(section_id: str):
    """Return a single node by ID."""
    node = get_section(section_id)
    if node is None:
        raise HTTPException(status_code=404, detail=f"Section not found: {section_id}")
    return node


@router.put("/api/script/sections/{section_id}")
def api_update_section(section_id: str, body: SectionUpdate):
    """Update a node's content (and optionally label)."""
    updated = update_section(section_id, body.content, body.label)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Section not found: {section_id}")
    return updated


@router.get("/api/script/changelog")
def api_script_changelog(tail: int = Query(default=50, le=200), _: str = Depends(require_api_key)):
    """Return recent script change history."""
    log_path = Path(settings.plans_dir) / "_script_changelog.jsonl"
    if not log_path.exists():
        return {"changes": []}
    lines = log_path.read_text().strip().split("\n")
    entries = []
    for line in lines[-tail:]:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return {"changes": entries}

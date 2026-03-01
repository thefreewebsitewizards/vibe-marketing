"""Manage the sales call script asset (JSON-backed)."""
import json
from datetime import datetime
from pathlib import Path

from loguru import logger

SCRIPT_PATH = Path(__file__).resolve().parent.parent.parent / "assets" / "sales_script.json"

_EMPTY_SCRIPT = {"updated_at": None, "nodes": [], "edges": []}


def _load_script() -> dict:
    """Read the JSON script file. Returns empty structure if missing."""
    if not SCRIPT_PATH.exists():
        logger.debug("Sales script not found at {}", SCRIPT_PATH)
        return dict(_EMPTY_SCRIPT)
    try:
        data = json.loads(SCRIPT_PATH.read_text())
        logger.debug("Loaded sales script ({} nodes)", len(data.get("nodes", [])))
        return data
    except (json.JSONDecodeError, KeyError) as e:
        logger.error("Failed to parse sales script: {}", e)
        return dict(_EMPTY_SCRIPT)


def _save_script(data: dict) -> None:
    """Write the JSON script file with updated timestamp."""
    data["updated_at"] = datetime.now().isoformat()
    SCRIPT_PATH.write_text(json.dumps(data, indent=2))
    logger.debug("Saved sales script")


def get_script_json() -> dict:
    """Return the full script data for the API."""
    return _load_script()


def get_section(section_id: str) -> dict | None:
    """Look up a single node by ID. Returns None if not found."""
    data = _load_script()
    for node in data.get("nodes", []):
        if node["id"] == section_id:
            return node
    return None


def update_section(section_id: str, content: str, label: str | None = None) -> dict | None:
    """Update a node's content (and optionally label). Returns updated node or None."""
    data = _load_script()
    for node in data.get("nodes", []):
        if node["id"] == section_id:
            node["content"] = content
            if label is not None:
                node["label"] = label
            _save_script(data)
            return node
    return None


def get_script_content() -> str:
    """Backward-compatible: generate flat text from nodes for prompt injection."""
    data = _load_script()
    nodes = data.get("nodes", [])
    if not nodes:
        return ""
    lines = ["# Sales Call Script — The Free Website Wizards\n"]
    for node in nodes:
        lines.append(f"## {node['label']}")
        lines.append(node["content"])
        lines.append("")
    return "\n".join(lines)


def get_script_summary() -> str:
    """Backward-compatible: return section IDs + labels for token efficiency."""
    data = _load_script()
    nodes = data.get("nodes", [])
    if not nodes:
        return ""
    lines = []
    for node in nodes:
        lines.append(f"- {node['id']}: {node['label']}")
    return "\n".join(lines)

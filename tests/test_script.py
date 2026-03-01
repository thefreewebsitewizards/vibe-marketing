import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.main import app

client = TestClient(app)


@pytest.fixture
def tmp_script(tmp_path):
    """Create a temporary sales_script.json and patch SCRIPT_PATH."""
    script_file = tmp_path / "sales_script.json"
    data = {
        "updated_at": "2026-01-01T00:00:00",
        "nodes": [
            {
                "id": "opening",
                "type": "action",
                "label": "Opening",
                "content": "Hello, this is a test.",
                "position": {"row": 1, "col": 1},
            },
            {
                "id": "closing",
                "type": "close",
                "label": "Closing",
                "content": "Goodbye.",
                "position": {"row": 2, "col": 1},
            },
        ],
        "edges": [
            {"from": "opening", "to": "closing", "label": None},
        ],
    }
    script_file.write_text(json.dumps(data))
    with patch("src.utils.script_manager.SCRIPT_PATH", script_file):
        yield script_file


# --- script_manager unit tests ---

def test_script_manager_load(tmp_script):
    from src.utils.script_manager import get_script_json
    data = get_script_json()
    assert "nodes" in data
    assert "edges" in data
    assert len(data["nodes"]) == 2
    assert data["nodes"][0]["id"] == "opening"


def test_script_manager_update_section(tmp_script):
    from src.utils.script_manager import update_section, get_section
    result = update_section("opening", "Updated content!")
    assert result is not None
    assert result["content"] == "Updated content!"
    # Verify persistence
    node = get_section("opening")
    assert node["content"] == "Updated content!"


def test_script_manager_missing_section(tmp_script):
    from src.utils.script_manager import get_section, update_section
    assert get_section("nonexistent") is None
    assert update_section("nonexistent", "text") is None


def test_script_manager_backward_compat(tmp_script):
    from src.utils.script_manager import get_script_content, get_script_summary
    content = get_script_content()
    assert "## Opening" in content
    assert "## Closing" in content
    assert "Hello, this is a test." in content

    summary = get_script_summary()
    assert "opening: Opening" in summary
    assert "closing: Closing" in summary


# --- API tests ---

def test_api_get_script(tmp_script):
    resp = client.get("/api/script")
    assert resp.status_code == 200
    data = resp.json()
    assert "nodes" in data
    assert len(data["nodes"]) == 2


def test_api_update_section(tmp_script):
    resp = client.put(
        "/api/script/sections/opening",
        json={"content": "New opening text"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["content"] == "New opening text"
    assert data["id"] == "opening"


def test_api_section_404(tmp_script):
    resp = client.get("/api/script/sections/nonexistent")
    assert resp.status_code == 404

    resp = client.put(
        "/api/script/sections/nonexistent",
        json={"content": "text"},
    )
    assert resp.status_code == 404

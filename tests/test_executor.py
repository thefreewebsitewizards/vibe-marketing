import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from src.services.executor import (
    classify_task, execute_plan,
    _handle_sales_script, _handle_content, _handle_n8n, _handle_code_task,
    _handle_knowledge_base,
)


def test_classify_task_auto():
    task = {"tools": ["sales_script"], "requires_human": False}
    assert classify_task(task) == "auto"


def test_classify_task_human():
    task = {"tools": ["meta_ads"], "requires_human": True}
    assert classify_task(task) == "human"


def test_classify_task_no_tools_defaults_auto():
    task = {"tools": [], "requires_human": False}
    assert classify_task(task) == "auto"


def test_execute_plan_splits_tasks(tmp_path):
    plan_data = {
        "title": "Test Plan",
        "summary": "test",
        "tasks": [
            {"title": "Auto task", "description": "do thing", "priority": "high",
             "estimated_hours": 1.0, "deliverables": [], "dependencies": [],
             "tools": ["claude_code"], "requires_human": False, "human_reason": ""},
            {"title": "Human task", "description": "approve spend", "priority": "high",
             "estimated_hours": 1.0, "deliverables": [], "dependencies": [],
             "tools": ["meta_ads"], "requires_human": True, "human_reason": "Budget needed"},
        ],
        "total_estimated_hours": 2.0,
    }
    plan_dir = tmp_path / "2026-03-10_TEST"
    plan_dir.mkdir()
    (plan_dir / "plan.json").write_text(json.dumps(plan_data))
    (plan_dir / "metadata.json").write_text(json.dumps({"reel_id": "TEST", "status": "approved"}))

    with patch("src.services.executor.settings") as mock_settings, \
         patch("src.services.executor._notify_human_tasks") as mock_notify, \
         patch("src.services.executor._notify_execution_complete"), \
         patch("src.services.executor.update_plan_status"):
        mock_settings.plans_dir = tmp_path
        result = execute_plan("TEST", "2026-03-10_TEST")

    assert result["auto_count"] == 1
    assert result["human_count"] == 1
    mock_notify.assert_called_once()


def test_execute_plan_no_plan_json(tmp_path):
    plan_dir = tmp_path / "2026-03-10_MISSING"
    plan_dir.mkdir()

    with patch("src.services.executor.settings") as mock_settings, \
         patch("src.services.executor.update_plan_status"):
        mock_settings.plans_dir = tmp_path
        result = execute_plan("MISSING", "2026-03-10_MISSING")

    assert result["auto_count"] == 0
    assert "error" in result


class TestHandleSalesScript:
    def test_should_update_section_with_tool_data(self):
        task = {"title": "Update intro", "description": "Change intro", "deliverables": []}
        tool_data = {"section_id": "intro", "new_content": "New intro text"}

        with patch("src.utils.script_manager.update_section") as mock_update, \
             patch("src.utils.script_manager.get_section", return_value={"id": "intro", "content": "old"}):
            result = _handle_sales_script(task, tool_data, "/tmp/plan")

        mock_update.assert_called_once_with("intro", "New intro text")
        assert "Updated section 'intro'" in result

    def test_should_extract_section_id_from_description(self):
        task = {
            "title": "Update intro",
            "description": "Use PUT /api/script/sections/intro to update",
            "deliverables": [],
        }
        tool_data = {}

        with patch("src.utils.script_manager.get_section", return_value={"id": "intro"}):
            result = _handle_sales_script(task, tool_data, "/tmp/plan")

        assert "no new_content" in result

    def test_should_skip_when_no_section_id(self):
        task = {"title": "Update script", "description": "Vague update", "deliverables": []}
        result = _handle_sales_script(task, {}, "/tmp/plan")
        assert "No section_id" in result

    def test_should_skip_when_section_not_found(self):
        task = {"title": "Update intro", "description": "", "deliverables": []}
        tool_data = {"section_id": "nonexistent", "new_content": "text"}

        with patch("src.utils.script_manager.get_section", return_value=None):
            result = _handle_sales_script(task, tool_data, "/tmp/plan")

        assert "not found" in result


class TestHandleContent:
    def test_should_save_drafts_from_tool_data(self, tmp_path):
        task = {"title": "Create Ad Copy", "deliverables": []}
        tool_data = {"content_type": "ad_copy", "drafts": ["Draft headline 1", "Draft headline 2"]}

        result = _handle_content(task, tool_data, str(tmp_path))

        assert "Saved 2 draft(s)" in result
        drafts_dir = tmp_path / "drafts"
        assert drafts_dir.exists()
        files = list(drafts_dir.glob("*.md"))
        assert len(files) == 1
        content = files[0].read_text()
        assert "Draft headline 1" in content
        assert "Draft headline 2" in content

    def test_should_fall_back_to_deliverables(self, tmp_path):
        task = {"title": "Write Email", "deliverables": ["Subject: Hello", "Body: World"]}
        tool_data = {}

        result = _handle_content(task, tool_data, str(tmp_path))

        assert "Saved 2 draft(s)" in result

    def test_should_skip_when_no_content(self, tmp_path):
        task = {"title": "Empty task", "deliverables": []}
        result = _handle_content(task, {}, str(tmp_path))
        assert "skipped" in result


class TestHandleN8n:
    def test_should_save_workflow_spec(self, tmp_path):
        task = {
            "title": "Lead nurture flow",
            "description": "Create an n8n workflow for lead nurture",
            "deliverables": ["Webhook trigger", "Email node"],
        }

        result = _handle_n8n(task, {}, str(tmp_path))

        assert "Saved workflow spec" in result
        files = list((tmp_path / "drafts").glob("n8n_*.md"))
        assert len(files) == 1
        content = files[0].read_text()
        assert "lead nurture" in content.lower()


class TestHandleCodeTask:
    def test_should_log_task(self):
        task = {"title": "Fix bug", "description": "Fix the login bug in auth.py"}
        result = _handle_code_task(task, {}, "/tmp/plan")
        assert "Logged for Claude Code" in result


class TestHandleKnowledgeBase:
    def test_should_save_entry(self, tmp_path):
        plan_dir = tmp_path / "2026-03-11_KB1"
        plan_dir.mkdir()
        (plan_dir / "metadata.json").write_text(json.dumps({
            "reel_id": "KB1", "source_url": "https://instagram.com/reel/KB1/",
        }))

        task = {"title": "Note AI insight", "description": "AI agents are the future"}
        tool_data = {
            "title": "AI agents trend",
            "content": "AI agents are transforming business automation",
            "category": "ai_automation",
            "tags": ["ai", "agents"],
        }

        with patch("src.utils.knowledge_base.settings") as mock_settings:
            mock_settings.plans_dir = tmp_path
            result = _handle_knowledge_base(task, tool_data, str(plan_dir))

        assert "Saved" in result
        assert "AI agents trend" in result

        # Verify the KB file was created
        kb_file = tmp_path / "_knowledge_base.json"
        assert kb_file.exists()
        entries = json.loads(kb_file.read_text())
        assert len(entries) == 1
        assert entries[0]["category"] == "ai_automation"
        assert entries[0]["tags"] == ["ai", "agents"]

    def test_should_skip_when_no_content(self, tmp_path):
        task = {"title": "Empty note", "description": ""}
        result = _handle_knowledge_base(task, {}, str(tmp_path))
        assert "skipped" in result

    def test_should_fall_back_to_description(self, tmp_path):
        plan_dir = tmp_path / "2026-03-11_KB2"
        plan_dir.mkdir()

        task = {"title": "Insight note", "description": "Use webhooks for real-time sync"}
        tool_data = {"category": "operations"}

        with patch("src.utils.knowledge_base.settings") as mock_settings:
            mock_settings.plans_dir = tmp_path
            result = _handle_knowledge_base(task, tool_data, str(plan_dir))

        assert "Saved" in result


class TestExecutePlanLevelFilter:
    def test_should_filter_tasks_by_approved_level(self, tmp_path):
        """Only tasks at or below approved_level should execute."""
        plan_data = {
            "title": "Tiered Plan",
            "tasks": [
                {"title": "L1 note", "description": "note it", "level": 1,
                 "tools": ["knowledge_base"], "requires_human": False,
                 "tool_data": {"content": "test note"}},
                {"title": "L2 build", "description": "build it", "level": 2,
                 "tools": ["claude_code"], "requires_human": False},
                {"title": "L3 deep", "description": "go deep", "level": 3,
                 "tools": ["claude_code"], "requires_human": False},
            ],
        }
        plan_dir = tmp_path / "2026-03-11_LVL"
        plan_dir.mkdir()
        (plan_dir / "plan.json").write_text(json.dumps(plan_data))
        (plan_dir / "metadata.json").write_text(json.dumps({
            "reel_id": "LVL", "status": "approved", "approved_level": 1,
        }))

        with patch("src.services.executor.settings") as mock_settings, \
             patch("src.services.executor._notify_execution_complete"), \
             patch("src.services.executor.update_plan_status"), \
             patch("src.utils.knowledge_base.settings") as kb_settings:
            mock_settings.plans_dir = tmp_path
            kb_settings.plans_dir = tmp_path
            result = execute_plan("LVL", "2026-03-11_LVL")

        # Only L1 task should execute (1 auto task)
        assert result["auto_count"] == 1

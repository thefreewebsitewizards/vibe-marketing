import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from src.models import (
    PipelineResult, PlanStatus, ReelMetadata, TranscriptResult,
    AnalysisResult, ImplementationPlan, PlanTask,
)
from src.utils.plan_writer import _md_to_html, _html_esc


def _make_result() -> PipelineResult:
    return PipelineResult(
        reel_id="TEST123",
        status=PlanStatus.REVIEW,
        metadata=ReelMetadata(url="https://instagram.com/reel/TEST123", shortcode="TEST123", creator="tester"),
        transcript=TranscriptResult(text="test transcript"),
        analysis=AnalysisResult(category="sales", summary="test", key_insights=["i1"], relevance_score=0.8),
        plan=ImplementationPlan(
            title="Test Plan",
            summary="A test",
            tasks=[
                PlanTask(
                    title="Update sales script",
                    description="Change intro section",
                    priority="high",
                    estimated_hours=2.0,
                    deliverables=["Updated script"],
                    tools=["sales_script"],
                    requires_human=False,
                ),
                PlanTask(
                    title="Create ad copy",
                    description="Write Meta ad",
                    priority="medium",
                    estimated_hours=1.0,
                    deliverables=["Ad copy doc"],
                    tools=["meta_ads"],
                    requires_human=True,
                    human_reason="Needs budget approval",
                ),
            ],
            total_estimated_hours=3.0,
        ),
    )


class TestMdToHtml:
    def test_should_convert_bold(self):
        assert "<strong>bold</strong>" in _md_to_html("**bold** text")

    def test_should_convert_italic(self):
        assert "<em>italic</em>" in _md_to_html("*italic* text")

    def test_should_convert_inline_code(self):
        assert "<code>code</code>" in _md_to_html("`code` here")

    def test_should_convert_bullet_list(self):
        result = _md_to_html("- item one\n- item two")
        assert "<ul>" in result
        assert "<li>item one</li>" in result
        assert "<li>item two</li>" in result

    def test_should_escape_html_before_converting(self):
        result = _md_to_html("**<script>alert(1)</script>**")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_should_handle_empty_string(self):
        assert _md_to_html("") == ""
        assert _md_to_html(None) == ""

    def test_should_convert_line_breaks(self):
        result = _md_to_html("line one\nline two")
        assert "<br>" in result


def test_write_plan_saves_plan_json(tmp_path):
    """write_plan should create a plan.json with structured task data."""
    with patch("src.utils.plan_writer.settings") as mock_settings, \
         patch("src.utils.plan_writer.route_plan", return_value="tfww"):
        mock_settings.plans_dir = tmp_path
        from src.utils.plan_writer import write_plan
        result = _make_result()
        write_plan(result)

    plan_json_path = list(tmp_path.glob("*/plan.json"))[0]
    data = json.loads(plan_json_path.read_text())

    assert data["title"] == "Test Plan"
    assert len(data["tasks"]) == 2
    assert data["tasks"][0]["title"] == "Update sales script"
    assert data["tasks"][0]["tools"] == ["sales_script"]
    assert data["tasks"][1]["requires_human"] is True
    assert data["tasks"][1]["human_reason"] == "Needs budget approval"

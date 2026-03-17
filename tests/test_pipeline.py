import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.models import (
    ReelMetadata, TranscriptResult, AnalysisResult,
    ImplementationPlan, PlanTask, PipelineResult, PlanStatus, PlanIndexEntry,
    DetailedNotes, BusinessApplication, FactCheck,
    SimilarPlan, SimilarityResult,
)
from src.utils.plan_writer import write_plan
from src.utils.capability_manager import get_capabilities_context


def _make_analysis(**overrides) -> AnalysisResult:
    """Helper to build an AnalysisResult with all required fields."""
    defaults = dict(
        category="marketing",
        summary="Test summary",
        key_insights=["Insight 1", "Insight 2"],
        relevance_score=0.8,
        theme="Short theme for scanning",
        detailed_notes=DetailedNotes(
            what_it_is="A test reel about marketing",
            how_useful="Demonstrates gift-framing language",
            how_not_useful="Only applies to B2C",
            target_audience="Dylan (sales)",
        ),
        business_applications=[
            BusinessApplication(
                area="Ad copy",
                recommendation="Use gift-framing in Meta ads",
                target_system="meta_ads",
                urgency="high",
            ),
        ],
        business_impact="Could increase CTR by reframing offers as gifts",
        fact_checks=[
            FactCheck(
                claim="Gift-framing increases conversions by 30%",
                verdict="unverified",
                explanation="No source cited in the reel",
            ),
        ],
    )
    defaults.update(overrides)
    return AnalysisResult(**defaults)


def _make_task(**overrides) -> PlanTask:
    """Helper to build a PlanTask with all required fields."""
    defaults = dict(
        title="Task 1",
        description="Do the thing",
        priority="high",
        estimated_hours=2.0,
        deliverables=["Output 1"],
        tools=["claude_code"],
        requires_human=False,
        human_reason="",
    )
    defaults.update(overrides)
    return PlanTask(**defaults)


def test_plan_writer(tmp_path):
    """Test that plan_writer creates correct directory structure and files."""
    with patch("src.utils.plan_writer.settings") as mock_settings:
        mock_settings.plans_dir = tmp_path

        result = PipelineResult(
            reel_id="TEST123",
            status=PlanStatus.REVIEW,
            metadata=ReelMetadata(
                url="https://instagram.com/reel/TEST123/",
                shortcode="TEST123",
                creator="testuser",
                caption="Test caption",
                duration=30.0,
            ),
            transcript=TranscriptResult(
                text="This is a test transcript",
                language="en",
                duration=30.0,
            ),
            analysis=_make_analysis(),
            plan=ImplementationPlan(
                title="Test Plan",
                summary="A test implementation plan",
                tasks=[
                    _make_task(),
                    _make_task(
                        title="Human Task",
                        requires_human=True,
                        human_reason="Needs ad spend approval",
                    ),
                ],
                total_estimated_hours=4.0,
            ),
        )

        plan_dir = write_plan(result)

        assert plan_dir.exists()
        assert (plan_dir / "plan.md").exists()
        assert (plan_dir / "notes.md").exists()
        assert (plan_dir / "metadata.json").exists()
        assert (plan_dir / "transcript.txt").exists()
        assert (plan_dir / "analysis.json").exists()

        # Check transcript content
        assert (plan_dir / "transcript.txt").read_text() == "This is a test transcript"

        # Check metadata
        meta = json.loads((plan_dir / "metadata.json").read_text())
        assert meta["reel_id"] == "TEST123"
        assert meta["creator"] == "testuser"

        # Check plan.md contains new sections
        plan_md = (plan_dir / "plan.md").read_text()
        assert "[NEEDS HUMAN]" in plan_md
        assert "Why This Matters" in plan_md
        assert "Business Applications" in plan_md
        assert "Fact Checks" in plan_md
        assert "Short theme for scanning" in plan_md

        # Check notes.md
        notes_md = (plan_dir / "notes.md").read_text()
        assert "Analysis Notes" in notes_md
        assert "Short theme for scanning" in notes_md

        # Check index has new fields
        index_path = tmp_path / "_index.json"
        assert index_path.exists()
        index = json.loads(index_path.read_text())
        assert len(index["plans"]) == 1
        entry = index["plans"][0]
        assert entry["reel_id"] == "TEST123"
        assert entry["status"] == "review"
        assert entry["theme"] == "Short theme for scanning"
        assert entry["category"] == "marketing"
        assert entry["relevance_score"] == 0.8


def test_plan_index_entry_model():
    entry = PlanIndexEntry(
        reel_id="ABC",
        title="Test",
        status=PlanStatus.REVIEW,
        plan_dir="2026-02-26_ABC",
        created_at="2026-02-26T00:00:00",
        source_url="https://instagram.com/reel/ABC/",
    )
    assert entry.reel_id == "ABC"
    assert entry.status == PlanStatus.REVIEW
    # New fields default to empty/zero
    assert entry.theme == ""
    assert entry.category == ""
    assert entry.relevance_score == 0.0


def test_plan_index_entry_with_new_fields():
    entry = PlanIndexEntry(
        reel_id="ABC",
        title="Test",
        status=PlanStatus.REVIEW,
        plan_dir="2026-02-26_ABC",
        created_at="2026-02-26T00:00:00",
        source_url="https://instagram.com/reel/ABC/",
        theme="Gift-framing for lead gen",
        category="marketing",
        relevance_score=0.9,
    )
    assert entry.theme == "Gift-framing for lead gen"
    assert entry.category == "marketing"
    assert entry.relevance_score == 0.9


def test_analysis_result_score_bounds():
    result = _make_analysis(relevance_score=0.5)
    assert 0.0 <= result.relevance_score <= 1.0

    with pytest.raises(Exception):
        _make_analysis(relevance_score=1.5)


def test_analysis_result_backward_compat():
    """Old analysis data without new fields still parses."""
    result = AnalysisResult(
        category="test",
        summary="test",
        key_insights=["insight"],
        relevance_score=0.5,
    )
    assert result.theme == ""
    assert result.business_impact == ""
    assert result.business_applications == []
    assert result.fact_checks == []
    assert result.detailed_notes.what_it_is == ""


def test_plan_task_backward_compat():
    """Old task data without requires_human still parses."""
    task = PlanTask(
        title="Old task",
        description="From before the upgrade",
    )
    assert task.requires_human is False
    assert task.human_reason == ""


def test_plan_task_human_flag():
    task = _make_task(requires_human=True, human_reason="Needs budget approval")
    assert task.requires_human is True
    assert task.human_reason == "Needs budget approval"


def test_capability_manager_loads_json():
    """get_capabilities_context returns formatted text from the real capabilities.json."""
    context = get_capabilities_context()
    assert "ghl" in context
    assert "MCP Servers" in context
    assert "Active Integrations" in context


def test_capability_manager_missing_file():
    """get_capabilities_context returns empty string if file doesn't exist."""
    with patch("src.utils.capability_manager.CAPABILITIES_PATH", Path("/nonexistent/capabilities.json")):
        context = get_capabilities_context()
        assert context == ""


def test_plan_writer_creates_view_html(tmp_path):
    """write_plan generates a view.html file."""
    with patch("src.utils.plan_writer.settings") as mock_settings:
        mock_settings.plans_dir = tmp_path

        result = PipelineResult(
            reel_id="HTML1",
            status=PlanStatus.REVIEW,
            metadata=ReelMetadata(
                url="https://instagram.com/reel/HTML1/",
                shortcode="HTML1",
                creator="htmluser",
                caption="Test",
                duration=30.0,
            ),
            transcript=TranscriptResult(text="Test transcript", language="en", duration=30.0),
            analysis=_make_analysis(),
            plan=ImplementationPlan(
                title="HTML Test Plan",
                summary="Testing HTML generation",
                tasks=[_make_task()],
                total_estimated_hours=2.0,
            ),
        )

        plan_dir = write_plan(result)

        assert (plan_dir / "view.html").exists()
        html = (plan_dir / "view.html").read_text()
        assert "HTML Test Plan" in html
        assert "Short theme for scanning" in html
        assert "htmluser" in html


def test_plan_writer_tiered_format(tmp_path):
    """write_plan generates plan.md with tasks grouped by level."""
    with patch("src.utils.plan_writer.settings") as mock_settings:
        mock_settings.plans_dir = tmp_path

        result = PipelineResult(
            reel_id="TIER1",
            status=PlanStatus.REVIEW,
            metadata=ReelMetadata(
                url="https://instagram.com/reel/TIER1/",
                shortcode="TIER1",
                creator="tieruser",
            ),
            transcript=TranscriptResult(text="Test"),
            analysis=_make_analysis(),
            plan=ImplementationPlan(
                title="Tiered Plan",
                summary="A tiered plan",
                tasks=[
                    _make_task(title="Note the insight", level=1),
                    _make_task(title="Build the widget", level=2),
                    _make_task(title="Go deep on system", level=3, requires_human=True, human_reason="Needs budget"),
                ],
                total_estimated_hours=5.0,
                content_angle="Behind the scenes of our AI pipeline",
                level_summaries={"1": "Record it", "2": "Build it", "3": "Ship it"},
            ),
        )

        plan_dir = write_plan(result)

        plan_md = (plan_dir / "plan.md").read_text()
        assert "L1" in plan_md
        assert "L2" in plan_md
        assert "L3" in plan_md
        assert "Note the insight" in plan_md
        assert "Build the widget" in plan_md
        assert "Go deep on system" in plan_md
        assert "DDB Content Angle" in plan_md
        assert "Behind the scenes" in plan_md


def test_reel_metadata_content_type_default():
    """ReelMetadata defaults to content_type='reel'."""
    meta = ReelMetadata(url="https://instagram.com/reel/X/", shortcode="X")
    assert meta.content_type == "reel"


def test_reel_metadata_carousel():
    """ReelMetadata accepts content_type='carousel'."""
    meta = ReelMetadata(
        url="https://instagram.com/p/X/", shortcode="X", content_type="carousel",
    )
    assert meta.content_type == "carousel"


def test_similarity_result_model():
    """SimilarityResult and SimilarPlan models work correctly."""
    sim = SimilarityResult(
        similar_plans=[
            SimilarPlan(title="Existing Plan", reel_id="ABC", score=75, overlap_areas=["ad copy"]),
        ],
        recommendation="merge",
        max_score=75,
    )
    assert sim.max_score == 75
    assert sim.recommendation == "merge"
    assert len(sim.similar_plans) == 1
    assert sim.similar_plans[0].score == 75


def test_similarity_result_empty():
    """SimilarityResult defaults to empty."""
    sim = SimilarityResult()
    assert sim.similar_plans == []
    assert sim.recommendation == "generate"
    assert sim.max_score == 0


def test_pipeline_result_with_similarity():
    """PipelineResult accepts a similarity result."""
    sim = SimilarityResult(
        similar_plans=[SimilarPlan(title="Old Plan", reel_id="OLD", score=60)],
        recommendation="generate",
        max_score=60,
    )
    result = PipelineResult(
        reel_id="X",
        metadata=ReelMetadata(url="https://instagram.com/reel/X/", shortcode="X"),
        transcript=TranscriptResult(text="test"),
        analysis=_make_analysis(),
        plan=ImplementationPlan(title="T", summary="S", tasks=[_make_task()]),
        similarity=sim,
    )
    assert result.similarity is not None
    assert result.similarity.max_score == 60


def test_plan_writer_hides_empty_fact_checks(tmp_path):
    """view.html should not show Fact Checks heading when empty."""
    with patch("src.utils.plan_writer.settings") as mock_settings:
        mock_settings.plans_dir = tmp_path

        result = PipelineResult(
            reel_id="NOFACT",
            status=PlanStatus.REVIEW,
            metadata=ReelMetadata(
                url="https://instagram.com/reel/NOFACT/",
                shortcode="NOFACT",
                creator="user",
                duration=30.0,
            ),
            transcript=TranscriptResult(text="Test", language="en", duration=30.0),
            analysis=_make_analysis(fact_checks=[]),
            plan=ImplementationPlan(
                title="Empty Checks Plan",
                summary="Test",
                tasks=[_make_task()],
                total_estimated_hours=2.0,
            ),
        )

        plan_dir = write_plan(result)
        html = (plan_dir / "view.html").read_text()
        # The <h2>Fact Checks</h2> heading should not appear
        assert "<h2>Fact Checks</h2>" not in html


def test_plan_writer_shows_fact_checks_expanded(tmp_path):
    """view.html should show Fact Checks expanded (not collapsible) when populated."""
    with patch("src.utils.plan_writer.settings") as mock_settings:
        mock_settings.plans_dir = tmp_path

        result = PipelineResult(
            reel_id="HASFACT",
            status=PlanStatus.REVIEW,
            metadata=ReelMetadata(
                url="https://instagram.com/reel/HASFACT/",
                shortcode="HASFACT",
                creator="user",
                duration=30.0,
            ),
            transcript=TranscriptResult(text="Test", language="en", duration=30.0),
            analysis=_make_analysis(),
            plan=ImplementationPlan(
                title="With Checks Plan",
                summary="Test",
                tasks=[_make_task()],
                total_estimated_hours=2.0,
            ),
        )

        plan_dir = write_plan(result)
        html = (plan_dir / "view.html").read_text()
        assert "<h2>Fact Checks</h2>" in html
        # Should NOT be collapsible (no onclick toggle)
        assert 'collapsible" onclick="toggle(this)">Fact Checks' not in html


def test_plan_writer_content_angle_in_html(tmp_path):
    """write_plan includes level_summaries in HTML view and content_angle in plan.md."""
    with patch("src.utils.plan_writer.settings") as mock_settings:
        mock_settings.plans_dir = tmp_path

        result = PipelineResult(
            reel_id="CA1",
            status=PlanStatus.REVIEW,
            metadata=ReelMetadata(
                url="https://instagram.com/reel/CA1/",
                shortcode="CA1",
                creator="causer",
            ),
            transcript=TranscriptResult(text="Test"),
            analysis=_make_analysis(),
            plan=ImplementationPlan(
                title="Content Angle Plan",
                summary="Plan with DDB angle",
                tasks=[_make_task()],
                total_estimated_hours=2.0,
                content_angle="How we use AI to analyze reels",
                level_summaries={"1": "Note it", "2": "Build it", "3": "Go deep"},
            ),
        )

        plan_dir = write_plan(result)

        html = (plan_dir / "view.html").read_text()
        assert "Implementation Levels" in html

        # content_angle is still rendered in plan.md
        plan_md = (plan_dir / "plan.md").read_text()
        assert "DDB Content Angle" in plan_md
        assert "How we use AI to analyze reels" in plan_md


def test_plan_writer_similarity_in_html(tmp_path):
    """view.html should include similarity callout when present."""
    with patch("src.utils.plan_writer.settings") as mock_settings:
        mock_settings.plans_dir = tmp_path

        sim = SimilarityResult(
            similar_plans=[SimilarPlan(title="Old Plan", reel_id="OLD", score=72, overlap_areas=["ad copy"])],
            recommendation="merge",
            max_score=72,
        )

        result = PipelineResult(
            reel_id="SIM1",
            status=PlanStatus.REVIEW,
            metadata=ReelMetadata(
                url="https://instagram.com/reel/SIM1/",
                shortcode="SIM1",
                creator="simuser",
                duration=30.0,
            ),
            transcript=TranscriptResult(text="Test", language="en", duration=30.0),
            analysis=_make_analysis(),
            plan=ImplementationPlan(
                title="Similar Plan", summary="Test", tasks=[_make_task()], total_estimated_hours=2.0,
            ),
            similarity=sim,
        )

        plan_dir = write_plan(result)
        html = (plan_dir / "view.html").read_text()
        assert "Similar to:" in html
        assert "Old Plan" in html
        assert "72%" in html

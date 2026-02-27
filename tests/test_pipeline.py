import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.models import (
    ReelMetadata, TranscriptResult, AnalysisResult,
    ImplementationPlan, PlanTask, PipelineResult, PlanStatus, PlanIndexEntry,
)
from src.utils.plan_writer import write_plan


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
            analysis=AnalysisResult(
                category="marketing",
                summary="Test summary",
                key_insights=["Insight 1", "Insight 2"],
                relevance_score=0.8,
            ),
            plan=ImplementationPlan(
                title="Test Plan",
                summary="A test implementation plan",
                tasks=[
                    PlanTask(
                        title="Task 1",
                        description="Do the thing",
                        priority="high",
                        estimated_hours=2.0,
                        deliverables=["Output 1"],
                        tools=["claude_code"],
                    )
                ],
                total_estimated_hours=2.0,
            ),
        )

        plan_dir = write_plan(result)

        assert plan_dir.exists()
        assert (plan_dir / "plan.md").exists()
        assert (plan_dir / "metadata.json").exists()
        assert (plan_dir / "transcript.txt").exists()
        assert (plan_dir / "analysis.json").exists()

        # Check transcript content
        assert (plan_dir / "transcript.txt").read_text() == "This is a test transcript"

        # Check metadata
        meta = json.loads((plan_dir / "metadata.json").read_text())
        assert meta["reel_id"] == "TEST123"
        assert meta["creator"] == "testuser"

        # Check index
        index_path = tmp_path / "_index.json"
        assert index_path.exists()
        index = json.loads(index_path.read_text())
        assert len(index["plans"]) == 1
        assert index["plans"][0]["reel_id"] == "TEST123"
        assert index["plans"][0]["status"] == "review"


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


def test_analysis_result_score_bounds():
    result = AnalysisResult(
        category="test",
        summary="test",
        key_insights=[],
        relevance_score=0.5,
    )
    assert 0.0 <= result.relevance_score <= 1.0

    with pytest.raises(Exception):
        AnalysisResult(
            category="test",
            summary="test",
            key_insights=[],
            relevance_score=1.5,
        )

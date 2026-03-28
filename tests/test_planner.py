"""Tests for the planner service — similarity / delta checking."""

import json
from unittest.mock import patch

from src.models import AnalysisResult, BusinessApplication
from src.services.llm import ChatResult
from src.services.planner import check_plan_similarity


def _make_analysis(**overrides) -> AnalysisResult:
    defaults = dict(
        category="marketing",
        summary="Test summary about gift-framing",
        key_insights=["Insight 1", "Insight 2"],
        relevance_score=0.8,
        theme="Gift-framing for lead gen",
        business_applications=[
            BusinessApplication(area="ads", recommendation="Use gift framing in ad copy"),
        ],
    )
    defaults.update(overrides)
    return AnalysisResult(**defaults)


def _delta_response(with_related: bool = True) -> str:
    """Build a JSON string mimicking the new delta-analysis LLM response."""
    related = []
    if with_related:
        related = [{
            "title": "Old Gift Plan",
            "reel_id": "ABC123",
            "overlap_areas": ["ad copy", "lead gen"],
            "new_value": "Teaches the 3-step gift ladder instead of single offer",
        }]
    return json.dumps({
        "related_plans": related,
        "unique_contributions": [
            "3-step gift ladder framework",
            "Warm audience re-engagement via gifts",
        ],
        "focus_guidance": "Focus on the gift ladder framework; skip generic ad copy advice already covered.",
    })


@patch("src.services.planner.get_model_for_step", return_value="test-model")
@patch("src.services.planner.chat")
@patch("src.services.planner.get_past_plan_summaries")
def test_delta_check_finds_related_plans(mock_summaries, mock_chat, mock_model):
    """When related plans exist, they are returned with new_value comparisons."""
    mock_summaries.return_value = "- [ABC123] Old Gift Plan: Update ad copy"
    mock_chat.return_value = ChatResult(text=_delta_response(with_related=True))

    analysis = _make_analysis()
    result, chat_result = check_plan_similarity(analysis)

    assert result.recommendation == "generate"
    assert len(result.similar_plans) == 1
    plan = result.similar_plans[0]
    assert plan.title == "Old Gift Plan"
    assert plan.reel_id == "ABC123"
    assert len(plan.comparisons) == 1
    assert "gift ladder" in plan.comparisons[0].new_content

    # Single LLM call (no separate enrichment step)
    assert mock_chat.call_count == 1

    # Focus guidance stashed on result
    assert "gift ladder" in getattr(result, "_focus_guidance", "")
    assert len(getattr(result, "_unique_contributions", [])) == 2


@patch("src.services.planner.get_model_for_step", return_value="test-model")
@patch("src.services.planner.chat")
@patch("src.services.planner.get_past_plan_summaries")
def test_no_related_plans(mock_summaries, mock_chat, mock_model):
    """When no related plans exist, result is empty but still generates."""
    mock_summaries.return_value = "- [XYZ] Some other plan"
    mock_chat.return_value = ChatResult(text=_delta_response(with_related=False))

    analysis = _make_analysis()
    result, _ = check_plan_similarity(analysis)

    assert result.recommendation == "generate"
    assert len(result.similar_plans) == 0
    assert mock_chat.call_count == 1


@patch("src.services.planner.get_model_for_step", return_value="test-model")
@patch("src.services.planner.chat")
@patch("src.services.planner.get_past_plan_summaries")
def test_never_returns_skip(mock_summaries, mock_chat, mock_model):
    """Recommendation is always 'generate' — never skips."""
    mock_summaries.return_value = "- [ABC123] Old Gift Plan: Update ad copy"
    # Even if the LLM somehow returns "skip", we force "generate"
    mock_chat.return_value = ChatResult(text=json.dumps({
        "related_plans": [{
            "title": "Old Gift Plan",
            "reel_id": "ABC123",
            "overlap_areas": ["everything"],
            "new_value": "",
        }],
        "unique_contributions": [],
        "focus_guidance": "Very similar",
    }))

    analysis = _make_analysis()
    result, _ = check_plan_similarity(analysis)

    assert result.recommendation == "generate"


@patch("src.services.planner.get_model_for_step", return_value="test-model")
@patch("src.services.planner.chat")
@patch("src.services.planner.get_past_plan_summaries")
def test_no_existing_plans_returns_early(mock_summaries, mock_chat, mock_model):
    """When get_past_plan_summaries returns empty, return early with no LLM calls."""
    mock_summaries.return_value = ""

    analysis = _make_analysis()
    result, chat_result = check_plan_similarity(analysis)

    assert result.similar_plans == []
    assert result.recommendation == "generate"
    assert chat_result is None
    mock_chat.assert_not_called()


@patch("src.services.planner.get_model_for_step", return_value="test-model")
@patch("src.services.planner.chat")
@patch("src.services.planner.get_past_plan_summaries")
def test_json_parse_failure_returns_generate(mock_summaries, mock_chat, mock_model):
    """When LLM returns invalid JSON, gracefully return generate."""
    mock_summaries.return_value = "- [ABC123] Old Plan: task"
    mock_chat.return_value = ChatResult(text="not valid json at all")

    analysis = _make_analysis()
    result, _ = check_plan_similarity(analysis)

    assert result.recommendation == "generate"
    assert result.similar_plans == []

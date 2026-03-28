import json
from loguru import logger

from src.config import settings
from src.models import (
    AnalysisResult, ReelMetadata, ImplementationPlan, PlanTask,
    SimilarityResult, SimilarPlan, ContentComparison,
)
from src.prompts.generate_plan import build_plan_prompt
from src.utils.plan_manager import get_past_plan_summaries, load_plan_content
from src.utils.capability_manager import get_capabilities_context
from src.services.llm import chat, ChatResult, get_model_for_step
from src.utils.json_extract import extract_json, normalize_string_list


def _parse_level(value) -> int:
    """Parse level from LLM output — handles 1, "1", "l1", "L2", etc."""
    if isinstance(value, int):
        return value
    s = str(value).strip().lower().lstrip("l")
    try:
        return int(s)
    except (ValueError, TypeError):
        return 1


def check_plan_similarity(analysis: AnalysisResult) -> tuple[SimilarityResult, ChatResult | None]:
    """Find what new value this analysis adds beyond existing plans.

    Never skips — always returns recommendation="generate". The output
    tells the plan generator which areas are already covered (so it can
    focus on the delta) and which are genuinely new.
    """
    existing_plans = get_past_plan_summaries(limit=20)
    if not existing_plans:
        return SimilarityResult(recommendation="generate"), None

    system = (
        "You are a value-delta analyst. Your job is NOT to detect duplicates — "
        "it is to find what NEW value this reel adds beyond what we already have. "
        "Two reels on the same topic almost always teach different tactics, "
        "frameworks, or angles. Focus on the unique contribution. "
        "Respond with valid JSON only."
    )
    user_content = f"""Analyze what NEW value this reel adds beyond our existing plans.

**New reel analysis:**
- Theme: {analysis.theme}
- Category: {analysis.category}
- Summary: {analysis.summary}
- Key insights: {', '.join(analysis.key_insights[:8])}
- Business applications: {', '.join(a.recommendation for a in analysis.business_applications[:5])}

**Existing plans we already have:**
{existing_plans}

Return JSON:
{{
  "related_plans": [
    {{
      "title": "Title of the related existing plan",
      "reel_id": "ID from the brackets",
      "overlap_areas": ["area1"],
      "new_value": "What THIS reel adds that the existing plan doesn't cover (be specific)"
    }}
  ],
  "unique_contributions": ["specific tactic/framework/angle this reel brings that no existing plan covers"],
  "focus_guidance": "1-2 sentences telling the plan generator what to emphasize (the new stuff) and what to skip (already well-covered)"
}}

Rules:
- Only include related plans that share a topic area — max 3
- Every reel has SOMETHING new. Even if the topic overlaps, the specific tactics, examples, frameworks, or angles differ. Find them.
- "new_value" should be specific: not "different perspective" but "teaches the 3-2-1 email framework for re-engagement"
- "unique_contributions" is the most important field — what does this reel teach that we don't already have?
- "focus_guidance" steers the plan generator to avoid retreading old ground"""

    try:
        chat_result = chat(system=system, user_content=user_content, max_tokens=600, model_override=get_model_for_step("similarity"))
        data = extract_json(chat_result.text, context="similarity")
        similar = [
            SimilarPlan(
                title=p.get("title", ""),
                reel_id=p.get("reel_id", ""),
                score=0,
                overlap_areas=p.get("overlap_areas", []),
                comparisons=[ContentComparison(
                    area="new value",
                    new_content=p.get("new_value", ""),
                    verdict="different_angle",
                )] if p.get("new_value") else [],
            )
            for p in data.get("related_plans", [])
        ]

        # Build focus guidance from unique contributions + guidance
        unique = data.get("unique_contributions", [])
        guidance = data.get("focus_guidance", "")

        max_score = max((p.score for p in similar), default=0)
        result = SimilarityResult(
            similar_plans=similar,
            recommendation="generate",
            max_score=max_score,
        )
        # Stash guidance for the plan generator (accessed via _build_comparison_context)
        result._focus_guidance = guidance
        result._unique_contributions = unique
        return result, chat_result
    except (json.JSONDecodeError, IndexError, KeyError) as e:
        logger.warning(f"Similarity check failed to parse: {e}")
        return SimilarityResult(recommendation="generate"), chat_result


def generate_plan(analysis: AnalysisResult, metadata: ReelMetadata, user_context: str = "", similarity: SimilarityResult | None = None) -> tuple[ImplementationPlan, ChatResult]:
    """Generate an implementation plan from the analysis using an LLM."""

    existing_plans = get_past_plan_summaries(limit=10)
    capabilities = get_capabilities_context()

    script_context = ""
    script_section_ids = ""
    if analysis.category == "sales":
        from src.utils.script_manager import get_script_content, get_script_summary
        script_context = get_script_content()
        if script_context:
            script_section_ids = get_script_summary()
            logger.info("Injecting sales script context into plan prompt")

    comparison_context = ""
    if similarity:
        lines = []
        # Focus guidance from the delta analysis
        guidance = getattr(similarity, "_focus_guidance", "")
        unique = getattr(similarity, "_unique_contributions", [])
        if guidance:
            lines.append(f"**Focus guidance:** {guidance}")
        if unique:
            lines.append("**Unique contributions from this reel:**")
            for u in unique:
                lines.append(f"- {u}")
        # Related plans context
        for sp in similarity.similar_plans:
            if sp.comparisons:
                for c in sp.comparisons:
                    if c.new_content:
                        lines.append(
                            f"- Related to \"{sp.title}\": This reel adds: {c.new_content[:200]}"
                        )
        if lines:
            comparison_context = "\n".join(lines)

    system_prompt, user_prompt = build_plan_prompt(
        analysis, metadata, existing_plans, script_context, script_section_ids,
        capabilities_context=capabilities,
        user_context=user_context,
        comparison_context=comparison_context,
    )

    logger.info("Generating implementation plan...")
    chat_result = chat(system=system_prompt, user_content=user_prompt, max_tokens=8192, model_override=get_model_for_step("plan"))

    try:
        data = extract_json(chat_result.text, context="planner")

        tasks = []
        for t in data.get("tasks", []):
            tool_data = t.get("tool_data") or {}
            tools = normalize_string_list(t.get("tools") or [])

            # Validate sales_script section_id — swap to knowledge_base if hallucinated
            if "sales_script" in tools and tool_data.get("section_id"):
                from src.utils.script_manager import get_section
                if get_section(tool_data["section_id"]) is None:
                    logger.warning(f"Hallucinated section_id '{tool_data['section_id']}' — converting to knowledge_base task")
                    tools = ["knowledge_base"]
                    tool_data = {
                        "title": t.get("title", ""),
                        "content": tool_data.get("new_content") or tool_data.get("note") or t.get("description", ""),
                        "category": "sales",
                        "tags": ["script_suggestion", tool_data["section_id"]],
                    }

            tasks.append(PlanTask(
                title=t.get("title") or "",
                description=t.get("description") or "",
                priority=t.get("priority") or "medium",
                estimated_hours=float(t.get("estimated_hours") or 1.0),
                deliverables=normalize_string_list(t.get("deliverables") or []),
                dependencies=normalize_string_list(t.get("dependencies") or []),
                tools=tools,
                requires_human=bool(t.get("requires_human", False)),
                human_reason=t.get("human_reason") or "",
                level=_parse_level(t.get("level", 1)),
                change_type=t.get("change_type") or "",
                tool_data=tool_data,
            ))

        plan = ImplementationPlan(
            title=data.get("title", f"Plan: {metadata.shortcode}"),
            summary=data.get("summary", ""),
            tasks=tasks,
            total_estimated_hours=sum(t.estimated_hours for t in tasks),
            recommended_action=data.get("recommended_action", ""),
            content_angle=data.get("content_angle", ""),
            level_summaries=data.get("level_summaries", {}),
        )
    except (json.JSONDecodeError, IndexError, KeyError) as e:
        logger.warning(f"Failed to parse plan JSON ({e}), creating single-task plan")
        logger.debug(f"finish_reason={chat_result.finish_reason}, tokens={chat_result.completion_tokens}/{chat_result.total_tokens}")
        raw = chat_result.text
        plan = ImplementationPlan(
            title=f"Plan: {metadata.shortcode}",
            summary=raw[:500],
            tasks=[PlanTask(
                title="Review and implement insights",
                description=raw,
                priority="medium",
                estimated_hours=2.0,
            )],
            total_estimated_hours=2.0,
        )

    logger.info(f"Plan generated: {plan.title} ({len(plan.tasks)} tasks, {plan.total_estimated_hours}h)")
    return plan, chat_result

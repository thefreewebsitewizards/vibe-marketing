"""Generate a content repurposing plan from a reel analysis."""

import json
from loguru import logger

from src.models import AnalysisResult, ReelMetadata, ImplementationPlan, PlanTask
from src.prompts.content_repurposing import build_repurposing_prompt
from src.services.llm import chat, ChatResult, get_model_for_step
from src.utils.json_extract import extract_json, normalize_string_list


def generate_repurposing_plan(
    analysis: AnalysisResult, metadata: ReelMetadata, transcript: str,
) -> tuple[ImplementationPlan, ChatResult]:
    """Generate a content repurposing plan from the analysis."""

    system_prompt, user_prompt = build_repurposing_prompt(analysis, metadata, transcript)

    logger.info("Generating content repurposing plan...")
    chat_result = chat(system=system_prompt, user_content=user_prompt, max_tokens=8192, model_override=get_model_for_step("repurposing"))

    try:
        data = extract_json(chat_result.text, context="repurposer")

        tasks = []
        for t in data.get("tasks", []):
            tasks.append(PlanTask(
                title=t.get("title") or "",
                description=t.get("description") or "",
                priority=t.get("priority") or "medium",
                estimated_hours=float(t.get("estimated_hours") or 1.0),
                deliverables=normalize_string_list(t.get("deliverables") or []),
                dependencies=normalize_string_list(t.get("dependencies") or []),
                tools=normalize_string_list(t.get("tools") or []),
                requires_human=bool(t.get("requires_human", True)),
                human_reason=t.get("human_reason") or "",
            ))

        plan = ImplementationPlan(
            title=data.get("title", f"Repurposing: {metadata.shortcode}"),
            summary=data.get("summary", ""),
            tasks=tasks,
            total_estimated_hours=sum(t.estimated_hours for t in tasks),
        )
    except (json.JSONDecodeError, IndexError, KeyError) as e:
        logger.warning(f"Failed to parse repurposing JSON ({e}), creating single-task plan")
        logger.debug(f"finish_reason={chat_result.finish_reason}, tokens={chat_result.completion_tokens}/{chat_result.total_tokens}")
        raw = chat_result.text
        plan = ImplementationPlan(
            title=f"Repurposing: {metadata.shortcode}",
            summary=raw[:500],
            tasks=[PlanTask(
                title="Create adapted content from reel",
                description=raw,
                priority="medium",
                estimated_hours=2.0,
                requires_human=True,
                human_reason="Needs filming and content approval",
            )],
            total_estimated_hours=2.0,
        )

    logger.info(f"Repurposing plan generated: {plan.title} ({len(plan.tasks)} tasks, {plan.total_estimated_hours}h)")
    return plan, chat_result

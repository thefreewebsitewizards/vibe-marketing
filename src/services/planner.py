import json
import anthropic
from loguru import logger

from src.config import settings
from src.models import AnalysisResult, ReelMetadata, ImplementationPlan, PlanTask
from src.prompts.generate_plan import build_plan_prompt
from src.utils.plan_manager import get_past_plan_summaries


def generate_plan(analysis: AnalysisResult, metadata: ReelMetadata) -> ImplementationPlan:
    """Generate an implementation plan from the analysis using Claude."""
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    existing_plans = get_past_plan_summaries(limit=10)

    script_context = ""
    script_section_ids = ""
    if analysis.category == "sales":
        from src.utils.script_manager import get_script_content, get_script_summary
        script_context = get_script_content()
        if script_context:
            script_section_ids = get_script_summary()
            logger.info("Injecting sales script context into plan prompt")

    system_prompt, user_prompt = build_plan_prompt(
        analysis, metadata, existing_plans, script_context, script_section_ids
    )

    logger.info("Generating implementation plan...")
    response = client.messages.create(
        model=settings.anthropic_model,
        max_tokens=3000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw = response.content[0].text

    try:
        json_text = raw
        if "```json" in raw:
            json_text = raw.split("```json")[1].split("```")[0]
        elif "```" in raw:
            json_text = raw.split("```")[1].split("```")[0]

        data = json.loads(json_text)

        tasks = []
        for t in data.get("tasks", []):
            tasks.append(PlanTask(
                title=t.get("title", ""),
                description=t.get("description", ""),
                priority=t.get("priority", "medium"),
                estimated_hours=float(t.get("estimated_hours", 1.0)),
                deliverables=t.get("deliverables", []),
                dependencies=t.get("dependencies", []),
                tools=t.get("tools", []),
            ))

        plan = ImplementationPlan(
            title=data.get("title", f"Plan: {metadata.shortcode}"),
            summary=data.get("summary", ""),
            tasks=tasks,
            total_estimated_hours=sum(t.estimated_hours for t in tasks),
        )
    except (json.JSONDecodeError, IndexError, KeyError):
        logger.warning("Failed to parse plan JSON, creating single-task plan")
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
    return plan

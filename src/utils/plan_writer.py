import json
from datetime import datetime
from pathlib import Path
from loguru import logger

from src.config import settings
from src.models import PipelineResult, PlanIndexEntry, PlanStatus


def write_plan(result: PipelineResult) -> Path:
    """Write all plan artifacts to the plans directory."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    plan_dir_name = f"{date_str}_{result.reel_id}"
    plan_dir = settings.plans_dir / plan_dir_name
    plan_dir.mkdir(parents=True, exist_ok=True)

    # Write transcript
    (plan_dir / "transcript.txt").write_text(result.transcript.text)

    # Write analysis
    (plan_dir / "analysis.json").write_text(
        json.dumps(result.analysis.model_dump(), indent=2)
    )

    # Write metadata
    metadata = {
        "reel_id": result.reel_id,
        "status": result.status.value,
        "source_url": result.metadata.url,
        "creator": result.metadata.creator,
        "caption": result.metadata.caption,
        "duration": result.metadata.duration,
        "created_at": result.created_at.isoformat(),
    }
    (plan_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

    # Write plan as markdown
    plan_md = _format_plan_md(result)
    (plan_dir / "plan.md").write_text(plan_md)

    # Update index
    _update_index(result, plan_dir_name)

    result.plan_dir = str(plan_dir)
    logger.info(f"Plan written to {plan_dir}")
    return plan_dir


def _format_plan_md(result: PipelineResult) -> str:
    plan = result.plan
    lines = [
        f"# {plan.title}",
        "",
        f"**Source:** [{result.metadata.creator}]({result.metadata.url})",
        f"**Category:** {result.analysis.category}",
        f"**Relevance:** {result.analysis.relevance_score:.0%}",
        f"**Total Hours:** {plan.total_estimated_hours:.1f}h",
        f"**Status:** {result.status.value}",
        "",
        "## Summary",
        "",
        plan.summary,
        "",
        "## Key Insights",
        "",
    ]
    for insight in result.analysis.key_insights:
        lines.append(f"- {insight}")

    if result.analysis.swipe_phrases:
        lines.extend(["", "## Swipe Phrases", ""])
        for phrase in result.analysis.swipe_phrases:
            lines.append(f"- {phrase}")

    lines.extend(["", "## Tasks", ""])

    for i, task in enumerate(plan.tasks, 1):
        lines.append(f"### {i}. {task.title}")
        lines.append(f"**Priority:** {task.priority} | **Hours:** {task.estimated_hours:.1f}h | **Tools:** {', '.join(task.tools)}")
        lines.append("")
        lines.append(task.description)
        if task.deliverables:
            lines.append("")
            lines.append("**Deliverables:**")
            for d in task.deliverables:
                lines.append(f"- {d}")
        if task.dependencies:
            lines.append(f"\n**Depends on:** {', '.join(task.dependencies)}")
        lines.append("")

    return "\n".join(lines)


def _update_index(result: PipelineResult, plan_dir_name: str) -> None:
    index_path = settings.plans_dir / "_index.json"

    if index_path.exists():
        with open(index_path) as f:
            index = json.load(f)
    else:
        index = {"plans": []}

    entry = PlanIndexEntry(
        reel_id=result.reel_id,
        title=result.plan.title,
        status=PlanStatus.REVIEW,
        plan_dir=plan_dir_name,
        created_at=result.created_at.isoformat(),
        source_url=result.metadata.url,
    )
    index["plans"].append(entry.model_dump())

    with open(index_path, "w") as f:
        json.dump(index, f, indent=2)

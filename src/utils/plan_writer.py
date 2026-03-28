"""Plan artifact writer -- main entry point for writing plan files to disk.

Delegates HTML rendering to html_renderer and notes formatting to plan_formatter.
"""
import json
from datetime import datetime
from pathlib import Path

from loguru import logger

from src.config import settings
from src.models import PipelineResult, PlanIndexEntry, PlanStatus, ImplementationPlan
from src.utils.plan_router import route_plan
from src.utils.html_renderer import render_plan_html, html_esc as _html_esc, md_to_html as _md_to_html
from src.utils.plan_formatter import format_notes_md
from src.utils.reel_registry import append_reel_entry


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
    if result.cost_breakdown:
        metadata["cost_breakdown"] = result.cost_breakdown.model_dump()
    (plan_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

    # Write plan as markdown
    plan_md = _format_plan_md(result)
    (plan_dir / "plan.md").write_text(plan_md)

    # Write structured plan data for executor
    (plan_dir / "plan.json").write_text(
        json.dumps(result.plan.model_dump(), indent=2)
    )

    # Write analysis-only quick-reference notes
    notes_md = format_notes_md(result)
    (plan_dir / "notes.md").write_text(notes_md)

    # Write pre-rendered HTML view
    view_html = render_plan_html(result)
    (plan_dir / "view.html").write_text(view_html)

    # Route blurb to sister project folder
    routed_to = route_plan(result) or ""

    # Update index
    _update_index(result, plan_dir_name, routed_to=routed_to)

    # Append to central reel registry
    append_reel_entry(result)

    result.plan_dir = str(plan_dir)
    logger.info(f"Plan written to {plan_dir}")
    return plan_dir


def write_plan_md(plan: ImplementationPlan, plan_md_path: Path) -> None:
    """Overwrite just the plan.md file (used for refinement)."""
    lines = [
        f"# {plan.title}",
        "",
    ]

    if plan.recommended_action:
        lines.extend([f"**Do this:** {plan.recommended_action}", ""])

    lines.extend(["## Summary", "", plan.summary, ""])

    if plan.content_angle:
        lines.extend(["## DDB Content Angle", "", plan.content_angle, ""])

    # Level summaries
    if plan.level_summaries:
        lines.append("## Implementation Levels")
        lines.append("")
        level_labels = {"1": "L1 -- Note it", "2": "L2 -- Build it", "3": "L3 -- Go deep"}
        for k, v in plan.level_summaries.items():
            label = level_labels.get(k, f"L{k}")
            lines.append(f"- **{label}:** {v}")
        lines.append("")

    # Tasks grouped by level
    lines.extend(["## Tasks", ""])
    level_labels = {1: "L1 -- Note it", 2: "L2 -- Build it", 3: "L3 -- Go deep"}
    task_num = 0
    for lvl in (1, 2, 3):
        lvl_tasks = [t for t in plan.tasks if t.level == lvl]
        if not lvl_tasks:
            continue

        lines.append(f"### {level_labels.get(lvl, f'L{lvl}')}")
        lines.append("")

        for task in lvl_tasks:
            task_num += 1
            human_flag = " [NEEDS HUMAN]" if task.requires_human else ""
            lines.append(f"#### {task_num}. {task.title}{human_flag}")
            lines.append(f"**Priority:** {task.priority} | **Hours:** {task.estimated_hours:.1f}h | **Tools:** {', '.join(task.tools)}")
            if task.requires_human and task.human_reason:
                lines.append(f"**Why human needed:** {task.human_reason}")
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

    plan_md_path.write_text("\n".join(lines))


def _format_plan_md(result: PipelineResult) -> str:
    plan = result.plan
    analysis = result.analysis
    lines = [
        f"# {plan.title}",
        "",
        f"**Source:** [{result.metadata.creator}]({result.metadata.url})",
        f"**Category:** {analysis.category}",
        f"**Relevance:** {analysis.relevance_score:.0%}",
        f"**Total Hours:** {plan.total_estimated_hours:.1f}h",
        f"**Status:** {result.status.value}",
    ]

    if plan.recommended_action:
        lines.extend(["", f"**Do this:** {plan.recommended_action}"])

    if analysis.theme:
        lines.extend(["", f"> *{analysis.theme}*"])

    if analysis.business_impact:
        lines.extend(["", "## Why This Matters", "", analysis.business_impact])

    lines.extend(["", "## Summary", "", plan.summary])

    # Video breakdown
    vb = analysis.video_breakdown
    if vb.main_points or vb.key_quotes:
        lines.extend(["", "## What This Video Covers", ""])
        if vb.creator_context:
            lines.append(f"*{vb.creator_context}*")
            lines.append("")
        if vb.hook:
            lines.append(f"**Hook:** {vb.hook}")
            lines.append("")
        if vb.main_points:
            for i, point in enumerate(vb.main_points, 1):
                lines.append(f"{i}. {point}")
            lines.append("")
        if vb.key_quotes:
            lines.append("**Key quotes:**")
            for q in vb.key_quotes:
                lines.append(f'> "{q}"')
                lines.append("")

    # Detailed notes
    notes = analysis.detailed_notes
    if notes.what_it_is or notes.how_useful:
        lines.extend(["", "## Detailed Notes", ""])
        if notes.what_it_is:
            lines.append(f"**What it is:** {notes.what_it_is}")
        if notes.how_useful:
            lines.append(f"**How it helps us:** {notes.how_useful}")
        if notes.how_not_useful:
            lines.append(f"**Limitations:** {notes.how_not_useful}")
        if notes.target_audience:
            lines.append(f"**Who should see this:** {notes.target_audience}")

    # Business applications
    if analysis.business_applications:
        lines.extend(["", "## Business Applications", ""])
        for ba in analysis.business_applications:
            lines.append(f"- **[{ba.urgency.upper()}]** {ba.area}: {ba.recommendation} *(target: {ba.target_system})*")

    # Reality checks
    if analysis.reality_checks:
        lines.extend(["", "## Reality Check", ""])
        for rc in analysis.reality_checks:
            icon = {"solid": "SOLID", "plausible": "PLAUSIBLE", "questionable": "QUESTIONABLE", "misleading": "MISLEADING"}
            lines.append(f"- **[{icon.get(rc.verdict, '?')}]** \"{rc.claim}\" -- {rc.explanation}")
            if rc.better_alternative:
                lines.append(f"  - Instead: {rc.better_alternative}")

    # Key insights
    lines.extend(["", "## Key Insights", ""])
    for insight in analysis.key_insights:
        lines.append(f"- {insight}")

    # Content angle
    if plan.content_angle:
        lines.extend(["", "## DDB Content Angle", "", plan.content_angle])

    # Implementation levels
    lines.extend(["", "## Implementation Levels", ""])

    level_labels = {1: "L1 -- Note it", 2: "L2 -- Build it", 3: "L3 -- Go deep"}
    for lvl_summary_key, summary_text in plan.level_summaries.items():
        lvl = int(lvl_summary_key)
        label = level_labels.get(lvl, f"L{lvl}")
        lines.append(f"- **{label}:** {summary_text}")
    lines.append("")

    # Tasks grouped by level
    lines.extend(["## Tasks", ""])

    human_count = sum(1 for t in plan.tasks if t.requires_human)
    if human_count:
        lines.append(f"*{human_count} task(s) require human action (marked [NEEDS HUMAN])*\n")

    task_num = 0
    for lvl in (1, 2, 3):
        lvl_tasks = [t for t in plan.tasks if t.level == lvl]
        if not lvl_tasks:
            continue

        label = level_labels.get(lvl, f"L{lvl}")
        lines.append(f"### {label}")
        lines.append("")

        for task in lvl_tasks:
            task_num += 1
            human_flag = " [NEEDS HUMAN]" if task.requires_human else ""
            lines.append(f"#### {task_num}. {task.title}{human_flag}")
            lines.append(f"**Priority:** {task.priority} | **Hours:** {task.estimated_hours:.1f}h | **Tools:** {', '.join(task.tools)}")
            if task.change_type:
                lines.append(f"**Change type:** {task.change_type}")
            if task.requires_human and task.human_reason:
                lines.append(f"**Why human needed:** {task.human_reason}")
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

    # Social media play
    cr = analysis.content_response
    if cr.react_angle or cr.repurpose_ideas or cr.corrections:
        lines.extend(["", "## Social Media Play", ""])
        if cr.react_angle:
            lines.append(f"**React angle:** {cr.react_angle}")
        if cr.corrections:
            lines.append("**Corrections:**")
            for c in cr.corrections:
                lines.append(f"- {c}")
        if cr.repurpose_ideas:
            lines.append("**Repurpose ideas:**")
            for r in cr.repurpose_ideas:
                lines.append(f"- {r}")
        if cr.engagement_hook:
            lines.append(f"**Engagement hook:** {cr.engagement_hook}")

    return "\n".join(lines)


def _update_index(result: PipelineResult, plan_dir_name: str, *, routed_to: str = "") -> None:
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
        theme=result.analysis.theme,
        category=result.analysis.category,
        relevance_score=result.analysis.relevance_score,
        estimated_cost=result.cost_breakdown.total_cost_usd if result.cost_breakdown else 0.0,
        routed_to=routed_to,
        task_count=len(result.plan.tasks),
        total_hours=result.plan.total_estimated_hours,
    )
    index["plans"].append(entry.model_dump())

    with open(index_path, "w") as f:
        json.dump(index, f, indent=2)

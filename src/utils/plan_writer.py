import json
from datetime import datetime
from pathlib import Path
from loguru import logger

from src.config import settings
from src.models import PipelineResult, PlanIndexEntry, PlanStatus, ImplementationPlan
from src.utils.plan_router import route_plan


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
    notes_md = _format_notes_md(result)
    (plan_dir / "notes.md").write_text(notes_md)

    # Write repurposing plan if present
    if result.repurposing_plan:
        repurposing_md = _format_repurposing_md(result.repurposing_plan)
        (plan_dir / "repurposing_plan.md").write_text(repurposing_md)

    # Write personal brand plan if present
    if result.personal_brand_plan:
        pb_md = _format_repurposing_md(result.personal_brand_plan)
        (plan_dir / "personal_brand_plan.md").write_text(pb_md)

    # Write pre-rendered HTML view
    view_html = _render_plan_html(result)
    (plan_dir / "view.html").write_text(view_html)

    # Route blurb to sister project folder
    routed_to = route_plan(result) or ""

    # Update index
    _update_index(result, plan_dir_name, routed_to=routed_to)

    result.plan_dir = str(plan_dir)
    logger.info(f"Plan written to {plan_dir}")
    return plan_dir


def write_plan_md(plan: ImplementationPlan, plan_md_path: Path) -> None:
    """Overwrite just the plan.md file (used for refinement)."""
    lines = [
        f"# {plan.title}",
        "",
        "## Summary",
        "",
        plan.summary,
        "",
        "## Tasks",
        "",
    ]
    for i, task in enumerate(plan.tasks, 1):
        human_flag = " [NEEDS HUMAN]" if task.requires_human else ""
        lines.append(f"### {i}. {task.title}{human_flag}")
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

    # Fact checks
    if analysis.fact_checks:
        lines.extend(["", "## Fact Checks", ""])
        for fc in analysis.fact_checks:
            icon = {"verified": "OK", "outdated": "OUTDATED", "better_alternative": "UPDATE", "unverified": "?"}
            lines.append(f"- **[{icon.get(fc.verdict, '?')}]** \"{fc.claim}\" — {fc.explanation}")
            if fc.better_alternative:
                lines.append(f"  - Better: {fc.better_alternative}")

    # Key insights
    lines.extend(["", "## Key Insights", ""])
    for insight in analysis.key_insights:
        lines.append(f"- {insight}")

    if analysis.swipe_phrases:
        lines.extend(["", "## Swipe Phrases", ""])
        for phrase in analysis.swipe_phrases:
            lines.append(f"- {phrase}")

    # Tasks
    lines.extend(["", "## Implementation Tasks", ""])

    human_count = sum(1 for t in plan.tasks if t.requires_human)
    if human_count:
        lines.append(f"*{human_count} task(s) require human action (marked [NEEDS HUMAN])*\n")

    for i, task in enumerate(plan.tasks, 1):
        human_flag = " [NEEDS HUMAN]" if task.requires_human else ""
        lines.append(f"### {i}. {task.title}{human_flag}")
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

    return "\n".join(lines)


def _format_notes_md(result: PipelineResult) -> str:
    """Quick-reference analysis notes (no tasks)."""
    analysis = result.analysis
    lines = [
        f"# Analysis Notes: {result.metadata.creator}",
        "",
        f"**Source:** {result.metadata.url}",
        f"**Category:** {analysis.category}",
        f"**Relevance:** {analysis.relevance_score:.0%}",
    ]

    if analysis.theme:
        lines.extend(["", f"> *{analysis.theme}*"])

    if analysis.business_impact:
        lines.extend(["", f"**Bottom line:** {analysis.business_impact}"])

    lines.extend(["", "## Summary", "", analysis.summary])

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

    notes = analysis.detailed_notes
    if notes.what_it_is:
        lines.extend(["", "## Notes", ""])
        if notes.what_it_is:
            lines.append(f"- **What:** {notes.what_it_is}")
        if notes.how_useful:
            lines.append(f"- **Useful:** {notes.how_useful}")
        if notes.how_not_useful:
            lines.append(f"- **Not useful:** {notes.how_not_useful}")
        if notes.target_audience:
            lines.append(f"- **For:** {notes.target_audience}")

    if analysis.business_applications:
        lines.extend(["", "## Applications", ""])
        for ba in analysis.business_applications:
            lines.append(f"- [{ba.urgency}] {ba.area} -> {ba.target_system}: {ba.recommendation}")

    lines.extend(["", "## Key Insights", ""])
    for insight in analysis.key_insights:
        lines.append(f"- {insight}")

    if analysis.swipe_phrases:
        lines.extend(["", "## Swipe Phrases", ""])
        for phrase in analysis.swipe_phrases:
            lines.append(f"- {phrase}")

    if analysis.fact_checks:
        lines.extend(["", "## Fact Checks", ""])
        for fc in analysis.fact_checks:
            lines.append(f"- [{fc.verdict}] {fc.claim}: {fc.explanation}")

    return "\n".join(lines)


def _format_repurposing_md(plan: ImplementationPlan) -> str:
    """Format a repurposing plan as markdown."""
    lines = [
        f"# {plan.title}",
        "",
        "## Summary",
        "",
        plan.summary,
        "",
        "## Content Tasks",
        "",
    ]

    for i, task in enumerate(plan.tasks, 1):
        human_flag = " [NEEDS HUMAN]" if task.requires_human else ""
        lines.append(f"### {i}. {task.title}{human_flag}")
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

    return "\n".join(lines)


def _render_plan_html(result: PipelineResult) -> str:
    """Render the full plan as a standalone HTML page."""
    from pathlib import Path
    template_path = Path(__file__).resolve().parent.parent.parent / "static" / "plan_view.html"
    if not template_path.exists():
        return "<html><body><p>Template not found</p></body></html>"

    template = template_path.read_text()

    analysis = result.analysis
    plan = result.plan

    # Build similarity HTML
    similarity_html = ""
    if result.similarity and result.similarity.similar_plans:
        top = result.similarity.similar_plans[0]
        rec_text = {
            "merge": "Consider merging tasks rather than separate execution.",
            "skip": "Very similar — review carefully before proceeding.",
            "generate": "Different enough to proceed.",
        }.get(result.similarity.recommendation, "")
        similarity_html = (
            f'<div class="similarity-callout">'
            f'<strong>Similar to:</strong> {_html_esc(top.title)} ({top.score}% overlap)'
        )
        if top.overlap_areas:
            similarity_html += f'<br>Overlap: {_html_esc(", ".join(top.overlap_areas))}'
        if rec_text:
            similarity_html += f'<br><em>{rec_text}</em>'
        similarity_html += '</div>'

    # Build applications HTML
    applications_html = ""
    if analysis.business_applications:
        for ba in analysis.business_applications:
            color = {"high": "#ef4444", "medium": "#f59e0b", "low": "#22c55e"}.get(ba.urgency, "#94a3b8")
            applications_html += (
                f'<div class="card" style="border-left: 3px solid {color};">'
                f'<span class="badge" style="background:{color};">{ba.urgency.upper()}</span> '
                f'<strong>{_html_esc(ba.area)}</strong> <em>({_html_esc(ba.target_system)})</em>'
                f'<p>{_md_to_html(ba.recommendation)}</p></div>'
            )

    # Key insights HTML
    insights_html = "".join(f"<li>{_md_to_html(i)}</li>" for i in analysis.key_insights)

    # Swipe phrases HTML
    phrases_html = "".join(f"<li>{_md_to_html(p)}</li>" for p in analysis.swipe_phrases) if analysis.swipe_phrases else "<li>None extracted</li>"

    # Fact checks HTML
    fact_checks_html = ""
    if analysis.fact_checks:
        for fc in analysis.fact_checks:
            icon = {"verified": "OK", "outdated": "OUTDATED", "better_alternative": "UPDATE", "unverified": "?"}.get(fc.verdict, "?")
            fc_line = f'<div class="card"><strong>[{icon}]</strong> "{_html_esc(fc.claim)}" &mdash; {_html_esc(fc.explanation)}'
            if fc.better_alternative:
                fc_line += f"<br><em>Better: {_html_esc(fc.better_alternative)}</em>"
            fc_line += "</div>"
            fact_checks_html += fc_line

    # Tasks HTML
    tasks_html = ""
    human_count = sum(1 for t in plan.tasks if t.requires_human)
    if human_count:
        tasks_html += f'<p class="human-note">{human_count} task(s) require human action</p>'

    for i, task in enumerate(plan.tasks, 1):
        human_badge = ' <span class="badge" style="background:#ef4444;">NEEDS HUMAN</span>' if task.requires_human else ""
        deliverables = "".join(f"<li>{_html_esc(d)}</li>" for d in task.deliverables)
        deps = f"<p><em>Depends on: {_html_esc(', '.join(task.dependencies))}</em></p>" if task.dependencies else ""
        human_reason = f"<p><em>Why human needed: {_html_esc(task.human_reason)}</em></p>" if task.requires_human and task.human_reason else ""
        tasks_html += (
            f'<div class="task">'
            f'<h3>{i}. {_html_esc(task.title)}{human_badge}</h3>'
            f'<p class="task-meta">{_html_esc(task.priority)} &middot; {task.estimated_hours:.1f}h &middot; {_html_esc(", ".join(task.tools))}</p>'
            f'{human_reason}'
            f'<div class="task-desc">{_md_to_html(task.description)}</div>'
            f'{"<ul>" + deliverables + "</ul>" if deliverables else ""}'
            f'{deps}'
            f'</div>'
        )

    # Repurposing section HTML
    repurposing_html = ""
    if result.repurposing_plan:
        rp = result.repurposing_plan
        repurposing_html += f'<h2>Content Repurposing Guide</h2><p>{_md_to_html(rp.summary)}</p>'
        for i, task in enumerate(rp.tasks, 1):
            human_badge = ' <span class="badge" style="background:#ef4444;">NEEDS HUMAN</span>' if task.requires_human else ""
            deliverables = "".join(f"<li>{_md_to_html(d)}</li>" for d in task.deliverables)
            repurposing_html += (
                f'<div class="task">'
                f'<h3>{i}. {_html_esc(task.title)}{human_badge}</h3>'
                f'<p class="task-meta">{_html_esc(task.priority)} &middot; {task.estimated_hours:.1f}h</p>'
                f'<div class="task-desc">{_md_to_html(task.description)}</div>'
                f'{"<ul>" + deliverables + "</ul>" if deliverables else ""}'
                f'</div>'
            )

    # Personal brand section HTML
    personal_brand_html = ""
    if result.personal_brand_plan:
        pb = result.personal_brand_plan
        personal_brand_html += f'<h2>Dylan Does Business — Personal Brand Plan</h2><p>{_md_to_html(pb.summary)}</p>'
        for i, task in enumerate(pb.tasks, 1):
            human_badge = ' <span class="badge" style="background:#ef4444;">NEEDS HUMAN</span>' if task.requires_human else ""
            deliverables = "".join(f"<li>{_md_to_html(d)}</li>" for d in task.deliverables)
            personal_brand_html += (
                f'<div class="task">'
                f'<h3>{i}. {_html_esc(task.title)}{human_badge}</h3>'
                f'<p class="task-meta">{_html_esc(task.priority)} &middot; {task.estimated_hours:.1f}h</p>'
                f'<div class="task-desc">{_md_to_html(task.description)}</div>'
                f'{"<ul>" + deliverables + "</ul>" if deliverables else ""}'
                f'</div>'
            )

    # Video breakdown HTML
    vb = analysis.video_breakdown
    video_breakdown_html = ""
    if vb.main_points or vb.key_quotes:
        video_breakdown_html = '<h2>What This Video Covers</h2>'
        if vb.creator_context:
            video_breakdown_html += f'<div class="creator-ctx">{_html_esc(vb.creator_context)}</div>'
        if vb.hook:
            video_breakdown_html += f'<div class="hook"><strong>Hook:</strong> {_html_esc(vb.hook)}</div>'
        if vb.main_points:
            points = "".join(f"<li>{_html_esc(p)}</li>" for p in vb.main_points)
            video_breakdown_html += f'<ul class="point-list">{points}</ul>'
        if vb.key_quotes:
            for q in vb.key_quotes:
                video_breakdown_html += f'<div class="quote">&ldquo;{_html_esc(q)}&rdquo;</div>'

    # Detailed notes HTML
    notes = analysis.detailed_notes
    notes_html = ""
    if notes.what_it_is or notes.how_useful:
        if notes.what_it_is:
            notes_html += f"<p><strong>What it is:</strong> {_md_to_html(notes.what_it_is)}</p>"
        if notes.how_useful:
            notes_html += f"<p><strong>How it helps us:</strong> {_md_to_html(notes.how_useful)}</p>"
        if notes.how_not_useful:
            notes_html += f"<p><strong>Limitations:</strong> {_md_to_html(notes.how_not_useful)}</p>"
        if notes.target_audience:
            notes_html += f"<p><strong>Who should see this:</strong> {_html_esc(notes.target_audience)}</p>"

    # Duration display
    dur = result.metadata.duration
    duration_str = f"{int(dur)}s" if dur < 60 else f"{int(dur // 60)}m {int(dur % 60)}s"

    # Relevance badge color
    score = analysis.relevance_score
    relevance_color = "#22c55e" if score >= 0.85 else "#f59e0b" if score >= 0.70 else "#ef4444"

    # Cost breakdown HTML
    cost_html = ""
    if result.cost_breakdown and result.cost_breakdown.calls:
        cb = result.cost_breakdown
        cost_rows = "".join(
            f'<tr><td>{_html_esc(c.step)}</td><td>{c.prompt_tokens:,}</td>'
            f'<td>{c.completion_tokens:,}</td><td>${c.cost_usd:.4f}</td></tr>'
            for c in cb.calls
        )
        cost_html = (
            f'<h2><a href="/costs" style="color:#f8fafc;text-decoration:none;">Cost Breakdown →</a></h2>'
            f'<div class="card"><div class="cost-table-wrap"><table>'
            f'<tr style="color:#94a3b8;text-align:left;"><th>Step</th><th>Prompt</th>'
            f'<th>Completion</th><th>Cost</th></tr>'
            f'{cost_rows}'
            f'<tr style="border-top:1px solid #334155;font-weight:600;">'
            f'<td>Total</td><td colspan="2"></td><td>${cb.total_cost_usd:.4f}</td></tr>'
            f'</table></div></div>'
        )

    replacements = {
        "{{similarity_html}}": similarity_html,
        "{{title}}": _html_esc(plan.title),
        "{{theme}}": _html_esc(analysis.theme) if analysis.theme else "",
        "{{relevance_score}}": f"{score:.0%}",
        "{{relevance_color}}": relevance_color,
        "{{business_impact}}": _html_esc(analysis.business_impact) if analysis.business_impact else "",
        "{{summary}}": _md_to_html(plan.summary),
        "{{video_breakdown_html}}": video_breakdown_html,
        "{{notes_html}}": notes_html,
        "{{applications_html}}": applications_html,
        "{{insights_html}}": insights_html,
        "{{phrases_html}}": phrases_html,
        "{{fact_checks_section}}": _build_fact_checks_section(fact_checks_html),
        "{{tasks_html}}": tasks_html,
        "{{total_hours}}": f"{plan.total_estimated_hours:.1f}",
        "{{duration}}": duration_str,
        "{{repurposing_html}}": repurposing_html,
        "{{personal_brand_html}}": personal_brand_html,
        "{{source_url}}": _html_esc(result.metadata.url),
        "{{creator}}": _html_esc(result.metadata.creator),
        "{{category}}": _html_esc(analysis.category),
        "{{routed_to_html}}": _build_route_badge(analysis.routing_target),
        "{{cost_html}}": cost_html,
        "{{reel_id}}": _html_esc(result.reel_id),
        "{{status}}": result.status.value,
        "{{action_buttons_html}}": _build_action_buttons(result.reel_id, result.status.value),
    }

    html = template
    for key, value in replacements.items():
        html = html.replace(key, value)

    return html


def _build_action_buttons(reel_id: str, status: str) -> str:
    """Build action buttons bar for plan view."""
    reel_id_esc = _html_esc(reel_id)
    buttons = (
        f'<div class="action-bar">'
        f'<button class="action-btn back" onclick="location.href=\'/\'">Dashboard</button>'
        f'<button class="action-btn approve" onclick="updateStatus(\'{reel_id_esc}\',\'approved\',this)">Approve</button>'
        f'<button class="action-btn reject" onclick="updateStatus(\'{reel_id_esc}\',\'failed\',this)">Reject</button>'
        f'<button class="action-btn complete" onclick="updateStatus(\'{reel_id_esc}\',\'completed\',this)">Mark Complete</button>'
        f'<span id="action-status" class="action-status">Status: {_html_esc(status)}</span>'
        f'</div>'
    )
    return buttons


def _build_route_badge(routing_target: str) -> str:
    if not routing_target:
        return ""
    return f' &middot; <span class="badge badge-route">{_html_esc(routing_target)}</span>'


def _build_fact_checks_section(fact_checks_html: str) -> str:
    """Build fact checks section: hidden when empty, expanded when populated."""
    if not fact_checks_html:
        return ""
    return (
        '<h2>Fact Checks</h2>\n'
        f'<div>{fact_checks_html}</div>'
    )


def _html_esc(text: str) -> str:
    """Escape HTML special characters."""
    if not text:
        return ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


def _md_to_html(text: str) -> str:
    """Convert basic markdown to HTML for plan view rendering.

    Handles: **bold**, *italic*, `code`, line breaks, and bullet lists.
    Escapes HTML first for safety, then applies markdown conversion.
    """
    import re

    if not text:
        return ""

    escaped = _html_esc(text)

    # Bold: **text**
    escaped = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', escaped)
    # Italic: *text* (but not inside <strong> tags)
    escaped = re.sub(r'(?<!</strong>)\*(.+?)\*', r'<em>\1</em>', escaped)
    # Inline code: `text`
    escaped = re.sub(r'`(.+?)`', r'<code>\1</code>', escaped)

    # Split into lines for block-level processing
    lines = escaped.split('\n')
    result_lines = []
    in_list = False

    for line in lines:
        stripped = line.strip()

        # Bullet list item: - text
        if stripped.startswith('- '):
            if not in_list:
                result_lines.append('<ul>')
                in_list = True
            result_lines.append(f'<li>{stripped[2:]}</li>')
        else:
            if in_list:
                result_lines.append('</ul>')
                in_list = False

            if stripped:
                result_lines.append(f'{stripped}<br>')
            else:
                result_lines.append('<br>')

    if in_list:
        result_lines.append('</ul>')

    # Clean up trailing <br> before </ul>
    html = '\n'.join(result_lines)
    html = html.replace('<br>\n<ul>', '\n<ul>')
    # Remove double <br> at end
    if html.endswith('<br>'):
        html = html[:-4]

    return html


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

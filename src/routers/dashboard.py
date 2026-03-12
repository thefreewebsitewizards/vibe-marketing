import json
from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from src.config import settings
from src.utils.plan_manager import get_index

router = APIRouter()

_CATEGORY_LABELS = {
    "marketing": "Marketing",
    "sales": "Sales",
    "ai_automation": "AI & Automation",
    "operations": "Operations",
    "content": "Content",
    "general": "General",
}

_STATUS_COLORS = {
    "processing": "#8b5cf6",
    "review": "#f59e0b",
    "approved": "#22c55e",
    "in_progress": "#3b82f6",
    "completed": "#6b7280",
    "skipped": "#94a3b8",
    "failed": "#ef4444",
}


def _esc(text: str) -> str:
    if not text:
        return ""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


@router.get("/", response_class=HTMLResponse)
def dashboard():
    """Serve the main dashboard page."""
    template_path = Path(__file__).resolve().parent.parent.parent / "static" / "dashboard.html"
    template = template_path.read_text()

    index = get_index()
    plans = index.get("plans", [])

    # Stats
    total = len(plans)
    review_count = sum(1 for p in plans if p.get("status") == "review")
    approved_count = sum(1 for p in plans if p.get("status") == "approved")
    completed_count = sum(1 for p in plans if p.get("status") == "completed")
    total_cost = sum(p.get("estimated_cost", 0) for p in plans)

    stats_html = (
        '<div class="stats">'
        f'<div class="stat"><div class="stat-value">{total}</div><div class="stat-label">Total Plans</div></div>'
        f'<div class="stat"><div class="stat-value">{review_count}</div><div class="stat-label">In Review</div></div>'
        f'<div class="stat"><div class="stat-value">{approved_count}</div><div class="stat-label">Approved</div></div>'
        f'<div class="stat"><div class="stat-value">{completed_count}</div><div class="stat-label">Completed</div></div>'
        f'<a href="/costs" class="stat" style="text-decoration:none;color:inherit;"><div class="stat-value">${total_cost:.3f}</div><div class="stat-label">Total Cost →</div></a>'
        '</div>'
    )

    # Group by category
    by_category: dict[str, list[dict]] = defaultdict(list)
    for p in plans:
        cat = p.get("category", "general") or "general"
        by_category[cat].append(p)

    # Sort categories: ones with more plans first
    sorted_cats = sorted(by_category.items(), key=lambda x: -len(x[1]))

    categories_html = ""
    if not plans:
        categories_html = '<div class="empty-state">No plans yet. Send a reel to the Telegram bot to get started.</div>'
    else:
        for cat, cat_plans in sorted_cats:
            label = _CATEGORY_LABELS.get(cat, cat.replace("_", " ").title())
            # Sort plans newest first
            cat_plans.sort(key=lambda p: p.get("created_at", ""), reverse=True)

            cards_html = ""
            for p in cat_plans:
                reel_id = _esc(p.get("reel_id", ""))
                title = _esc(p.get("title", "Untitled"))
                theme = _esc(p.get("theme", ""))
                status = p.get("status", "review")
                score = p.get("relevance_score", 0)
                cost = p.get("estimated_cost", 0)
                created = p.get("created_at", "")[:10]

                score_pct = f"{score:.0%}" if score else ""
                rel_color = "#22c55e" if score >= 0.7 else "#f59e0b" if score >= 0.4 else "#94a3b8"

                cost_badge = f'<span class="badge badge-cost">${cost:.3f}</span>' if cost else ""
                routed = _esc(p.get("routed_to", ""))
                route_badge = f'<span class="badge badge-route">{routed}</span>' if routed else ""

                cards_html += (
                    f'<a class="plan-card" href="/plans/{reel_id}/view" data-status="{status}">'
                    f'<div class="plan-card-top">'
                    f'<div><div class="plan-title">{title}</div>'
                    f'{"<div class=plan-theme>" + theme + "</div>" if theme else ""}'
                    f'</div>'
                    f'<span class="badge badge-{status}">{status.replace("_", " ")}</span>'
                    f'</div>'
                    f'<div class="plan-meta">'
                    f'{"<span class=badge badge-relevance style=color:" + rel_color + ">" + score_pct + "</span>" if score_pct else ""}'
                    f'{route_badge}'
                    f'{cost_badge}'
                    f'<span class="plan-date">{created}</span>'
                    f'</div></a>'
                )

            categories_html += (
                f'<div class="category-section">'
                f'<div class="category-header" onclick="toggleCategory(this)">'
                f'<span class="category-toggle">-</span>'
                f'<h2>{_esc(label)}</h2>'
                f'<span class="category-badge">{len(cat_plans)}</span>'
                f'</div>'
                f'<div class="category-plans">{cards_html}</div>'
                f'</div>'
            )

    html = template.replace("{{stats_html}}", stats_html)
    html = html.replace("{{categories_html}}", categories_html)
    return HTMLResponse(html)


_STEP_COLORS = {
    "analysis": "#3b82f6",
    "similarity": "#f59e0b",
    "plan": "#22c55e",
}


@router.get("/costs", response_class=HTMLResponse)
def costs_page():
    """Serve the cost breakdown page with per-plan and per-step details."""
    template_path = Path(__file__).resolve().parent.parent.parent / "static" / "costs.html"
    template = template_path.read_text()

    index = get_index()
    plans = index.get("plans", [])

    # Load cost breakdowns from metadata files
    plan_costs = []
    step_totals: dict[str, float] = defaultdict(float)
    total_estimated = 0.0
    total_actual = 0.0
    total_tokens = 0

    for p in plans:
        plan_dir = p.get("plan_dir", "")
        meta_path = settings.plans_dir / plan_dir / "metadata.json"
        if not meta_path.exists():
            continue

        try:
            meta = json.loads(meta_path.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        cb = meta.get("cost_breakdown")
        if not cb or not cb.get("calls"):
            continue

        calls = cb["calls"]
        plan_est = sum(c.get("cost_usd", 0) for c in calls)
        plan_actual = sum(c.get("actual_cost_usd", 0) for c in calls if c.get("actual_cost_usd") is not None)
        plan_tokens = sum(c.get("prompt_tokens", 0) + c.get("completion_tokens", 0) for c in calls)
        has_actual = any(c.get("actual_cost_usd") is not None for c in calls)

        total_estimated += plan_est
        total_actual += plan_actual
        total_tokens += plan_tokens

        step_pills = []
        for c in calls:
            step = c.get("step", "?")
            cost = c.get("actual_cost_usd") if c.get("actual_cost_usd") is not None else c.get("cost_usd", 0)
            step_totals[step] += cost
            color = _STEP_COLORS.get(step, "#64748b")
            step_pills.append(
                f'<span class="step-pill" style="background:{color};">'
                f'{_esc(step)} ${cost:.4f}</span>'
            )

        plan_costs.append({
            "reel_id": p.get("reel_id", ""),
            "title": p.get("title", "Untitled"),
            "created_at": p.get("created_at", ""),
            "estimated": plan_est,
            "actual": plan_actual if has_actual else None,
            "tokens": plan_tokens,
            "step_pills": "".join(step_pills),
        })

    # Sort newest first
    plan_costs.sort(key=lambda x: x["created_at"], reverse=True)

    # Totals cards
    actual_card = ""
    if total_actual > 0:
        actual_card = (
            f'<div class="total-card">'
            f'<div class="total-value">${total_actual:.4f}</div>'
            f'<div class="total-label">Actual Cost</div></div>'
        )
    totals_html = (
        f'<div class="total-card">'
        f'<div class="total-value">${total_estimated:.4f}</div>'
        f'<div class="total-label">Estimated Cost</div></div>'
        f'{actual_card}'
        f'<div class="total-card">'
        f'<div class="total-value">{total_tokens:,}</div>'
        f'<div class="total-label">Total Tokens</div></div>'
        f'<div class="total-card">'
        f'<div class="total-value">{len(plan_costs)}</div>'
        f'<div class="total-label">Plans with Cost Data</div></div>'
    )

    # Step bars
    max_step_cost = max(step_totals.values()) if step_totals else 1
    step_bars_html = ""
    for step, cost in sorted(step_totals.items(), key=lambda x: -x[1]):
        pct = (cost / max_step_cost) * 100 if max_step_cost > 0 else 0
        color = _STEP_COLORS.get(step, "#64748b")
        step_bars_html += (
            f'<div class="step-bar">'
            f'<div class="step-name">{_esc(step)}</div>'
            f'<div class="step-fill-wrap"><div class="step-fill" style="width:{pct:.0f}%;background:{color};"></div></div>'
            f'<div class="step-cost">${cost:.4f}</div>'
            f'</div>'
        )

    # Plan rows
    plan_rows_html = ""
    for pc in plan_costs:
        cost_display = f"${pc['actual']:.4f}" if pc["actual"] is not None else f"${pc['estimated']:.4f}"
        date = pc["created_at"][:10] if pc["created_at"] else ""
        plan_rows_html += (
            f'<a class="plan-row" href="/plans/{_esc(pc["reel_id"])}/view">'
            f'<div class="plan-row-top">'
            f'<div class="plan-row-title">{_esc(pc["title"])}</div>'
            f'<div class="plan-row-cost">{cost_display}</div>'
            f'</div>'
            f'<div class="plan-row-meta">'
            f'<div class="step-pills">{pc["step_pills"]}</div>'
            f'<span class="plan-row-date">{date} · {pc["tokens"]:,} tokens</span>'
            f'</div></a>'
        )

    if not plan_rows_html:
        plan_rows_html = '<div style="color:#64748b;text-align:center;padding:40px;">No cost data available yet.</div>'

    html = template.replace("{{totals_html}}", totals_html)
    html = html.replace("{{step_bars_html}}", step_bars_html)
    html = html.replace("{{plan_rows_html}}", plan_rows_html)
    return HTMLResponse(html)

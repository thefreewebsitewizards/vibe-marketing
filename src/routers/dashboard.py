from collections import defaultdict
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

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
        f'<div class="stat"><div class="stat-value">${total_cost:.3f}</div><div class="stat-label">Total Cost</div></div>'
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

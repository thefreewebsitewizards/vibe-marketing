from collections import Counter
from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from src.utils.knowledge_base import get_entries, search_entries, get_recent_context

router = APIRouter(prefix="/knowledge")


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
def knowledge_page(
    category: str = "",
    tag: str = "",
    limit: int = Query(default=50, le=200),
):
    """Serve the knowledge base HTML page."""
    template_path = Path(__file__).resolve().parent.parent.parent / "static" / "knowledge.html"
    template = template_path.read_text()

    entries = get_entries(category=category, tag=tag, limit=limit)

    # Stats
    all_entries = get_entries(limit=200)
    categories = Counter(e.get("category", "general") for e in all_entries)
    all_tags = Counter(t for e in all_entries for t in e.get("tags", []))

    stats_html = (
        '<div class="stats">'
        f'<div class="stat"><div class="stat-value">{len(all_entries)}</div><div class="stat-label">Entries</div></div>'
        f'<div class="stat"><div class="stat-value">{len(categories)}</div><div class="stat-label">Categories</div></div>'
        f'<div class="stat"><div class="stat-value">{len(all_tags)}</div><div class="stat-label">Tags</div></div>'
        "</div>"
    )

    # Category filter options
    category_options = ""
    for cat, count in categories.most_common():
        label = cat.replace("_", " ").title() if cat else "General"
        category_options += f'<option value="{_esc(cat)}">{_esc(label)} ({count})</option>'

    # Entry cards (newest first)
    entries_sorted = sorted(entries, key=lambda e: e.get("created_at", ""), reverse=True)
    entries_html = ""
    for e in entries_sorted:
        title = _esc(e.get("title", "Untitled"))
        content = _esc(e.get("content", ""))
        cat = e.get("category", "")
        tags = e.get("tags", [])
        created = e.get("created_at", "")[:10]
        source_url = e.get("source_url", "")
        reel_id = e.get("reel_id", "")

        cat_badge = f'<span class="badge badge-category">{_esc(cat.replace("_", " ").title())}</span>' if cat else ""
        tag_badges = "".join(f'<span class="badge badge-tag">{_esc(t)}</span>' for t in tags)
        source_link = f' <a class="entry-link" href="{_esc(source_url)}">source</a>' if source_url else ""
        plan_link = f' <a class="entry-link" href="/plans/{_esc(reel_id)}/view">plan</a>' if reel_id else ""

        entries_html += (
            f'<div class="entry-card" data-category="{_esc(cat)}">'
            f'<div class="entry-title">{title}</div>'
            f'<div class="entry-content">{content}</div>'
            f'<div class="entry-meta">'
            f'{cat_badge}{tag_badges}'
            f'<span class="entry-date">{created}</span>'
            f'{source_link}{plan_link}'
            f"</div></div>"
        )

    if not entries_html:
        entries_html = '<div class="empty-state">No knowledge base entries yet. Process some reels to build up insights.</div>'

    html = template.replace("{{stats_html}}", stats_html)
    html = html.replace("{{category_options}}", category_options)
    html = html.replace("{{entries_html}}", entries_html)
    return HTMLResponse(html)


@router.get("/api")
def list_entries_api(
    category: str = "",
    tag: str = "",
    limit: int = Query(default=50, le=200),
):
    """List knowledge base entries as JSON, optionally filtered by category or tag."""
    entries = get_entries(category=category, tag=tag, limit=limit)
    return {"entries": entries, "count": len(entries)}


@router.get("/search")
def search(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=20, le=100),
):
    """Search knowledge base by text query."""
    results = search_entries(query=q, limit=limit)
    return {"results": results, "count": len(results)}


@router.get("/context")
def context(limit: int = Query(default=10, le=50)):
    """Get recent KB entries formatted as context for LLM prompts."""
    return {"context": get_recent_context(limit=limit)}

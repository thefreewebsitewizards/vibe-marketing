from fastapi import APIRouter, Query

from src.utils.knowledge_base import get_entries, search_entries, get_recent_context

router = APIRouter(prefix="/knowledge")


@router.get("/")
def list_entries(
    category: str = "",
    tag: str = "",
    limit: int = Query(default=50, le=200),
):
    """List knowledge base entries, optionally filtered by category or tag."""
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
